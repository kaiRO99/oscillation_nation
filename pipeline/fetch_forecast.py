"""Extend the monthly climate past NASA POWER with Meteomatics: recent months the POWER archive does not have
yet, plus the ECMWF seasonal forecast as far ahead as it goes (about 7 months). Also forecasts the Oceanic
Nino Index from the same model's sea surface temperature.

Usage:  python scripts/fetch_forecast.py [--refresh]
Needs   METEOMATICS_USER / METEOMATICS_PASSWORD in the environment or in .env (git-ignored)
Reads   data/climate/*.bin + meta.json      (fetch_power.py; "power_last" = last month POWER has)
        data/raw/ecodistrict_points.json    (build_ecodistricts.py)
Writes  data/climate/*.bin + meta.json      months after power_last replaced/appended from Meteomatics
        data/oni_forecast.json              forecast ONI seasons
Caches  data/raw/meteomatics/               monthly aggregates per model and month (--refresh to redo)

Method (simple on purpose):
  * A few requests per month for a 1-degree grid over Canada, daily values. Model "ecmwf-era5" (ECMWF
    reanalysis) for months that are over, "ecmwf-mmsf" (ECMWF seasonal forecast) from the current month
    on (its 51-member ensemble mean, which damps extremes such as T2M_MAX and frost days a little). Daily values are aggregated the way POWER aggregates months (T2M_MAX = warmest
    daily max, frost days = days with a minimum below 0 C, ...), then interpolated to each ecodistrict's
    POWER sample points and averaged.
  * Bias correction: ERA5 is also fetched for the months of the current year that POWER has, and each
    ecodistrict gets a correction (an offset for temperatures and humidity, a ratio for precipitation,
    wind, sunshine and snow depth) so the Meteomatics months sit on the POWER scale. The same correction is
    used for the seasonal forecast.
  * Forecast T2M_MAX / T2M_MIN (warmest / coldest day of the month) = 1991-2020 POWER normal + forecast
    mean-temperature anomaly, because the ensemble mean flattens the extremes.
  * Variables Meteomatics' seasonal forecast lacks (snowfall, evapotranspiration, soil wetness) are left
    missing after power_last.
  * ONI: daily sea surface temperature over Nino 3.4 (5S-5N, 170W-120W) from ecmwf-mmsf, shifted so its
    second half of last month matches NOAA's observed OISST Nino 3.4 for that month, turned into an anomaly
    with the 1991-2020 OISST climatology, and moved onto the ONI (ERSST) scale with the average ONI-OISST
    difference of the last three observed seasons. Seasons are 3-month running means.
"""
import argparse
import base64
import calendar
import datetime as dt
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLIM = ROOT / "data" / "climate"
PTS = ROOT / "data" / "raw" / "ecodistrict_points.json"
CACHE = ROOT / "data" / "raw" / "meteomatics"
API = "https://api.meteomatics.com"
OISST = "https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices"
SEASON_MODEL = "ecmwf-mmsf"
# the seasonal model defaults to ECMWF's control run (one member); use the 51-member ensemble mean instead
ENS = {"ecmwf-mmsf": "&ens_select=mean"}
NO_ENS = {"global_rad_24h:J"}  # its ensemble mean times out on the server: control run instead
PAST_MODEL = "ecmwf-era5"  # ~5 days behind real time; much faster than "mix" (1 km downscaling)

# 1-degree grid over Canada (covers every POWER sample point, 41.75-83.25 N, 140.75-52.75 W)
LAT0, LAT1, LON0, LON1 = 41, 84, -141, -52

PARAMS = ["t_mean_2m_24h:C", "t_max_2m_24h:C", "t_min_2m_24h:C", "dew_point_2m:C", "precip_24h:mm",
          "wind_speed_2m:ms", "global_rad_24h:J", "snow_depth:cm"]
# climate variable -> how the correction is applied
FC_VARS = {"T2M": "add", "T2M_MAX": "add", "T2M_MIN": "add", "T2MDEW": "add", "PRECIP": "ratio",
           "RH2M": "add", "WS2M": "ratio", "SOLAR": "ratio", "SNODP": "ratio", "FROST_DAYS": "add"}


