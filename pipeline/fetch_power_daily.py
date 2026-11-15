"""Daily NASA POWER weather for farmland ecodistricts, reduced to monthly crop-stress indices.

Usage:  python pipeline/fetch_power_daily.py [--start 1981] [--split 2025] [--workers 4]
Reads   data/ecodistricts.min.geojson          polygons (sample points, as fetch_power.py: <= 4 on a 0.5 deg grid)
        data/ecodistricts.json                 which ecodistricts are farmland (have an AAFC crop inventory record)
Writes  data/raw/power_daily_indices.npz       per ecodistrict and month (float32, NaN = missing):
          KDD26..KDD33  heat degree-days above 26..33 C (single-sine daily temperature curve between Tmin and
                  Tmax). Several thresholds so a model can warm a past season exactly: degree-days above 30 C
                  in a season 1 C warmer = degree-days above 29 C in the season as it was
          HOT30   days with Tmax >= 30 C
          GDD5    growing degree-days above 5 C (daily mean)
          CHU     Ontario corn heat units
          KFROST  days with Tmin <= -2 C (killing frost)
          RDAYS   days with >= 1 mm precipitation
          DRY     longest run of days with < 1 mm within the month
          P5MAX   wettest 5 days (mm), attributed to the month the 5-day window ends in
          PRECIP  total precipitation (mm)
        ids, start ('1981-01'), months, last_day (last day with data)
Caches  data/raw/power_daily/   one JSON response per sample point and year range; years after --split are a
                                separate request, so a new season re-downloads only that

Why: the monthly means the yield model used cannot see a heat wave during canola flowering or a three-week
dry spell in July; these indices can. Same source as the monthly layers (MERRA-2, ~0.5 deg), so the forecast
season's starting conditions and the training data stay consistent. No login required. Uses numpy.
"""
import argparse
import datetime
import json
import math
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from geo import sample_points

ROOT = Path(__file__).resolve().parent.parent
CDATA = ROOT / "data"
CACHE = ROOT / "data" / "raw" / "power_daily"
OUT = ROOT / "data" / "raw" / "power_daily_indices.npz"
POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
UA = {"User-Agent": "oscillation-nation-data-script"}
PARAMS = ["T2M_MAX", "T2M_MIN", "PRECTOTCORR"]
KDD_BASES = list(range(26, 34))
INDICES = [f"KDD{t}" for t in KDD_BASES] + ["HOT30", "GDD5", "CHU", "KFROST", "RDAYS", "DRY", "P5MAX", "PRECIP"]


_LOCK = threading.Lock()
_NEXT = [0.0]
RATE = [60.0]  # requests per minute, all workers together (POWER answers HTTP 429 when pushed harder)


def throttle():
    with _LOCK:
        now = time.monotonic()
        wait = _NEXT[0] - now
        _NEXT[0] = max(now, _NEXT[0]) + 60.0 / RATE[0]
    if wait > 0:
        time.sleep(wait)


def fetch_range(lon, lat, start, end):
    today = datetime.date.today()
    # a range that is still in progress is cached under today's date, so it refreshes once a day
    stamp = f"_{today:%Y%m%d}" if end >= today.year else ""
    path = CACHE / f"{lat:.3f}_{lon:.3f}_{start}_{end}{stamp}.json"
    if path.exists():
        return json.loads(path.read_text())
    stop = min(datetime.date(end, 12, 31), today)
    url = (f"{POWER}?parameters={','.join(PARAMS)}&community=AG&longitude={lon}&latitude={lat}"
           f"&start={start}0101&end={stop:%Y%m%d}&format=JSON")
    for attempt in range(10):
        throttle()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
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


def degree_days_above(tmin, tmax, base):
    """Single-sine degree-days above `base` for each day (Baskerville & Emin 1969)."""
    m = (tmax + tmin) / 2
    a = np.maximum((tmax - tmin) / 2, 1e-6)
    with np.errstate(invalid="ignore"):
        th = np.arcsin(np.clip((base - m) / a, -1, 1))
        dd = ((m - base) * (math.pi / 2 - th) + a * np.cos(th)) / math.pi
    dd = np.where(tmax <= base, 0.0, np.where(tmin >= base, m - base, dd))
    return np.where(np.isnan(tmin) | np.isnan(tmax), np.nan, dd)


