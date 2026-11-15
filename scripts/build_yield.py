"""Aggregate the SLC crop-yield table into the compact file the map loads.

Usage:  python scripts/build_yield.py
Reads   data/historicalEstimatedCropYieldSlc.csv
            one row per Soil Landscape (SL) polygon, ecodistrict, province and year,
            with an estimated yield (kg/ha) per crop code.
Writes  data/yield.json
            {"units", "crops": [[code,label]...], "y0", "d": {ecoid: [[yield per year] per crop]}}
        Yields are averaged across the SLC polygons that make up each ecodistrict, rounded to
        whole kg/ha; a year with no data for a crop is null. The map reads each crop's series,
        shows the value for the slider's year, and compares it with that ecodistrict's own
        long-term average for the crop ("more / less than average").
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "historicalEstimatedCropYieldSlc.csv"
DST = ROOT / "data" / "yield.json"

# Curated major field crops that cover (nearly) every ecodistrict and year, in display order.
# code -> label shown in the UI.
CROPS = [
    ("WHTSPG", "Spring wheat"),
    ("WHTDUR", "Durum wheat"),
    ("WHTWINT", "Winter wheat"),
    ("BARLEY", "Barley"),
    ("OATS", "Oats"),
    ("CANOLA", "Canola"),
    ("FLAXSD", "Flaxseed"),
    ("SOYBNS", "Soybeans"),
    ("CORNGR", "Grain corn"),
    ("DFPEAS", "Dry peas"),
    ("LENTIL", "Lentils"),
    ("SUNFLS", "Sunflower seed"),
    ("POTATS", "Potatoes"),
    ("OHAYFD", "Hay & fodder"),
    ("ALFALFA", "Alfalfa"),
]
CODES = [c for c, _ in CROPS]


def main():
    if not SRC.exists():
        raise SystemExit(f"missing {SRC.relative_to(ROOT)}")

    # acc[ecoid][code] = [sum, count] per year, keyed by year
    acc = {}
    years = set()
    with SRC.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            eco = int(row["ECODISTRIC"])
            year = int(row["YEAR"])
            years.add(year)
            per = acc.setdefault(eco, {})
            for code in CODES:
                v = row.get(code, "").strip()
                if not v:
                    continue
                try:
                    x = float(v)
                except ValueError:
                    continue
                slot = per.setdefault(code, {})
                s = slot.get(year)
                if s is None:
                    slot[year] = [x, 1]
                else:
                    s[0] += x
                    s[1] += 1

    y0, y1 = min(years), max(years)
    span = y1 - y0 + 1
    out = {}
    for eco, per in acc.items():
        rows = []
        any_data = False
        for code in CODES:
            slot = per.get(code, {})
            series = [None] * span
            for year, (s, c) in slot.items():
                series[year - y0] = round(s / c)
                any_data = True
            rows.append(series)
        if any_data:
            out[str(eco)] = rows

    doc = {
        "source": "AAFC historical estimated crop yield by Soil Landscape of Canada polygon, "
                  "averaged per ecodistrict",
        "units": "kg/ha",
        "crops": [[c, l] for c, l in CROPS],
        "y0": y0,
        "d": out,
    }
    DST.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DST.relative_to(ROOT)} ({DST.stat().st_size / 1e6:.2f} MB): "
          f"{len(out)} ecodistricts, {len(CROPS)} crops, years {y0}-{y1}")


if __name__ == "__main__":
    main()
