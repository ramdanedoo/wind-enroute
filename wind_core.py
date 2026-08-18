"""
wind_core.py — Logika inti analisa angin enroute dari GFS
=========================================================
Berisi fungsi perhitungan (wind component, bearing, jarak) dan pengambilan
data GFS via Open-Meteo. Dipakai oleh app.py (Streamlit) maupun CLI.

Sumber data: GFS (NOAA) via Open-Meteo API (gratis, tanpa API key).
NOT FOR REAL WORLD NAVIGATION — untuk latihan & simulasi.
"""

import csv
import math
import time
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry

# --- Session dengan retry otomatis (cegah ConnectionResetError) ---
_SESSION = requests.Session()
_retry = Retry(total=4, backoff_factor=0.6,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET"])
_adapter = HTTPAdapter(max_retries=_retry)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)
_SESSION.headers.update({"User-Agent": "wind-enroute-tool/2.0"})

# --- Level altitude yang tersedia ---
FL_TO_HPA = {
    50: 850, 100: 700, 140: 600, 180: 500,
    240: 400, 300: 300, 340: 250, 390: 200, 450: 150,
}
ALL_HPA = [850, 700, 600, 500, 400, 300, 250, 200, 150]
COMPARE_FLS = [240, 300, 340, 390]

_CACHE = {}


def nearest_fl_key(fl):
    return min(FL_TO_HPA.keys(), key=lambda k: abs(k - fl))


# ---------- Matematika ----------
def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def wind_components(wind_dir, wind_spd, track):
    angle = math.radians(wind_dir - track)
    head = wind_spd * math.cos(angle)   # + = headwind
    cross = wind_spd * math.sin(angle)  # + = dari kanan
    return head, cross


def isa_temp(alt_ft):
    if alt_ft <= 36089:
        return 15.0 - 1.98 * (alt_ft / 1000.0)
    return -56.5


# ---------- Muat rute ----------
def load_route(csv_path):
    """CSV -> list dict {ident, lat, lon, fl}. fl bisa None kalau kolom kosong."""
    route = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                fl = row.get('fl', '').strip()
                route.append({
                    'ident': row['ident'].strip(),
                    'lat': float(row['lat']),
                    'lon': float(row['lon']),
                    'fl': int(fl) if fl else None,
                })
            except (KeyError, ValueError):
                continue
    return route


def load_route_from_text(text):
    """Muat rute dari isi CSV berupa string (untuk upload di web)."""
    route = []
    for row in csv.DictReader(text.splitlines()):
        try:
            fl = row.get('fl', '').strip()
            route.append({
                'ident': row['ident'].strip(),
                'lat': float(row['lat']),
                'lon': float(row['lon']),
                'fl': int(fl) if fl else None,
            })
        except (KeyError, ValueError):
            continue
    return route


# ---------- Ambil data GFS ----------
def _fetch_all_levels(lat, lon):
    key = (round(lat, 3), round(lon, 3))
    if key in _CACHE:
        return _CACHE[key]
    url = "https://api.open-meteo.com/v1/gfs"
    hourly = []
    for hpa in ALL_HPA:
        hourly += [f"wind_speed_{hpa}hPa", f"wind_direction_{hpa}hPa",
                   f"temperature_{hpa}hPa", f"geopotential_height_{hpa}hPa"]
    params = {"latitude": lat, "longitude": lon, "hourly": hourly,
              "wind_speed_unit": "kn", "forecast_days": 3, "timezone": "UTC"}
    last_err = None
    for attempt in range(4):
        try:
            r = _SESSION.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            _CACHE[key] = data
            return data
        except Exception as e:
            last_err = e
            time.sleep(0.8 * (attempt + 1))
    raise last_err


def fetch_wind(lat, lon, hpa, target_time):
    data = _fetch_all_levels(lat, lon)
    times = data["hourly"]["time"]
    target_str = target_time.strftime("%Y-%m-%dT%H:00")
    if target_str in times:
        idx = times.index(target_str)
    else:
        idx = min(range(len(times)),
                  key=lambda i: abs(datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target_time))
    return {
        "dir": data["hourly"][f"wind_direction_{hpa}hPa"][idx],
        "spd": data["hourly"][f"wind_speed_{hpa}hPa"][idx],
        "temp": data["hourly"][f"temperature_{hpa}hPa"][idx],
        "hgt": data["hourly"][f"geopotential_height_{hpa}hPa"][idx],
        "time": times[idx],
    }


# ---------- Analisa rute ----------
def analyze_route(route, fl=None, target_time=None, use_profile=False):
    """
    Analisa angin per waypoint.
      use_profile=False : semua waypoint pakai satu 'fl' (mode cruise).
      use_profile=True  : tiap waypoint pakai FL-nya sendiri dari CSV
                          (profil climb/cruise/descent, mirip OFP).
    Kembalikan (rows, summary).
    """
    rows = []
    total_dist, wc_sum = 0.0, 0.0
    n = len(route)

    for i, wp in enumerate(route):
        name, lat, lon = wp['ident'], wp['lat'], wp['lon']

        # tentukan FL untuk waypoint ini
        if use_profile:
            wfl = wp.get('fl') or fl or 330   # fallback kalau kolom fl kosong
        else:
            wfl = fl
        fl_key = nearest_fl_key(wfl)
        hpa = FL_TO_HPA[fl_key]
        alt_ft = fl_key * 100

        w = fetch_wind(lat, lon, hpa, target_time)

        if i < n - 1:
            nlat, nlon = route[i+1]['lat'], route[i+1]['lon']
            trk = bearing(lat, lon, nlat, nlon)
            dist = haversine_nm(lat, lon, nlat, nlon)
        else:
            trk = rows[-1]["track"] if rows else 0.0
            dist = 0.0

        head, cross = wind_components(w["dir"], w["spd"], trk)
        rows.append({
            "ident": name, "lat": lat, "lon": lon, "fl": fl_key,
            "track": round(trk), "dist": round(dist),
            "wind_dir": round(w["dir"]), "wind_spd": round(w["spd"]),
            "headwind": round(head), "crosswind": round(cross),
            "oat": round(w["temp"]), "isa_dev": round(w["temp"] - isa_temp(alt_ft)),
        })
        if i < n - 1:
            total_dist += dist
            wc_sum += head * dist

    avg_wc = wc_sum / total_dist if total_dist else 0
    summary = {
        "mode": "profile" if use_profile else "cruise",
        "fl": (nearest_fl_key(fl) if fl and not use_profile else None),
        "total_dist": round(total_dist),
        "avg_wc": round(avg_wc),
        "avg_wc_label": f"{'M' if avg_wc>=0 else 'P'}{abs(round(avg_wc)):03d}",
        "wind_type": "HEADWIND" if avg_wc >= 0 else "TAILWIND",
    }
    return rows, summary


def compare_altitudes(route, target_time, fls=None):
    """Bandingkan average wind component di beberapa FL (mode cruise). Return list dict."""
    fls = fls or COMPARE_FLS
    out = []
    for fl in fls:
        _, s = analyze_route(route, fl=fl, target_time=target_time, use_profile=False)
        out.append({"fl": nearest_fl_key(fl), "avg_wc": s["avg_wc"],
                    "label": s["avg_wc_label"], "type": s["wind_type"]})
    best = min(out, key=lambda x: x["avg_wc"]) if out else None
    return out, best
