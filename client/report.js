// Comparison report: your ecodistrict in one month vs a similar region in its matched month.
//   report.html?a=<your id>&ta=YYYY-MM&b=<their id>&tb=YYYY-MM[&pa=nino|neutral|nina&pb=...]
// Opened from a match in the map's "Places like yours" panel. Built from the same static files the map
// uses (data/); no backend. Download = the browser's print dialog -> Save as PDF (see report.css).
'use strict';

const params = new URLSearchParams(location.search);

// reuse the ?v= from this script's URL (set in report.html) so data files are cache-busted together
const V = new URL(document.currentScript.src).searchParams.get('v') || '0';
const withV = (path) => `${path}?v=${V}`;

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, nd = 1) => (v == null || Number.isNaN(Number(v)) ? '–' : Number(v).toFixed(nd));
const signed = (v, nd = 1) => (v == null || Number.isNaN(v) ? '–' : `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v).toFixed(nd)}`);

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
  'November', 'December'];
const ENSO = { nino: 'El Niño', neutral: 'Neutral', nina: 'La Niña' };
const NORMAL = [1991, 2020];
const CROP_GROUPS = { // crop_fields keys -> display name (same groups as the map)
  cereals: 'Cereals', corn: 'Corn', canola: 'Canola & oilseeds', soy: 'Soybeans', pulses: 'Pulses',
  veg: 'Vegetables & potatoes', fruit: 'Fruit, berries & vines', other: 'Other crops',
};
const SOIL_KEYS = ['awhc', 'sand', 'silt', 'clay', 'oc', 'ph', 'drainage'];
// climate variables compared for the two matched months: [key, decimals]
const CLIMATE = [['T2M', 1], ['T2M_MAX', 1], ['T2M_MIN', 1], ['FROST_DAYS', 0], ['PRECIP', 0], ['SNODP', 0],
  ['ET', 0], ['GWETROOT', 2]];

$('#print').addEventListener('click', () => window.print());

const getJSON = (p) => fetch(withV(p)).then((r) => {
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
});
const getBin = (p) => fetch(withV(p)).then((r) => (r.ok ? r.arrayBuffer() : null)).catch(() => null);

class ReportError extends Error {}

async function load() {
  const a = Number(params.get('a')), b = Number(params.get('b'));
  const ta = params.get('ta'), tb = params.get('tb');
  if (!a || !b) return fail('Pick your ecodistrict on the map, click a similar region, then “Generate report”.');
  if (![ta, tb].every((m) => /^\d{4}-\d{2}$/.test(m ?? ''))) return fail('The report link is missing its months (ta, tb).');
  try {
    const [eco, aci, meta, simMeta] = await Promise.all([
      getJSON('data/ecodistricts.json'),
      getJSON('data/aci_classes.json'),
      getJSON('data/climate/meta.json'),
      getJSON('data/similarity/meta.json').catch(() => null),
    ]);
    for (const id of [a, b]) if (!eco.d[id]) throw new ReportError(`No ecodistrict ${id}.`);
    const [simBuf, ...bins] = await Promise.all([
      simMeta?.pool.includes(a) ? getBin(`data/similarity/${a}.bin`) : null,
      ...CLIMATE.map(([k]) => getBin(`data/climate/${k}.bin`)),
    ]);
    const ctx = { eco, aci, meta, simMeta, simBuf, bins: Object.fromEntries(CLIMATE.map(([k], i) => [k, bins[i] && new Int16Array(bins[i])])) };
    render(buildReport(ctx, { id: a, month: ta, phase: params.get('pa') }, { id: b, month: tb, phase: params.get('pb') }));
  } catch (e) {
    fail(e instanceof ReportError ? e.message : `Could not load the report data (${e.message}).`);
  }
}

function fail(msg) {
  $('#report').innerHTML = `<p class="status error">${esc(msg)}</p>`;
}

