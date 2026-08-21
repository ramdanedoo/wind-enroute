"""
app.py — Wind Enroute (retro kaiju poster theme, responsive)
Web app analisa angin enroute dari forecast GFS (NOAA).
Optimal untuk laptop & HP.
NOT FOR REAL WORLD NAVIGATION — untuk latihan & simulasi.
"""
import os
import glob
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

import wind_core as wc

st.set_page_config(page_title="WIND ENROUTE · Flight Planner", page_icon="🦖",
                   layout="wide", initial_sidebar_state="collapsed")

ROUTES_DIR = "routes"
RED="#E8452F"; RED_DK="#B8331F"; CREAM="#F5F0E6"; CREAM2="#EFE8D8"
INK="#1a1a1a"; DIM="#7a6f5f"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bungee&family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;600;800&display=swap');

.stApp {{ background:{CREAM};
    background-image:radial-gradient({DIM}22 1px, transparent 1px);
    background-size:5px 5px; }}
.block-container {{ padding-top:1rem; padding-left:1rem; padding-right:1rem;
    max-width:1400px; }}

.checker {{ height:14px; width:100%;
    background-image:
      linear-gradient(45deg,{INK} 25%,transparent 25%,transparent 75%,{INK} 75%),
      linear-gradient(45deg,{INK} 25%,transparent 25%,transparent 75%,{INK} 75%);
    background-size:14px 14px; background-position:0 0,7px 7px; margin-bottom:6px; }}

.hero {{ font-family:'Bungee',cursive; color:{RED};
    text-align:center; line-height:.95; letter-spacing:1px; margin:6px 0 2px 0;
    text-shadow:3px 3px 0 {INK}, 5px 5px 0 rgba(0,0,0,.12);
    font-size:clamp(2rem, 8vw, 3.2rem); }}
.banner {{ background:{RED}; color:{CREAM}; text-align:center;
    font-family:'Bungee',cursive; letter-spacing:2px;
    padding:5px 16px; border:3px solid {INK}; border-radius:8px;
    display:inline-block; box-shadow:3px 3px 0 {INK};
    font-size:clamp(.85rem, 3.5vw, 1.15rem); }}
.kata {{ text-align:center; color:{RED}; font-family:'Inter',sans-serif;
    font-weight:800; letter-spacing:3px; margin-top:6px;
    font-size:clamp(.7rem, 3vw, .9rem); }}
.center {{ text-align:center; }}

.pcard {{ background:{CREAM}; border:3px solid {INK}; border-radius:10px;
    padding:10px 14px; box-shadow:4px 4px 0 {INK}; margin-bottom:10px; }}
.pcard.alert {{ background:{RED}; }}
.pcard .lbl {{ font-family:'JetBrains Mono',monospace; font-size:.6rem;
    letter-spacing:2px; text-transform:uppercase; color:{DIM}; font-weight:600; }}
.pcard.alert .lbl {{ color:{CREAM}; opacity:.85; }}
.pcard .val {{ font-family:'Bungee',cursive; font-size:1.4rem; color:{INK};
    line-height:1.15; margin-top:2px; }}
.pcard.alert .val {{ color:{CREAM}; }}
.pcard .sub {{ font-family:'JetBrains Mono',monospace; font-size:.6rem;
    color:{DIM}; letter-spacing:1px; }}
.pcard.alert .sub {{ color:{CREAM}; opacity:.9; }}

section[data-testid="stSidebar"] {{ background:{CREAM2}; border-right:3px solid {INK}; }}
.side-title {{ font-family:'Bungee',cursive; color:{INK}; font-size:1rem;
    letter-spacing:1px; margin-bottom:8px; }}
.stButton>button {{ font-family:'Bungee',cursive; letter-spacing:1px;
    border:3px solid {INK}; border-radius:8px; box-shadow:3px 3px 0 {INK};
    transition:all .12s; }}
.stButton>button[kind="primary"] {{ background:{RED}; color:{CREAM}; }}
.stButton>button:hover {{ transform:translate(2px,2px); box-shadow:1px 1px 0 {INK}; }}

.pfoot {{ background:{RED}; color:{CREAM}; text-align:center;
    font-family:'Bungee',cursive; letter-spacing:2px;
    padding:8px; border:3px solid {INK}; border-radius:8px; margin-top:10px;
    font-size:clamp(.75rem, 3vw, 1rem); }}

#MainMenu, footer, header {{ visibility:hidden; }}
h3 {{ font-family:'Bungee',cursive !important; color:{INK} !important; }}

