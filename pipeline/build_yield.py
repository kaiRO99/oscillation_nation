"""Aggregate the SLC crop-yield table into the compact file the map loads.

Usage:  python scripts/build_yield.py
Reads   data/raw/historicalEstimatedCropYieldSlc.csv  (git-ignored; data/ is also accepted)
            AAFC "Estimated Historical Crop Yields in Canada by SLC": one row per Soil Landscape
            (SL) polygon, ecodistrict, province and year, with an estimated yield (kg/ha) per crop.
            Not in the repo (47 MB). Recover it with
              git show 43d0c3e:data/historicalEstimatedCropYieldSlc.csv > data/raw/historicalEstimatedCropYieldSlc.csv
Writes  data/yield.json
            {"units", "crops": [[code,label]...], "y0", "res": {code: resolution},
             "d": {ecoid: [[yield per year] per crop]}}
        Yields are averaged across the SLC polygons that make up each ecodistrict, rounded to
        whole kg/ha; a year with no data for a crop is null. The map reads each crop's series,
        shows the value for the slider's year, and compares it with that ecodistrict's own
        long-term average for the crop ("more / less than average").

Caveats the map has to respect:
  * Every SLC polygon gets a yield, farmed or not (the source downscales provincial / regional
    statistics). The map hides yield in non-farm ecodistricts using the crop inventory.
  * For many crops the "polygon" yield is one regional (Census Agricultural Region) or provincial
    figure copied to every polygon. "res" records, per crop, the finest level the values actually
    vary at: "local" (within regions), "region", or "province".
  * 2024 is a copy of 2021 rather than a new estimate: every polygon repeats its 2021 value for
    most crops (~57% of polygons for barley, oats and canola; alfalfa is genuine). A copy error like
    that hits the whole year, so a year is dropped (null) for a crop when at least COPY_SHARE of its
    polygons repeat the same earlier year AND at least half of all crops show that same copy.
    Single-crop matches are not dropped: for province / region-level crops (peas, lentils,
    sunflower) one provincial figure covers most polygons and can equal an earlier year by chance.
    They are listed as "suspect" instead. "dropped" lists [year, year it copies]; "last" is each
    crop's last real year.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC_NAME = "historicalEstimatedCropYieldSlc.csv"
SRC = next((p for p in (ROOT / "data" / "raw" / SRC_NAME, ROOT / "data" / SRC_NAME) if p.exists()),
           ROOT / "data" / "raw" / SRC_NAME)
DST = ROOT / "data" / "yield.json"
# a crop counts as "region" / "province" resolution when at least this share of region-years
# (province-years) has a single value across all of its polygons
SAME_SHARE = 0.8
# a crop-year is treated as a copy when at least this share of polygons repeat an earlier year exactly
COPY_SHARE = 0.5

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
    # distinct values per (crop, year, region) and (crop, year, province), to measure resolution
    by_region = defaultdict(set)
    by_prov = defaultdict(set)
    # raw polygon values per crop and year, to detect copied years
    poly = {code: defaultdict(dict) for code in CODES}
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
                by_region[(code, year, row["SADREGION"])].add(v)
                by_prov[(code, year, row["PROVINCE"])].add(v)
                poly[code][year][row["SL"]] = x
                slot = per.setdefault(code, {})
                s = slot.get(year)
                if s is None:
                    slot[year] = [x, 1]
                else:
                    s[0] += x
                    s[1] += 1

    y0, y1 = min(years), max(years)
    span = y1 - y0 + 1
    candidates = find_copied_years(poly, y0, y1)
    # a (year, source year) pair is systematic when at least half the crops repeat it
    pair_count = defaultdict(int)
    for found in candidates.values():
        for y, src in found.items():
            pair_count[(y, src)] += 1
    systematic = {p for p, n in pair_count.items() if n >= len(CODES) / 2}
    dropped = {code: {y: src for y, src in candidates[code].items() if (y, src) in systematic} for code in CODES}
    suspect = {code: {y: src for y, src in candidates[code].items() if (y, src) not in systematic} for code in CODES}
    out = {}
    for eco, per in acc.items():
        rows = []
        any_data = False
        for code in CODES:
            slot = per.get(code, {})
            series = [None] * span
            for year, (s, c) in slot.items():
                if year in dropped[code]:
                    continue
                series[year - y0] = round(s / c)
                any_data = True
            rows.append(series)
        if any_data:
            out[str(eco)] = rows
    last = {code: max(y0 + i for rows in out.values() for i, v in enumerate(rows[k]) if v is not None)
            for k, code in enumerate(CODES)}

    def same_share(groups, code):
        g = [vals for (c, _, _), vals in groups.items() if c == code]
        return sum(len(v) == 1 for v in g) / len(g) if g else 1.0

    res = {}
    for code in CODES:
        if same_share(by_prov, code) >= SAME_SHARE:
            res[code] = "province"
        elif same_share(by_region, code) >= SAME_SHARE:
            res[code] = "region"
        else:
            res[code] = "local"

    doc = {
        "source": "AAFC historical estimated crop yield by Soil Landscape of Canada polygon, "
                  "averaged per ecodistrict",
        "units": "kg/ha",
        "crops": [[c, l] for c, l in CROPS],
        "y0": y0,
        "res": res,
        "last": last,
        "dropped": {code: sorted([y, src] for y, src in dropped[code].items()) for code in CODES if dropped[code]},
        "suspect": {code: sorted([y, src] for y, src in suspect[code].items()) for code in CODES if suspect[code]},
        "d": out,
    }
    DST.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DST.relative_to(ROOT)} ({DST.stat().st_size / 1e6:.2f} MB): "
          f"{len(out)} ecodistricts, {len(CROPS)} crops, years {y0}-{y1}")
    for code in CODES:
        copies = ", ".join(f"{y}={src}" for y, src in sorted(dropped[code].items())) or "none"
        sus = ", ".join(f"{y}={src}" for y, src in sorted(suspect[code].items()))
        print(f"  {code:8s} {res[code]:8s} (one value per region in {same_share(by_region, code):.0%} "
              f"of region-years, per province in {same_share(by_prov, code):.0%}); last {last[code]}; "
              f"dropped: {copies}" + (f"; suspect, kept: {sus}" if sus else ""))


def find_copied_years(poly, y0, y1, min_polygons=50):
    """{crop: {year: earlier year it copies}} for crop-years where >= COPY_SHARE of polygons
    repeat an earlier year's value exactly."""
    out = {}
    for code, by_year in poly.items():
        sls = sorted({sl for vals in by_year.values() for sl in vals})
        col = {sl: i for i, sl in enumerate(sls)}
        arr = np.full((y1 - y0 + 1, len(sls)), np.nan)
        for year, vals in by_year.items():
            for sl, x in vals.items():
                arr[year - y0, col[sl]] = x
        found = {}
        for yi in range(1, arr.shape[0]):
            cur, prev = arr[yi], arr[:yi]
            both = ~np.isnan(prev) & ~np.isnan(cur)
            n = both.sum(axis=1)
            share = np.where(n >= min_polygons, ((prev == cur) & both).sum(axis=1) / np.maximum(n, 1), 0)
            j = int(share.argmax())
            if share[j] >= COPY_SHARE:
                found[y0 + yi] = y0 + j
        out[code] = found
    return out


if __name__ == "__main__":
    main()
