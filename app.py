"""
app.py — Web app analisa angin enroute (Streamlit)
==================================================
Buka di browser/HP: pilih rute, pilih Flight Level, lihat analisa angin
dari forecast GFS (NOAA). Bisa juga bandingkan altitude & upload rute baru.

Jalankan lokal:  streamlit run app.py
Deploy         :  Streamlit Community Cloud (lihat README)

NOT FOR REAL WORLD NAVIGATION — untuk latihan & simulasi.
"""

import os
import glob
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st

import wind_core as wc

# ---------------- Konfigurasi halaman ----------------
st.set_page_config(page_title="Wind Enroute — GFS", page_icon="🛩️", layout="wide")

st.title("🛩️ Analisa Angin Enroute")
st.caption("Data angin dari forecast **GFS (NOAA)** via Open-Meteo · "
           "**NOT FOR REAL WORLD NAVIGATION** — untuk latihan & simulasi")

ROUTES_DIR = "routes"


def list_routes():
    files = sorted(glob.glob(os.path.join(ROUTES_DIR, "*.csv")))
    return {os.path.splitext(os.path.basename(f))[0]: f for f in files}


# ---------------- Sidebar: input ----------------
with st.sidebar:
    st.header("⚙️ Pengaturan")

    routes = list_routes()
    route_names = list(routes.keys())

    uploaded = st.file_uploader("Atau upload CSV rute sendiri", type="csv")

    if uploaded is not None:
        text = uploaded.getvalue().decode("utf-8")
        route = wc.load_route_from_text(text)
        route_label = os.path.splitext(uploaded.name)[0].upper()
        st.success(f"Rute di-upload: {route_label} ({len(route)} wpt)")
    elif route_names:
        route_label = st.selectbox("Pilih rute", route_names)
        route = wc.load_route(routes[route_label])
    else:
        st.warning("Belum ada file rute di folder 'routes/'.")
        route, route_label = [], "-"

    st.divider()

    # cek apakah rute punya data FL per-waypoint
    has_profile = any(wp.get('fl') for wp in route) if route else False

    mode = st.radio(
        "Mode analisa",
        ["Profil OFP (climb/cruise/descent)", "Cruise (satu FL)"],
        index=0 if has_profile else 1,
        help="Profil OFP = tiap waypoint pakai altitude aslinya (mirip navlog). "
             "Cruise = seluruh rute di satu FL (untuk banding altitude).",
    )
    use_profile = mode.startswith("Profil")

    if use_profile and not has_profile:
        st.warning("CSV ini belum punya kolom 'fl'. Ekstrak ulang PDF pakai "
                   "ofp_to_csv.py versi baru, atau pilih mode Cruise.")

    fl = st.select_slider(
        "Cruise Level" if use_profile else "Flight Level",
        options=[240, 300, 340, 390],
        value=340,
        help=("Mode Profil: ini mengatur CRUISE level. Climb & descent tetap "
              "ikut CSV. Mode Cruise: seluruh rute di FL ini."),
    )

    hours_ahead = st.slider(
        "Forecast jam ke depan", 0, 48, 1,
        help="0 = sekarang. Makin dekat makin akurat.",
    )

    st.divider()
    run = st.button("🔍 Analisa", type="primary", use_container_width=True)
    run_compare = st.button("📊 Bandingkan Altitude", use_container_width=True)


# ---------------- Fungsi bantu tampilan ----------------
def target_time():
    t = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return t.replace(minute=0, second=0, microsecond=0)


def fmt_crosswind(x):
    return f"{abs(x)}{'R' if x >= 0 else 'L'}"


