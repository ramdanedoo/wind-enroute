#!/usr/bin/env python3
"""
ofp_to_csv.py — Ekstrak waypoint + koordinat dari PDF OFP SimBrief ke CSV
=========================================================================
Baca file PDF OFP SimBrief, ambil semua waypoint dari Flight Log (navlog),
lalu simpan sebagai CSV rapi yang bisa dibuka di Excel dan dipakai tool angin.

CARA PAKAI:
    pip install pdfplumber
    python ofp_to_csv.py OFP.pdf
    python ofp_to_csv.py OFP.pdf -o routes/WIII-WALL.csv    # tentukan nama output

Hasil CSV kolom:
    seq, ident, lat, lon, lat_str, lon_str
    (seq = urutan, ident = nama waypoint, lat/lon = desimal, *_str = format asli OFP)

CATATAN:
    - Otomatis skip titik non-navigasi seperti T O C / T O D (Top of Climb/Descent)
      bisa diaktifkan/dimatikan dengan --keep-toc
    - Untuk latihan & arsip pribadi. NOT FOR REAL WORLD NAVIGATION.
"""

import argparse
import csv
import os
import re
import sys

try:
    import pdfplumber
except ImportError:
    sys.exit("Butuh library 'pdfplumber'. Jalankan: pip install pdfplumber")


# Pola koordinat OFP: S0607.4 / E10639.7 / N0142.3 / W12005.6
# Lintang: 1 huruf (N/S) + DDMM.m   (2 digit derajat + menit)
# Bujur : 1 huruf (E/W) + DDDMM.m   (3 digit derajat + menit)
LAT_RE = re.compile(r'\b([NS])(\d{2})(\d{2}\.\d)\b')
LON_RE = re.compile(r'\b([EW])(\d{3})(\d{2}\.\d)\b')


def dms_to_decimal(hemi, deg, minutes):
    """Konversi hemisfer + derajat + menit -> desimal."""
    val = int(deg) + float(minutes) / 60.0
    if hemi in ('S', 'W'):
        val = -val
    return round(val, 5)


def clean_ident(raw):
    """Rapikan nama waypoint (buang spasi ganda, tangani 'T O C' -> 'TOC')."""
    ident = raw.strip()
    # T O C / T O D sering ter-spasi
    compact = ident.replace(' ', '')
    if compact in ('TOC', 'TOD'):
        return compact
    # Nama bandara panjang seperti "SOEKARNO-HA" biarkan apa adanya
    return ident