// ---------------------------------------------------------------------------
// Report data
// ---------------------------------------------------------------------------
const districtName = (r) => `${r.region_name || 'Ecoregion ' + r.region}${r.prov ? ', ' + r.prov : ''}`;
const monthIndex = (ym, start) => (Number(ym.slice(0, 4)) - Number(start.slice(0, 4))) * 12 + Number(ym.slice(5, 7)) - Number(start.slice(5, 7));
const monthName = (ym) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;

function buildReport(ctx, A, B) {
  const { meta } = ctx;
  for (const side of [A, B]) {
    side.t = monthIndex(side.month, meta.start);
    if (side.t < 0 || side.t >= meta.months) throw new ReportError(`${side.month} is outside the data (${meta.start} onward).`);
    side.r = ctx.eco.d[side.id];
    side.name = `${districtName(side.r)} (${side.id})`;
    side.row = meta.ids.indexOf(side.id);
    side.forecast = isForecast(meta, side.t);
  }
  return {
    A, B,
    match: findMatch(ctx, A, B),
    distance_km: haversine(A.r.lp, B.r.lp),
    climate: CLIMATE.map(([key, nd]) => ({
      key, nd, label: meta.vars[key].label, units: meta.vars[key].units,
      a: climateAt(ctx, key, A), b: climateAt(ctx, key, B),
    })),
    soil: [soilData(A.r, ctx.eco), soilData(B.r, ctx.eco)],
    crops: [cropData(A.r, ctx.eco, ctx.aci), cropData(B.r, ctx.eco, ctx.aci)],
    soilFields: ctx.eco.soil_fields,
    sources: [...Object.values(ctx.eco.sources ?? {}), meta.source, meta.extension?.source].filter(Boolean),
    similarity_method: ctx.simMeta?.method,
  };
}

function isForecast(meta, t) {
  const ext = meta.extension;
  if (!ext) return false;
  return ext.kinds?.[t - monthIndex(ext.first, meta.start)] === 'forecast';
}

// The match as stored in A's similarity file (rank 1..k and score), or null if B isn't in A's top k for
// that month. File layout (similarity/meta.json): [month][k] x 4 bytes = uint16 LE pool index, uint8 year
// offset from start, uint8 score.
function findMatch({ simMeta, simBuf }, A, B) {
  if (!simBuf) return null;
  const { k, pool, start } = simMeta;
  const dv = new DataView(simBuf);
  const yB = Number(B.month.slice(0, 4)) - Number(start.slice(0, 4));
  for (let i = 0; i < k; i++) {
    const o = (A.t * k + i) * 4;
    if (o + 4 > simBuf.byteLength) break;
    if (pool[dv.getUint16(o, true)] === B.id && dv.getUint8(o + 2) === yB) return { rank: i + 1, score: dv.getUint8(o + 3), k };
  }
  return null;
}

// value in that month and its difference from the district's 1991-2020 normal for the calendar month
function climateAt({ meta, bins }, key, side) {
  const a = bins[key];
  if (!a || side.row < 0) return { v: null, anom: null };
  const n = meta.months, scale = meta.vars[key].scale, base = side.row * n;
  const val = (t) => (a[base + t] === -32768 ? null : a[base + t] * scale);
  const y0 = Number(meta.start.slice(0, 4));
  let s = 0, c = 0;
  for (let y = NORMAL[0]; y <= NORMAL[1]; y++) {
    const t = (y - y0) * 12 + (side.t % 12);
    const v = t >= 0 && t < n ? val(t) : null;
    if (v != null) { s += v; c++; }
  }
  const v = val(side.t);
  return { v, anom: v != null && c ? v - s / c : null };
}

