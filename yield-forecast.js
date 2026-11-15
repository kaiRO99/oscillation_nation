'use strict';
// ---------------------------------------------------------------------------
// Yield forecast text for the Crop yield layer when the slider is in the forecast season.
// Data: data/yield_forecast.json from pipeline/build_yield_forecast.py (method + caveats in that
// script's docstring and pipeline/README.md). app.js loads the data (state.yieldFc), draws the map
// (paintYieldForecast) and calls these builders for the layer's info text, the tooltip and the
// selected-ecodistrict panel. Uses app.js globals: state, esc, fmt, signed, infoHtml, yieldFcRec,
// cropPresence, isYieldFc.
// ---------------------------------------------------------------------------

// past seasons whose summer had a big non-ENSO cause, flagged when they show up as El Niño analogs
const YF_ANALOG_NOTE = { 1992: 'Pinatubo eruption cooled that summer', 1983: 'followed the 1982 El Chichón eruption' };

const yfKg = (v) => (v == null ? '–' : Math.round(v).toLocaleString('en-CA'));
const yfPct = (p) => `${Math.round(p * 100)}%`;
const yfSp0 = (v) => signed(Math.round(v) === 0 ? 0 : v, 0);  // signed whole number, never "−0"
const yfLabel = (code) => state.yieldFc?.crops.find((c) => c[0] === code)?.[1] || state.yield?.crops.find((c) => c[0] === code)?.[1] || code;

// how far to trust this crop's forecast, from the walk-forward test (each year predicted from earlier years)
function yfSkillText(code) {
  const s = state.yieldFc.skill[code];
  if (!s) return '';
  const ci = s.crpss_enso_90ci;
  return `<b>Track record</b> (each year ${s.years[0]}–${s.years[1]} re-forecast from earlier years only): ` +
    `the 80% range held <b>${fmt(s.cov80, 0)}%</b> of actual yields and the 95% range ${fmt(s.cov95, 0)}%; ` +
    `typical miss of the middle estimate ${fmt(s.mape, 0)}%. ` +
    `Versus simply expecting the last 5 years’ average: ${signed(s.crpss_naive, 1)}% ` +
    `${s.crpss_naive >= 0 ? 'better' : '<b>worse</b>'}. ` +
    `El Niño weighting: ${signed(s.crpss_enso, 1)}% (90% CI ${signed(ci[0], 1)} to ${signed(ci[1], 1)}%)` +
    `${ci[0] > 0 ? '' : ', not distinguishable from no effect'}.` +
    (s.recent_below > 58
      ? ` <b>Optimistic lately:</b> since ${s.recent_from}, ${fmt(s.recent_below, 0)}% of actual yields came in below the middle estimate.`
      : s.recent_below < 42
        ? ` <b>Cautious lately:</b> since ${s.recent_from}, only ${fmt(s.recent_below, 0)}% came in below the middle estimate.`
        : '');
}

// layer info popover while the slider is in the forecast season
function yieldFcInfoHtml(code, label, mode) {
  const d = state.yieldFc, e = d.enso, g = e.hindcast_gain;
  if (!d.f[code]) {
    return `<b>${esc(label)}</b>: no ${d.target} forecast. It needs observed regional yields (Statistics Canada), ` +
      'which exist for the 12 principal field crops but not potatoes, hay or alfalfa.';
  }
  const top = e.analogs.slice(0, 4).map((a) => `${a.year}${YF_ANALOG_NOTE[a.year] ? '*' : ''}`).join(', ');
  return `<b>${esc(label)}: ${d.target} forecast.</b> Middle estimate per Census Agricultural Region (the finest level ` +
    'with observed yields), so ecodistricts in a region share it; hover or pick an ecodistrict for the 80% and 95% ranges. ' +
    (mode === 'anom'
      ? '“Difference from average” here means <b>% vs a normal year</b> with today’s farming and climate, not vs the long-term ' +
        'average, which for a forecast would mostly show the yield trend. '
      : '') +
    '<br><br><b>How:</b> a weather-to-yield model fitted on 1981–2025 observed yields and NASA POWER weather (summer highs, soil ' +
    'moisture, heat degree-days above 30 °C, dry spells, downpours, frost)' +
    (d.weather_model?.analog_blend > 0
      ? ', half regression and half <b>conditions-based analogs</b>: in the past seasons anywhere whose weather and normal ' +
        'climate were most like a given summer here, how far yields fell from their own normal'
      : '') +
    '; every past summer is ' +
    'a possible 2027 summer, moved onto today’s climate and onto this season’s starting soil moisture (observed fall 2026; ' +
    'ECMWF Oct–May precipitation forecast), weighted by NOAA CPC’s El Niño outlook ' +
    `(winter RONI ≈ ${signed(e.djf.median, 1)}, summer ≈ ${signed(e.jja.median, 1)}; closest past seasons ${top}). ` +
    (g ? `El Niño weighting improved past forecasts by only ${signed(g.crpss, 1)}% (90% CI ${signed(g.ci90[0], 1)} to ` +
      `${signed(g.ci90[1], 1)}%), so the forecast is mostly trend + starting conditions + an honest range. ` : '') +
    `<br><br>${yfSkillText(code)}`;
}

