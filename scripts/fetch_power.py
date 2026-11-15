"""Monthly NASA POWER climate for every ecodistrict.

Usage:  python scripts/fetch_power.py [--start 1981] [--end 2026] [--split 2025] [--workers 4]
Reads   data/raw/ecodistrict_points.json   (from build_ecodistricts.py)
Writes  data/climate/<VAR>.bin             Int16 little-endian, [ecodistrict][month], value = int * scale,
                                           -32768 = missing; ecodistricts in data/ecodistricts.json order
        data/climate/meta.json             variables, units, scales, months, ecodistrict id order
Caches  data/raw/power/                    one JSON response per sample point and year range (reruns resume from
                                           it); years up to --split are one request, later years another, so a new
                                           year only re-downloads that year

Each ecodistrict is the cos(latitude)-weighted mean of its sample points (~0.5 deg MERRA-2 grid).
No login required. Uses numpy.
"""
import argparse
import calendar
import json
import math
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PTS = ROOT / "data" / "raw" / "ecodistrict_points.json"
CACHE = ROOT / "data" / "raw" / "power"
OUT = ROOT / "data" / "climate"
POWER = "https://power.larc.nasa.gov/api/temporal/monthly/point"
UA = {"User-Agent": "oscillation-nation-data-script"}

# key: (POWER parameter, label, output units, scale, conversion)
#   conversion: None, "month" (per-day rate -> monthly total) or "et" (MJ/m2/day latent heat -> mm/month)
VARS = {
    "T2M": ("T2M", "Mean temperature", "°C", 0.1, None),
    "T2M_MAX": ("T2M_MAX", "Max temperature", "°C", 0.1, None),
    "T2M_MIN": ("T2M_MIN", "Min temperature", "°C", 0.1, None),
    "T2MDEW": ("T2MDEW", "Dew point", "°C", 0.1, None),
    "PRECIP": ("PRECTOTCORR", "Precipitation", "mm", 0.1, "month"),
    "SNOWFALL": ("PRECSNOLAND", "Snowfall (water equiv.)", "mm", 0.1, "month"),
    "SNODP": ("SNODP", "Snow depth", "cm", 0.1, None),
    "RH2M": ("RH2M", "Relative humidity", "%", 0.1, None),
    "SOLAR": ("ALLSKY_SFC_SW_DWN", "Solar radiation", "MJ/m²/day", 0.01, None),
    "WS2M": ("WS2M", "Wind speed", "m/s", 0.01, None),
    "ET": ("EVPTRNS", "Evapotranspiration", "mm", 0.1, "et"),
    "GWETTOP": ("GWETTOP", "Surface soil wetness", "0–1", 0.001, None),
    "GWETROOT": ("GWETROOT", "Root-zone soil wetness", "0–1", 0.001, None),
    "GWETPROF": ("GWETPROF", "Profile soil wetness", "0–1", 0.001, None),
    "FROST_DAYS": ("FROST_DAYS", "Frost days", "days", 0.1, None),
}


def fetch_point(lon, lat, ranges):
    """Merge the responses for several year ranges into one {fill, parameter} dict."""
    parts = [fetch_range(lon, lat, s, e) for s, e in ranges]
    out = {"fill": parts[0]["fill"], "parameter": {}}
    for part in parts:
        for k, series in part["parameter"].items():
            out["parameter"].setdefault(k, {}).update(series)
    return out


