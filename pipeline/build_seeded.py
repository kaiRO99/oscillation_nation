"""Build data/seeded.json: how much of each crop was actually seeded, by region and year.

Why: the crop-yield layer (data/yield.json) is modelled — provincial / regional yields given to
every Soil Landscape polygon — so it reports a yield even where a crop is barely grown. Seeded
area is the context: if almost nothing went in the ground, the yield there is noise. The map uses
it for a standalone "Seeded area" layer, to fade the yield layer in years / regions where the crop
was hardly planted, and as the "effort" axis of the "Seeded area vs result" view.

Resolution: Statistics Canada publishes seeded area by Small Area Data Region (SADR, the Census
Agricultural Regions), not by ecodistrict. Each ecodistrict is assigned, year by year, the SADR that
most of its Soil Landscape polygons fall in that year (the yield CSV records each polygon's region
per year). Region definitions change over time, so the assignment has to be per year:
  * Saskatchewan replaced its 20 regions with 17 census-division regions in 2017. StatCan lists the
    two sets under separate labels that reuse the numbers 1-17, so they are kept as separate series
    (key "47NN" up to 2016, "47NNb" from 2017) rather than spliced.
  * Quebec renumbered its regions in 1993, 1998 and 2003; StatCan has Quebec only from 2007, under
    the current regions.
  * A handful of Alberta / Manitoba polygons move region in 1993.
Coverage: Prairies, BC (from 1991), Ontario, Quebec (from 2007). A region can be large (BC
"Non Peace" is all of BC outside the Peace River), so region-level seeded area says nothing about
whether a particular ecodistrict in it is farmed — the map uses the crop inventory for that.

Province totals: the regional table only covers the crops each province reports by region (Ontario
has no wheat rows at all), so a missing regional figure can't tell "not grown" from "not reported".
The complete provincial table (StatCan 32-10-0359, every principal crop, every province) answers
"was this crop grown in this province this year?" for every yield crop except potatoes. Any missing
provincial figure ("..", "F", "x", or no row) is stored as null; the map treats null or under
1,000 ha province-wide as "not really grown here".

Usage:  python scripts/build_seeded.py        # downloads the StatCan tables if missing
Reads   data/raw/historicalEstimatedCropYieldSlc.csv (or data/)  ecodistrict -> SADR, per year
        data/raw/sad_crops.zip     StatCan 32-10-0002 (by region), auto-downloaded
        data/raw/prov_crops.zip    StatCan 32-10-0359 (by province), auto-downloaded
Writes  data/seeded.json
            {"units":"ha","y0","y1","crops":[[code,label]...],
             "cars":{key:[[ha per year] per crop]},
             "eco2car":{ecoid:[[first year, key or null], ...]},   runs of years, in order
             "prov":{yield crop code:{province:[ha per year]}}}    province totals
"""
import csv
import io
import json
import re
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YIELD_NAME = "historicalEstimatedCropYieldSlc.csv"
YIELD_CSV = next((p for p in (ROOT / "data" / "raw" / YIELD_NAME, ROOT / "data" / YIELD_NAME) if p.exists()),
                 ROOT / "data" / "raw" / YIELD_NAME)
ZIP = ROOT / "data" / "raw" / "sad_crops.zip"
ZIP_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100002-eng.zip"
PROV_ZIP = ROOT / "data" / "raw" / "prov_crops.zip"
PROV_ZIP_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100359-eng.zip"
OUT = ROOT / "data" / "seeded.json"