/* ===== RESPONSIVE: di HP, kolom menumpuk & padding lebih kecil ===== */
@media (max-width: 640px) {{
    .block-container {{ padding-left:.5rem; padding-right:.5rem; }}
    .pcard .val {{ font-size:1.2rem; }}
    /* paksa kolom Streamlit jadi full-width (menumpuk) di HP */
    div[data-testid="column"] {{ width:100% !important; flex:1 1 100% !important;
        min-width:100% !important; }}
}}
</style>
""", unsafe_allow_html=True)


def list_routes():
    files = sorted(glob.glob(os.path.join(ROUTES_DIR, "*.csv")))
    return {os.path.splitext(os.path.basename(f))[0]: f for f in files}

def target_time(h, custom=None):
    if custom is not None:
        return custom.replace(minute=0, second=0, microsecond=0)
    t = datetime.now(timezone.utc) + timedelta(hours=h)
    return t.replace(minute=0, second=0, microsecond=0)

def pcard(col, label, value, sub="", alert=False):
    cls = "pcard alert" if alert else "pcard"
    col.markdown(f'<div class="{cls}"><div class="lbl">{label}</div>'
                 f'<div class="val">{value}</div><div class="sub">{sub}</div></div>',
                 unsafe_allow_html=True)

# ===== Header =====
st.markdown('<div class="checker"></div>', unsafe_allow_html=True)
st.markdown('<div class="hero">WIND ENROUTE</div>', unsafe_allow_html=True)
st.markdown('<div class="center"><span class="banner">FLIGHT PLANNER</span></div>',
            unsafe_allow_html=True)
st.markdown('<div class="kata">フライト プランナー</div>', unsafe_allow_html=True)
st.write("")

# ===== KONTROL UTAMA DI ATAS (kelihatan langsung di HP) =====
routes = list_routes(); route_names = list(routes.keys())

with st.expander("⚙️ FLIGHT SETUP — ketuk untuk atur rute & mode", expanded=True):
    cc1, cc2 = st.columns([1, 1])
    with cc1:
        uploaded = st.file_uploader("Upload CSV rute (opsional)", type="csv")
        if uploaded is not None:
            route = wc.load_route_from_text(uploaded.getvalue().decode("utf-8"))
            route_label = os.path.splitext(uploaded.name)[0].upper()
        elif route_names:
            route_label = st.selectbox("ROUTE", route_names)
            route = wc.load_route(routes[route_label])
        else:
            st.warning("Belum ada rute di folder routes/."); route, route_label = [], "-"
        has_profile = any(wp.get('fl') for wp in route) if route else False
    with cc2:
        mode = st.radio("MODE", ["Profil OFP (climb/cruise/descent)", "Cruise (satu FL)"],
                        index=0 if has_profile else 1)
        use_profile = mode.startswith("Profil")
        fl = st.select_slider("CRUISE LEVEL" if use_profile else "FLIGHT LEVEL",
                              options=[240, 300, 340, 390], value=340)
        wx_time_mode = st.radio("WAKTU FORECAST",
                                ["Cepat (+jam dari sekarang)", "Tanggal & jam spesifik"],
                                horizontal=False)
        if wx_time_mode.startswith("Cepat"):
            hours_ahead = st.slider("FORECAST +JAM", 0, 120, 1)
            custom_dt = None
        else:
            from datetime import date, time as dtime
            cd1, cd2 = st.columns([1, 1])
            pick_date = cd1.date_input("Tanggal (UTC)")
            pick_hour = cd2.selectbox("Jam UTC", list(range(24)), index=8)
            custom_dt = datetime.combine(pick_date, dtime(hour=pick_hour),
                                         tzinfo=timezone.utc)
            hours_ahead = 0

    b1, b2 = st.columns([1, 1])
    run = b1.button("▶ ANALISA", type="primary", use_container_width=True)
    run_compare = b2.button("▤ BANDINGKAN ALTITUDE", use_container_width=True)
    run_wx = st.button("☁ CEK CUACA BANDARA", use_container_width=True)

# ===== Plotly =====
def style_fig(fig, height=300):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=CREAM,
        font=dict(family="JetBrains Mono, monospace", color=INK, size=11),
        height=height, margin=dict(l=8, r=8, t=34, b=8),
        xaxis=dict(gridcolor="#d8cfba", zerolinecolor=INK, linecolor=INK),
        yaxis=dict(gridcolor="#d8cfba", zerolinecolor=INK, linecolor=INK))
    return fig

def wind_bar(df):
    colors = [RED if h >= 0 else "#c9b98f" for h in df["headwind"]]
    fig = go.Figure()
    fig.add_bar(x=df["ident"], y=df["headwind"], marker=dict(color=colors,
                line=dict(color=INK, width=1.2)),
                hovertemplate="%{x}<br>%{y:+d} kt<extra></extra>")
    fig.add_hline(y=0, line=dict(color=INK, width=1.5))
    fig.update_layout(title=dict(text="WIND COMPONENT · red=headwind",
                                 font=dict(size=11, color=DIM)))
    return style_fig(fig)

def profile_chart(df):
    fig = go.Figure()
    fig.add_scatter(x=df["ident"], y=df["fl"]*100, mode="lines+markers",
                    line=dict(color=RED, width=3), marker=dict(size=6, color=RED,
                    line=dict(color=INK, width=1)),
                    fill="tozeroy", fillcolor="rgba(232,69,47,.12)",
                    hovertemplate="%{x}<br>%{y:,.0f} ft<extra></extra>")
    fig.update_layout(title=dict(text="VERTICAL PROFILE", font=dict(size=11, color=DIM)),
                      yaxis=dict(title="ALT ft"))
    return style_fig(fig, 260)

def wind_altitude_chart(results):
    """Grafik angin per FL: sumbu Y = altitude, X = avg wind component.
    Bantu lihat FL mana yang paling menguntungkan secara visual (vertikal)."""
    fls = [r["fl"]*100 for r in results]
    wcs = [r["avg_wc"] for r in results]
    colors = [RED if w >= 0 else "#3a8a3a" for w in wcs]
    fig = go.Figure()
    fig.add_scatter(x=wcs, y=fls, mode="lines+markers",
                    line=dict(color=INK, width=2, dash="dot"),
                    marker=dict(size=12, color=colors, line=dict(color=INK, width=1.5)),
                    hovertemplate="FL%{customdata:03d}<br>%{x:+d} kt<extra></extra>",
                    customdata=[r["fl"] for r in results])
    fig.add_vline(x=0, line=dict(color=DIM, width=1))
    fig.update_layout(
        title=dict(text="PROFIL ANGIN VERTIKAL · geser kiri (tailwind) = lebih hemat",
                   font=dict(size=11, color=DIM)),
        xaxis=dict(title="WIND COMPONENT (kt) · + headwind / − tailwind"),
        yaxis=dict(title="ALTITUDE (ft)"))
    return style_fig(fig, 340)


def route_map(rows):
    """Peta rute: garis penghubung waypoint + panah arah angin tiap titik.
    Panah pakai karakter '↑' yang diputar sesuai arah DATANG angin."""
    pts = [{"lat": r["lat"], "lon": r["lon"], "name": r["ident"]} for r in rows]
    path = [[p["lon"], p["lat"]] for p in pts]

    # panah angin: arah "from" → tanda panah menunjuk ke arah angin bertiup (from+180)
    arrows = []
    for r in rows:
        wf = r.get("wind_dir", 0)
        spd = r.get("wind_spd", 0)
        arrows.append({
            "lat": r["lat"], "lon": r["lon"],
            "text": "➤",
            "angle": -(wf + 180) % 360,   # deck rotasi; panah ke arah tiupan
            "info": f"{r['ident']} · {wf:03d}/{spd}kt · HW {r.get('headwind',0):+d}",
        })

    layers = [
        # garis rute
        pdk.Layer("PathLayer", data=[{"path": path}],
                  get_path="path", get_color=[26, 26, 26], width_min_pixels=2),
        # titik waypoint
        pdk.Layer("ScatterplotLayer", data=pts,
                  get_position=["lon", "lat"], get_radius=3000,
                  get_fill_color=[232, 69, 47], pickable=True),
        # label waypoint
        pdk.Layer("TextLayer", data=pts,
                  get_position=["lon", "lat"], get_text="name",
                  get_size=11, get_color=[26, 26, 26],
                  get_pixel_offset=[0, -14]),
        # panah angin
        pdk.Layer("TextLayer", data=arrows,
                  get_position=["lon", "lat"], get_text="text",
                  get_size=22, get_color=[0, 120, 200],
                  get_angle="angle", pickable=True),
    ]
    lats = [p["lat"] for p in pts]; lons = [p["lon"] for p in pts]
    view = pdk.ViewState(latitude=sum(lats)/len(lats),
                         longitude=sum(lons)/len(lons), zoom=5.2)
    return pdk.Deck(layers=layers, initial_view_state=view,
                    map_style="light",
                    tooltip={"text": "{info}{name}"})

# ===== Analisa =====
if run and route:
    tgt = target_time(hours_ahead, custom_dt)
    with st.spinner("🦖 Menarik data GFS…"):
        rows, summary = wc.analyze_route(route, fl=fl, target_time=tgt,
                                         use_profile=use_profile)
    df = pd.DataFrame(rows)
    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)
    pcard(c1, "ROUTE", route_label, f"{len(route)} waypoints")
    pcard(c2, "DISTANCE", f"{summary['total_dist']} NM", "ground")
    if summary["mode"] == "profile":
        pcard(c3, "MODE", "PROFILE", f"cruise FL{summary['fl']:03d}")
    else:
        pcard(c3, "CRUISE", f"FL{summary['fl']:03d}", "fixed")
    pcard(c4, "AVG WIND", summary["avg_wc_label"], summary["wind_type"],
          alert=(summary["avg_wc"] >= 0))

    st.write("")
    # Tabel LENGKAP (semua kolom). Di HP otomatis bisa scroll horizontal.
    tbl = {
        "WPT": df["ident"],
        "FL": df["fl"].map(lambda x: f"FL{x:03d}"),
        "TRK": df["track"].map(lambda x: f"{x:03d}"),
        "DIST": df["dist"],
        "WIND": df["wind_dir"].astype(str).str.zfill(3)+"/"+df["wind_spd"].astype(str),
        "HW": df["headwind"],
        "XW": df["crosswind"],
    }
    if "oat" in df.columns and df["oat"].notna().any():
        tbl["OAT"] = df["oat"]
    if "isa_dev" in df.columns and df["isa_dev"].notna().any():
        tbl["ISA"] = df["isa_dev"]
    df_show = pd.DataFrame(tbl)

    # Warna: headwind merah, tailwind hijau. XW dibedakan juga.
    def hw_c(v):
        return f"color:{RED};font-weight:800" if v >= 0 else "color:#3a8a3a;font-weight:800"
    def xw_c(v):
        return "color:#8a6d3b;font-weight:700"

    fmt = {"HW": "{:+d}", "XW": "{:+d}"}
    if "ISA" in df_show.columns:
        fmt["ISA"] = "{:+d}"

    sty = df_show.style
    # base dulu (jangan set color global agar tidak menimpa warna HW)
    sty = sty.set_properties(**{"font-family": "JetBrains Mono, monospace",
                                "background-color": CREAM,
                                "border": f"1px solid {INK}"})
    # warna teks default untuk kolom non-HW
    non_hw = [c for c in df_show.columns if c != "HW"]
    sty = sty.set_properties(subset=non_hw, **{"color": INK})
    # warna HW diterapkan TERAKHIR agar menang
    sty = sty.map(hw_c, subset=["HW"])
    sty = sty.format(fmt)
    sty = sty.set_table_styles([{"selector": "th", "props": [
        ("background-color", RED), ("color", CREAM),
        ("font-family", "Bungee"), ("font-size", "11px"),
        ("border", f"2px solid {INK}")]}])
    st.dataframe(sty, use_container_width=True, hide_index=True, height=400)

    # Charts menumpuk (full width masing-masing) — enak di HP & laptop
    st.plotly_chart(wind_bar(df), use_container_width=True)
    st.plotly_chart(profile_chart(df), use_container_width=True)

    # Peta rute + panah angin
    st.markdown(f'<div style="color:{RED};font-family:Bungee;font-size:.85rem;'
                f'margin:8px 0 4px">🗺 PETA RUTE & ANGIN</div>', unsafe_allow_html=True)
    st.caption("Garis = rute · titik merah = waypoint · panah biru = arah angin bertiup")
    try:
        st.pydeck_chart(route_map(rows), use_container_width=True)
    except Exception as e:
        st.info(f"Peta tidak bisa dimuat: {e}")

    st.download_button("⬇ EXPORT CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{route_label}_wind.csv", mime="text/csv",
                       use_container_width=True)
    st.markdown('<div class="pfoot">GFS · NOAA FORECAST</div>', unsafe_allow_html=True)
    st.markdown('<div class="checker" style="margin-top:6px"></div>', unsafe_allow_html=True)

# ===== Bandingkan =====
elif run_compare and route:
    tgt = target_time(hours_ahead, custom_dt)
    with st.spinner("🦖 Membandingkan altitude…"):
        results, best = wc.compare_altitudes(route, tgt)
    st.markdown('<div class="side-title">▤ ALTITUDE COMPARISON</div>', unsafe_allow_html=True)
    cA, cB = st.columns(2)
    cC, cD = st.columns(2)
    cells = [cA, cB, cC, cD]
    for cell, r in zip(cells, results):
        tag = " ◀BEST" if best and r["fl"]==best["fl"] else ""
        pcard(cell, f"FL{r['fl']:03d}", r["label"], r["type"]+tag,
              alert=(r["avg_wc"]>=0))
    cmp_df = pd.DataFrame({"FL":[f"FL{r['fl']:03d}" for r in results],
                           "wc":[r["avg_wc"] for r in results]})
    fig = go.Figure()
    fig.add_bar(x=cmp_df["FL"], y=cmp_df["wc"], marker=dict(
        color=[RED if w>=0 else "#c9b98f" for w in cmp_df["wc"]],
        line=dict(color=INK, width=1.2)),
        hovertemplate="%{x}<br>%{y:+d} kt<extra></extra>")
    fig.update_layout(title=dict(text="AVG WIND COMPONENT vs ALTITUDE",
                                 font=dict(size=11, color=DIM)))
    st.plotly_chart(style_fig(fig, 320), use_container_width=True)
    # Grafik profil angin vertikal (altitude di sumbu Y)
    st.plotly_chart(wind_altitude_chart(results), use_container_width=True)
    st.markdown('<div class="pfoot">GFS · NOAA FORECAST</div>', unsafe_allow_html=True)

# ===== Cek Cuaca Bandara (METAR/TAF) =====
elif run_wx and route:
    airports = wc.extract_airports(route)
    if not airports:
        st.warning("Tidak ada kode ICAO bandara terdeteksi di rute ini.")
    else:
        with st.spinner(f"☁ Mengambil METAR/TAF untuk {', '.join(airports)}…"):
            wx = wc.fetch_metar_taf(airports)
        st.markdown('<div class="side-title">☁ CUACA BANDARA</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div style="color:{DIM};font-family:JetBrains Mono;'
                    f'font-size:.66rem;margin-bottom:12px">Sumber: aviationweather.gov '
                    f'(NOAA) · METAR=observasi aktual · TAF=prakiraan terminal</div>',
                    unsafe_allow_html=True)
        for icao in airports:
            data = wx.get(icao, {})
            metar_raw = data.get("metar")
            taf_raw = data.get("taf")
            st.markdown(f'<div class="pcard"><div class="lbl">AIRPORT</div>'
                        f'<div class="val">{icao}</div></div>',
                        unsafe_allow_html=True)
            if metar_raw:
                st.markdown(f'<div style="color:{RED};font-family:Bungee;'
                            f'font-size:.8rem;margin:4px 0">METAR</div>',
                            unsafe_allow_html=True)
                st.markdown(f'<div style="color:{INK};font-family:JetBrains Mono;'
                            f'font-size:.8rem;line-height:1.5">🔎 {wc.decode_metar(metar_raw)}</div>',
                            unsafe_allow_html=True)
                st.code(metar_raw, language=None)
            else:
                st.info(f"METAR {icao} tidak tersedia.")
            if taf_raw:
                st.markdown(f'<div style="color:{RED};font-family:Bungee;'
                            f'font-size:.8rem;margin:4px 0">TAF (prakiraan)</div>',
                            unsafe_allow_html=True)
                st.code(taf_raw, language=None)
            else:
                st.caption(f"TAF {icao} tidak tersedia.")
            st.write("")
        st.markdown('<div class="pfoot">METAR/TAF · AVIATIONWEATHER.GOV</div>',
                    unsafe_allow_html=True)

# ===== Awal =====
else:
    if route:
        st.markdown(f'<div class="center" style="color:{DIM};font-family:JetBrains Mono;'
                    f'font-size:.72rem;letter-spacing:1px;margin-bottom:10px">'
                    f'▐ {route_label} · {len(route)} WAYPOINTS · TEKAN ANALISA</div>',
                    unsafe_allow_html=True)
        map_df = pd.DataFrame([{"lat": w["lat"], "lon": w["lon"]} for w in route])
        st.map(map_df, size=10, color="#E8452F")
    else:
        st.info("Pilih rute di atas untuk mulai.")
    st.markdown('<div class="pfoot">GFS · NOAA FORECAST</div>', unsafe_allow_html=True)
