# 🛩️ Wind Enroute — Analisa Angin dari GFS

Web app + tool untuk menarik angin enroute dari forecast **GFS (NOAA)** dan
menghitung wind component (headwind/tailwind), crosswind, OAT, dan ISA deviation
per waypoint — mirip navlog SimBrief, tapi buatan sendiri.

> **NOT FOR REAL WORLD NAVIGATION** — untuk latihan & simulasi.

## 📁 Struktur (semua dalam satu folder)

```
wind-enroute/
├── app.py            # Web app (Streamlit)
├── cli.py            # Versi terminal
├── ofp_to_csv.py     # Parser PDF OFP → CSV
├── wind_core.py      # Logika perhitungan & ambil data GFS
├── requirements.txt
├── routes/           # Arsip CSV rute
└── README.md
```

## 🔄 Alur Kerja

```
1. Generate OFP di SimBrief → simpan PDF
2. python ofp_to_csv.py OFP.pdf -o routes/RUTE.csv
3. streamlit run app.py
```

## 🖥️ Jalankan Lokal

```bash
pip install -r requirements.txt
python ofp_to_csv.py OFP.pdf -o routes/WIII-WALL.csv
streamlit run app.py
# atau terminal:
python cli.py routes/WIII-WALL.csv --profile
python cli.py routes/WIII-WALL.csv --compare
```

## 📊 Dua Mode Analisa

| Mode | Kegunaan |
|------|----------|
| **Profil OFP** | Tiap waypoint pakai altitude aslinya (climb/cruise/descent). Butuh kolom `fl`. |
| **Cruise (satu FL)** | Seluruh rute di satu FL. Untuk banding altitude. |

## ☁️ Deploy ke Streamlit Cloud

```bash
git add .
git commit -m "update"
git push
```
Lalu di share.streamlit.io: New app → pilih repo → app.py → Deploy.
Update berikutnya cukup `git push`, auto re-deploy.

## Sumber Data
- Angin & suhu: GFS (NOAA) via Open-Meteo API (gratis)
- Koordinat & FL: dari OFP SimBrief (bersumber AIP)
