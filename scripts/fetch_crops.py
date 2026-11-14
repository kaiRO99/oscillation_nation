"""Share of each crop group per ecodistrict and year, from the AAFC Annual Crop Inventory (ACI).

Usage:  python scripts/fetch_crops.py [--years 2009-2025] [--pixel 250] [--workers 5]
Reads   data/ecodistricts.min.geojson, data/aci_classes.json, data/raw/soil.json (which ecodistricts to query)
Writes  data/raw/crops.json   per ecodistrict and year: cropland % of land, % of cropland per crop group,
                              pasture %, and the most common crop class
Caches  data/raw/aci/         one histogram response per ecodistrict and year

Uses the ImageServer computeHistograms operation (resampled to --pixel metres) with the same
"annual_crop_inventory" raster function as the map, so class values match data/aci_classes.json.
Source: AAFC Annual Crop Inventory, Open Government Licence - Canada. Standard library only.
"""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from geo import ring_area

ROOT = Path(__file__).resolve().parent.parent
ACI = "https://agriculture.canada.ca/imagery-images/rest/services/annual_crop_inventory"
CACHE = ROOT / "data" / "raw" / "aci"
DST = ROOT / "data" / "raw" / "crops.json"
UA = {"User-Agent": "oscillation-nation-data-script"}

# Crop groups (remapped class values, as in the map legend). Pasture and non-crop land cover are kept apart.
GROUPS = {
    "cereals": [15, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 66, 67],
    "corn": [29],
    "canola": [35, 32, 33, 34, 36, 37, 38, 39, 41],
    "soy": [40],
    "pulses": [42, 43, 44, 45, 46, 47, 48, 69],
    "veg": [49, 50, 51, 52, 53],
    "fruit": [54, 55, 56, 57, 58, 59, 60, 61, 62],
    "other": [10, 11, 24, 30, 31, 63, 64, 65, 68, 70],
}
PASTURE = [12, 13, 14]
NOT_LAND = [0, 1]  # cloud, water


def esri_rings(geom):
    """Outer rings only, clockwise (ESRI treats counter-clockwise rings as holes)."""
    rings = []
    for poly in geom["coordinates"]:
        r = poly[0]
        signed = sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))
        rings.append(r if signed < 0 else r[::-1])
    return rings


def histogram(did, year, rings, pixel):
    path = CACHE / f"{did}_{year}.json"
    if path.exists():
        return json.loads(path.read_text())
    q = {
        "geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryPolygon",
        "pixelSize": json.dumps({"x": pixel, "y": pixel, "spatialReference": {"wkid": 3857}}),
        "renderingRule": json.dumps({"rasterFunction": "annual_crop_inventory"}),
        "f": "json",
    }
    body = urllib.parse.urlencode(q).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(f"{ACI}/{year}/ImageServer/computeHistograms", data=body, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(5 * 2 ** attempt)
    else:
        raise RuntimeError(f"ACI kept failing for {did} {year}")
    if "histograms" in d and d["histograms"]:
        h = d["histograms"][0]
        lo = h["min"] + 0.5
        out = {str(round(lo + i)): c for i, c in enumerate(h["counts"]) if c}
    else:
        out = {"error": str(d.get("error", d))[:200]}
    path.write_text(json.dumps(out))
    return out


def summarise(counts):
    c = {int(k): v for k, v in counts.items() if k != "error"}
    land = sum(v for k, v in c.items() if k not in NOT_LAND)
    if land == 0:
        return None
    crop_vals = [v for g in GROUPS.values() for v in g]
    crop = sum(c.get(v, 0) for v in crop_vals)
    rec = {
        "crop": round(100 * crop / land, 1),
        "pasture": round(100 * sum(c.get(v, 0) for v in PASTURE) / land, 1),
        "groups": {g: round(100 * sum(c.get(v, 0) for v in vals) / crop, 1) if crop else 0 for g, vals in GROUPS.items()},
        "top": max(crop_vals, key=lambda v: c.get(v, 0)) if crop else None,
    }
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default=None, help="e.g. 2015-2025 (default: every ACI year)")
    ap.add_argument("--pixel", type=int, default=250, help="histogram resolution in Web Mercator metres")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    years = json.loads((ROOT / "data" / "aci_classes.json").read_text())["years"]
    if a.years:
        y0, y1 = map(int, a.years.split("-"))
        years = [y for y in years if y0 <= y <= y1]
    soil = json.loads((ROOT / "data" / "raw" / "soil.json").read_text())["eco"]
    feats = {f["id"]: f for f in json.loads((ROOT / "data" / "ecodistricts.min.geojson").read_text())["features"]}
    ids = sorted(int(i) for i in soil if int(i) in feats)  # agricultural ecodistricts (SLC v3.2 detail)
    jobs = [(d, y) for d in ids for y in years]
    print(f"{len(ids)} ecodistricts x {len(years)} years = {len(jobs)} histograms")

    CACHE.mkdir(parents=True, exist_ok=True)
    rings = {d: esri_rings(feats[d]["geometry"]) for d in ids}
    out = {}
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        res = ex.map(lambda j: histogram(j[0], j[1], rings[j[0]], a.pixel), jobs)
        for i, ((d, y), counts) in enumerate(zip(jobs, res), 1):
            s = summarise(counts)
            if s:
                out.setdefault(str(d), {})[str(y)] = s
            if i % 250 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} ({time.time() - t0:.0f} s)", flush=True)

    DST.write_text(json.dumps({"years": years, "groups": list(GROUPS), "eco": out}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DST.relative_to(ROOT)}: {len(out)} ecodistricts with crop data")


if __name__ == "__main__":
    main()