def add_months(y, m, d):
    k = y * 12 + m - 1 + d
    return k // 12, k % 12 + 1


def creds():
    env = dict(os.environ)
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    user, pw = env.get("METEOMATICS_USER"), env.get("METEOMATICS_PASSWORD")
    if not user or not pw:
        raise SystemExit("Set METEOMATICS_USER and METEOMATICS_PASSWORD (environment or .env)")
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def get(url, auth, timeout=600):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"Authorization": auth, "User-Agent": "oscillation-nation"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read()[:400]
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"Meteomatics {e.code}: {body!r}") from e
            print(f"    retry: HTTP {e.code}", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"    retry: {type(e).__name__}", flush=True)
        time.sleep(10 * 2 ** attempt)
    raise RuntimeError("Meteomatics kept failing")


def month_grid(y, m, model, auth, refresh):
    """Monthly aggregates on the grid: dict var -> (n_lat, n_lon) array, in POWER units."""
    path = CACHE / f"{model}_{y}-{m:02d}.npz"
    if path.exists() and not refresh:
        return with_rh(dict(np.load(path)))
    days = calendar.monthrange(y, m)[1]
    t0 = dt.datetime(y, m, 1) + dt.timedelta(days=1)  # 24 h values ending 00Z on day d+1 cover day d
    t1 = dt.datetime(y, m, days) + dt.timedelta(days=1)
    print(f"  {model} {y}-{m:02d} ...", flush=True)
    parts = []
    # the API allows 1 million values per request; the ensemble mean is slow to compute, so one variable each
    groups = [[q] for q in PARAMS] if model in ENS else (PARAMS[:5], PARAMS[5:])  # RH2M: see with_rh
    for group in groups:
        ens = "" if group[0] in NO_ENS else ENS.get(model, "")
        url = (f"{API}/{t0:%Y-%m-%dT%H:%M:%SZ}--{t1:%Y-%m-%dT%H:%M:%SZ}:P1D/{','.join(group)}/"
               f"{LAT1},{LON0}_{LAT0},{LON1}:1,1/csv?model={model}{ens}")
        parts.append(pd.read_csv(io.StringIO(get(url, auth)), sep=";").set_index(["lat", "lon", "validdate"]))
    df = pd.concat(parts, axis=1).reset_index()
    df.columns = [c.removesuffix("-mean") for c in df.columns]  # ensemble-mean columns are named "<param>-mean"
    df = df.replace([-666, -999], np.nan)
    df["i"] = (df["lat"] - LAT0).round().astype(int)
    df["j"] = (df["lon"] - LON0).round().astype(int)
    shape = (LAT1 - LAT0 + 1, LON1 - LON0 + 1)
    g = df.groupby(["i", "j"])
    agg = pd.DataFrame({
        "T2M": g["t_mean_2m_24h:C"].mean(),
        "T2M_MAX": g["t_max_2m_24h:C"].max(),
        "T2M_MIN": g["t_min_2m_24h:C"].min(),
        "T2MDEW": g["dew_point_2m:C"].mean(),
        "PRECIP": g["precip_24h:mm"].mean() * days,  # mean daily total x days (tolerates a missing day)
        "WS2M": g["wind_speed_2m:ms"].mean(),
        "SOLAR": g["global_rad_24h:J"].mean() / 1e6,  # J/m2 per day -> MJ/m2/day
        "SNODP": g["snow_depth:cm"].mean(),
        "FROST_DAYS": g["t_min_2m_24h:C"].apply(lambda s: (s < 0).mean() * days),
    })
    out = {}
    for k in agg:
        a = np.full(shape, np.nan, dtype=np.float32)
        idx = agg.index.to_frame().to_numpy()
        a[idx[:, 0], idx[:, 1]] = agg[k].to_numpy()
        out[k] = a
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **out)
    return with_rh(out)


def with_rh(g):
    """Relative humidity from the monthly mean temperature and dew point (Magnus formula). The API's
    relative_humidity_2m is a single 00Z value per day (afternoon in Canada), which is far from a daily mean."""
    es = lambda t: np.exp(17.625 * t / (t + 243.04))
    g["RH2M"] = np.clip(100 * es(g["T2MDEW"]) / es(g["T2M"]), 0, 100).astype(np.float32)
    return g


