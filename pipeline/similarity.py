"""Precompute "places like yours": for every farmland ecodistrict and month, the most similar other
ecodistricts in the same calendar month, or the month before or after, of a different year.

Usage:  python pipeline/similarity.py [--k 10] [--shift 1]
Reads   data/climate/*.bin + meta.json   (fetch_power.py)
        data/ecodistricts.json           (build_client_data.py; soil per ecodistrict)
Writes  data/similarity/meta.json        pool of ecodistrict ids, months, record layout, variables and weights
        data/similarity/<id>.bin         per query ecodistrict: [month][k] records of 5 bytes:
                                         uint16 pool index, uint8 year offset from start year,
                                         uint8 calendar month 0-11, uint8 score 0-100 (year and month are the
                                         matched month's own, so they can differ from the query's)

Method (deliberately simple):
  * Pool = ecodistricts that have soil data (agricultural Canada).
  * Each (ecodistrict, month) is a vector of the monthly climate variables plus static soil properties.
    Monthly totals (precipitation, snowfall, evapotranspiration, frost days) are taken per day, so months of
    different length compare fairly. Climate variables are z-scored with the query calendar month's mean and
    spread across the whole pool and observed years, and the months either side get the same scaling, so a
    June and a July are compared in the same units. Soil variables are z-scored across ecodistricts. Each
    variable has a weight (WEIGHTS below).
  * Distance = weighted squared Euclidean distance. Candidates are the same calendar month, or up to
    --shift months either side (a place whose season runs earlier or later), in a different year. Same-year
    matches would just be neighbours sharing the same weather; "year" is the one the query month falls in,
    so a December 2019 candidate counts as the same year as a January 2020 query. The query's own
    ecodistrict is excluded. For each other ecodistrict we keep its best month, then the k best
    ecodistricts. On a tie the same calendar month wins.
  * Score = 100 * exp(-2 * d2 / sum(weights)): 100 = identical; a random pair (E[d2] = 2 * sum(weights))
    scores about 2, so the scale spreads out the close matches. With three months to pick from per
    ecodistrict, scores run a little higher than with same-month matching only.
  * Months after NASA POWER's last month (Meteomatics recent months and the seasonal forecast, see
    fetch_forecast.py) are queries only: they are matched against observed months. They lack a few
    variables (snowfall, evapotranspiration, soil wetness); the distance then uses only the variables both
    months have, with sum(weights) taken over those.
"""
import argparse
import calendar
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
# monthly totals: compared per day, so a 28-day February and a 31-day March line up
TOTALS = {"PRECIP", "SNOWFALL", "ET", "FROST_DAYS"}


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
    ap.add_argument("--shift", type=int, default=1, help="also match this many months before and after")
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
    assert m0 == 1, "column -> calendar month (c % 12) assumes the record starts in January"
    # months up to POWER's last are observed and can be matched; later ones (Meteomatics recent months and
    # forecast) can only be the query
    pl = meta.get("power_last")
    n_obs = n_m if not pl else (int(pl[:4]) - y0) * 12 + int(pl[5:]) - m0 + 1
    w = np.array([WEIGHTS[k] for k in clim_keys + soil_keys], dtype=np.float32)
    days = np.array([calendar.monthrange(y0 + c // 12, c % 12 + 1)[1] for c in range(n_m)], dtype=np.float32)
    clim = {k: (v / days if k in TOTALS else v) for k, v in clim.items()}
    shifts = [0] + [s for o in range(1, a.shift + 1) for s in (-o, o)]  # same month first, so it wins ties
    print(f"pool {P} ecodistricts, {n_m} months ({n_obs} observed), {len(w)} variables, month shifts {shifts}")

    # static soil block, z-scored across the pool; a missing value (e.g. no texture for organic soils) counts as average
    S = np.array([[eco[str(d)]["soil"].get(k[5:]) for k in soil_keys] for d in pool], dtype=np.float64)
    oc = soil_keys.index("soil.oc")
    S[:, oc] = np.log1p(S[:, oc])  # organic carbon is very skewed (peat ~40 %, most farmland 1-5 %)
    S = (S - np.nanmean(S, 0)) / np.nanstd(S, 0)
    S = np.clip(S, -3, 3)  # keep one extreme soil property from swamping the climate
    S = np.nan_to_num(S, nan=0.0).astype(np.float32)

    rows = np.array([row[d] for d in pool])
    result = np.zeros((P, n_m, a.k, 5), dtype=np.uint8)
    shifted, total = [0] * 12, [0] * 12  # how many kept matches come from a neighbouring month
    for m in range(12):
        cols = np.arange(m, n_m, 12)  # this calendar month, every year
        Y = len(cols)
        # scale with this calendar month's observed values, and use the same scale for the months either side
        norm = {}
        for k in clim_keys:
            ref = clim[k][rows][:, cols[cols < n_obs]]
            sd = np.nanstd(ref)
            norm[k] = (np.nanmean(ref), sd if sd > 0 else 1)

        def features(cc):
            """(P*Y, n_vars) features for columns cc (one per year); NaN where missing or outside the record."""
            inside = (cc >= 0) & (cc < n_m)
            ci = np.clip(cc, 0, n_m - 1)
            C = np.stack([np.where(inside, (clim[k][rows][:, ci] - norm[k][0]) / norm[k][1], np.nan)
                          for k in clim_keys], axis=-1)  # (P, Y, n_clim)
            return np.concatenate([C, np.broadcast_to(S[:, None, :], (P, Y, S.shape[1]))], axis=-1).reshape(P * Y, -1)

        X = features(cols)  # queries: this month, every year
        Mq = (~np.isnan(X)).astype(np.float32)  # 1 where the value exists
        X = np.nan_to_num(X, nan=0.0).astype(np.float32)
        cands = []  # per shift: candidate columns, presence mask, Z*M, Z*Z*M, can be a match
        for o in shifts:
            cc = cols + o
            Z = features(cc)
            Mk = (~np.isnan(Z)).astype(np.float32)
            Z = np.nan_to_num(Z, nan=0.0).astype(np.float32)
            cand_ok = np.tile((cc >= 0) & (cc < n_obs), P)  # only observed months can be matches
            cands.append((cc, Mk, Z * Mk, Z * Z * Mk, cand_ok))
        year_of = np.tile(np.arange(Y), P)
        for s in range(0, P * Y, a.chunk):
            q, mq = X[s:s + a.chunk], Mq[s:s + a.chunk]
            qi = np.arange(s, s + len(q))
            A = mq * w  # weights of the variables the query has
            best = np.full((len(q), P), np.inf, dtype=np.float32)  # best distance per candidate ecodistrict
            best_c = np.zeros((len(q), P), dtype=np.int64)  # and the column (month) it came from
            for cc, Mk, Zc, Zc2, cand_ok in cands:
                # weighted squared distance over the variables both sides have, and the weight that covers
                d2 = (A * q * q) @ Mk.T - 2 * (A * q) @ Zc.T + A @ Zc2.T
                W = A @ Mk.T
                d2 = np.maximum(d2, 0) / np.maximum(W, 1e-6)  # mean weighted distance per unit of weight
                d2[:, ~cand_ok] = np.inf
                d2[year_of[qi][:, None] == year_of[None, :]] = np.inf  # skip the same year
                d2 = d2.reshape(len(q), P, Y)
                d2[np.arange(len(q)), qi // Y, :] = np.inf  # skip own ecodistrict
                by = d2.argmin(2)
                bd = np.take_along_axis(d2, by[..., None], 2)[..., 0]  # (q, P)
                better = bd < best
                best = np.where(better, bd, best)
                best_c = np.where(better, cc[by], best_c)
            top = np.argpartition(best, a.k, axis=1)[:, :a.k]
            order = np.take_along_axis(best, top, 1).argsort(1)
            top = np.take_along_axis(top, order, 1)
            score = np.round(100 * np.exp(-2 * np.take_along_axis(best, top, 1)))
            col = np.take_along_axis(best_c, top, 1)
            qp, qy = qi // Y, qi % Y
            mi = qy * 12 + m
            result[qp, mi, :, 0] = top & 0xFF
            result[qp, mi, :, 1] = top >> 8
            result[qp, mi, :, 2] = col // 12
            result[qp, mi, :, 3] = col % 12
            result[qp, mi, :, 4] = score
            shifted[m] += int((col % 12 != m).sum())
            total[m] += col.size
        print(f"  month {m + 1:2d} done, {100 * shifted[m] / total[m]:.0f}% of matches from a neighbouring month",
              flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.bin"):
        f.unlink()
    for i, d in enumerate(pool):
        (OUT / f"{d}.bin").write_bytes(result[i].tobytes())
    (OUT / "meta.json").write_text(json.dumps({
        "pool": pool, "start": meta["start"], "months": n_m, "observed_months": n_obs, "k": a.k, "shift": a.shift,
        "weights": WEIGHTS, "record_bytes": 5,
        "layout": "per file: [month][k] x 5 bytes = uint16 LE pool index, uint8 year offset from start, "
                  "uint8 calendar month 0-11, uint8 score (year and month are the matched month's)",
        "method": f"same calendar month or up to {a.shift} month(s) either side, different (observed) year, other "
                  "ecodistricts; weighted z-score distance over the variables both months have (monthly totals "
                  "per day); score = 100*exp(-2*d2/sum(w))",
    }, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.glob("*.bin"))
    print(f"wrote {P} files to {OUT.relative_to(ROOT)} ({size / 1e6:.1f} MB)")
    print("median best score:", int(np.median(result[:, :n_obs, 0, 4])), " median 10th score:", int(np.median(result[:, :n_obs, -1, 4])))
    print(f"matches from a neighbouring month: {100 * sum(shifted) / sum(total):.0f}%")
    if n_m > n_obs:
        print("after POWER: median best", int(np.median(result[:, n_obs:, 0, 4])), " 10th", int(np.median(result[:, n_obs:, -1, 4])))


if __name__ == "__main__":
    main()
