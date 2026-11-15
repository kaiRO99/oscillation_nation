"""Precompute "places like yours": for every farmland ecodistrict and month, the most similar other
ecodistricts in the same calendar month of a different year.

Usage:  python scripts/similarity.py [--k 10]
Reads   data/climate/*.bin + meta.json   (fetch_power.py)
        data/ecodistricts.json           (build_client_data.py; soil per ecodistrict)
Writes  data/similarity/meta.json        pool of ecodistrict ids, months, record layout, variables and weights
        data/similarity/<id>.bin         per query ecodistrict: [month][k] records of 4 bytes:
                                         uint16 pool index, uint8 year offset from start year, uint8 score 0-100

Method (deliberately simple):
  * Pool = ecodistricts that have soil data (agricultural Canada).
  * Each (ecodistrict, month) is a vector of the monthly climate variables plus static soil properties.
    Climate variables are z-scored within each calendar month across the whole pool and observed years;
    soil variables are z-scored across ecodistricts. Each variable has a weight (WEIGHTS below).
  * Distance = weighted squared Euclidean distance. Candidates are the same calendar month in a
    different year (same-year matches would just be neighbours sharing the same weather); the
    query's own ecodistrict is excluded. For each other ecodistrict we keep its best year, then
    the k best ecodistricts.
  * Score = 100 * exp(-2 * d2 / sum(weights)): 100 = identical; a random pair (E[d2] = 2 * sum(weights))
    scores about 2, so the scale spreads out the close matches.
  * Months after NASA POWER's last month (Meteomatics recent months and the seasonal forecast, see
    fetch_forecast.py) are queries only: they are matched against observed months. They lack a few
    variables (snowfall, evapotranspiration, soil wetness); the distance then uses only the variables both
    months have, with sum(weights) taken over those.
"""
import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLIM = ROOT / "data" / "climate"
OUT = ROOT / "data" / "similarity"

# Weights per variable. Temperature has several closely related variables, so each counts for less.
WEIGHTS = {
    "T2M": 0.5, "T2M_MAX": 0.5, "T2M_MIN": 0.5, "T2MDEW": 0.25, "FROST_DAYS": 0.5,
    "PRECIP": 1.0, "SNOWFALL": 0.25, "SNODP": 0.25, "RH2M": 0.25, "SOLAR": 0.5, "WS2M": 0.25, "ET": 0.75,
    "GWETTOP": 0.5, "GWETROOT": 1.0, "GWETPROF": 0.5,
    "soil.awhc": 1.0, "soil.clay": 0.5, "soil.sand": 0.5, "soil.oc": 0.25, "soil.ph": 0.5,
}


