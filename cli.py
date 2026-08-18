#!/usr/bin/env python3
"""
cli.py — Versi terminal (buat yang suka command line)
=====================================================
    python cli.py routes/WIII-WALL.csv
    python cli.py routes/WIII-WAAA.csv --fl 300
    python cli.py routes/WIII-WAOO.csv --compare
    python cli.py routes/WIII-WALL.csv --hours 12
"""
import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

import wind_core as wc


def main():
    ap = argparse.ArgumentParser(description="Analisa angin enroute (GFS) — CLI")
    ap.add_argument("route_csv", help="File CSV rute")
    ap.add_argument("--fl", type=int, default=330)
    ap.add_argument("--hours", type=int, default=1)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--profile", action="store_true",
                    help="Pakai FL per-waypoint dari CSV (climb/cruise/descent)")
    args = ap.parse_args()

    if not os.path.exists(args.route_csv):
        sys.exit(f"File tidak ditemukan: {args.route_csv}")

    route = wc.load_route(args.route_csv)
    if len(route) < 2:
        sys.exit("Rute butuh minimal 2 waypoint.")
    name = os.path.splitext(os.path.basename(args.route_csv))[0].upper()

    tgt = (datetime.now(timezone.utc) + timedelta(hours=args.hours)
           ).replace(minute=0, second=0, microsecond=0)

    if args.compare:
        print(f"\n Rute: {name} ({len(route)} wpt)")
        results, best = wc.compare_altitudes(route, tgt)
        print(f"\n{'FL':>6}{'AVG W/C':>12}{'Jenis':>12}")
        print("-"*30)
        for r in results:
            print(f"FL{r['fl']:03d}{r['avg_wc']:>+9d} kt{r['type']:>12}")
        print("-"*30)
        if best:
            print(f" Angin terbaik: FL{best['fl']:03d} ({best['label']})\n")
        return

    rows, s = wc.analyze_route(route, fl=args.fl, target_time=tgt,
                               use_profile=args.profile)
    mode_lbl = "PROFIL OFP" if s["mode"] == "profile" else f"FL{s['fl']:03d}"
    print(f"\n{'='*74}")
    print(f" {name}  |  {mode_lbl}  |  {tgt.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*74}")
    print(f"{'WPT':<7}{'FL':>6}{'TRK':>5}{'DIST':>6}{'WIND':>9}{'H/W':>7}{'X/W':>7}{'OAT':>6}{'ISA':>6}")
    print("-"*74)
    for r in rows:
        xw = f"{abs(r['crosswind'])}{'R' if r['crosswind']>=0 else 'L'}"
        print(f"{r['ident']:<7}FL{r['fl']:03d}{r['track']:>5}{r['dist']:>6}"
              f"{r['wind_dir']:>4}/{r['wind_spd']:<4}"
              f"{r['headwind']:>+6}{xw:>7}{r['oat']:>6}{r['isa_dev']:>+6}")
    print("-"*74)
    print(f" Total {s['total_dist']} NM  |  AVG WIND COMP: {s['avg_wc_label']} kt "
          f"({s['wind_type']})\n")


if __name__ == "__main__":
    main()
