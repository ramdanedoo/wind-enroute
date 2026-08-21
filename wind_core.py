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
from functools import lru_cache
from collections import OrderedDict

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry

# --- Rate Limiting ---
class RateLimiter:
    """Membatasi jumlah request per menit ke API eksternal."""
    def __init__(self, max_requests_per_minute=8):
        self.max_requests = max_requests_per_minute
        self.requests = []  # list of timestamps
    
    def wait_if_needed(self):
        """Menunda jika sudah melebihi batas request per menit."""
        now = time.time()
        # Hapus request yang lebih dari 60 detik lalu
        self.requests = [t for t in self.requests if now - t < 60]
        
        if len(self.requests) >= self.max_requests:
            # Hitung berapa detik harus menunggu
            oldest = self.requests[0]
            wait_time = 60 - (now - oldest) + 0.5  # sedikit buffer
            if wait_time > 0:
                time.sleep(wait_time)
        
        self.requests.append(time.time())

# Karena sekarang pakai batch multi-lokasi (1 request per rute, bukan 18),
# limit bisa dilonggarkan. 20/menit aman untuk Open-Meteo gratis.
_rate_limiter = RateLimiter(max_requests_per_minute=20)

# --- Session dengan retry otomatis ---
_SESSION = requests.Session()
_retry = Retry(
    total=8,  # ↑ dari 4 menjadi 8
    backoff_factor=1.5,  # ↑ exponential backoff lebih agresif
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True  # hormonal Retry-After header dari server
)
_adapter = HTTPAdapter(max_retries=_retry)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)
_SESSION.headers.update({"User-Agent": "wind-enroute-tool/2.1"})

# --- Level altitude yang tersedia ---
FL_TO_HPA = {
    50: 850, 100: 700, 140: 600, 180: 500,
    240: 400, 300: 300, 340: 250, 390: 200, 450: 150,
}
ALL_HPA = [850, 700, 600, 500, 400, 300, 250, 200, 150]
COMPARE_FLS = [240, 300, 340, 390]

# --- Cache dengan batas ukuran ---
# Menggunakan dict biasa dengan manajemen manual untuk menghindari memory leak
_cache = OrderedDict()
_CACHE_MAX_SIZE = 100  # maksimal 100 lokasi di cache


def _cache_get(key):
    if key in _cache:
        # Pindahkan ke akhir (recently used)
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _cache_set(key, value):
    if key in _cache:
        _cache.move_to_end(key)
    else:
        if len(_cache) >= _CACHE_MAX_SIZE:
            _cache.popitem(last=False)  # hapus yang paling lama
        _cache[key] = value


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
def _build_hourly_params():
    """
    Bangun list variabel hourly: wind speed, direction, dan temperature.
    Temperature dikembalikan agar OAT & ISA deviation tersedia di tabel.
    """
    hourly = []
    for hpa in ALL_HPA:
        hourly.append(f"wind_speed_{hpa}hPa")
        hourly.append(f"wind_direction_{hpa}hPa")
        hourly.append(f"temperature_{hpa}hPa")
    return hourly


