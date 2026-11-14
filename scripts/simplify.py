"""Make a small, web-friendly copy of the ecoregion GeoJSON.

Usage:  python scripts/simplify.py [tolerance_degrees]
Reads   data/ecoregion.geojson       (NEF terrestrial ecoregions v2.2, ~13.5 MB)
Writes  data/ecoregions.min.geojson  (simplified, one MultiPolygon per ecoregion, ~1 MB)

Uses only the Python standard library (Douglas-Peucker per ring).
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "ecoregion.geojson"
DST = ROOT / "data" / "ecoregions.min.geojson"
TOL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.01  # degrees (~1 km)


def douglas_peucker(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    tol2 = tol * tol
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        best, best_i = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if seg == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best:
                best, best_i = d, i
        if best > tol2:
            keep[best_i] = True
            stack += [(a, best_i), (best_i, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(r):
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2


def geodesic_ring_area_km2(ring):
    """Area of a lon/lat ring on a sphere (R = 6371 km)."""
    R = 6371.0088
    total = 0.0
    for i in range(len(ring) - 1):
        lon1, lat1 = map(math.radians, ring[i])
        lon2, lat2 = map(math.radians, ring[i + 1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total) * R * R / 2


def polygon_area_km2(rings):
    # outer ring minus holes, measured on the full-resolution geometry
    return geodesic_ring_area_km2(rings[0]) - sum(geodesic_ring_area_km2(r) for r in rings[1:])


def simplify_polygon(rings):
    out = []
    for i, ring in enumerate(rings):
        if i > 0 and ring_area(ring) < 4 * TOL * TOL:
            continue  # drop holes too small to see
        s = douglas_peucker(ring, TOL)
        if len(s) < 4:
            if i > 0:
                continue
            s = ring  # never lose an outer ring
        out.append([[round(x, 4), round(y, 4)] for x, y in s])
    return out


def main():
    src = json.loads(SRC.read_text(encoding="utf-8"))
    merged = {}
    for f in src["features"]:
        p = f["properties"]
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        rid = p["ECOREGION_ID"]
        m = merged.setdefault(rid, {
            "type": "Feature",
            "id": rid,
            "properties": {
                "id": rid,
                "zone": p["ECOZONE_ID"],
                "province": round(p["ECOPROVINCE_ID"], 1),
                "name_en": p["ECOREGION_NAME_EN"].strip(),
                "name_fr": p["ECOREGION_NAME_FR"].strip(),
                "area_km2": 0,
            },
            "geometry": {"type": "MultiPolygon", "coordinates": []},
        })
        # SHAPE_Area in the source is inflated at high latitudes, so measure it ourselves
        m["properties"]["area_km2"] += sum(polygon_area_km2(poly) for poly in polys)
        m["geometry"]["coordinates"] += [simplify_polygon(poly) for poly in polys]

    feats = sorted(merged.values(), key=lambda f: f["id"])
    for f in feats:
        f["properties"]["area_km2"] = round(f["properties"]["area_km2"])
    DST.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{len(src['features'])} polygons -> {len(feats)} ecoregions, wrote {DST.name} "
          f"({DST.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