# ---------------- Aksi: Analisa ----------------
if run and route:
    tgt = target_time()
    with st.spinner(f"Menarik data GFS untuk {len(route)} waypoint…"):
        rows, summary = wc.analyze_route(
            route, fl=fl, target_time=tgt, use_profile=use_profile)

    # Ringkasan atas
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rute", route_label)
    c2.metric("Total Jarak", f"{summary['total_dist']} NM")
    if summary["mode"] == "profile":
        c3.metric("Mode", "Profil OFP", f"cruise FL{summary['fl']:03d}")
    else:
        c3.metric("Cruise", f"FL{summary['fl']:03d}")
    c4.metric("Avg Wind Comp",
              summary["avg_wc_label"],
              summary["wind_type"],
              delta_color="inverse")

    mode_txt = (f"Profil OFP — climb/descent ikut CSV, cruise di FL{summary['fl']:03d}"
                if summary["mode"] == "profile"
                else f"Cruise FL{summary['fl']:03d} — seluruh rute satu level")
    st.caption(f"Forecast: {tgt.strftime('%Y-%m-%d %H:%M UTC')} · {mode_txt} · "
               f"Bandingkan dengan AVG W/C di OFP SimBrief")

    # Tabel
    df = pd.DataFrame(rows)
    df_show = pd.DataFrame({
        "WPT": df["ident"],
        "FL": df["fl"].map(lambda x: f"FL{x:03d}"),
        "TRK°": df["track"],
        "DIST": df["dist"],
        "WIND": df["wind_dir"].astype(str) + "/" + df["wind_spd"].astype(str),
        "H/W": df["headwind"].map(lambda x: f"{x:+d}"),
        "X/W": df["crosswind"].map(fmt_crosswind),
        "OAT": df["oat"],
        "ISAΔ": df["isa_dev"].map(lambda x: f"{x:+d}"),
    })
    st.dataframe(df_show, use_container_width=True, hide_index=True, height=460)

    # Grafik headwind per waypoint
    st.subheader("Grafik Wind Component per Waypoint")
    chart_df = df[["ident", "headwind", "crosswind"]].set_index("ident")
    chart_df.columns = ["Headwind (+) / Tailwind (-)", "Crosswind (R+/L-)"]
    st.bar_chart(chart_df, height=300)

    st.caption("Positif = headwind/dari kanan · Negatif = tailwind/dari kiri")

    # Download hasil
    csv_out = df.to_csv(index=False).encode("utf-8")
    suffix = "profil" if summary["mode"] == "profile" else f"FL{summary['fl']}"
    st.download_button("⬇️ Download hasil (CSV)", csv_out,
                       file_name=f"{route_label}_{suffix}_wind.csv",
                       mime="text/csv")


# ---------------- Aksi: Bandingkan Altitude ----------------
if run_compare and route:
    tgt = target_time()
    with st.spinner("Membandingkan beberapa altitude…"):
        results, best = wc.compare_altitudes(route, tgt)

    st.subheader("📊 Perbandingan Altitude")
    st.caption("Wind component terkecil = paling menguntungkan dari sisi angin. "
               "Tapi ingat: terbang rendah lebih boros fuel — keputusan nyata "
               "adalah trade-off antara angin & efisiensi altitude.")

    cmp_df = pd.DataFrame([{
        "Flight Level": f"FL{r['fl']:03d}",
        "Avg Wind Comp (kt)": r["avg_wc"],
        "Jenis": r["type"],
        "Label": r["label"],
    } for r in results])

    col1, col2 = st.columns([1, 1])
    with col1:
        st.dataframe(cmp_df, use_container_width=True, hide_index=True)
        if best:
            st.success(f"✅ Angin paling menguntungkan: **FL{best['fl']:03d}** "
                       f"({best['label']} kt)")
    with col2:
        chart = pd.DataFrame(
            {"Avg Wind Comp (kt)": [r["avg_wc"] for r in results]},
            index=[f"FL{r['fl']:03d}" for r in results],
        )
        st.bar_chart(chart, height=280)


# ---------------- Kondisi awal ----------------
if not run and not run_compare:
    st.info("👈 Pilih rute & Flight Level di panel kiri, lalu klik **Analisa**.")
    if route:
        st.subheader(f"Preview rute: {route_label}")
        prev = pd.DataFrame([{
            "Waypoint": w["ident"], "Lat": w["lat"], "Lon": w["lon"],
            "FL": f"FL{w['fl']:03d}" if w.get("fl") else "-",
        } for w in route])
        c1, c2 = st.columns([1, 1])
        with c1:
            st.dataframe(prev, use_container_width=True, hide_index=True, height=360)
        with c2:
            # peta sederhana pakai st.map (butuh kolom lat/lon)
            map_df = prev.rename(columns={"Lat": "lat", "Lon": "lon"})
            st.map(map_df, size=8)