def prefetch_route(route):
    """
    OPTIMASI UTAMA: ambil SEMUA waypoint dalam SATU request (multi-lokasi).
    Open-Meteo menerima koordinat dipisah koma, mengembalikan array hasil.
    Ini mengubah 18 request → 1 request, jadi cepat & tidak kena rate limit.
    Hasil disimpan ke cache yang sama, sehingga fetch_wind() tinggal baca cache.
    """
    # kumpulkan koordinat unik yang belum ada di cache
    todo = []
    for wp in route:
        key = (round(wp['lat'], 3), round(wp['lon'], 3))
        if _cache_get(key) is None and key not in [t[0] for t in todo]:
            todo.append((key, wp['lat'], wp['lon']))
    if not todo:
        return

    _rate_limiter.wait_if_needed()
    url = "https://api.open-meteo.com/v1/gfs"
    params = {
        "latitude": ",".join(str(t[1]) for t in todo),
        "longitude": ",".join(str(t[2]) for t in todo),
        "hourly": _build_hourly_params(),
        "wind_speed_unit": "kn",
        "forecast_days": 3,
        "timezone": "UTC",
    }

    last_err = None
    for attempt in range(8):
        try:
            r = _SESSION.get(url, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            # Multi-lokasi → Open-Meteo balas LIST of dict (satu per koordinat).
            # Single-lokasi → balas satu dict. Normalisasi jadi list.
            results = data if isinstance(data, list) else [data]
            for (key, _, _), loc_data in zip(todo, results):
                _cache_set(key, loc_data)
            return
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429:
                retry_after = r.headers.get('Retry-After')
                time.sleep(int(retry_after) + 1 if retry_after else 5 * (attempt + 1))
                last_err = e
            else:
                last_err = e
                break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            time.sleep(2 * (attempt + 1))
            last_err = e
        except Exception as e:
            last_err = e
            break
    # kalau batch gagal, biarkan — fetch_wind akan fallback per-lokasi
    if last_err:
        print(f"[prefetch] batch gagal, fallback per-waypoint: {last_err}")


def _fetch_all_levels(lat, lon):
    """Fetch data GFS untuk satu lokasi. Dengan rate limiting dan cache."""
    key = (round(lat, 3), round(lon, 3))
    
    # Cek cache dulu
    cached = _cache_get(key)
    if cached is not None:
        return cached
    
    # Rate limiting
    _rate_limiter.wait_if_needed()
    
    url = "https://api.open-meteo.com/v1/gfs"
    hourly = _build_hourly_params()
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": hourly,
        "wind_speed_unit": "kn",
        "forecast_days": 3,
        "timezone": "UTC"
    }
    
    last_err = None
    for attempt in range(8):  # ↑ dari 4 menjadi 8
        try:
            r = _SESSION.get(url, params=params, timeout=60)  # ↑ timeout 30→60
            r.raise_for_status()
            data = r.json()
            _cache_set(key, data)
            return data
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429:
                # 429 Too Many Requests - tunggu lebih lama dan coba lagi
                retry_after = r.headers.get('Retry-After')
                if retry_after:
                    sleep_time = int(retry_after) + 1
                else:
                    sleep_time = 5 * (attempt + 1)  # exponential: 5, 10, 15, ...
                time.sleep(sleep_time)
                last_err = e
            else:
                last_err = e
                break  # error selain 429, berhenti
        except requests.exceptions.Timeout:
            # Timeout - coba lagi dengan delay
            sleep_time = 2 * (attempt + 1)
            time.sleep(sleep_time)
            last_err = e
        except requests.exceptions.ConnectionError:
            # Connection error - coba lagi dengan delay
            sleep_time = 3 * (attempt + 1)
            time.sleep(sleep_time)
            last_err = e
        except Exception as e:
            last_err = e
            break
    
    if last_err is not None:
        raise last_err
    raise RuntimeError("Unknown error fetching GFS data")


def fetch_wind(lat, lon, hpa, target_time):
    """Ambil data wind untuk satu level tekanan tertentu."""
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
        "temp": data["hourly"].get(f"temperature_{hpa}hPa", [None])[idx]
                if f"temperature_{hpa}hPa" in data["hourly"] else None,
        "time": times[idx],
    }


