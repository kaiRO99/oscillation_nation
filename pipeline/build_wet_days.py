"""Wet days and precipitation per wet day for the map's Precipitation picker, from daily NASA POWER.

Usage:  python pipeline/build_wet_days.py
Reads   data/raw/power_daily_indices.npz   (fetch_power_daily.py): RDAYS and PWET per farmland ecodistrict and month
        data/climate/meta.json             (fetch_power.py, then fetch_forecast.py)
Writes  data/climate/WET_DAYS.bin          days with >= 1 mm of precipitation (rain or melted snow)
        data/climate/WET_DAY_PRECIP.bin    precipitation on those days / their number: mm per wet day, how heavy it
                                           is when it does rain (the "simple daily intensity index", SDII). Only the
                                           wet days' own precipitation counts, so drizzle on dry days doesn't inflate it
        data/climate/meta.json             adds both variables ("forecast": false, "coverage": "farmland")

Run after fetch_power.py and fetch_forecast.py: fetch_power.py rewrites meta.json without these variables.
(fetch_forecast.py keeps them.)

Same Int16 layout as fetch_power.py. Values exist only for the farmland ecodistricts fetch_power_daily.py
covers, and only up to NASA POWER's last monthly month ("power_last"), like the other POWER-only variables.
Months after that are missing (-32768), and so are the other ecodistricts. There is no forecast: the
seasonal forecast we have is ECMWF's ensemble MEAN, and averaging 51 members spreads rain thinly over most
days, so counting its wet days would be badly biased.

Both are averages over an ecodistrict's sample points (up to 4, ~0.5 deg apart), pooled as total wet-day
precipitation / total wet days, so a count can be fractional. Reanalysis grid cells tend to have more wet days,
with less rain on each, than a single rain gauge.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLIM = ROOT / "data" / "climate"
DAILY = ROOT / "data" / "raw" / "power_daily_indices.npz"

VARS = {
    "WET_DAYS": {"label": "Wet days (≥ 1 mm)", "units": "days", "scale": 0.1},
    "WET_DAY_PRECIP": {"label": "Precipitation per wet day", "units": "mm", "scale": 0.1},
}


def month_index(ym, start):
    return (int(ym[:4]) - int(start[:4])) * 12 + int(ym[5:7]) - int(start[5:7])


def main():
    meta = json.loads((CLIM / "meta.json").read_text(encoding="utf-8"))
    if not DAILY.exists():
        raise SystemExit(f"missing {DAILY.relative_to(ROOT)}: run pipeline/fetch_power_daily.py first")
    dz = np.load(DAILY)
    if "PWET" not in dz:
        raise SystemExit(f"{DAILY.name} has no PWET: re-run pipeline/fetch_power_daily.py")
    if str(dz["start"]) != meta["start"]:
        raise SystemExit(f"{DAILY.name} starts {dz['start']}, climate/meta.json {meta['start']}: re-run fetch_power_daily.py")

    n_d, n_m = len(meta["ids"]), meta["months"]
    row = {int(e): i for i, e in enumerate(meta["ids"])}
    # only months NASA POWER's monthly record covers (see docstring), and only those the daily file has
    pl = meta.get("power_last")
    n_use = min(int(dz["months"]), month_index(pl, meta["start"]) + 1 if pl else n_m)

    rdays, pwet = dz["RDAYS"].astype(np.float64), dz["PWET"].astype(np.float64)
    out = {k: np.full((n_d, n_m), np.nan) for k in VARS}
    missing = []
    for i, e in enumerate(dz["ids"]):
        r = row.get(int(e))
        if r is None:
            missing.append(int(e))
            continue
        rd, pw = rdays[i, :n_use], pwet[i, :n_use]
        out["WET_DAYS"][r, :n_use] = rd
        with np.errstate(invalid="ignore", divide="ignore"):
            out["WET_DAY_PRECIP"][r, :n_use] = np.where(rd > 0, pw / rd, np.nan)
    if missing:
        print(f"  {len(missing)} daily ecodistricts not in climate/meta.json (skipped): {missing[:10]}")

    for key, v in VARS.items():
        q = np.round(out[key] / v["scale"])
        q = np.where(np.isnan(q), -32768, np.clip(q, -32767, 32767)).astype("<i2")
        (CLIM / f"{key}.bin").write_bytes(q.tobytes())
        meta["vars"][key] = {**v, "source": "NASA POWER daily (PRECTOTCORR), pipeline/fetch_power_daily.py",
                             "forecast": False, "coverage": "farmland"}
        have = ~np.isnan(out[key][:, :n_use])
        print(f"  {key:15s} {have.any(axis=1).sum()} ecodistricts, months 1..{n_use}, "
              f"median {np.nanmedian(out[key]):.1f} {v['units']}")
    (CLIM / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {', '.join(VARS)} to {CLIM.relative_to(ROOT)} (daily data to {dz['last_day']})")


if __name__ == "__main__":
    main()