// why an ecodistrict has no forecast for a crop: no regional statistics here at all (e.g. Atlantic
// Canada), StatCan doesn't publish the crop for this region (e.g. wheat or canola in Ontario / Quebec),
// or it is published but too little was grown recently to forecast
function yfWhyNone(id, code, label) {
  const d = state.yieldFc, key = d.eco[id];
  if (!key) return 'no regional yield statistics here (StatCan’s regional table covers the Prairies, BC, Ontario and Quebec)';
  if (!(d.published?.[code] || []).includes(key)) return `Statistics Canada doesn’t publish ${esc(label.toLowerCase())} yields for ${esc(d.regions[key]?.name || 'this region')}`;
  return `too little ${esc(label.toLowerCase())} grown in ${esc(d.regions[key]?.name || 'this region')} recently to forecast`;
}

// tooltip lines for one ecodistrict
function yieldFcTipHtml(id, code) {
  const d = state.yieldFc, label = yfLabel(code), T = d.target;
  const head = `${esc(label)} ${T} <span class="fc-tag">forecast</span>`;
  if (!d.f[code]) return `<div class="muted">${head}: none for this crop (no observed regional yields)</div>`;
  const p = cropPresence(id, code, T);
  if (p === 'none') return `<div class="muted">${head}: none shown, not farmland</div>`;
  const r = yieldFcRec(id, code);
  if (!r) return `<div class="muted">${head}: none, ${yfWhyNone(id, code, label)}</div>`;
  const f = r.f, q = f.q;
  return `<div>${head}: <b>${yfKg(q[3])}</b> kg/ha <span class="muted">(80%: ${yfKg(q[1])}–${yfKg(q[5])})</span></div>` +
    `<div class="muted">${yfSp0(100 * (q[3] / f.normal - 1))}% vs a normal year · ${yfPct(f.p_below)} chance below normal · ` +
    `${esc(r.region.name)}</div>` +
    (p === 'trace' ? `<div class="muted"><b>Barely grown in this ecodistrict</b>; the figure is the region’s</div>` : '');
}

// selected-ecodistrict panel block
function yieldFcPanelHtml(id, code) {
  const d = state.yieldFc, label = yfLabel(code), T = d.target;
  const head = `<div class="you-head" style="margin-top:8px"><b>${esc(label)} ${T}</b> <span class="fc-tag">forecast</span>`;
  if (!d.f[code]) return `${head}</div><p class="small">No forecast for this crop (no observed regional yields).</p>`;
  if (cropPresence(id, code, T) === 'none') return `${head}</div><p class="small">Not farmland: no forecast shown.</p>`;
  const r = yieldFcRec(id, code);
  if (!r) { const why = yfWhyNone(id, code, label); return `${head}</div><p class="small">No forecast: ${why}.</p>`; }
  const f = r.f, q = f.q;
  const hist = d.hind[code]?.[r.key] || [];
  const inside = hist.filter((h) => h[4] >= h[1] && h[4] <= h[3]).length;
  const recent = 100 * (f.last5 / f.normal - 1);
  return `${head} ${infoHtml(yfDetailsHtml(f, T))}</div>` +
    `<div class="muted">${esc(r.region.name)} · regional figure</div>` +
    `<dl>` +
    `<dt>Middle estimate</dt><dd><b>${yfKg(q[3])}</b> kg/ha <span class="muted">(${yfSp0(100 * (q[3] / f.normal - 1))}% vs normal)</span></dd>` +
    `<dt>80% range</dt><dd>${yfKg(q[1])} – ${yfKg(q[5])}</dd>` +
    `<dt>95% range</dt><dd>${yfKg(q[0])} – ${yfKg(q[6])}</dd>` +
    `<dt>Normal year</dt><dd>${yfKg(f.normal)} <span class="muted">(last 5 yrs ${yfKg(f.last5)})</span></dd>` +
    `<dt>Below normal</dt><dd>${yfPct(f.p_below)} chance</dd>` +
    `<dt>≥20% shortfall</dt><dd>${yfPct(f.p_short)} chance <span class="muted">(usual ${yfPct(f.p_short_usual)})</span></dd>` +
    `</dl>` +
    (Math.abs(recent) > 10
      ? `<p class="small">The last 5 years ran ${yfSp0(recent)}% vs a normal year here (${recent < 0 ? 'hotter or drier' : 'kinder'} ` +
        `summers than usual); the forecast assumes ${T}’s summer could resemble any past one.</p>` : '') +
    yfChart(hist, f, T) +
    `<p class="small">Band: the 80% range forecast before each season from earlier years only; dots: what happened` +
    (hist.length ? ` (inside the band ${inside} of ${hist.length} years here).` : '.') + '</p>';
}

