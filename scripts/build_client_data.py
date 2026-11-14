"""Merge the per-ecodistrict tables into the one file the map loads.

Usage:  python scripts/build_client_data.py
Reads   data/raw/ecodistrict_points.json (build_ecodistricts.py), data/raw/soil.json (fetch_soil.py),
        data/raw/crops.json (fetch_crops.py)
Writes  data/ecodistricts.json   {"d": {id: {region, region_name, zone, prov, area, lp, soil, crops}}, ...}
                                 crops is keyed by year; climate lives separately in data/climate/
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"


def main():
    pts = json.loads((RAW / "ecodistrict_points.json").read_text(encoding="utf-8"))
    soil = json.loads((RAW / "soil.json").read_text(encoding="utf-8"))
    crops_path = RAW / "crops.json"
    crops = json.loads(crops_path.read_text(encoding="utf-8")) if crops_path.exists() else {"years": [], "groups": [], "eco": {}}

    d = {}
    for i, p in sorted(pts.items(), key=lambda kv: int(kv[0])):
        s = soil["eco"].get(i)
        rec = {
            "region": p["region"], "region_name": p["region_name"], "zone": p["zone"],
            "area": p["area_km2"], "lp": p["label"],
        }
        if s:
            rec["prov"] = s["province"]
            rec["soil"] = {k: v for k, v in s.items() if k != "province"}
        c = crops["eco"].get(i)
        if c:
            # compact: year -> [crop %, pasture %, top class, group shares...]
            rec["crops"] = {y: [r["crop"], r["pasture"], r["top"]] + [r["groups"][g] for g in crops["groups"]]
                            for y, r in c.items()}
        d[i] = rec

    out = {
        "sources": {
            "boundaries": "AAFC National Ecological Framework v2.2 ecodistricts",
            "soil": "AAFC Soil Landscapes of Canada v3.2 + National Soil DataBase (area-weighted per ecodistrict)",
            "crops": "AAFC Annual Crop Inventory, computeHistograms per ecodistrict",
        },
        "soil_orders": soil["orders"],
        "soil_fields": {"awhc": "Available water holding capacity 0–100 cm (mm)", "sand": "Sand, 0–30 cm (%)",
                        "silt": "Silt, 0–30 cm (%)", "clay": "Clay, 0–30 cm (%)", "oc": "Organic carbon, 0–30 cm (%)",
                        "ph": "pH (CaCl2), 0–30 cm", "drainage": "Drainage class (1 very rapid – 7 very poor)",
                        "order": "Dominant soil order"},
        "crop_years": crops["years"],
        "crop_fields": ["crop", "pasture", "top"] + crops["groups"],
        "d": d,
    }
    dst = ROOT / "data" / "ecodistricts.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {dst.relative_to(ROOT)} ({dst.stat().st_size / 1e3:.0f} kB): {len(d)} ecodistricts, "
          f"{sum('soil' in r for r in d.values())} with soil, {sum('crops' in r for r in d.values())} with crops")


if __name__ == "__main__":
    main()
