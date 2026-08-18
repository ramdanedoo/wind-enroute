"""
app.py — Wind Enroute (retro kaiju poster theme)
Web app analisa angin enroute dari forecast GFS (NOAA).
NOT FOR REAL WORLD NAVIGATION — untuk latihan & simulasi.
"""
import os
import glob
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import wind_core as wc

st.set_page_config(page_title="WIND ENROUTE · Flight Planner", page_icon="🦖",
                   layout="wide", initial_sidebar_state="expanded")

ROUTES_DIR = "routes"
# Palet poster kaiju
RED="#E8452F"; RED_DK="#B8331F"; CREAM="#F5F0E6"; CREAM2="#EFE8D8"
INK="#1a1a1a"; DIM="#7a6f5f"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bungee&family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;600;800&display=swap');

.stApp {{ background:{CREAM};
    background-image:
        radial-gradient({DIM}22 1px, transparent 1px);
    background-size: 5px 5px;
}}
.block-container {{ padding-top:1.4rem; max-width:1400px; }}

/* checkered strip */
.checker {{ height:16px; width:100%;
    background-image:
      linear-gradient(45deg,{INK} 25%,transparent 25%,transparent 75%,{INK} 75%),
      linear-gradient(45deg,{INK} 25%,transparent 25%,transparent 75%,{INK} 75%);
    background-size:16px 16px; background-position:0 0,8px 8px; margin-bottom:6px; }}

/* hero title */
.hero {{ font-family:'Bungee',cursive; font-size:3.2rem; color:{RED};
    text-align:center; line-height:.95; letter-spacing:1px; margin:6px 0 2px 0;
    text-shadow:4px 4px 0 {INK}, 6px 6px 0 rgba(0,0,0,.15); }}
.banner {{ background:{RED}; color:{CREAM}; text-align:center;
    font-family:'Bungee',cursive; font-size:1.15rem; letter-spacing:2px;
    padding:6px 20px; border:3px solid {INK}; border-radius:8px;
    display:inline-block; box-shadow:3px 3px 0 {INK}; }}
.kata {{ text-align:center; color:{RED}; font-family:'Inter',sans-serif;
    font-weight:800; font-size:.9rem; letter-spacing:3px; margin-top:6px; }}
.center {{ text-align:center; }}

/* poster cards */
.pcard {{ background:{CREAM}; border:3px solid {INK}; border-radius:10px;
    padding:10px 14px; box-shadow:4px 4px 0 {INK};
    position:relative; margin-bottom:6px; }}
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

/* sidebar */
section[data-testid="stSidebar"] {{ background:{CREAM2}; border-right:3px solid {INK}; }}
.side-title {{ font-family:'Bungee',cursive; color:{INK}; font-size:1.1rem;
    letter-spacing:1px; margin-bottom:8px; }}
.stButton>button {{ font-family:'Bungee',cursive; letter-spacing:1px;
    border:3px solid {INK}; border-radius:8px; box-shadow:3px 3px 0 {INK};
    transition:all .12s; }}
.stButton>button[kind="primary"] {{ background:{RED}; color:{CREAM}; }}
.stButton>button[kind="primary"]:hover {{ transform:translate(2px,2px);
    box-shadow:1px 1px 0 {INK}; }}
.stButton>button:hover {{ transform:translate(2px,2px); box-shadow:1px 1px 0 {INK}; }}

/* footer */
.pfoot {{ background:{RED}; color:{CREAM}; text-align:center;
    font-family:'Bungee',cursive; letter-spacing:3px; font-size:1rem;
    padding:8px; border:3px solid {INK}; border-radius:8px; margin-top:10px; }}