# yield.json crop code -> StatCan 32-10-0359 "Type of crop" (province totals).
# Alfalfa is the bulk of tame hay, so it uses the tame-hay area; potatoes aren't in the table.
PROV_CROP = {
    "WHTSPG": "Wheat, spring", "WHTDUR": "Wheat, durum", "WHTWINT": "Wheat, winter remaining",
    "BARLEY": "Barley", "OATS": "Oats", "CANOLA": "Canola (rapeseed)", "FLAXSD": "Flaxseed",
    "SUNFLS": "Sunflower seed", "SOYBNS": "Soybeans", "CORNGR": "Corn for grain",
    "DFPEAS": "Peas, dry", "LENTIL": "Lentils", "OHAYFD": "Tame hay", "ALFALFA": "Tame hay",
}
PROV_ABBR = {
    "Newfoundland and Labrador": "NL", "Prince Edward Island": "PE", "Nova Scotia": "NS",
    "New Brunswick": "NB", "Quebec": "QC", "Ontario": "ON", "Manitoba": "MB",
    "Saskatchewan": "SK", "Alberta": "AB", "British Columbia": "BC",
}

# StatCan "Type of crop" name -> yield.json crop code (and display order).
# Potatoes, hay and alfalfa are not "principal field crops" in this table, so they have no
# seeded-area context.
CROPS = [
    ("Wheat, spring", "WHTSPG", "Spring wheat"),
    ("Wheat, durum", "WHTDUR", "Durum wheat"),
    ("Wheat, winter remaining", "WHTWINT", "Winter wheat"),
    ("Barley", "BARLEY", "Barley"),
    ("Oats", "OATS", "Oats"),
    ("Canola", "CANOLA", "Canola"),
    ("Flaxseed", "FLAXSD", "Flaxseed"),
    ("Soybeans", "SOYBNS", "Soybeans"),
    ("Corn for grain", "CORNGR", "Grain corn"),
    ("Peas, dry", "DFPEAS", "Dry peas"),
    ("Lentils", "LENTIL", "Lentils"),
    ("Sunflower seed", "SUNFLS", "Sunflower seed"),
]
NAME_TO_CODE = {name: code for name, code, _ in CROPS}
CODE_ORDER = [code for _, code, _ in CROPS]

# province name (as it appears after " - " in a SADR label) -> Standard Geographical Code
PROV_SGC = {
    "Québec": 24, "Quebec": 24, "Ontario": 35, "Manitoba": 46,
    "Saskatchewan": 47, "Alberta": 48, "British Columbia": 59,
}


def geo_to_key(geo):
    """StatCan GEO label -> series key, or None.

    The key is the SADREGION code (province SGC * 100 + region number), e.g.
    'Small Area Data Region 41 - Alberta' -> '4841', 'Non Peace, 1 - British Columbia' -> '5901'.
    Saskatchewan's 2017+ census-division regions ('... (corresponds to Census Division N from 2016
    Census of Agriculture)') reuse the old numbers for different areas, so they get a 'b' suffix.
    Bare province labels ('Alberta') and anything unrecognised return None.
    """
    if " - " not in geo:
        return None
    head, prov = geo.rsplit(" - ", 1)
    prov = prov.strip()
    later_set = "(" in prov
    prov = re.sub(r"\s*\(.*\)\s*$", "", prov)
    sgc = PROV_SGC.get(prov)
    if sgc is None:
        return None
    nums = re.findall(r"\d+", head)
    if not nums:
        return None
    return f"{sgc * 100 + int(nums[-1])}{'b' if later_set else ''}"


def ecodistrict_region_by_year():
    """{ecodistrict: {year: SADREGION code most of its polygons are in that year}}."""
    counts = defaultdict(lambda: defaultdict(Counter))
    with YIELD_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sadr = row.get("SADREGION", "").strip()
            if sadr:
                counts[int(row["ECODISTRIC"])][int(row["YEAR"])][int(sadr)] += 1
    # most polygons; break ties on the lower code so the output is deterministic
    return {eco: {y: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for y, c in by_year.items()}
            for eco, by_year in counts.items()}


def ensure_zip(path, url):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url} ...")
    urllib.request.urlretrieve(url, path)
    print(f"  saved {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")


