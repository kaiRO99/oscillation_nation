"""Web-friendly ecodistrict boundaries plus the points used to sample gridded data in each one.

Usage:  python scripts/build_ecodistricts.py [--tol DEG] [--step DEG] [--max-points N]
Reads   data/raw/nef_ca_ter_ecodistrict_v2_2.geojson   (downloaded automatically, ~29 MB)
        data/ecoregions.min.geojson                   (ecoregion names)
Writes  data/ecodistricts.min.geojson   one simplified MultiPolygon per ecodistrict
        data/raw/ecodistrict_points.json  label point, area and NASA POWER sample points per ecodistrict

Source: AAFC National Ecological Framework for Canada v2.2, Open Government Licence - Canada.
"""
import argparse
import json
import urllib.request
from pathlib import Path

from geo import label_point, polygon_area_km2, sample_points, simplify_polygon

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://agriculture.canada.ca/atlas/data_donnees/nationalEcologicalFramework/data_donnees/"
       "geoJSON/ed/nef_ca_ter_ecodistrict_v2_2.geojson")
RAW = ROOT / "data" / "raw" / "nef_ca_ter_ecodistrict_v2_2.geojson"
DST = ROOT / "data" / "ecodistricts.min.geojson"
PTS = ROOT / "data" / "raw" / "ecodistrict_points.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=0.008, help="simplification tolerance in degrees")
    ap.add_argument("--step", type=float, default=0.5, help="POWER sample grid spacing in degrees (POWER is ~0.5 deg)")
    ap.add_argument("--max-points", type=int, default=4, help="cap on POWER sample points per ecodistrict")
    a = ap.parse_args()

    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        print("downloading", URL)
        req = urllib.request.Request(URL, headers={"User-Agent": "oscillation-nation-data-script"})
        with urllib.request.urlopen(req, timeout=600) as r:
            RAW.write_bytes(r.read())
    src = json.loads(RAW.read_text(encoding="utf-8"))
    regions = {f["id"]: f["properties"]["name_en"]
               for f in json.loads((ROOT / "data" / "ecoregions.min.geojson").read_text(encoding="utf-8"))["features"]}

    merged = {}
    for f in src["features"]:
        p = f["properties"]
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        did = int(p["ECODISTRICT_ID"])
        m = merged.setdefault(did, {
            "type": "Feature", "id": did,
            "properties": {"id": did, "region": int(p["ECOREGION_ID"]), "zone": int(p["ECOZONE_ID"]), "area_km2": 0},
            "geometry": {"type": "MultiPolygon", "coordinates": []},
        })
        m["properties"]["area_km2"] += sum(polygon_area_km2(poly) for poly in polys)
        m["geometry"]["coordinates"] += [simplify_polygon(poly, a.tol) for poly in polys]

    feats = sorted(merged.values(), key=lambda f: f["id"])
    points = {}
    for f in feats:
        p = f["properties"]
        p["area_km2"] = round(p["area_km2"])
        polys = f["geometry"]["coordinates"]
        points[str(f["id"])] = {
            "region": p["region"], "region_name": regions.get(p["region"], ""), "zone": p["zone"],
            "area_km2": p["area_km2"], "label": label_point(polys),
            "power": sample_points(polys, a.step, a.max_points),
        }

    DST.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    PTS.write_text(json.dumps(points, separators=(",", ":")), encoding="utf-8")
    n = [len(v["power"]) for v in points.values()]
    uniq = {tuple(p) for v in points.values() for p in v["power"]}
    print(f"{len(src['features'])} polygons -> {len(feats)} ecodistricts, wrote {DST.name} ({DST.stat().st_size / 1e6:.2f} MB)")
    print(f"POWER sample points: {len(uniq)} unique (min {min(n)}, max {max(n)} per ecodistrict)")


if __name__ == "__main__":
    main()
