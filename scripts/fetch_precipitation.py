"""Monthly precipitation per ecoregion from NASA POWER, for the precipitation anomaly layer.

Usage:  python scripts/fetch_precipitation.py [--step DEG] [--max-points N] [--end YEAR] [--dry-run]
Reads   data/ecoregions.min.geojson
Writes  data/precip.json   growing-season (May-Sep) and winter (Dec-Feb) totals per ecoregion and year,
                           plus the 1991-2020 normal, so the map can show anomalies
Caches  data/raw/power/    one JSON response per sample point (safe to delete; reruns resume from it)

Precipitation is POWER's PRECTOTCORR (bias-corrected MERRA-2, ~0.5 deg), no login required.
Each ecoregion is sampled on a regular lon/lat grid (cos-latitude weighted), with at least one
point per ecoregion. Uses only the Python standard library.
"""
import argparse
import calendar
import json
import math
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "ecoregions.min.geojson"
DST = ROOT / "data" / "precip.json"
CACHE = ROOT / "data" / "raw" / "power"
POWER = "https://power.larc.nasa.gov/api/temporal/monthly/point"
UA = {"User-Agent": "oscillation-nation-data-script"}
START = 1990  # December 1990 is needed for the 1991 winter
NORMAL = (1991, 2020)
SEASONS = {"gs": [(0, m) for m in range(5, 10)],  # May-Sep of the same year
           "djf": [(-1, 12), (0, 1), (0, 2)]}     # Dec of the previous year, Jan-Feb


# ---------------------------------------------------------------------------
# Sample points
# ---------------------------------------------------------------------------
def in_ring(x, y, ring):
    c = False
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[i - 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
    return c


def in_multipolygon(x, y, polys):
    return any(in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]) for p in polys)


def grid_points(polys, step):
    xs = [x for p in polys for x, _ in p[0]]
    ys = [y for p in polys for _, y in p[0]]
    pts = []
    y = math.floor(min(ys) / step) * step + step / 2
    while y < max(ys):
        x = math.floor(min(xs) / step) * step + step / 2
        while x < max(xs):
            if in_multipolygon(x, y, polys):
                pts.append((round(x, 3), round(y, 3)))
            x += step
        y += step
    return pts


def sample_points(polys, step, max_points):
    pts = grid_points(polys, step)
    s = step
    while not pts and s > step / 64:  # small ecoregion: refine until something lands inside
        s /= 2
        pts = grid_points(polys, s)[:1]
    if not pts:  # last resort: a vertex of the largest outer ring
        ring = max((p[0] for p in polys), key=len)
        pts = [tuple(round(v, 3) for v in ring[0])]
    if len(pts) > max_points:  # thin evenly
        pts = [pts[round((i + 0.5) * len(pts) / max_points - 0.5)] for i in range(max_points)]
    return pts


# ---------------------------------------------------------------------------
# NASA POWER
# ---------------------------------------------------------------------------
def fetch_point(lon, lat, end):
    """Monthly precipitation totals (mm) at one point, keyed 'YYYYMM'."""
    path = CACHE / f"{lat:.3f}_{lon:.3f}_{START}_{end}.json"
    if path.exists():
        raw = json.loads(path.read_text())
    else:
        url = (f"{POWER}?parameters=PRECTOTCORR&community=AG&longitude={lon}&latitude={lat}"
               f"&start={START}&end={end}&format=JSON")
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                    raw = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429:
                    raise RuntimeError(f"POWER {e.code} for {lat},{lon}: {e.read()[:300]!r}") from e
                time.sleep(5 * 2 ** attempt)
            except (urllib.error.URLError, TimeoutError):
                time.sleep(5 * 2 ** attempt)
        else:
            raise RuntimeError(f"POWER kept failing for {lat},{lon}")
        path.write_text(json.dumps(raw))

    vals = raw["properties"]["parameter"]["PRECTOTCORR"]
    units = raw.get("parameters", {}).get("PRECTOTCORR", {}).get("units", "mm/day")
    fill = raw.get("header", {}).get("fill_value", -999)
    out = {}
    for k, v in vals.items():
        y, m = int(k[:4]), int(k[4:])
        if m > 12 or v is None or v == fill:  # month 13 is the annual value
            continue
        out[k] = v * calendar.monthrange(y, m)[1] if "day" in units else v
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def season_total(monthly, year, season):
    keys = [f"{year + dy}{m:02d}" for dy, m in SEASONS[season]]
    return sum(monthly[k] for k in keys) if all(k in monthly for k in keys) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=1.5, help="sample grid spacing in degrees")
    ap.add_argument("--max-points", type=int, default=8, help="cap on sample points per ecoregion")
    ap.add_argument("--end", type=int, default=date.today().year - 1, help="last (complete) year to fetch")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="only report sample point counts")
    a = ap.parse_args()

    feats = json.loads(SRC.read_text(encoding="utf-8"))["features"]
    points = {f["id"]: sample_points(f["geometry"]["coordinates"], a.step, a.max_points) for f in feats}
    unique = sorted({p for pts in points.values() for p in pts})
    print(f"{len(feats)} ecoregions, {len(unique)} sample points "
          f"(min {min(map(len, points.values()))}, max {max(map(len, points.values()))} per ecoregion)")
    if a.dry_run:
        return

    CACHE.mkdir(parents=True, exist_ok=True)
    data = {}
    with ThreadPoolExecutor(a.workers) as ex:
        for i, (p, monthly) in enumerate(zip(unique, ex.map(lambda p: fetch_point(*p, a.end), unique)), 1):
            data[p] = monthly
            if i % 25 == 0 or i == len(unique):
                print(f"  {i}/{len(unique)} points")

    years = list(range(START + 1, a.end + 1))
    eco = {}
    for rid, pts in points.items():
        w = [math.cos(math.radians(lat)) for _, lat in pts]
        rec = {"n": len(pts), "norm": {}}
        for s in SEASONS:
            series = []
            for y in years:
                v = [season_total(data[p], y, s) for p in pts]
                ok = [(vi, wi) for vi, wi in zip(v, w) if vi is not None]
                series.append(round(sum(vi * wi for vi, wi in ok) / sum(wi for _, wi in ok), 1) if ok else None)
            rec[s] = series
            base = [v for y, v in zip(years, series) if NORMAL[0] <= y <= NORMAL[1] and v is not None]
            rec["norm"][s] = round(sum(base) / len(base), 1) if base else None
        eco[str(rid)] = rec

    DST.write_text(json.dumps({
        "source": "NASA POWER, PRECTOTCORR (MERRA-2, bias-corrected), " + POWER,
        "note": "Precipitation totals in mm. gs = May-Sep of the year; djf = Dec of the previous year to Feb. "
                f"norm = {NORMAL[0]}-{NORMAL[1]} mean. Arrays are indexed by year starting at first_year.",
        "first_year": years[0],
        "last_year": years[-1],
        "normal": list(NORMAL),
        "eco": eco,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DST.name} ({DST.stat().st_size / 1e3:.0f} kB), {years[0]}-{years[-1]}")


if __name__ == "__main__":
    main()