#MainMenu, footer, header {{ visibility:hidden; }}
h3 {{ font-family:'Bungee',cursive !important; color:{INK} !important; }}
</style>
""", unsafe_allow_html=True)


def list_routes():
    files = sorted(glob.glob(os.path.join(ROUTES_DIR, "*.csv")))
    return {os.path.splitext(os.path.basename(f))[0]: f for f in files}

def target_time(h):
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

# ===== Sidebar =====
with st.sidebar:
    st.markdown('<div class="side-title">🦖 FLIGHT SETUP</div>', unsafe_allow_html=True)
    routes = list_routes(); route_names = list(routes.keys())
    uploaded = st.file_uploader("Upload CSV rute", type="csv")
    if uploaded is not None:
        route = wc.load_route_from_text(uploaded.getvalue().decode("utf-8"))
        route_label = os.path.splitext(uploaded.name)[0].upper()
    elif route_names:
        route_label = st.selectbox("ROUTE", route_names)
        route = wc.load_route(routes[route_label])
    else:
        st.warning("Belum ada rute di folder routes/."); route, route_label = [], "-"
    has_profile = any(wp.get('fl') for wp in route) if route else False
    st.divider()
    mode = st.radio("MODE", ["Profil OFP (climb/cruise/descent)", "Cruise (satu FL)"],
                    index=0 if has_profile else 1)
    use_profile = mode.startswith("Profil")
    fl = st.select_slider("CRUISE LEVEL" if use_profile else "FLIGHT LEVEL",
                          options=[240, 300, 340, 390], value=340)
    hours_ahead = st.slider("FORECAST +JAM", 0, 48, 1)
    st.divider()
    run = st.button("▶ ANALISA", type="primary", use_container_width=True)
    run_compare = st.button("▤ BANDINGKAN ALTITUDE", use_container_width=True)

# ===== Plotly (merah-krem) =====
def style_fig(fig, height=320):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=CREAM,
        font=dict(family="JetBrains Mono, monospace", color=INK, size=11),
        height=height, margin=dict(l=10, r=10, t=34, b=10),
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

# ===== Analisa =====
if run and route:
    tgt = target_time(hours_ahead)
    with st.spinner("🦖 Menarik data GFS…"):
        rows, summary = wc.analyze_route(route, fl=fl, target_time=tgt,
                                         use_profile=use_profile)
    df = pd.DataFrame(rows)
    c1, c2, c3, c4 = st.columns(4)
    pcard(c1, "ROUTE", route_label, f"{len(route)} waypoints")
    pcard(c2, "DISTANCE", f"{summary['total_dist']} NM", "ground")
    if summary["mode"] == "profile":
        pcard(c3, "MODE", "PROFILE", f"cruise FL{summary['fl']:03d}")
    else:
        pcard(c3, "CRUISE", f"FL{summary['fl']:03d}", "fixed")
    pcard(c4, "AVG WIND", summary["avg_wc_label"], summary["wind_type"],
          alert=(summary["avg_wc"] >= 0))

    st.write("")
    tcol, chcol = st.columns([1, 1])
    with tcol:
        df_show = pd.DataFrame({
            "WPT": df["ident"], "FL": df["fl"].map(lambda x: f"FL{x:03d}"),
            "WIND": df["wind_dir"].astype(str).str.zfill(3)+"/"+df["wind_spd"].astype(str),
            "HW": df["headwind"], "XW": df["crosswind"], "OAT": df["oat"]})
        def hw_c(v): return f"color:{RED};font-weight:800" if v>=0 else f"color:#6b8e23;font-weight:800"
        sty = (df_show.style.map(hw_c, subset=["HW"])
               .format({"HW":"{:+d}","XW":"{:+d}"})
               .set_properties(**{"font-family":"JetBrains Mono, monospace",
                                  "background-color":CREAM,"color":INK,"border":f"1px solid {INK}"})
               .set_table_styles([{"selector":"th","props":[("background-color",RED),
                   ("color",CREAM),("font-family","Bungee"),("font-size","11px"),
                   ("border",f"2px solid {INK}")]}]))
        st.dataframe(sty, use_container_width=True, hide_index=True, height=430)
    with chcol:
        st.plotly_chart(wind_bar(df), use_container_width=True)
        st.plotly_chart(profile_chart(df), use_container_width=True)

    st.download_button("⬇ EXPORT CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{route_label}_wind.csv", mime="text/csv")
    st.markdown('<div class="pfoot">GFS · NOAA FORECAST</div>', unsafe_allow_html=True)
    st.markdown('<div class="checker" style="margin-top:6px"></div>', unsafe_allow_html=True)

# ===== Bandingkan =====
if run_compare and route:
    tgt = target_time(hours_ahead)
    with st.spinner("🦖 Membandingkan altitude…"):
        results, best = wc.compare_altitudes(route, tgt)
    st.markdown('<div class="side-title">▤ ALTITUDE COMPARISON</div>', unsafe_allow_html=True)
    cols = st.columns(len(results))
    for col, r in zip(cols, results):
        tag = " ◀BEST" if best and r["fl"]==best["fl"] else ""
        pcard(col, f"FL{r['fl']:03d}", r["label"], r["type"]+tag,
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
    st.markdown('<div class="pfoot">GFS · NOAA FORECAST</div>', unsafe_allow_html=True)

# ===== Awal =====
if not run and not run_compare:
    if route:
        st.markdown(f'<div class="center" style="color:{DIM};font-family:JetBrains Mono;'
                    f'font-size:.75rem;letter-spacing:1px;margin-bottom:10px">'
                    f'▐ {route_label} · {len(route)} WAYPOINTS · TEKAN ANALISA</div>',
                    unsafe_allow_html=True)
        map_df = pd.DataFrame([{"lat": w["lat"], "lon": w["lon"]} for w in route])
        st.map(map_df, size=10, color="#E8452F")
    else:
        st.info("Pilih rute di panel kiri untuk mulai.")
    st.markdown('<div class="pfoot">GFS · NOAA FORECAST</div>', unsafe_allow_html=True)