// details popover: what moves this season, El Niño analogs, climate change, track record
function yfDetailsHtml(f, T) {
  const d = state.yieldFc, s = d.start;
  const parts = [];
  if (s && s.mode !== 'none' && f.fall_z != null) {
    const word = f.fall_z > 0.5 ? 'wetter than normal' : f.fall_z < -0.5 ? 'drier than normal' : 'near normal';
    parts.push(`soil going into winter (Aug–Sep ${T - 1}, observed) ${word}: <b>${yfSp0(f.fx_fall)}%</b>`);
  }
  if (s && s.mode === 'fall+wspr' && f.wspr_pct != null) {
    parts.push(`Oct–May precipitation ${Math.round(f.wspr_pct)}% of normal${s.wspr_is_forecast ? ' (ECMWF forecast)' : ''}: ` +
      `<b>${yfSp0(f.fx_wspr)}%</b>`);
  }
  parts.push(`El Niño weighting: <b>${yfSp0(100 * (f.q[3] / f.qb[3] - 1))}%</b>`);
  const an = (d.enso.analogs || []).slice(0, (f.an || []).length).map((a, i) =>
    `${a.year}${YF_ANALOG_NOTE[a.year] ? '*' : ''} ${yfSp0(f.an[i])}%`).join(', ');
  const notes = (d.enso.analogs || []).slice(0, (f.an || []).length)
    .filter((a) => YF_ANALOG_NOTE[a.year]).map((a) => `*${a.year}: ${YF_ANALOG_NOTE[a.year]}`).join('; ');
  const warm = 100 * (f.normal / f.normal9120 - 1);
  const scen = (f.warm || []).map((w, i) => `+${d.warming[i]} °C: ${yfKg(w[3])} (${yfSp0(100 * (w[3] / f.q[3] - 1))}%)`).join(', ');
  return `<b>What moves ${T} vs a normal year:</b> ${parts.join('; ')}.` +
    (an ? `<br><br><b>Closest El Niño seasons</b>, if ${T}’s summer repeated them in today’s climate: ${an}.${notes ? ` ${esc(notes)}.` : ''}` : '') +
    `<br><br><b>Climate change:</b> ` +
    (Math.abs(f.dT_now) < 0.1
      ? 'summer daily highs here show no clear trend since 1981. '
      : `summer daily highs here trend ${signed(f.dT_now, 1)} °C vs 1991–2020, worth ${yfSp0(warm)}% on a normal year. `) +
    `If summers ran hotter than today’s trend: ${scen} (sensitivity of a statistical model` +
    (d.skill[state.yieldCrop]?.r2_weather == null
      ? '; weather explains little of the year-to-year swing, so treat these loosely).'
      : d.skill[state.yieldCrop].r2_weather < 3
        ? '; in past tests the summer’s weather explained none of this crop’s regional year-to-year swing, so these ' +
          'figures say very little).'
        : `; even with the summer known, weather explains only about ${d.skill[state.yieldCrop].r2_weather}% of ` +
          'this crop’s year-to-year swing in past tests, so treat these loosely).') +
    `<br><br>${yfSkillText(state.yieldCrop)}`;
}