def to_districts(grid, ids, districts):
    """Bilinear interpolation to each ecodistrict's sample points, cos(lat)-weighted mean -> (n_ids,)."""
    out = np.full(len(ids), np.nan)
    for k, did in enumerate(ids):
        vals, ws = [], []
        for lon, lat in districts[did]["power"]:
            y, x = lat - LAT0, lon - LON0
            i, j = int(math.floor(y)), int(math.floor(x))
            fy, fx = y - i, x - j
            c = [(i, j, (1 - fy) * (1 - fx)), (i + 1, j, fy * (1 - fx)), (i, j + 1, (1 - fy) * fx), (i + 1, j + 1, fy * fx)]
            num = den = 0.0
            for a, b, w in c:
                v = grid[a, b]
                if not np.isnan(v):
                    num += v * w
                    den += w
            if den > 0:
                vals.append(num / den)
                ws.append(math.cos(math.radians(lat)))
        if ws:
            out[k] = np.average(vals, weights=ws)
    return out


def oni_forecast(auth, issued, end):
    """Forecast ONI seasons from ECMWF seasonal SST, anchored to NOAA's latest observations."""
    obs = pd.read_csv(io.StringIO(urllib.request.urlopen(OISST, timeout=60).read().decode()), sep=r"\s+")
    obs.columns = ["yr", "mon", "n12", "a12", "n3", "a3", "n4", "a4", "n34", "a34"]
    clim = (obs["n34"] - obs["a34"]).groupby(obs["mon"]).mean()  # 1991-2020 OISST climatology
    last = obs.iloc[-1]
    ly, lm = int(last["yr"]), int(last["mon"])
    # ONI (ERSST) vs OISST: average difference over the last 3 observed seasons
    oni = json.loads((ROOT / "data" / "oni.json").read_text(encoding="utf-8"))
    seasons = oni["seasons"]
    mon = {(int(r.yr), int(r.mon)): r.a34 for r in obs.itertuples()}
    diffs = []
    for rec in oni["data"][-3:]:
        c = seasons.index(rec["season"]) + 1  # centre month
        trip = [add_months(rec["year"], c, d) for d in (-1, 0, 1)]
        if all(t in mon for t in trip):
            diffs.append(rec["anom"] - np.mean([mon[t] for t in trip]))
    shift = float(np.mean(diffs)) if diffs else 0.0

    # model SST over Nino 3.4, daily, from mid last-observed month to the end of the forecast
    t0 = dt.datetime(ly, lm, 15)
    t1 = dt.datetime(end[0], end[1], calendar.monthrange(*end)[1])
    url = (f"{API}/{t0:%Y-%m-%dT%H:%M:%SZ}--{t1:%Y-%m-%dT%H:%M:%SZ}:P1D/t_sea_sfc:C/"
           f"5,-170_-5,-120:1,1/csv?model={SEASON_MODEL}{ENS[SEASON_MODEL]}")
    print("  Nino 3.4 SST forecast ...", flush=True)
    df = pd.read_csv(io.StringIO(get(url, auth)), sep=";").replace([-666, -999], np.nan)
    df["validdate"] = pd.to_datetime(df["validdate"])
    daily = df.groupby("validdate")[df.columns[-1]].mean()
    model_m = daily.groupby([daily.index.year, daily.index.month]).mean()
    offset = model_m[(ly, lm)] - last["n34"]  # model minus observed for the overlap month
    monthly = {(ly, lm): float(last["a34"]) + shift}
    for (y, m), v in model_m.items():
        if (y, m) > (ly, lm):
            monthly[(int(y), int(m))] = float(v - offset - clim[m]) + shift
    for back in (1, 2):  # the two months before, for the first seasons
        y, m = (ly, lm - back) if lm - back > 0 else (ly - 1, lm - back + 12)
        if (y, m) in mon:
            monthly[(y, m)] = float(mon[(y, m)]) + shift

    # seasons whose centre month is after the last observed ONI season
    lr = oni["data"][-1]
    start_c = (lr["year"], seasons.index(lr["season"]) + 1)
    keys = sorted(monthly)
    out = []
    for y, m in keys:
        if (y, m) <= start_c:
            continue
        prev = (y, m - 1) if m > 1 else (y - 1, 12)
        nxt = (y, m + 1) if m < 12 else (y + 1, 1)
        vals = [monthly[t] for t in (prev, (y, m), nxt) if t in monthly]
        # CPC labels a season with the year of its centre month (DJF 2027 = Dec 2026-Feb 2027)
        out.append({"season": seasons[m - 1], "year": y, "anom": round(float(np.mean(vals)), 2), "forecast": True,
                    "months_used": len(vals)})
    return {
        "source": f"Meteomatics {SEASON_MODEL} (ECMWF seasonal) sea surface temperature over Nino 3.4, "
                  f"anchored to NOAA CPC OISST ({OISST})",
        "issued": issued,
        "method": "monthly model SST minus its offset from the last observed OISST month, minus the 1991-2020 "
                  f"OISST climatology, plus {shift:+.2f} (average ONI - OISST over the last 3 seasons); "
                  "3-month running means centred on each month",
        "last_observed_oisst": f"{ly}-{lm:02d}",
        "monthly": {f"{y}-{m:02d}": round(v, 2) for (y, m), v in sorted(monthly.items())},
        "data": out,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download cached months")
    a = ap.parse_args()
    auth = creds()

    meta = json.loads((CLIM / "meta.json").read_text(encoding="utf-8"))
    districts = json.loads(PTS.read_text(encoding="utf-8"))
    ids = [str(i) for i in meta["ids"]]
    sy, sm = map(int, meta["start"].split("-"))
    ply, plm = map(int, meta["power_last"].split("-"))
    n_power = (ply - sy) * 12 + plm - sm + 1  # months up to and including power_last

    today = dt.date.today()
    fc_end = forecast_end(auth)
    print(f"POWER to {meta['power_last']}; Meteomatics analysis to {today:%Y-%m}; forecast to {fc_end[0]}-{fc_end[1]:02d}")

    # bias correction from the overlap: this year's POWER months vs ERA5
    n_d = len(ids)
    cube = {}
    for key, v in meta["vars"].items():
        x = np.frombuffer((CLIM / f"{key}.bin").read_bytes(), dtype="<i2").reshape(n_d, -1)[:, :n_power]
        x = x.astype(np.float64)
        x[x == -32768] = np.nan
        cube[key] = x * v["scale"]
    overlap = [(ply, m) for m in range(1, plm + 1)]
    months = []  # months after POWER, up to the end of the seasonal forecast
    y, m = ply, plm
    while (y, m) < fc_end:
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        months.append((y, m))
    def model_for(y, m):  # a month is "over" once ERA5 (about 5 days behind) covers its last day
        over = dt.date(y, m, calendar.monthrange(y, m)[1]) + dt.timedelta(days=7) <= today
        return PAST_MODEL if over else SEASON_MODEL

    jobs = [(y, m, PAST_MODEL) for y, m in overlap] + [(y, m, model_for(y, m)) for y, m in months]
    with ThreadPoolExecutor(4) as ex:  # fill the cache in parallel (the account allows 10 at once)
        list(ex.map(lambda j: month_grid(j[0], j[1], j[2], auth, a.refresh), jobs))

    P = {k: [] for k in FC_VARS}
    M = {k: [] for k in FC_VARS}
    for y, m in overlap:
        g = month_grid(y, m, PAST_MODEL, auth, False)
        col = (y - sy) * 12 + m - sm
        for k in FC_VARS:
            M[k].append(to_districts(g[k], ids, districts))
            P[k].append(cube[k][:, col])
    corr = {}
    for k, how in FC_VARS.items():
        p, mm = np.array(P[k]).T, np.array(M[k]).T  # (n_d, months)
        if how == "add":
            c = np.nanmean(p - mm, axis=1)
            corr[k] = np.nan_to_num(c, nan=0.0)
        else:
            sp, sm_ = np.nansum(np.where(np.isnan(mm), np.nan, p), 1), np.nansum(np.where(np.isnan(p), np.nan, mm), 1)
            r = np.where(sm_ > 1e-6, sp / np.maximum(sm_, 1e-6), 1.0)
            corr[k] = np.clip(np.nan_to_num(r, nan=1.0), 0.33, 3.0)
        print(f"  correction {k:10s} median {np.median(corr[k]):+.2f} ({how})")

    new = {k: np.full((n_d, len(months)), np.nan) for k in meta["vars"]}
    kinds = []
    for c, (y, m) in enumerate(months):
        model = model_for(y, m)
        kinds.append("analysis" if model == PAST_MODEL else "forecast")
        g = month_grid(y, m, model, auth, False)
        days = calendar.monthrange(y, m)[1]
        for k, how in FC_VARS.items():
            v = to_districts(g[k], ids, districts)
            v = v + corr[k] if how == "add" else v * corr[k]
            if k == "FROST_DAYS":
                v = np.clip(v, 0, days)
            elif k in ("PRECIP", "SNODP", "WS2M", "SOLAR"):
                v = np.maximum(v, 0)
            elif k == "RH2M":
                v = np.clip(v, 0, 100)
            new[k][:, c] = v

    # An ensemble mean smooths out the warmest / coldest day of the month, so in forecast months the
    # monthly extremes are the POWER 1991-2020 normal plus the forecast's mean-temperature anomaly.
    def normal(key, m):
        a, b = (1991 - sy) * 12 + m - sm, (2020 - sy) * 12 + m - sm
        return np.nanmean(cube[key][:, a:b + 1:12], axis=1)
    for c, ((y, m), kind) in enumerate(zip(months, kinds)):
        if kind == "forecast":
            anom = new["T2M"][:, c] - normal("T2M", m)
            for key in ("T2M_MAX", "T2M_MIN"):
                new[key][:, c] = normal(key, m) + anom

    for key, v in meta["vars"].items():
        full = np.concatenate([cube[key], new[key]], axis=1)
        q = np.round(full / v["scale"])
        q = np.where(np.isnan(q), -32768, np.clip(q, -32767, 32767)).astype("<i2")
        (CLIM / f"{key}.bin").write_bytes(q.tobytes())
        v["forecast"] = key in FC_VARS
    meta["months"] = n_power + len(months)
    meta["extension"] = {
        "source": f"Meteomatics API ({API}): '{PAST_MODEL}' for recent months, '{SEASON_MODEL}' (ECMWF seasonal "
                  "forecast) for future months; bias-corrected to POWER per ecodistrict",
        "issued": today.isoformat(),
        "first": f"{months[0][0]}-{months[0][1]:02d}" if months else None,
        "kinds": kinds,  # per month after power_last: "analysis" (ERA5, already happened) or "forecast"
        "vars": [k for k in FC_VARS],
    }
    meta["layout"] = "Int16 little-endian, row-major [ecodistrict][month]; value = int * scale; -32768 = missing"
    (CLIM / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"climate now {meta['months']} months ({len(months)} from Meteomatics)")

    fc = oni_forecast(auth, today.isoformat(), fc_end)
    (ROOT / "data" / "oni_forecast.json").write_text(json.dumps(fc, indent=1), encoding="utf-8")
    print("ONI forecast:", ", ".join(f"{r['season']} {r['year']} {r['anom']:+.2f}" for r in fc["data"]))


def forecast_end(auth):
    """Last full month the seasonal forecast covers (the API error message names the available range)."""
    url = f"{API}/2028-01-01T00:00:00Z/t_2m:C/50,-100/json?model={SEASON_MODEL}"
    try:
        get(url, auth, 60)
    except RuntimeError as e:
        found = re.search(r"and (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)Z", str(e))
        if not found:
            raise
        end = dt.datetime.fromisoformat(found.group(1))
        # the month must be complete: its last day + 1 at 00Z must be available
        y, m = end.year, end.month
        if end.day < calendar.monthrange(y, m)[1] or end.hour > 0:
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        nxt = dt.datetime(y, m, calendar.monthrange(y, m)[1]) + dt.timedelta(days=1)
        if nxt > end:
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        return y, m
    raise RuntimeError("could not read the forecast range")


if __name__ == "__main__":
    main()
