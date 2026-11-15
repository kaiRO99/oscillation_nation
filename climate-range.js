'use strict';
// ---------------------------------------------------------------------------
// 80% ranges for forecast climate months. Shared by app.js (tooltip, selected-ecodistrict panel) and
// report.js; pure functions, no globals from either page.
//
// The seasonal forecast is the MEAN of ECMWF's 51 ensemble members (pipeline/fetch_forecast.py). We have
// neither the members nor ECMWF's past forecasts, so how skilful the forecast is here is unknown. The range
// is therefore the forecast plus how far this calendar month has strayed from its usual level in this
// ecodistrict over the observed record (NASA POWER, 1981 on):
//   'add' (temperatures, frost days): the 10th-90th percentile of the year-to-year departures from the
//         ecodistrict's own linear trend for that calendar month, added to the forecast
//   'mul' (precipitation): the 10th-90th percentile of that month's total / its long-term mean, times the
//         forecast, so the range stays above zero and skewed the way rainfall is
// It gives the forecast no credit for skill (where ECMWF is skilful the range is wider than it needs to be), and
// it can't allow for the forecast itself being off: a seasonal model drifts from its own climate, which ECMWF
// removes with its past forecasts (re-forecasts), and we have none. (The yield forecast treats this forecast the
// same way: it shifts the centre and keeps the past spread.)
// ---------------------------------------------------------------------------
const FC_RANGE_KIND = {
  T2M: 'add', T2M_MAX: 'add', T2M_MIN: 'add', FROST_DAYS: 'add', PRECIP: 'mul', PRECIP_DAILY: 'mul',
};
const FC_RANGE_Q = [0.1, 0.9];
const FC_RANGE_MIN_YEARS = 15;

// linear-interpolated quantile of an ascending array
function quantileSorted(s, q) {
  const h = (s.length - 1) * q, i = Math.floor(h);
  return i + 1 < s.length ? s[i] + (h - i) * (s[i + 1] - s[i]) : s[i];
}

const daysInMonth = (year, month0) => new Date(Date.UTC(year, month0 + 1, 0)).getUTCDate();

// [lo, hi] departures ('add') or ratios ('mul') for one ecodistrict and calendar month m (0-11), or null.
// val(t) gives the value for month index t or null; only months t < nObs (observed) count.
function climateSpread(val, nObs, m, kind) {
  const xs = [], ys = [];
  for (let t = m; t < nObs; t += 12) {
    const v = val(t);
    if (v != null) { xs.push(t); ys.push(v); }
  }
  const n = ys.length;
  if (n < FC_RANGE_MIN_YEARS) return null;
  let dev;
  if (kind === 'mul') {
    const mean = ys.reduce((s, v) => s + v, 0) / n;
    if (!(mean > 0)) return null;
    dev = ys.map((v) => v / mean);
  } else {
    const mx = xs.reduce((s, v) => s + v, 0) / n, my = ys.reduce((s, v) => s + v, 0) / n;
    let sxy = 0, sxx = 0;
    for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; }
    const b = sxx ? sxy / sxx : 0;
    dev = ys.map((v, i) => v - (my + b * (xs[i] - mx)));
  }
  dev.sort((a, b) => a - b);
  return FC_RANGE_Q.map((q) => quantileSorted(dev, q));
}

// [lo, hi] around forecast value f, or null. days = days in that month (frost days can't exceed it).
function climateRange(key, f, spread, days) {
  const kind = FC_RANGE_KIND[key];
  if (f == null || !spread || !kind) return null;
  let [lo, hi] = kind === 'mul' ? [f * spread[0], f * spread[1]] : [f + spread[0], f + spread[1]];
  if (key === 'FROST_DAYS') { lo = Math.min(days, Math.max(0, lo)); hi = Math.min(days, Math.max(0, hi)); }
  return hi - lo > 1e-9 ? [lo, hi] : null;  // e.g. every January day below freezing: no range to show
}