// past-performance chart: hindcast 80% band + actual yields, then the forecast season's 80/95% range
function yfChart(hist, f, T) {
  const fq = f.q;
  const W = 300, H = 130, L = 34, Rm = 8, Tp = 8, B = 18;
  const pts = hist.map((h) => ({ y: h[0], lo: h[1], mid: h[2], hi: h[3], obs: h[4] }));
  const ys = [...pts.flatMap((p) => [p.lo, p.hi, p.obs]), fq[0], fq[6], f.normal];
  let lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo) * 0.06 || 100;
  lo = Math.max(0, lo - pad); hi += pad;
  const x0 = pts.length ? pts[0].y : T - 5, x1 = T;
  const X = (y) => L + (W - L - Rm) * (y - x0) / Math.max(1, x1 - x0);
  const Y = (v) => Tp + (H - Tp - B) * (1 - (v - lo) / (hi - lo));
  let s = `<svg class="yf-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Forecast ranges made before each season vs actual yields, and the ${T} forecast">`;
  const step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 3)));
  const st = [1, 2, 5].map((m) => m * step).find((v) => (hi - lo) / v <= 5) || step * 10;
  for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) {
    s += `<line x1="${L}" x2="${W - Rm}" y1="${Y(v)}" y2="${Y(v)}" stroke="#e2e0d8" stroke-width="0.6"/>` +
      `<text x="${L - 4}" y="${Y(v) + 3}" text-anchor="end">${yfKg(v)}</text>`;
  }
  const ticks = [x0, 2010, 2020, T].filter((v, i, a) => v >= x0 && v <= x1 && a.indexOf(v) === i)
    .filter((v) => v === x0 || v === T || (v - x0 > 3 && T - v > 3));
  for (const yr of ticks) {
    const anchor = yr === x0 ? 'start' : yr === T ? 'end' : 'middle';
    s += `<text x="${X(yr) + (yr === T ? 6 : 0)}" y="${H - 5}" text-anchor="${anchor}">${yr}</text>`;
  }
  if (pts.length > 1) {
    const band = pts.map((p) => `${X(p.y)},${Y(p.hi)}`).join(' ') + ' ' +
      pts.slice().reverse().map((p) => `${X(p.y)},${Y(p.lo)}`).join(' ');
    s += `<polygon points="${band}" fill="rgba(47,107,79,.16)"/>`;
    s += `<polyline points="${pts.map((p) => `${X(p.y)},${Y(p.mid)}`).join(' ')}" fill="none" stroke="#2f6b4f" stroke-width="1.2"/>`;
  }
  for (const p of pts) {
    const out = p.obs < p.lo || p.obs > p.hi;
    s += `<circle cx="${X(p.y)}" cy="${Y(p.obs)}" r="2.3" fill="${out ? '#c0392b' : '#1d2420'}"><title>${p.y}: actual ${yfKg(p.obs)}, ` +
      `80% range ${yfKg(p.lo)}–${yfKg(p.hi)}</title></circle>`;
  }
  const xt = X(T);
  s += `<line x1="${xt}" x2="${xt}" y1="${Y(fq[0])}" y2="${Y(fq[6])}" stroke="#2f6b4f" stroke-width="1"/>` +
    `<rect x="${xt - 4}" y="${Y(fq[5])}" width="8" height="${Math.max(1, Y(fq[1]) - Y(fq[5]))}" fill="#2f6b4f" opacity=".55"/>` +
    `<line x1="${xt - 6}" x2="${xt + 6}" y1="${Y(fq[3])}" y2="${Y(fq[3])}" stroke="#1d2420" stroke-width="1.6"/>` +
    `<line x1="${xt - 14}" x2="${xt + 6}" y1="${Y(f.normal)}" y2="${Y(f.normal)}" stroke="#5e6a63" stroke-dasharray="2 2" stroke-width="1"/>` +
    `<title>${T} forecast: ${yfKg(fq[3])} kg/ha, 80% ${yfKg(fq[1])}–${yfKg(fq[5])}, 95% ${yfKg(fq[0])}–${yfKg(fq[6])}; ` +
    `dashed = normal year ${yfKg(f.normal)}</title>`;
  return s + '</svg>';
}