function haversine([lon1, lat1], [lon2, lat2]) {
  const rad = Math.PI / 180, dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

function soilData(r, eco) {
  const s = r.soil;
  return s ? { order: eco.soil_orders[s.order] ?? s.order, order_pct: s.order_pct, ...Object.fromEntries(SOIL_KEYS.map((k) => [k, s[k]])) } : null;
}

function cropData(r, eco, aci) { // latest crop inventory year
  if (!r.crops) return null;
  const year = Math.max(...Object.keys(r.crops).map(Number));
  const row = Object.fromEntries(eco.crop_fields.map((f, i) => [f, r.crops[year][i]]));
  return {
    year, cropland: row.crop, pasture: row.pasture,
    top: row.top != null ? aci.classes[row.top]?.[0] : null,
    groups: Object.fromEntries(Object.keys(CROP_GROUPS).map((k) => [k, row[k] ?? 0])),
  };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
const phaseChip = (p) => (ENSO[p] ? `<span class="chip ${p}">${ENSO[p]}</span>` : '');
const sideHead = (s, cls) => `<th scope="col" class="side ${cls}">${esc(s.name)}<span class="sub">${monthName(s.month)}${s.forecast ? ' · forecast' : ''}</span></th>`;

function render(d) {
  const { A, B } = d;
  // Chrome and Edge suggest the page title as the PDF file name
  document.title = `Oscillation Nation - ${A.id} ${A.month} vs ${B.id} ${B.month}`;
  const today = new Date().toLocaleDateString('en-CA', { year: 'numeric', month: 'long', day: 'numeric' });
  const head = `<tr><th scope="col"></th>${sideHead(A, 'a')}${sideHead(B, 'b')}</tr>`;

  $('#report').innerHTML = `
    <header class="report-head">
      <p class="eyebrow">Comparison report</p>
      <h1><span class="a-ink">${esc(A.name)}</span> <span class="vs">vs</span> <span class="b-ink">${esc(B.name)}</span></h1>
      <p class="meta">Ecodistrict ${A.id} in ${monthName(A.month)} compared with ecodistrict ${B.id} in ${monthName(B.month)} · generated ${today}</p>
    </header>

    <section class="summary">
      <div class="card a">
        <p class="label">Your district</p>
        <p class="name">${esc(A.name)}</p>
        <p>${monthName(A.month)}${A.forecast ? ' (forecast)' : ''} ${phaseChip(A.phase)}</p>
      </div>
      <div class="score">
        ${d.match ? `<b>${d.match.score}</b><span>similarity</span><span class="muted">match #${d.match.rank} of ${d.match.k}</span>` : '<span class="muted">not in the top matches</span>'}
      </div>
      <div class="card b">
        <p class="label">Similar region</p>
        <p class="name">${esc(B.name)}</p>
        <p>${monthName(B.month)} ${phaseChip(B.phase)}</p>
      </div>
    </section>
    <p class="lede">Conditions in <b>${esc(B.name)}</b> in ${monthName(B.month)} were among the closest to
      <b>${esc(A.name)}</b> in ${monthName(A.month)}${A.forecast ? ' as forecast' : ''}. The two districts are
      ${Math.round(d.distance_km).toLocaleString()} km apart. What happened there can show what to expect, and what worked.</p>

    <section>
      <h2>Conditions in the matched months</h2>
      <p class="muted small">In brackets: difference from each district's ${NORMAL[0]}–${NORMAL[1]} normal for that calendar month.</p>
      <table class="compare">
        <thead>${head}</thead>
        <tbody>${d.climate.map((c) => `<tr>
          <th scope="row">${esc(c.label)} <span class="muted">(${esc(c.units)})</span></th>
          ${[c.a, c.b].map((x) => `<td class="num">${fmt(x.v, c.nd)} <span class="muted">(${signed(x.anom, c.nd)})</span></td>`).join('')}
        </tr>`).join('')}</tbody>
      </table>
    </section>

    <section>
      <h2>Overview</h2>
      <table class="compare">
        <thead>${head}</thead>
        <tbody>
          <tr><th scope="row">Ecodistrict</th><td>${A.id}</td><td>${B.id}</td></tr>
          <tr><th scope="row">Ecoregion</th><td>${esc(A.r.region_name ?? A.r.region)}</td><td>${esc(B.r.region_name ?? B.r.region)}</td></tr>
          <tr><th scope="row">Province</th><td>${esc(A.r.prov ?? '–')}</td><td>${esc(B.r.prov ?? '–')}</td></tr>
          <tr><th scope="row">Area</th><td>${Number(A.r.area).toLocaleString()} km²</td><td>${Number(B.r.area).toLocaleString()} km²</td></tr>
          <tr><th scope="row">Location</th><td>${latLon(A.r.lp)}</td><td>${latLon(B.r.lp)}</td></tr>
          <tr><th scope="row">ENSO phase in matched month</th><td>${phaseChip(A.phase) || '–'}</td><td>${phaseChip(B.phase) || '–'}</td></tr>
        </tbody>
      </table>
    </section>

    ${soilSection(d, head)}
    ${cropSection(d, head)}

    <section class="placeholder">
      <h2>What farmers there did</h2>
      <p>Coming soon: yields, irrigation and practices in ${esc(B.name)} around ${monthName(B.month)}, and how well they worked.</p>
    </section>

    <footer class="sources">
      <h2>Sources</h2>
      <ul>${d.sources.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>
      ${d.similarity_method ? `<p>Similarity: ${esc(d.similarity_method)}.</p>` : ''}
    </footer>`;
}

const latLon = (lp) => (lp ? `${fmt(lp[1], 2)}° N, ${fmt(-lp[0], 2)}° W` : '–');

function soilSection(d, head) {
  const [sa, sb] = d.soil;
  if (!sa && !sb) return '<section><h2>Soil</h2><p class="muted">No soil survey data for either district.</p></section>';
  const cell = (s, k, nd = 1) => `<td class="num">${s ? fmt(s[k], nd) : '–'}</td>`;
  return `<section>
    <h2>Soil</h2>
    <table class="compare">
      <thead>${head}</thead>
      <tbody>
        <tr><th scope="row">Dominant soil order</th>${[sa, sb].map((s) => `<td>${s ? `${esc(s.order)}${s.order_pct ? ` <span class="muted">(${s.order_pct}%)</span>` : ''}` : '–'}</td>`).join('')}</tr>
        ${SOIL_KEYS.map((k) => `<tr><th scope="row">${esc(d.soilFields[k])}</th>${cell(sa, k)}${cell(sb, k)}</tr>`).join('')}
      </tbody>
    </table>
  </section>`;
}

function cropSection(d, head) {
  const [ca, cb] = d.crops;
  if (!ca && !cb) return '<section><h2>Crops</h2><p class="muted">No crop inventory data for either district.</p></section>';
  const pct = (c, v) => `<td class="num">${c ? fmt(v) + '%' : '–'}</td>`;
  return `<section>
    <h2>Crops</h2>
    <p class="muted small">Latest Annual Crop Inventory year${ca && cb && ca.year !== cb.year ? 's' : ''}: ${[...new Set([ca?.year, cb?.year].filter(Boolean))].join(', ')}. Crop groups are a share of cropland.</p>
    <table class="compare">
      <thead>${head}</thead>
      <tbody>
        <tr><th scope="row">Most common crop</th><td>${esc(ca?.top ?? '–')}</td><td>${esc(cb?.top ?? '–')}</td></tr>
        <tr><th scope="row">Cropland (% of land)</th>${pct(ca, ca?.cropland)}${pct(cb, cb?.cropland)}</tr>
        <tr><th scope="row">Pasture (% of land)</th>${pct(ca, ca?.pasture)}${pct(cb, cb?.pasture)}</tr>
        ${Object.entries(CROP_GROUPS).filter(([k]) => ca?.groups[k] || cb?.groups[k]).map(([k, g]) => `<tr>
          <th scope="row">${esc(g)}</th>${pct(ca, ca?.groups[k])}${pct(cb, cb?.groups[k])}</tr>`).join('')}
      </tbody>
    </table>
  </section>`;
}

load();
