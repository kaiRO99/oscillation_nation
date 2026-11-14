"""Fetch the small lookup tables the map needs.

Usage:  python scripts/fetch_data.py
Writes  data/aci_classes.json  AAFC Annual Crop Inventory class table (value -> name, colour) and available years
        data/oni.json          NOAA CPC Oceanic Nino Index (3-month running mean SST anomaly, Nino 3.4)

The crop rasters themselves are not downloaded; the map streams them from AAFC's ImageServer.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACI = "https://agriculture.canada.ca/imagery-images/rest/services/annual_crop_inventory"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
UA = {"User-Agent": "oscillation-nation-data-script"}
SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8")


def fetch_aci():
    services = json.loads(get(f"{ACI}?f=json"))["services"]
    years = sorted(int(s["name"].split("/")[-1]) for s in services if s["type"] == "ImageServer")
    rr = urllib.parse.quote(json.dumps({"rasterFunction": "annual_crop_inventory"}))
    tables = {}
    for y in years:
        rat = json.loads(get(f"{ACI}/{y}/ImageServer/rasterAttributeTable?renderingRule={rr}&f=json"))
        rows = {}
        for f in rat["features"]:
            a = f["attributes"]
            rows[a["Value"]] = [a["ClassName"], "#%02x%02x%02x" % (a["Red"], a["Green"], a["Blue"])]
        tables[y] = rows
        print(f"ACI {y}: {len(rows)} classes")
    # the remapped class table is normally identical every year; store it once if so
    first = tables[years[0]]
    same = all(t == first for t in tables.values())
    out = {"years": years, "classes": {str(k): v for k, v in first.items()}} if same else \
          {"years": years, "classesByYear": {str(y): {str(k): v for k, v in t.items()} for y, t in tables.items()}}
    (ROOT / "data" / "aci_classes.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("class table identical across years:", same)


def fetch_oni():
    rows = []
    for line in get(ONI_URL).splitlines()[1:]:
        parts = line.split()
        if len(parts) == 4:
            rows.append({"season": parts[0], "year": int(parts[1]), "anom": float(parts[3])})
    (ROOT / "data" / "oni.json").write_text(json.dumps({
        "source": ONI_URL,
        "note": "ONI = 3-month running mean of ERSST.v5 SST anomalies in the Nino 3.4 region. "
                "El Nino: >= +0.5 for 5 consecutive overlapping seasons; La Nina: <= -0.5.",
        "seasons": SEASONS,
        "data": rows,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"ONI: {len(rows)} seasons, {rows[0]['year']}-{rows[-1]['year']} (last {rows[-1]['season']})")


if __name__ == "__main__":
    fetch_aci()
    fetch_oni()