# ---------- Analisa rute ----------
def analyze_route(route, fl=None, target_time=None, use_profile=False):
    """
    Analisa angin per waypoint.
      use_profile=False : semua waypoint pakai satu 'fl' (mode cruise).
      use_profile=True  : climb & descent ikut FL dari CSV, TAPI waypoint
                          yang berada di cruise (FL tertinggi rute) diganti
                          ke 'fl' pilihan slider. Jadi kamu bisa eksperimen
                          "profil OFP tapi cruise di FL sekian".
    Kembalikan (rows, summary).
    """
    rows = []
    total_dist, wc_sum = 0.0, 0.0
    n = len(route)

    # OPTIMASI: tarik semua waypoint sekaligus (1 request), bukan 18 request.
    prefetch_route(route)

    # Tentukan cruise FL asli dari CSV = FL tertinggi di rute.
    # Waypoint dengan FL == cruise_fl dianggap fase cruise → ikut slider.
    csv_fls = [wp.get('fl') for wp in route if wp.get('fl')]
    cruise_fl_csv = max(csv_fls) if csv_fls else None

    for i, wp in enumerate(route):
        name, lat, lon = wp['ident'], wp['lat'], wp['lon']
        wp_fl = wp.get('fl')

        # tentukan FL untuk waypoint ini
        if use_profile:
            if wp_fl is None:
                # CSV tanpa data FL. Departure (waypoint pertama) & arrival
                # (terakhir) ada di permukaan → pakai level terendah, BUKAN cruise.
                if i == 0 or i == n - 1:
                    wfl = 50   # ~permukaan (level GFS terendah yang dipakai)
                else:
                    wfl = fl or 330   # tengah tanpa FL → fallback slider
            elif cruise_fl_csv and wp_fl >= cruise_fl_csv - 5:
                # waypoint fase cruise → pakai FL pilihan slider
                wfl = fl or wp_fl
            else:
                # climb/descent → tetap ikut CSV
                wfl = wp_fl
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
        oat = w.get("temp")
        isa_dev = (round(oat - isa_temp(alt_ft)) if oat is not None else None)
        rows.append({
            "ident": name,
            "lat": lat,
            "lon": lon,
            "fl": fl_key,
            "track": round(trk),
            "dist": round(dist),
            "wind_dir": round(w["dir"]),
            "wind_spd": round(w["spd"]),
            "headwind": round(head),
            "crosswind": round(cross),
            "oat": round(oat) if oat is not None else None,
            "isa_dev": isa_dev,
        })
        if i < n - 1:
            total_dist += dist
            wc_sum += head * dist

    avg_wc = wc_sum / total_dist if total_dist else 0
    summary = {
        "mode": "profile" if use_profile else "cruise",
        "fl": nearest_fl_key(fl) if fl else None,
        "cruise_fl": nearest_fl_key(fl) if (use_profile and fl) else (
            nearest_fl_key(fl) if fl and not use_profile else None),
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
        out.append({
            "fl": nearest_fl_key(fl),
            "avg_wc": s["avg_wc"],
            "label": s["avg_wc_label"],
            "type": s["wind_type"]
        })
    best = min(out, key=lambda x: x["avg_wc"]) if out else None
    return out, best


# =============================================================================
# METAR / TAF — cuaca bandara (dari Aviation Weather Center, NOAA)
# Sumber: aviationweather.gov (gratis, tanpa API key)
# =============================================================================

def is_icao_airport(ident):
    """
    Tebak apakah sebuah ident adalah kode ICAO bandara (4 huruf).
    Waypoint enroute biasanya 5 huruf (TAVIP) atau ada angka (LL623).
    Bandara ICAO: 4 huruf, huruf semua (WIII, WALL, WAAA, WAOO).
    """
    return (len(ident) == 4 and ident.isalpha() and ident.isupper())


def extract_airports(route):
    """Ambil daftar kode ICAO bandara dari rute (waypoint 4-huruf)."""
    seen = []
    for wp in route:
        ident = wp['ident'] if isinstance(wp, dict) else wp[0]
        if is_icao_airport(ident) and ident not in seen:
            seen.append(ident)
    return seen


def fetch_metar_taf(icao_list):
    """
    Ambil METAR & TAF untuk daftar ICAO dari aviationweather.gov.
    Return dict: {icao: {"metar": raw, "taf": raw}}.
    Kalau data tak tersedia, value-nya None.
    """
    result = {}
    if not icao_list:
        return result
    ids = ",".join(icao_list)

    # METAR (format raw text)
    metars = {}
    try:
        _rate_limiter.wait_if_needed()
        r = _SESSION.get("https://aviationweather.gov/api/data/metar",
                         params={"ids": ids, "format": "raw", "hours": 2},
                         timeout=30)
        r.raise_for_status()
        for line in r.text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            tokens = line.split()
            # METAR bisa diawali "METAR"/"SPECI" lalu kode ICAO, atau langsung kode.
            # Cari kode ICAO yang cocok dari daftar di 2 token pertama.
            code = None
            for tok in tokens[:2]:
                if tok in icao_list:
                    code = tok
                    break
            if code is None:
                # fallback: token pertama yang bukan METAR/SPECI
                for tok in tokens[:2]:
                    if tok not in ("METAR", "SPECI"):
                        code = tok
                        break
            if code and code not in metars:
                metars[code] = line
    except Exception as e:
        print(f"[metar] gagal: {e}")

    # TAF (format raw text)
    tafs = {}
    try:
        _rate_limiter.wait_if_needed()
        r = _SESSION.get("https://aviationweather.gov/api/data/taf",
                         params={"ids": ids, "format": "raw"},
                         timeout=30)
        r.raise_for_status()
        blocks = r.text.strip().split("\n")
        current_code = None
        for line in blocks:
            line = line.strip()
            if not line:
                continue
            # baris TAF baru mulai dengan "TAF" atau kode ICAO
            first = line.split()[0] if line.split() else ""
            if first == "TAF":
                parts = line.split()
                current_code = parts[1] if len(parts) > 1 else None
                if current_code:
                    tafs[current_code] = line
            elif first in icao_list:
                current_code = first
                tafs[current_code] = line
            elif current_code:
                tafs[current_code] += " " + line
    except Exception as e:
        print(f"[taf] gagal: {e}")

    for icao in icao_list:
        result[icao] = {
            "metar": metars.get(icao),
            "taf": tafs.get(icao),
        }
    return result


# ---- Decoder METAR sederhana (bahasa manusia) ----
_CLOUD = {"FEW": "sedikit awan (1-2/8)", "SCT": "awan tersebar (3-4/8)",
          "BKN": "awan banyak (5-7/8)", "OVC": "tertutup awan (8/8)",
          "NSC": "tak ada awan signifikan", "SKC": "cerah", "CLR": "cerah",
          "CAVOK": "cerah, jarak pandang bagus (CAVOK)"}
_WX = {"RA": "hujan", "SHRA": "hujan lokal", "TS": "badai petir",
       "TSRA": "badai petir + hujan", "DZ": "gerimis", "BR": "kabut tipis",
       "HZ": "haze/asap", "FG": "kabut tebal", "FU": "asap", "VCTS": "badai di sekitar",
       "CB": "awan cumulonimbus (badai)"}


def decode_metar(raw):
    """Decode METAR mentah jadi ringkasan bahasa Indonesia."""
    if not raw:
        return "Data METAR tidak tersedia."
    parts = raw.split()
    out = []
    for p in parts:
        # Angin: 04013KT atau 04013G25KT atau VRB08KT
        if (p.endswith("KT") and (p[:3].isdigit() or p.startswith("VRB"))):
            if p.startswith("VRB"):
                spd = p[3:5]
                out.append(f"Angin variabel {spd}kt")
            else:
                d = p[:3]; spd = p[3:5]
                gust = ""
                if "G" in p:
                    gust = f" (gust {p[p.index('G')+1:p.index('G')+3]}kt)"
                out.append(f"Angin {d}° {spd}kt{gust}")
        # Visibility: 8000, 9999, atau CAVOK
        elif p == "CAVOK":
            out.append("CAVOK (cerah, visibility ≥10km)")
        elif p.isdigit() and len(p) == 4:
            vis = int(p)
            vis_txt = "≥10km" if vis >= 9999 else f"{vis}m"
            out.append(f"Visibility {vis_txt}")
        # Awan: FEW020, SCT025, BKN008, dst
        elif p[:3] in _CLOUD and len(p) >= 6 and p[3:6].isdigit():
            alt = int(p[3:6]) * 100
            cb = " (CB)" if p.endswith("CB") else ""
            out.append(f"{_CLOUD[p[:3]]} di {alt}ft{cb}")
        elif p in _CLOUD:
            out.append(_CLOUD[p])
        # Cuaca signifikan
        elif p in _WX:
            out.append(_WX[p])
        elif p.lstrip("+-") in _WX:
            pre = "hujan lebat " if p.startswith("+") else "ringan " if p.startswith("-") else ""
            out.append(pre + _WX[p.lstrip("+-")])
        # Suhu/dewpoint: 32/25 atau 30/M02
        elif "/" in p and len(p) <= 7 and (p[0].isdigit() or p[0] == "M"):
            t, d = p.split("/")
            t = t.replace("M", "-"); d = d.replace("M", "-")
            if t.lstrip("-").isdigit():
                out.append(f"Suhu {t}°C / dewpoint {d}°C")
        # QNH: Q1008 atau A2992
        elif p.startswith("Q") and p[1:].isdigit():
            out.append(f"QNH {p[1:]} hPa")
        elif p.startswith("A") and p[1:].isdigit():
            out.append(f"Altimeter {p[1:3]}.{p[3:]} inHg")
        elif p == "NOSIG":
            out.append("Tidak ada perubahan signifikan (NOSIG)")
    return " · ".join(out) if out else "Tidak bisa decode."