def monthly_indices(raw, day0, n_days, mon_idx, n_months):
    """(len(INDICES), n_months) for one point. A month with any missing day is NaN."""
    fill = raw["fill"]
    s = {}
    for p in PARAMS:
        a = np.full(n_days, np.nan)
        for k, v in raw["parameter"][p].items():
            i = (datetime.date(int(k[:4]), int(k[4:6]), int(k[6:])) - day0).days
            if 0 <= i < n_days and v != fill:
                a[i] = v
        s[p] = a
    tx, tn, pr = s["T2M_MAX"], s["T2M_MIN"], s["PRECTOTCORR"]
    tm = (tx + tn) / 2
    ymax = np.where(tx < 10, 0.0, 3.33 * (tx - 10) - 0.084 * (tx - 10) ** 2)
    ymin = np.where(tn < 4.44, 0.0, 1.8 * (tn - 4.44))
    wet = pr >= 1.0
    idx = np.arange(n_days)
    month_start = np.r_[True, mon_idx[1:] != mon_idx[:-1]]
    start_of_run = np.where(wet, idx + 1, np.where(month_start, idx, -1))
    run = np.where(wet | np.isnan(pr), 0, idx - np.maximum.accumulate(start_of_run) + 1)
    p5 = np.convolve(pr, np.ones(5), "full")[:n_days]  # NaN anywhere in the window -> NaN
    p5[:4] = np.nan
    daily = {
        **{f"KDD{t}": degree_days_above(tn, tx, float(t)) for t in KDD_BASES},
        "HOT30": np.where(np.isnan(tx), np.nan, tx >= 30),
        "GDD5": np.where(np.isnan(tm), np.nan, np.maximum(tm - 5, 0)),
        "CHU": np.where(np.isnan(tx) | np.isnan(tn), np.nan, (ymax + ymin) / 2),
        "KFROST": np.where(np.isnan(tn), np.nan, tn <= -2),
        "RDAYS": np.where(np.isnan(pr), np.nan, wet),
        "PRECIP": pr,
    }
    out = np.full((len(INDICES), n_months), np.nan)
    missing = np.bincount(mon_idx, np.isnan(tx) | np.isnan(tn) | np.isnan(pr), n_months) > 0
    for i, k in enumerate(INDICES):
        if k in daily:
            out[i] = np.bincount(mon_idx, np.nan_to_num(daily[k]), n_months)
        elif k == "DRY":
            v = np.zeros(n_months)
            np.maximum.at(v, mon_idx, run)
            out[i] = v
        elif k == "P5MAX":
            v = np.full(n_months, -np.inf)
            np.maximum.at(v, mon_idx, np.nan_to_num(p5, nan=-np.inf))
            out[i] = v
    out[:, missing] = np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1981)
    ap.add_argument("--split", type=int, default=2025, help="last year of the first (cached) request")
    ap.add_argument("--end", type=int, default=datetime.date.today().year, help="last year (default: this year)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rate", type=float, default=60.0, help="max requests per minute")
    a = ap.parse_args()
    RATE[0] = a.rate

    eco = json.loads((CDATA / "ecodistricts.json").read_text(encoding="utf-8"))["d"]
    farm = {int(k) for k, v in eco.items() if v.get("crops")}
    geo = json.loads((CDATA / "ecodistricts.min.geojson").read_text(encoding="utf-8"))
    pts = {}
    for f in geo["features"]:
        if f["id"] in farm:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            pts[f["id"]] = [tuple(p) for p in sample_points(polys, 0.5, 4)]
    ids = sorted(pts)
    unique = sorted({p for v in pts.values() for p in v})
    end_year = a.end
    ranges = [(a.start, min(a.split, end_year))] + ([(a.split + 1, end_year)] if end_year > a.split else [])
    day0 = datetime.date(a.start, 1, 1)
    n_days = (datetime.date(end_year, 12, 31) - day0).days + 1
    dates = [day0 + datetime.timedelta(i) for i in range(n_days)]
    mon_idx = np.array([(d.year - a.start) * 12 + d.month - 1 for d in dates])
    n_months = (end_year - a.start + 1) * 12
    print(f"{len(ids)} farmland ecodistricts, {len(unique)} sample points, daily {a.start}-{end_year}")

    def one(p):
        parts = [fetch_range(p[0], p[1], s, e) for s, e in ranges]
        raw = {"fill": parts[0]["fill"], "parameter": {}}
        for part in parts:
            for k, series in part["parameter"].items():
                raw["parameter"].setdefault(k, {}).update(series)
        return monthly_indices(raw, day0, n_days, mon_idx, n_months), max(raw["parameter"]["T2M_MAX"])

    CACHE.mkdir(parents=True, exist_ok=True)
    data, last = {}, []
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for i, (p, (arr, ld)) in enumerate(zip(unique, ex.map(one, unique)), 1):
            data[p] = arr
            last.append(ld)
            if i % 100 == 0 or i == len(unique):
                print(f"  {i}/{len(unique)} points ({time.time() - t0:.0f} s)", flush=True)

    cube = np.full((len(INDICES), len(ids), n_months), np.nan, dtype=np.float64)
    for k, did in enumerate(ids):
        ps = pts[did]
        stack = np.stack([data[p] for p in ps])  # (pts, indices, months)
        w = np.array([math.cos(math.radians(lat)) for _, lat in ps])[:, None, None] * ~np.isnan(stack)
        with np.errstate(invalid="ignore"):
            cube[:, k] = (np.nan_to_num(stack) * w).sum(0) / w.sum(0)
    np.savez_compressed(OUT, ids=np.array(ids), start=f"{a.start}-01", months=n_months, indices=np.array(INDICES),
                        last_day=min(last), **{k: cube[i].astype(np.float32) for i, k in enumerate(INDICES)})
    print(f"wrote {OUT.relative_to(ROOT)}: {len(INDICES)} indices x {len(ids)} ecodistricts x {n_months} months; "
          f"data to {min(last)}")


if __name__ == "__main__":
    main()