def parse_ofp(pdf_path, keep_toc=False):
    """
    Baca PDF OFP, kembalikan list waypoint: (ident, lat, lon, lat_str, lon_str).

    Strategi: navlog SimBrief menampilkan tiap waypoint dalam 2 baris.
      Baris 1: <IDENT> ... S0607.4 ...   (mengandung LAT)
      Baris 2: <IDENT/kosong> ... E10639.7 ...  (mengandung LON)
    Kita scan tiap baris; saat ketemu LAT simpan ident+lat, saat ketemu LON
    berikutnya pasangkan jadi satu waypoint.
    """
    waypoints = []
    seen = set()          # cegah duplikat (nama sama beruntun)
    pending = None        # menyimpan (lat, lat_str, toc_flag, fl) menunggu LON
    last_fl = None        # FL dari baris airway sebelum waypoint

    # FL muncul sebagai angka 3-digit di kolom awal baris airway (mis. "061", "330").
    # Range wajar 000-450. Kita tangkap dari baris yang TIDAK punya koordinat.
    fl_re = re.compile(r'^\s*\S*\s+(\d{3})\s')

    with pdfplumber.open(pdf_path) as pdf:
        in_navlog = False
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split('\n'):
                # Tandai mulai/berakhirnya bagian Flight Log
                if 'FLIGHT LOG' in line:
                    in_navlog = True
                    continue
                if in_navlog and ('WIND INFORMATION' in line or 'ATC Flight Plan' in line):
                    in_navlog = False
                if not in_navlog:
                    continue

                # Lewati penanda FIR & baris header
                if 'FIR' in line or 'POSITION' in line or 'IDENT' in line:
                    continue

                lat_m = LAT_RE.search(line)
                lon_m = LON_RE.search(line)

                # Baris airway (tanpa koordinat) → tangkap FL untuk waypoint berikutnya
                if not lat_m and not lon_m:
                    m = fl_re.match(line)
                    if m:
                        val = int(m.group(1))
                        if 0 <= val <= 450:
                            last_fl = val
                    continue

                if lat_m and not lon_m:
                    # baris LATITUDE → mulai waypoint baru.
                    before = line[:lat_m.start()].strip()
                    toc = clean_ident(before) in ('TOC', 'TOD')
                    lat = dms_to_decimal(lat_m.group(1), lat_m.group(2), lat_m.group(3))
                    pending = (lat, lat_m.group(0), toc, last_fl)

                elif lon_m and pending:
                    # baris LONGITUDE → token pertama = IDENT sebenarnya (WIII, PKY, BEMLO)
                    lat, lat_str, toc, fl = pending
                    lon = dms_to_decimal(lon_m.group(1), lon_m.group(2), lon_m.group(3))

                    tokens = line.split()
                    ident = tokens[0] if tokens else ""
                    # Buang penanda FIR yang diawali '-' (mis. -WAAF)
                    if ident.startswith('-'):
                        pending = None
                        continue
                    # Kalau token pertama = koordinat itu sendiri (mis. "E11023.0"),
                    # berarti baris ini tak punya ident → penanda FIR, lewati.
                    if LON_RE.match(ident) or LAT_RE.match(ident):
                        pending = None
                        continue

                    if toc:
                        ident = 'TOC' if 'C' in clean_ident(line[:lon_m.start()]) else 'TOD'
                        if not keep_toc:
                            pending = None
                            continue

                    if ident and ident not in seen:
                        waypoints.append((ident, lat, lon, lat_str, lon_m.group(0), fl))
                        seen.add(ident)
                    pending = None

    return waypoints


def guess_output_name(pdf_path, waypoints):
    """Tebak nama file output dari waypoint pertama & terakhir (asal-tujuan)."""
    if len(waypoints) >= 2:
        dep = waypoints[0][0]
        arr = waypoints[-1][0]
        # SOEKARNO-HA dll → biarkan, tapi kalau ada kode ICAO lebih baik
        return f"{dep}-{arr}.csv".replace(' ', '_')
    return "route.csv"


def write_csv(waypoints, out_path):
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['seq', 'ident', 'lat', 'lon', 'fl', 'lat_str', 'lon_str'])
        for i, (ident, lat, lon, ls, ns, fl) in enumerate(waypoints, 1):
            w.writerow([i, ident, lat, lon, fl if fl is not None else '', ls, ns])


def main():
    ap = argparse.ArgumentParser(
        description="Ekstrak waypoint dari PDF OFP SimBrief ke CSV")
    ap.add_argument("pdf", help="File PDF OFP SimBrief")
    ap.add_argument("-o", "--output", help="Nama file CSV output (opsional)")
    ap.add_argument("--keep-toc", action="store_true",
                    help="Ikutkan titik TOC/TOD (default: dibuang)")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f"File tidak ditemukan: {args.pdf}")

    print(f"Membaca OFP: {args.pdf} ...")
    wps = parse_ofp(args.pdf, keep_toc=args.keep_toc)

    if not wps:
        sys.exit("Tidak ada waypoint ditemukan. Pastikan ini PDF OFP SimBrief "
                 "dengan bagian Flight Log.")

    out = args.output or guess_output_name(args.pdf, wps)
    write_csv(wps, out)

    print(f"\n✓ Berhasil ekstrak {len(wps)} waypoint:")
    print(f"  {'SEQ':>3}  {'IDENT':<12}{'FL':>5}{'LAT':>11}{'LON':>12}")
    print("  " + "-"*45)
    for i, (ident, lat, lon, _, _, fl) in enumerate(wps, 1):
        fl_s = f"FL{fl:03d}" if fl is not None else "  -"
        print(f"  {i:>3}  {ident:<12}{fl_s:>5}{lat:>11.4f}{lon:>12.4f}")
    print("  " + "-"*45)
    print(f"\n✓ Disimpan ke: {out}")
    print(f"  Kolom 'fl' = altitude tiap waypoint (untuk profil climb/cruise/descent)")


if __name__ == "__main__":
    main()