def fetch_range(lon, lat, start, end):
    path = CACHE / f"{lat:.3f}_{lon:.3f}_{start}_{end}.json"
    if path.exists():
        return json.loads(path.read_text())
    params = ",".join(v[0] for v in VARS.values())
    url = (f"{POWER}?parameters={params}&community=AG&longitude={lon}&latitude={lat}"
           f"&start={start}&end={end}&format=JSON")
    for attempt in range(10):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                raw = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"POWER {e.code} for {lat},{lon}: {e.read()[:300]!r}") from e
            print(f"    retry {lat},{lon}: HTTP {e.code}", flush=True)
            time.sleep(min(120, 5 * 2 ** attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            print(f"    retry {lat},{lon}: {type(e).__name__}", flush=True)
            time.sleep(min(120, 5 * 2 ** attempt))
    else:
        raise RuntimeError(f"POWER kept failing for {lat},{lon}")
    raw = {"fill": raw.get("header", {}).get("fill_value", -999), "parameter": raw["properties"]["parameter"]}
    path.write_text(json.dumps(raw, separators=(",", ":")))
    return raw


def to_array(raw, months):
    """(n_vars, n_months) float array in output units, NaN where missing."""
    out = np.full((len(VARS), len(months)), np.nan)
    fill = raw["fill"]
    for i, (param, _, _, _, conv) in enumerate(VARS.values()):
        series = raw["parameter"][param]
        for j, (y, m) in enumerate(months):
            v = series.get(f"{y}{m:02d}")
            if v is None or v == fill:
                continue
            days = calendar.monthrange(y, m)[1]
            if conv == "month":
                v *= days
            elif conv == "et":
                v = v / 2.45 * days  # latent heat of vaporisation ~2.45 MJ/kg
            out[i, j] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1981)
    ap.add_argument("--end", type=int, default=2026)
    ap.add_argument("--split", type=int, default=2025, help="last year of the first (cached) request")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    districts = json.loads(PTS.read_text(encoding="utf-8"))
    ids = sorted(districts, key=int)
    unique = sorted({tuple(p) for d in districts.values() for p in d["power"]})
    months = [(y, m) for y in range(a.start, a.end + 1) for m in range(1, 13)]
    print(f"{len(ids)} ecodistricts, {len(unique)} sample points, {len(months)} months")

    ranges = [(a.start, min(a.end, a.split))] + ([(a.split + 1, a.end)] if a.end > a.split else [])
    CACHE.mkdir(parents=True, exist_ok=True)
    data = {}
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for i, (p, raw) in enumerate(zip(unique, ex.map(lambda p: fetch_point(*p, ranges), unique)), 1):
            data[p] = to_array(raw, months)
            if i % 100 == 0 or i == len(unique):
                print(f"  {i}/{len(unique)} points ({time.time() - t0:.0f} s)", flush=True)

    cube = np.full((len(VARS), len(ids), len(months)), np.nan)
    for k, did in enumerate(ids):
        pts = [tuple(p) for p in districts[did]["power"]]
        stack = np.stack([data[p] for p in pts])  # (pts, vars, months)
        w = np.array([math.cos(math.radians(lat)) for _, lat in pts])[:, None, None] * ~np.isnan(stack)
        with np.errstate(invalid="ignore"):
            cube[:, k, :] = np.nansum(stack * w, axis=0) / w.sum(axis=0)

    # last month where most ecodistricts have a temperature (POWER lags real time by a month or two)
    have = np.mean(~np.isnan(cube[0]), axis=0) > 0.5
    last = int(np.nonzero(have)[0].max())
    OUT.mkdir(parents=True, exist_ok=True)
    meta_vars = {}
    for i, (key, (param, label, units, scale, _)) in enumerate(VARS.items()):
        q = np.round(cube[i] / scale)
        q = np.where(np.isnan(q), -32768, np.clip(q, -32767, 32767)).astype("<i2")
        (OUT / f"{key}.bin").write_bytes(q.tobytes())
        meta_vars[key] = {"label": label, "units": units, "scale": scale, "power": param}
    (OUT / "meta.json").write_text(json.dumps({
        "source": "NASA POWER monthly point API (MERRA-2 / CERES), " + POWER,
        "start": f"{a.start}-01", "months": len(months), "ids": [int(i) for i in ids],
        "power_last": f"{months[last][0]}-{months[last][1]:02d}",
        "vars": meta_vars,
        "layout": "Int16 little-endian, row-major [ecodistrict][month]; value = int * scale; -32768 = missing",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(VARS)} variables to {OUT.relative_to(ROOT)} "
          f"({sum(f.stat().st_size for f in OUT.glob('*.bin')) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