def province_totals(y0, y1):
    """{yield crop code: {province: [seeded ha per year y0..y1, None where not published]}}."""
    by_name = defaultdict(lambda: defaultdict(dict))
    with zipfile.ZipFile(PROV_ZIP) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv") and "MetaData" not in n)
        f = io.TextIOWrapper(z.open(name), encoding="utf-8-sig")
        for row in csv.DictReader(f):
            if row["Harvest disposition"] != "Seeded area (hectares)":
                continue
            prov = PROV_ABBR.get(row["GEO"])
            year = int(row["REF_DATE"][:4])
            v = row["VALUE"].strip()
            if not prov or not y0 <= year <= y1 or not v:
                continue
            by_name[row["Type of crop"]][prov][year] = round(float(v))
    out = {}
    for code, crop_name in PROV_CROP.items():
        out[code] = {prov: [by_name[crop_name][prov].get(y) for y in range(y0, y1 + 1)]
                     for prov in PROV_ABBR.values()}
    return out


def main():
    if not YIELD_CSV.exists():
        raise SystemExit(f"missing {YIELD_CSV.relative_to(ROOT)} (see the build_yield.py docstring)")
    ensure_zip(ZIP, ZIP_URL)
    ensure_zip(PROV_ZIP, PROV_ZIP_URL)

    region_by_year = ecodistrict_region_by_year()

    # cars[key][code] = {year: hectares}
    cars = defaultdict(lambda: defaultdict(dict))
    years = set()
    with zipfile.ZipFile(ZIP) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv") and "MetaData" not in n)
        f = io.TextIOWrapper(z.open(name), encoding="utf-8-sig")
        for row in csv.DictReader(f):
            if row["Harvest disposition"] != "Seeded area (hectares)":
                continue
            code = NAME_TO_CODE.get(row["Type of crop"])
            if not code:
                continue
            key = geo_to_key(row["GEO"])
            if key is None:
                continue
            v = row["VALUE"].strip()
            if not v:
                continue
            try:
                ha = round(float(v))
            except ValueError:
                continue
            year = int(row["REF_DATE"])
            years.add(year)
            if year in cars[key][code]:
                raise SystemExit(f"two StatCan rows map to {key} {code} {year}: check geo_to_key")
            cars[key][code][year] = ha

    y0, y1 = min(years), max(years)
    span = y1 - y0 + 1

    out_cars = {}
    published = defaultdict(set)  # key -> years with any seeded figure
    for key, per in cars.items():
        rows = []
        for code in CODE_ORDER:
            series = [None] * span
            for year, ha in per.get(code, {}).items():
                series[year - y0] = ha
                published[key].add(year)
            rows.append(series)
        if published[key]:
            out_cars[key] = rows

    # ecodistrict -> region key, year by year, compressed to runs [[first year, key or None], ...].
    # The yield CSV ends a year before the StatCan table; later years reuse its last assignment.
    eco_out = {}
    for eco, by_year in region_by_year.items():
        known = sorted(by_year)
        runs = []
        for year in range(y0, y1 + 1):
            src = year if year in by_year else max((y for y in known if y <= year), default=known[0])
            code = by_year[src]
            key = next((k for k in (str(code), f"{code}b") if year in published.get(k, ())), None)
            if not runs or runs[-1][1] != key:
                runs.append([year, key])
        if any(k is not None for _, k in runs):
            eco_out[str(eco)] = runs

    doc = {
        "source": "Statistics Canada table 32-10-0002, Estimated areas, yield and production "
                  "of principal field crops by Small Area Data Regions. Open Government Licence - Canada. "
                  "Each ecodistrict takes the Small Area Data Region most of its Soil Landscape "
                  "polygons fall in.",
        "units": "ha",
        "y0": y0, "y1": y1,
        "crops": [[code, label] for _, code, label in CROPS],
        "cars": out_cars,
        "eco2car": eco_out,
        "prov": province_totals(y0, y1),
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} kB): "
          f"{len(out_cars)} regions, {len(eco_out)} ecodistricts linked, "
          f"{len(CROPS)} crops, years {y0}-{y1}")


if __name__ == "__main__":
    main()