def load_climate(meta):
    n_d, n_m = len(meta["ids"]), meta["months"]
    out = {}
    for key, v in meta["vars"].items():
        a = np.frombuffer((CLIM / f"{key}.bin").read_bytes(), dtype="<i2").reshape(n_d, n_m).astype(np.float32)
        a[a == -32768] = np.nan
        out[key] = a * v["scale"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--chunk", type=int, default=600)
    a = ap.parse_args()

    meta = json.loads((CLIM / "meta.json").read_text(encoding="utf-8"))
    eco = json.loads((ROOT / "data" / "ecodistricts.json").read_text(encoding="utf-8"))["d"]
    clim = load_climate(meta)
    row = {d: i for i, d in enumerate(meta["ids"])}
    soil_keys = [k for k in WEIGHTS if k.startswith("soil.")]
    clim_keys = [k for k in WEIGHTS if not k.startswith("soil.")]
    pool = [d for d in meta["ids"] if eco.get(str(d), {}).get("soil")]
    P = len(pool)
    n_m = meta["months"]
    y0, m0 = map(int, meta["start"].split("-"))
    # months up to POWER's last are observed and can be matched; later ones (Meteomatics recent months and
    # forecast) can only be the query
    pl = meta.get("power_last")
    n_obs = n_m if not pl else (int(pl[:4]) - y0) * 12 + int(pl[5:]) - m0 + 1
    w = np.array([WEIGHTS[k] for k in clim_keys + soil_keys], dtype=np.float32)
    print(f"pool {P} ecodistricts, {n_m} months ({n_obs} observed), {len(w)} variables")

    # static soil block, z-scored across the pool; a missing value (e.g. no texture for organic soils) counts as average
    S = np.array([[eco[str(d)]["soil"].get(k[5:]) for k in soil_keys] for d in pool], dtype=np.float64)
    oc = soil_keys.index("soil.oc")
    S[:, oc] = np.log1p(S[:, oc])  # organic carbon is very skewed (peat ~40 %, most farmland 1-5 %)
    S = (S - np.nanmean(S, 0)) / np.nanstd(S, 0)
    S = np.clip(S, -3, 3)  # keep one extreme soil property from swamping the climate
    S = np.nan_to_num(S, nan=0.0).astype(np.float32)

    rows = np.array([row[d] for d in pool])
    result = np.zeros((P, n_m, a.k, 4), dtype=np.uint8)
    for m in range(12):
        cols = np.arange(m, n_m, 12)  # this calendar month, every year
        Y = len(cols)
        obs_col = cols < n_obs
        blocks = []
        for k in clim_keys:
            x = clim[k][rows][:, cols]  # (P, Y), NaN where missing (e.g. no forecast for this variable)
            ref = x[:, obs_col]
            mu, sd = np.nanmean(ref), np.nanstd(ref)
            blocks.append((x - mu) / (sd if sd > 0 else 1))
        C = np.stack(blocks, axis=-1)  # (P, Y, n_clim)
        X = np.concatenate([C, np.broadcast_to(S[:, None, :], (P, Y, S.shape[1]))], axis=-1).reshape(P * Y, -1)
        Mk = (~np.isnan(X)).astype(np.float32)  # 1 where the value exists
        X = np.nan_to_num(X, nan=0.0).astype(np.float32)
        Xc, Xc2 = X * Mk, X * X * Mk
        year_of = np.tile(np.arange(Y), P)
        cand_ok = np.tile(obs_col, P)  # only observed months can be matches
        for s in range(0, P * Y, a.chunk):
            q, mq = X[s:s + a.chunk], Mk[s:s + a.chunk]
            A = mq * w  # weights of the variables the query has
            # weighted squared distance over the variables both sides have, and the weight that covers
            d2 = (A * q * q) @ Mk.T - 2 * (A * q) @ Xc.T + A @ Xc2.T
            W = A @ Mk.T
            d2 = np.maximum(d2, 0) / np.maximum(W, 1e-6)  # mean weighted distance per unit of weight
            qi = np.arange(s, s + len(q))
            d2[:, ~cand_ok] = np.inf
            d2[year_of[qi][:, None] == year_of[None, :]] = np.inf  # skip the same year
            d2 = d2.reshape(len(q), P, Y)
            d2[np.arange(len(q)), qi // Y, :] = np.inf  # skip own ecodistrict
            best_y = d2.argmin(2)
            best = np.take_along_axis(d2, best_y[..., None], 2)[..., 0]  # (q, P)
            top = np.argpartition(best, a.k, axis=1)[:, :a.k]
            order = np.take_along_axis(best, top, 1).argsort(1)
            top = np.take_along_axis(top, order, 1)
            score = np.round(100 * np.exp(-2 * np.take_along_axis(best, top, 1)))
            yr = np.take_along_axis(best_y, top, 1)
            qp, qy = qi // Y, qi % Y
            mi = qy * 12 + m
            result[qp, mi, :, 0] = top & 0xFF
            result[qp, mi, :, 1] = top >> 8
            result[qp, mi, :, 2] = yr
            result[qp, mi, :, 3] = score
        print(f"  month {m + 1:2d} done", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.bin"):
        f.unlink()
    for i, d in enumerate(pool):
        (OUT / f"{d}.bin").write_bytes(result[i].tobytes())
    (OUT / "meta.json").write_text(json.dumps({
        "pool": pool, "start": meta["start"], "months": n_m, "observed_months": n_obs, "k": a.k, "weights": WEIGHTS,
        "layout": "per file: [month][k] x 4 bytes = uint16 LE pool index, uint8 year offset from start, uint8 score",
        "method": "same calendar month, different (observed) year, other ecodistricts; weighted z-score distance over "
                  "the variables both months have; score = 100*exp(-2*d2/sum(w))",
    }, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.glob("*.bin"))
    print(f"wrote {P} files to {OUT.relative_to(ROOT)} ({size / 1e6:.1f} MB)")
    print("median best score:", int(np.median(result[:, :n_obs, 0, 3])), " median 10th score:", int(np.median(result[:, :n_obs, -1, 3])))
    if n_m > n_obs:
        print("after POWER: median best", int(np.median(result[:, n_obs:, 0, 3])), " 10th", int(np.median(result[:, n_obs:, -1, 3])))


if __name__ == "__main__":
    main()
