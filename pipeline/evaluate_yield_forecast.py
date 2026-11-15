"""How accurate is the yield forecast? A walk-forward test of pipeline/build_yield_forecast.py.

Usage:  python pipeline/evaluate_yield_forecast.py [--json out.json] [--from 1991]
          --from  first test year (default 2001). 1991 also tests the strong El Nino seasons 1992, 1995 and
                  1998, forecast from only 10-17 training years, so compare phases within one run
Reads   the same inputs as build_yield_forecast.py, plus data/yield_forecast.json for the El Nino
        weighting the build chose (enso.kernel_h, enso.lam). Run the build first.

Test design: for every year t from HIND0 (2001) to the last year with yields, refit the model on the years
before t and forecast t with only what was known the November before (fall soil moisture, a statistical
ENSO forecast; no Oct-May precipitation, no summer weather). Score against StatCan's observed regional
yield. Every region-crop-year with an observation is one test case (~7,400).

Printed per crop:
  medErr / meanErr  median / mean absolute % error of the middle estimate
  naive             median abs % error of "the last 5 years' average" (the farmer's rule of thumb)
  <=10% / <=20%     share of forecasts within 10 % / 20 % of the actual yield
  dirCorr           correlation of (forecast - normal) with (actual - normal): does it call the direction?
  BSS               Brier skill score of the "chance below normal" vs always saying 50 %
  knownWx           median abs % error if the summer weather had been known (an upper bound for a perfect
                    seasonal weather forecast)
  R2wx              share of the year-to-year swing around a normal year that the known summer weather
                    explains, out of sample (can be negative: worse than predicting a normal year)
Then the same split by the ENSO phase of the winter before the season (DJF RONI >= +0.5 El Nino, >= +1.0
strong, <= -0.5 La Nina), each El Nino season on its own, and each crop in El Nino seasons vs the rest, with:
  noENSO          median abs % error without the El Nino weighting (does the weighting help when it matters?)
  cov80 / cov95   share inside the 80 % / 95 % range, recalibrated per crop leave-that-year-out as the build does
  bias            median of actual / middle estimate - 1: + means yields beat the forecast
Overall interval coverage (80 % / 95 %) is also printed by build_yield_forecast.py itself.

Caveat: the model form (trend shape, starting conditions, ENSO weighting) was chosen on this same
2001-2025 test, so these scores are slightly optimistic; there is no untouched test period.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_yield_forecast as b  # noqa: E402


def phase(djf):
    """ENSO phase of a growing season, by the winter (DJF RONI) before it: what the forecast is issued on."""
    if djf >= 1.0:
        return "strong El Nino"
    if djf >= 0.5:
        return "El Nino"
    if djf <= -0.5:
        return "La Nina"
    return "neutral"


def coverage(rows):
    """Whether each outcome fell inside the recalibrated 80 % / 95 % range, recalibrating as
    build_yield_forecast.py does (per crop, from the other years' PITs: leave-that-year-out)."""
    in80, in95 = np.zeros(len(rows), bool), np.zeros(len(rows), bool)
    for c in {r[0] for r in rows}:
        idx = np.array([i for i, r in enumerate(rows) if r[0] == c])
        yrs = np.array([rows[i][7] for i in idx])
        dev = np.abs(np.clip(np.array([rows[i][8] for i in idx]), 1e-6, 1 - 1e-6) - 0.5)
        for t in np.unique(yrs):
            m = yrs == t
            a80, a95 = np.quantile(dev[~m], [0.8, 0.95])
            in80[idx[m]] = dev[m] <= a80
            in95[idx[m]] = dev[m] <= a95
    return in80, in95


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write the per-crop scores here")
    ap.add_argument("--from", dest="first", type=int, default=b.HIND0,
                    help=f"first test year (default {b.HIND0}). 1991 adds the strong El Nino seasons 1992, 1995 and "
                         "1998, forecast from fewer training years")
    a = ap.parse_args()
    built = json.loads(b.OUT.read_text(encoding="utf-8"))
    cfg = (built["enso"]["kernel_h"], built["enso"]["lam"])
    ctx = b.Ctx()
    rows = []
    for code, d in ctx.crop.items():
        for t in range(a.first, ctx.Y1 + 1):
            m = b.Model(ctx, code, t - 1)
            if not m.valid:
                continue
            ti = t - ctx.cy0
            regions = m.regions(d["ok"][:, ti])
            if not regions:
                continue
            pool = m.pool
            w = b.enso_weights(ctx.roni_d[pool], ctx.roni_j[pool], b.stat_enso_forecast(ctx.roni, t), *cfg)
            wb = np.full(pool.sum(), 1 / pool.sum())
            mu, sd, _ = m.members(regions, t, ante_use=("fall",))
            mu0, _, _ = m.members(regions, t, ante_use=())
            med = b.mix_quantiles(mu, w, sd, [0.5])[:, 0]
            med_blind = b.mix_quantiles(mu, wb, sd, [0.5])[:, 0]  # same, without the El Nino weighting
            normal = b.mix_quantiles(mu0, wb, sd, [0.5])[:, 0]
            p_below = b.mix_cdf(normal, mu, w, sd)
            y = d["obs"][regions, ti]
            pit = b.mix_cdf(y, mu, w, sd)
            for i, r in enumerate(regions):
                past = d["obs"][r, :ti][~np.isnan(d["obs"][r, :ti])]
                naive = past[-5:].mean() if len(past) >= 5 else np.nan
                known = m.predict_known(r, ti) if not np.isnan(m.B[r, ti]).any() else np.nan
                rows.append((code, y[i], med[i], normal[i], p_below[i], naive, known, t, pit[i], med_blind[i]))
        print(f"  tested {code}", flush=True)

    def score(sel, label):
        y, med, nor, pb, nv, kw = (np.array([r[k] for r in sel]) for k in range(1, 7))
        err = lambda pred: np.abs(np.exp(y - pred) - 1) * 100
        ok = ~np.isnan(nv)
        okk = ~np.isnan(kw)
        below = (y < nor).astype(float)
        return {
            "crop": label, "n": len(sel),
            "med_err": float(np.median(err(med))), "mean_err": float(np.mean(err(med))),
            "naive_med_err": float(np.median(err(nv[ok]))),
            "within10": float(np.mean(err(med) <= 10) * 100), "within20": float(np.mean(err(med) <= 20) * 100),
            "dir_corr": float(np.corrcoef(med - nor, y - nor)[0, 1]),
            "brier_skill": float((1 - np.mean((pb - below) ** 2) / np.mean((0.5 - below) ** 2)) * 100),
            "known_wx_med_err": float(np.median(err(kw[okk]))),
            "known_wx_r2": float((1 - np.sum((y[okk] - kw[okk]) ** 2) / np.sum((y[okk] - nor[okk]) ** 2)) * 100),
        }

    out = [score([r for r in rows if r[0] == c], c) for c in ctx.crop] + [score(rows, "ALL")]
    print(f"\nwalk-forward test {a.first}-{ctx.Y1}, El Nino weighting h={cfg[0]} lam={cfg[1]}")
    print(f"{'crop':7s} {'n':>5s} {'medErr':>7s} {'meanErr':>7s} {'naive':>6s} {'<=10%':>6s} {'<=20%':>6s} "
          f"{'dirCorr':>7s} {'BSS':>6s} | {'knownWx':>7s} {'R2wx':>6s}")
    for s in out:
        print(f"{s['crop']:7s} {s['n']:5d} {s['med_err']:6.1f}% {s['mean_err']:6.1f}% {s['naive_med_err']:5.1f}% "
              f"{s['within10']:5.0f}% {s['within20']:5.0f}% {s['dir_corr']:7.2f} {s['brier_skill']:5.1f}% | "
              f"{s['known_wx_med_err']:6.1f}% {s['known_wx_r2']:5.0f}%")

    # ---- by ENSO phase of the winter before the season ("strong El Nino" = DJF RONI >= 1.0, also El Nino)
    in80, in95 = coverage(rows)
    djf = {t: float(ctx.roni_d[t - ctx.cy0]) for t in {r[7] for r in rows}}

    def phase_score(idx, label):
        sel = [rows[i] for i in idx]
        y, med, nv, kw, mb = (np.array([r[k] for r in sel]) for k in (1, 2, 5, 6, 9))
        err = lambda pred: np.abs(np.exp(y - pred) - 1) * 100
        ok, okk = ~np.isnan(nv), ~np.isnan(kw)
        return {"group": label, "seasons": sorted({r[7] for r in sel}), "n": len(sel),
                "med_err": float(np.median(err(med))), "no_enso_med_err": float(np.median(err(mb))),
                "naive_med_err": float(np.median(err(nv[ok]))), "within20": float(np.mean(err(med) <= 20) * 100),
                "cov80": float(in80[idx].mean() * 100), "cov95": float(in95[idx].mean() * 100),
                # median actual vs middle estimate: + = yields beat the forecast, - = forecast too high
                "bias": float(np.median(np.exp(y - med) - 1) * 100),
                "known_wx_med_err": float(np.median(err(kw[okk])))}

    groups = {"strong El Nino": lambda t: djf[t] >= 1.0, "El Nino (all)": lambda t: djf[t] >= 0.5,
              "neutral": lambda t: -0.5 < djf[t] < 0.5, "La Nina": lambda t: djf[t] <= -0.5}
    by_phase = [phase_score(np.array([i for i, r in enumerate(rows) if f(r[7])]), g) for g, f in groups.items()]
    by_phase.append(phase_score(np.arange(len(rows)), "all seasons"))
    head = (f"{'':16s} {'seasons':>7s} {'n':>5s} {'medErr':>7s} {'noENSO':>7s} {'naive':>6s} {'<=20%':>6s} "
            f"{'cov80':>6s} {'cov95':>6s} {'bias':>6s} | {'knownWx':>7s}")
    print(f"\nby ENSO phase of the winter before the season (DJF RONI: El Nino >= +0.5, strong >= +1.0); "
          f"noENSO = same model without the El Nino weighting; bias = median actual vs middle estimate")
    print(head)
    for s in by_phase:
        print(f"{s['group']:16s} {len(s['seasons']):7d} {s['n']:5d} {s['med_err']:6.1f}% {s['no_enso_med_err']:6.1f}% "
              f"{s['naive_med_err']:5.1f}% {s['within20']:5.0f}% {s['cov80']:5.0f}% {s['cov95']:5.0f}% "
              f"{s['bias']:+5.1f}% | {s['known_wx_med_err']:6.1f}%")
    by_year = [phase_score(np.array([i for i, r in enumerate(rows) if r[7] == t]), str(t))
               for t in sorted(djf) if djf[t] >= 0.5]
    print("\neach El Nino season")
    print(head.replace("seasons", "   DJF "))
    for s in by_year:
        t = int(s["group"])
        print(f"{t:<16d} {djf[t]:+7.2f} {s['n']:5d} {s['med_err']:6.1f}% {s['no_enso_med_err']:6.1f}% "
              f"{s['naive_med_err']:5.1f}% {s['within20']:5.0f}% {s['cov80']:5.0f}% {s['cov95']:5.0f}% "
              f"{s['bias']:+5.1f}% | {s['known_wx_med_err']:6.1f}%")
    by_crop = []
    print("\nby crop: El Nino seasons (DJF >= +0.5) vs the rest")
    print(f"{'crop':7s} {'Nino seasons':>12s} {'medErr':>7s} {'naive':>6s} {'cov80':>6s} {'bias':>6s} | "
          f"{'other medErr':>12s} {'naive':>6s} {'cov80':>6s} {'bias':>6s}")
    for c in ctx.crop:
        ni = np.array([i for i, r in enumerate(rows) if r[0] == c and djf[r[7]] >= 0.5])
        oi = np.array([i for i, r in enumerate(rows) if r[0] == c and djf[r[7]] < 0.5])
        if len(ni) == 0 or len(oi) == 0:
            continue
        sn, so = phase_score(ni, c), phase_score(oi, c)
        by_crop.append({"crop": c, "el_nino": sn, "other": so})
        print(f"{c:7s} {len(sn['seasons']):12d} {sn['med_err']:6.1f}% {sn['naive_med_err']:5.1f}% {sn['cov80']:5.0f}% "
              f"{sn['bias']:+5.1f}% | {so['med_err']:11.1f}% {so['naive_med_err']:5.1f}% {so['cov80']:5.0f}% {so['bias']:+5.1f}%")
    if a.json:
        Path(a.json).write_text(json.dumps({"crops": out, "by_enso_phase": by_phase, "el_nino_seasons": by_year,
                                            "by_crop_enso": by_crop}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
