'use strict';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const ONI_SEASONS = ['DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ', 'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ'];
const ENSO = {
  nino: { label: 'El Niño', color: '#d0453a' },
  neutral: { label: 'Neutral', color: '#4c9a5b' },
  nina: { label: 'La Niña', color: '#2f6db5' },
};
const NORMAL = [1991, 2020];

// colour ramps (low -> high)
const RAMPS = {
  temp: ['#313695', '#4575b4', '#74add1', '#e0f3f8', '#fee090', '#f46d43', '#d73027', '#a50026'],
  wet: ['#f6efdc', '#d9e8b5', '#9fd2a8', '#5cb8b2', '#2b8cbe', '#225ea8', '#253494'],
  sun: ['#2c115f', '#721f81', '#b73779', '#f1605d', '#feb078', '#fcfdbf'],
  cold: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'],
  wind: ['#f7f4f9', '#d4b9da', '#c994c7', '#df65b0', '#980043'],
  soil: ['#f7f1e3', '#e3cfa1', '#c9a467', '#9a7240', '#5c4227'],
  awhc: ['#fff7d6', '#d6e9a8', '#86c58a', '#3c9a8f', '#1d5f80'],
  anomTemp: ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b'],
  anomWet: ['#8c510a', '#d8b365', '#f6e8c3', '#f5f5f5', '#c7eae5', '#5ab4ac', '#01665e'],
  money: ['#e8d49a', '#d8b365', '#c69a3f', '#b06a1c', '#8c3a10', '#5e1a08'],
};
const VAR_KIND = {
  T2M: 'temp', T2M_MAX: 'temp', T2M_MIN: 'temp', T2MDEW: 'temp', FROST_DAYS: 'cold', SNODP: 'cold', SNOWFALL: 'cold',
  PRECIP: 'wet', RH2M: 'wet', ET: 'wet', GWETTOP: 'wet', GWETROOT: 'wet', GWETPROF: 'wet', SOLAR: 'sun', WS2M: 'wind',
};
const SOIL_KIND = { awhc: 'awhc', sand: 'soil', silt: 'soil', clay: 'soil', oc: 'soil', ph: 'soil', drainage: 'wet' };
const SOIL_ORDER_COLORS = {
  BR: '#c98b4f', CH: '#3d2f22', CY: '#a8c6d9', GL: '#5e7f9a', LU: '#d9c58b', OR: '#6b4c7a', PZ: '#b8574a',
  RG: '#e6dfc9', SZ: '#9a9a6a', VE: '#4f6b3a',
};
const CROP_GROUPS = {
  cereals: ['Cereals', '#c08a3e'], corn: ['Corn', '#e94f37'], canola: ['Canola & oilseeds', '#f2cf2e'],
  soy: ['Soybeans', '#6f9a32'], pulses: ['Pulses', '#3f8f86'], veg: ['Vegetables & potatoes', '#8e5ba6'],
  fruit: ['Fruit, berries & vines', '#d0457e'], other: ['Other crops', '#8a8a8a'],
};

// irrigation crop-type colours (national breakdown bar) and the slider-month -> season mapping
const IRR_CROP_COLORS = {
  'Field crops': '#2b8cbe', 'Hay': '#86c58a', 'Improved pasture': '#c9a467',
  'Fruit': '#d0457e', 'Vegetable': '#8e5ba6', 'Forage crops': '#5ab4ac',
};
// calendar month index (0=Jan) -> irrigation season key; off-season months fall back to the full-season total
const IRR_MONTH_PERIOD = { 3: 'AM', 4: 'AM', 5: 'Jun', 6: 'Jul', 7: 'Aug', 8: 'SO', 9: 'SO' };

// Reuse the ?v= from this script's URL (set in index.html) so data files are cache-busted together
const V = new URL(document.currentScript.src).searchParams.get('v') || '0';
const withV = (path) => `${path}?v=${V}`;
const $ = (s) => document.querySelector(s);
const fmt = (v, nd = 1) => (v == null || Number.isNaN(v) ? '–' : Number(v).toFixed(nd));
const signed = (v, nd = 1) => (v == null ? '–' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(nd));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const state = {
  t: 0, y0: 1981, n: 0,
  climateVar: 'T2M', climateMode: 'value', soilVar: 'awhc',
  yieldCrop: 'WHTSPG', yieldMode: 'value', yield: null, yieldIdx: {}, yieldMeans: {}, yieldDomains: {},
  seededCrop: 'WHTSPG', seeded: null, seededIdx: {}, seededDomains: {}, seededMaxCache: {},
  finance: null, financeMetric: 'total_net', provPts: null, financeMeans: {},
  irrigation: null, irrigationPeriod: 'auto', irrigationGeo: 'basin', irrigationMode: 'value',
  drainageGeo: null, basinPts: null, eco2basin: {},
  meta: null, eco: null, ids: [], rowOf: {}, bins: {}, normals: {}, domains: {},
  oni: [], enso: [], oniFc: [], classes: {},
  nObs: 0, nowT: null, kinds: [], // months < nObs are NASA POWER; later ones come from Meteomatics
  simMeta: null, simCache: {}, sel: null, matches: [], shownMatches: new Set(), hover: null,
};

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/positron',
  center: [-98, 53],
  zoom: 3.4,
  maxZoom: 12,
  attributionControl: {
    compact: true,
    customAttribution: 'Ecodistricts, soil & crops © AAFC (OGL-Canada) · Climate: NASA POWER, Meteomatics · ONI © NOAA CPC',
  },
});
map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

const getJSON = (p) => fetch(withV(p)).then((r) => {
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
});

const dataReady = Promise.all([
  getJSON('data/oni.json'),
  getJSON('data/ecodistricts.json'),
  getJSON('data/climate/meta.json'),
  getJSON('data/aci_classes.json'),
  getJSON('data/similarity/meta.json').catch(() => null),
  getJSON('data/oni_forecast.json').catch(() => null),
  getJSON('data/yield.json').catch(() => null),
  getJSON('data/financials.json').catch(() => null),
  getJSON('data/seeded.json').catch(() => null),
  getJSON('data/irrigation.json').catch(() => null),
  getJSON('data/drainage.min.geojson').catch(() => null),
]);

const monthIndex = (ym, y0) => (Number(ym.slice(0, 4)) - y0) * 12 + Number(ym.slice(5, 7)) - 1;

const uiReady = dataReady.then(async ([oni, eco, meta, aci, simMeta, oniFc, yieldData, financeData, seededData, irrigationData, drainageData]) => {
  state.eco = eco;
  state.meta = meta;
  state.simMeta = simMeta;
  state.yield = yieldData;
  state.finance = financeData;
  if (financeData && !(state.financeMetric in financeData.metrics)) {
    state.financeMetric = Object.keys(financeData.metrics)[0];
  }
  if (yieldData) {
    yieldData.crops.forEach(([code], i) => { state.yieldIdx[code] = i; });
    if (!(state.yieldCrop in state.yieldIdx)) state.yieldCrop = yieldData.crops[0][0];
    const first = yieldData.d[Object.keys(yieldData.d)[0]];
    yieldData.y1 = yieldData.y0 + (first ? first[0].length - 1 : 0);
  }
  state.seeded = seededData;
  if (seededData) {
    seededData.crops.forEach(([code], i) => { state.seededIdx[code] = i; });
    if (!(state.seededCrop in state.seededIdx)) state.seededCrop = seededData.crops[0][0];
  }
  state.irrigation = irrigationData;
  state.drainageGeo = drainageData;
  if (!drainageData) state.irrigationGeo = 'prov';  // no basin geometry -> fall back to provinces
  state.classes = aci.classes;
  state.ids = meta.ids;
  meta.ids.forEach((id, i) => { state.rowOf[id] = i; });
  state.y0 = Number(meta.start.slice(0, 4));
  state.n = meta.months;
  state.nObs = meta.power_last ? monthIndex(meta.power_last, state.y0) + 1 : state.n;
  const ext = meta.extension;
  state.kinds = new Array(state.n).fill('observed');
  if (ext) {
    ext.kinds.forEach((k, i) => { state.kinds[state.nObs + i] = k; });
    state.nowT = clampT(monthIndex(ext.issued, state.y0));
  }
  buildEnso(oni.data.concat((oniFc?.data || []).map((r) => ({ ...r, forecast: true }))));

  const q = new URLSearchParams(location.search);
  const qm = /^(\d{4})-(\d{2})$/.exec(q.get('m') || '');
  state.t = qm ? clampT((Number(qm[1]) - state.y0) * 12 + Number(qm[2]) - 1) : clampT(state.nowT ?? state.n - 6); // default: this month
  if (meta.vars[q.get('v')]) state.climateVar = q.get('v');

  buildUI();
  await loadVar(state.climateVar);
  setMonth(state.t);
  const qd = Number(q.get('d'));
  if (qd && eco.d[qd]) selectDistrict(qd, { fly: false });
}).catch((e) => {
  console.error(e);
  $('#oni-text').textContent = 'Could not load the data files. Run the scripts in scripts/ first (see README).';
});

map.on('load', async () => {
  await uiReady;
  if (!state.eco) return;
  const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
  const fs = (k) => ['feature-state', k];
  const isNum = (k) => ['==', ['typeof', fs(k)], 'number'];

  map.addSource('ed', { type: 'geojson', data: withV('data/ecodistricts.min.geojson'), promoteId: 'id' });

  // soil (bottom), climate, then boundaries / matches / selection
  map.addLayer({ id: 'soil-fill', type: 'fill', source: 'ed', layout: { visibility: 'none' },
    paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.8 } }, firstLabel);
  map.addLayer({ id: 'climate-fill', type: 'fill', source: 'ed',
    paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.72 } }, firstLabel);
  map.addLayer({ id: 'seeded-fill', type: 'fill', source: 'ed', layout: { visibility: 'none' },
    paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.78 } }, firstLabel);
  map.addLayer({ id: 'irrigation-fill', type: 'fill', source: 'ed', layout: { visibility: 'none' },
    paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.78 } }, firstLabel);
  // irrigation by drainage basin: a separate, finer sub-provincial geography (own source)
  if (state.drainageGeo) {
    map.addSource('drainage', { type: 'geojson', data: state.drainageGeo });
    map.addLayer({ id: 'drainage-fill', type: 'fill', source: 'drainage', layout: { visibility: 'none' },
      paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.82 } }, firstLabel);
    map.addLayer({ id: 'drainage-line', type: 'line', source: 'drainage', layout: { visibility: 'none' },
      paint: { 'line-color': '#0b3c5d', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.4, 8, 1.4], 'line-opacity': 0.5 } }, firstLabel);
  }
  // yield fades where the crop is barely seeded (feature-state 'yg' = share of the region's
  // own peak planting); unknown (no seeded data) coalesces to 1 so it stays full strength.
  map.addLayer({ id: 'yield-fill', type: 'fill', source: 'ed', layout: { visibility: 'none' },
    paint: { 'fill-color': 'rgba(0,0,0,0)',
      'fill-opacity': ['interpolate', ['linear'], ['coalesce', fs('yg'), 1], 0, 0.12, 0.05, 0.78] } }, firstLabel);
  map.addLayer({ id: 'hit', type: 'fill', source: 'ed', paint: { 'fill-color': '#000', 'fill-opacity': 0 } }, firstLabel);
  map.addLayer({ id: 'lines', type: 'line', source: 'ed',
    paint: { 'line-color': '#34413a', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.2, 8, 1], 'line-opacity': 0.45 } }, firstLabel);
  map.addLayer({ id: 'match-fill', type: 'fill', source: 'ed',
    paint: { 'fill-color': '#ff8a00', 'fill-opacity': ['case', isNum('match'), 0.55, 0] } }, firstLabel);
  map.addLayer({ id: 'match-line', type: 'line', source: 'ed',
    paint: { 'line-color': '#b35c00', 'line-width': ['case', isNum('match'), 1.6, 0] } });
  map.addLayer({ id: 'hover-line', type: 'line', source: 'ed',
    paint: { 'line-color': '#111', 'line-width': ['case', ['boolean', fs('hover'), false], 1.6, 0] } });
  map.addLayer({ id: 'sel-line', type: 'line', source: 'ed',
    paint: { 'line-color': '#111', 'line-width': ['case', ['boolean', fs('sel'), false], 3, 0] } });

  // crop bubbles at each ecodistrict's label point
  const pts = Object.entries(state.eco.d).filter(([, r]) => r.crops)
    .map(([id, r]) => ({ type: 'Feature', id: Number(id), properties: { id: Number(id) }, geometry: { type: 'Point', coordinates: r.lp } }));
  map.addSource('crop-pts', { type: 'geojson', data: { type: 'FeatureCollection', features: pts } });
  const sq = ['sqrt', ['coalesce', fs('crop'), 0]];
  const grpColor = ['match', ['coalesce', fs('grp'), ''], ...Object.entries(CROP_GROUPS).flatMap(([k, [, c]]) => [k, c]), '#999'];
  map.addLayer({ id: 'crops', type: 'circle', source: 'crop-pts', layout: { visibility: 'none' },
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, ['*', sq, 0.45], 6, ['*', sq, 1.3], 9, ['*', sq, 3]],
      'circle-color': grpColor, 'circle-opacity': ['case', isNum('crop'), 0.88, 0],
      'circle-stroke-color': '#fff', 'circle-stroke-width': ['case', isNum('crop'), 0.8, 0],
    } });

  // farm-support payment labels: one dollar figure per province (no colour fill)
  const labelFont = map.getStyle().layers.find((l) => l.type === 'symbol' && l.layout?.['text-font'])?.layout['text-font'] || ['Noto Sans Regular'];
  map.addSource('finance-pts', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'finance-labels', type: 'symbol', source: 'finance-pts', layout: {
      visibility: 'none',
      'text-field': ['get', 'label'],
      'text-font': labelFont,
      'text-size': ['interpolate', ['linear'], ['zoom'], 3, 12, 6, 17, 9, 22],
      'text-allow-overlap': false,
      'text-padding': 4,
    }, paint: {
      'text-color': ['coalesce', ['get', 'color'], '#8c3a10'], 'text-halo-color': '#fff', 'text-halo-width': 2, 'text-halo-blur': 0.4,
    } });

  // irrigation volume labels: one m³ figure per province
  map.addSource('irrigation-pts', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'irrigation-labels', type: 'symbol', source: 'irrigation-pts', layout: {
      visibility: 'none',
      'text-field': ['get', 'label'],
      'text-font': labelFont,
      'text-size': ['interpolate', ['linear'], ['zoom'], 3, 12, 6, 17, 9, 22],
      'text-allow-overlap': false,
      'text-padding': 4,
    }, paint: {
      'text-color': '#0b3c5d', 'text-halo-color': '#fff', 'text-halo-width': 2, 'text-halo-blur': 0.4,
    } });

  map.on('sourcedata', function onData(e) {
    if (e.sourceId === 'ed' && e.isSourceLoaded) {
      map.off('sourcedata', onData);
      applyLayers();
      paintAll();
      if (state.sel != null) map.setFeatureState({ source: 'ed', id: state.sel }, { sel: true });
      renderSim();
    }
  });

  map.on('mousemove', 'hit', (e) => {
    const id = e.features[0]?.id;
    if (id !== state.hover) {
      if (state.hover != null) map.setFeatureState({ source: 'ed', id: state.hover }, { hover: false });
      state.hover = id;
      map.setFeatureState({ source: 'ed', id }, { hover: true });
    }
    map.getCanvas().style.cursor = 'pointer';
    showTip(id, e.point);
  });
  map.on('mouseleave', 'hit', () => {
    if (state.hover != null) map.setFeatureState({ source: 'ed', id: state.hover }, { hover: false });
    state.hover = null;
    map.getCanvas().style.cursor = '';
    $('#tip').hidden = true;
  });
  map.on('click', 'hit', (e) => selectDistrict(e.features[0].id, { fly: false }));
});

// ---------------------------------------------------------------------------
// Time & ENSO
// ---------------------------------------------------------------------------
const clampT = (t) => Math.max(0, Math.min(state.n - 1, t));
const tYear = (t) => state.y0 + Math.floor(t / 12);
const tLabel = (t) => `${MONTHS[t % 12]} ${tYear(t)}`;
const isFuture = (t) => state.kinds[t] === 'forecast';
const isExt = (t) => t >= state.nObs; // not in NASA POWER yet (Meteomatics)

// ONI is a 3-month running mean; put each season on its centre month (DJF -> Jan).
// An El Niño / La Niña episode needs the threshold met for at least 5 overlapping seasons in a row.
function buildEnso(rows) {
  const series = rows.map((r) => ({ k: (r.year - state.y0) * 12 + ONI_SEASONS.indexOf(r.season), v: r.anom, fc: !!r.forecast }))
    .sort((a, b) => a.k - b.k);
  const cls = series.map(() => 'neutral');
  for (const [sign, name] of [[1, 'nino'], [-1, 'nina']]) {
    let i = 0;
    while (i < series.length) {
      if (series[i].v * sign >= 0.5) {
        let j = i;
        while (j + 1 < series.length && series[j + 1].v * sign >= 0.5 && series[j + 1].k === series[j].k + 1) j++;
        if (j - i + 1 >= 5) for (let x = i; x <= j; x++) cls[x] = name;
        i = j + 1;
      } else i++;
    }
  }
  state.oni = new Array(state.n).fill(null);
  state.enso = new Array(state.n).fill(null);
  state.oniFc = new Array(state.n).fill(false);
  series.forEach((s, i) => {
    if (s.k >= 0 && s.k < state.n) { state.oni[s.k] = s.v; state.enso[s.k] = cls[i]; state.oniFc[s.k] = s.fc; }
  });
}

function drawOni() {
  const svg = $('#oni-chart');
  const W = 300, H = 70, mid = H / 2;
  const range = Math.max(2.4, ...state.oni.filter((v) => v != null).map(Math.abs));
  const sc = (mid - 3) / range;
  const bw = W / state.n;
  let s = '';
  for (const v of [0.5, -0.5]) s += `<line x1="0" x2="${W}" y1="${mid - v * sc}" y2="${mid - v * sc}" class="thr"/>`;
  state.oni.forEach((v, t) => {
    if (v == null) return;
    const h = v * sc;
    s += `<rect x="${(t * bw).toFixed(2)}" width="${(bw + 0.08).toFixed(2)}" y="${(h >= 0 ? mid - h : mid).toFixed(2)}" ` +
      `height="${Math.max(0.4, Math.abs(h)).toFixed(2)}" fill="${ENSO[state.enso[t]].color}"${state.oniFc[t] ? ' fill-opacity="0.45"' : ''}/>`;
  });
  // forecast zone: from the first forecast ONI season or climate month on
  const f0 = Math.min(...[state.oniFc.indexOf(true), state.kinds.indexOf('forecast')].filter((i) => i >= 0));
  state.fcX = null;
  if (Number.isFinite(f0)) {
    const x0 = f0 * bw;
    s = `<rect x="${x0.toFixed(2)}" width="${(W - x0).toFixed(2)}" y="0" height="${H}" class="fc-zone"/>` + s +
      `<line x1="${x0.toFixed(2)}" x2="${x0.toFixed(2)}" y1="0" y2="${H}" class="fc-line"/>`;
    state.fcX = x0 / W * 100;
  }
  s += `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" class="zero"/><line id="oni-sel" y1="0" y2="${H}" class="sel"/>`;
  svg.innerHTML = s;

  // coloured strip under the chart, one hard-stop segment per run of the same phase
  const stops = [];
  let start = 0;
  for (let t = 1; t <= state.n; t++) {
    if (t === state.n || state.enso[t] !== state.enso[start]) {
      const c = ENSO[state.enso[start] || 'neutral'].color;
      stops.push(`${c} ${(start / state.n * 100).toFixed(3)}%`, `${c} ${(t / state.n * 100).toFixed(3)}%`);
      start = t;
    }
  }
  const veil = state.fcX != null ? `linear-gradient(90deg, transparent ${state.fcX}%, rgba(255,255,255,.5) ${state.fcX}%), ` : '';
  $('#enso-strip').style.background = `${veil}linear-gradient(90deg, ${stops.join(', ')})`;
}

// ---- time controls: steppers, pickers, keyboard, and two "tapes" (10 years and 3 years) that always keep
// the selected month in the middle. Drag a tape like film to scroll through time, click to jump.
const TAPES = [{ id: 'tape-fine', months: 36 }];

function syncTimeControls() {
  $('#pick-month').value = state.t % 12;
  $('#pick-year').value = tYear(state.t);
  TAPES.forEach(drawTape);
}

function drawTape({ id, months }) {
  const svg = $('#' + id);
  if (!svg) return;
  const W = 360, top = 2, H = 32, mid = top + H / 2, bw = W / months, half = Math.floor(months / 2);
  const t0 = state.t - half; // month at the left edge; the selected month sits in the middle slot
  const vals = [];
  for (let i = 0; i < months; i++) { const v = state.oni[t0 + i]; if (v != null) vals.push(Math.abs(v)); }
  const sc = (H / 2 - 1) / Math.max(1.5, ...vals);
  const fcFrom = state.kinds.indexOf('forecast');
  let s = '';
  if (fcFrom >= 0 && fcFrom < t0 + months) {
    const x = Math.max(0, (fcFrom - t0) * bw);
    s += `<rect x="${x.toFixed(1)}" width="${(W - x).toFixed(1)}" y="${top}" height="${H}" class="fc"/>`;
  }
  const every = months > 60 ? 2 : 1; // year labels: every other year on the 10-year tape
  for (let i = 0; i < months; i++) {
    const t = t0 + i;
    if (t < 0 || t >= state.n) continue;
    const x = i * bw;
    if (t % 12 === 0) {
      s += `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${top}" y2="${top + H + 2}" class="yr"/>`;
      if (tYear(t) % every === 0) s += `<text x="${(x + (months > 60 ? 0 : 6 * bw)).toFixed(1)}" y="45" class="lbl">${tYear(t)}</text>`;
    } else if (months <= 36 && t % 3 === 0) {
      s += `<text x="${(x + bw / 2).toFixed(1)}" y="45" class="lbl" style="font-size:7.5px">${MONTHS[t % 12][0]}</text>`;
    }
    const v = state.oni[t];
    if (v == null) continue;
    const h = v * sc;
    const gap = months > 60 ? 0.15 : 0.8;
    s += `<rect x="${(x + gap).toFixed(2)}" width="${Math.max(0.5, bw - 2 * gap).toFixed(2)}" y="${(h >= 0 ? mid - h : mid).toFixed(2)}" ` +
      `height="${Math.max(0.6, Math.abs(h)).toFixed(2)}" fill="${ENSO[state.enso[t]].color}"${state.oniFc[t] ? ' fill-opacity="0.45"' : ''}/>`;
  }
  const cx = half * bw;
  s += `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" class="zero"/>` +
    `<rect x="${(cx - (months > 60 ? 1 : 0)).toFixed(2)}" width="${Math.max(bw, 2).toFixed(2)}" y="${top - 1}" height="${H + 2}" class="cur"/>`;
  svg.innerHTML = s;
}

function hoverLabel(t) {
  const v = state.oni[t];
  return t == null ? '' : `${tLabel(t)}${v == null ? '' : ` · ONI ${signed(v, 2)}`}${isFuture(t) ? ' (forecast)' : ''}`;
}

// a tape: drag = scroll time (grab-the-film: drag right goes back), click = jump, wheel = step
function tapeControl({ id, months }) {
  const el = $('#' + id);
  const half = Math.floor(months / 2);
  const tAt = (e) => { const b = el.getBoundingClientRect(); return state.t - half + Math.floor((e.clientX - b.left) / b.width * months); };
  let drag = null;
  el.addEventListener('pointerdown', (e) => {
    el.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, t: state.t, moved: false, w: el.getBoundingClientRect().width };
    el.classList.add('dragging');
  });
  el.addEventListener('pointermove', (e) => {
    if (!drag) { $('#thover').textContent = hoverLabel(clampT(tAt(e))); return; }
    const dx = e.clientX - drag.x;
    if (Math.abs(dx) > 3) drag.moved = true;
    if (drag.moved) setMonth(drag.t - Math.round(dx / drag.w * months));
  });
  const end = (e) => {
    if (!drag) return;
    if (!drag.moved) setMonth(tAt(e));
    drag = null;
    el.classList.remove('dragging');
  };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', () => { drag = null; el.classList.remove('dragging'); });
  el.addEventListener('pointerleave', () => { if (!drag) $('#thover').textContent = ''; });
  el.addEventListener('wheel', (e) => {
    e.preventDefault();
    const d = Math.sign(e.deltaY || e.deltaX);
    setMonth(state.t + d * (months > 60 ? 12 : 1));
  }, { passive: false });
}

function buildTimeControls() {
  $('#pick-month').innerHTML = MONTHS.map((m, i) => `<option value="${i}">${m}</option>`).join('');
  const y1 = tYear(state.n - 1);
  let yo = '';
  for (let y = state.y0; y <= y1; y++) yo += `<option value="${y}">${y}</option>`;
  $('#pick-year').innerHTML = yo;
  const pick = () => setMonth((Number($('#pick-year').value) - state.y0) * 12 + Number($('#pick-month').value));
  $('#pick-month').addEventListener('change', pick);
  $('#pick-year').addEventListener('change', pick);

  // step buttons; holding one down keeps stepping, faster the longer it is held
  for (const b of document.querySelectorAll('.step[data-step]')) {
    let timer = null;
    const stop = () => { clearTimeout(timer); timer = null; };
    b.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      const d = Number(b.dataset.step);
      setMonth(state.t + d);
      let delay = 350;
      const again = () => { setMonth(state.t + d); delay = Math.max(40, delay * 0.8); timer = setTimeout(again, delay); };
      timer = setTimeout(again, delay);
    });
    for (const ev of ['pointerup', 'pointerleave', 'pointercancel']) b.addEventListener(ev, stop);
    b.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setMonth(state.t + Number(b.dataset.step)); } });
  }
  $('#go-now').addEventListener('click', () => setMonth(state.nowT ?? state.n - 1));
  $('#go-now').hidden = state.nowT == null;

  TAPES.forEach(tapeControl);

  // the big ONI chart: click or drag to scrub absolutely (the whole record)
  const chart = $('#oni-chart');
  const chartT = (e) => { const b = chart.getBoundingClientRect(); return Math.floor((e.clientX - b.left) / b.width * state.n); };
  let down = false;
  chart.addEventListener('pointerdown', (e) => { down = true; chart.setPointerCapture(e.pointerId); setMonth(chartT(e)); });
  chart.addEventListener('pointermove', (e) => {
    $('#thover').textContent = hoverLabel(clampT(chartT(e)));
    if (down) setMonth(chartT(e));
  });
  chart.addEventListener('pointerup', () => { down = false; });
  chart.addEventListener('pointerleave', () => { if (!down) $('#thover').textContent = ''; });

  // keyboard: arrows step a month, Shift + arrows a year (when not typing in a field)
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      setMonth(state.t + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 12 : 1));
    }
  });
}

// map + similarity repaint at most once per frame, so dragging stays smooth
let paintQueued = false;
function schedulePaint() {
  if (paintQueued) return;
  paintQueued = true;
  requestAnimationFrame(() => { paintQueued = false; paintAll(); renderSim(); });
  setTimeout(() => { if (paintQueued) { paintQueued = false; paintAll(); renderSim(); } }, 120); // hidden tab: no rAF
}

function setMonth(t) {
  state.t = clampT(t);
  const slider = $('#month');
  slider.value = state.t;
  syncTimeControls();
  // fixed-size labels so nothing below moves when crossing into the forecast
  $('#month-label').textContent = tLabel(state.t);
  const ph = state.enso[state.t], v = state.oni[state.t], fc = state.oniFc[state.t];
  const badge = $('#enso-badge');
  badge.textContent = ph ? `${ENSO[ph].label} · ONI ${signed(v, 2)}` : 'ONI n/a';
  badge.className = 'badge ' + (ph || '') + (fc ? ' fc' : '');
  badge.title = fc ? 'Forecast ONI' : 'Observed ONI';
  $('#month-src').innerHTML = isFuture(state.t)
    ? '<span class="fc-tag">forecast</span>ECMWF seasonal forecast via Meteomatics'
    : isExt(state.t)
      ? `Recent month · ERA5 via Meteomatics${fc ? ' · ONI forecast' : ''}`
      : `Observed · NASA POWER${fc ? ' · ONI forecast' : ''}`;
  $('#oni-text').innerHTML = `ONI for the ${ONI_SEASONS[state.t % 12]} season centred on ${tLabel(state.t)}. ` +
    'Coloured as an El Niño / La Niña episode when it stays beyond ±0.5 °C for 5+ overlapping seasons; the shaded end is ' +
    'forecast (ECMWF Niño 3.4 sea temperature via Meteomatics). Drag the chart for any year, the 3-year strip for single months, or use the arrow keys.';
  const sel = $('#oni-sel');
  if (sel) {
    const x = (state.t + 0.5) * 300 / state.n;
    sel.setAttribute('x1', x); sel.setAttribute('x2', x);
  }
  const url = new URL(location.href);
  url.searchParams.set('m', `${tYear(state.t)}-${String(state.t % 12 + 1).padStart(2, '0')}`);
  history.replaceState(null, '', url);
  schedulePaint();
}

// ---------------------------------------------------------------------------
// Climate data (Int16 binaries, one per variable, loaded on demand)
// ---------------------------------------------------------------------------
async function loadVar(key) {
  if (!state.bins[key]) {
    state.bins[key] = fetch(withV(`data/climate/${key}.bin`)).then((r) => r.arrayBuffer()).then((b) => new Int16Array(b));
  }
  if (state.bins[key] instanceof Promise) state.bins[key] = await state.bins[key];
  return state.bins[key];
}

function climate(key, row, t) {
  const a = state.bins[key];
  if (!a || a instanceof Promise) return null;
  const v = a[row * state.n + t];
  return v === -32768 ? null : v * state.meta.vars[key].scale;
}

// 1991-2020 mean per ecodistrict and calendar month
function normals(key) {
  if (state.normals[key]) return state.normals[key];
  const nd = state.ids.length, out = new Float32Array(nd * 12).fill(NaN);
  const a0 = Math.max(0, (NORMAL[0] - state.y0) * 12), a1 = Math.min(state.n, (NORMAL[1] - state.y0 + 1) * 12);
  for (let r = 0; r < nd; r++) {
    for (let m = 0; m < 12; m++) {
      let s = 0, c = 0;
      for (let t = a0 + m; t < a1; t += 12) {
        const v = climate(key, r, t);
        if (v != null) { s += v; c++; }
      }
      if (c) out[r * 12 + m] = s / c;
    }
  }
  return (state.normals[key] = out);
}

function climateValue(key, row, t, mode = state.climateMode) {
  const v = climate(key, row, t);
  if (v == null || mode === 'value') return v;
  const n = normals(key)[row * 12 + (t % 12)];
  return Number.isNaN(n) ? null : v - n;
}

function quantile(vals, q) {
  const s = Float64Array.from(vals).sort();
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

// colour range per variable, mode and calendar month: the same for every year, so years compare directly,
// but July is not washed out by January's range
function climateDomain(key, mode, m) {
  const id = `${key}.${mode}.${m}`;
  if (state.domains[id]) return state.domains[id];
  const vals = [];
  for (let r = 0; r < state.ids.length; r++) {
    for (let t = m; t < state.n; t += 12) {
      const v = climateValue(key, r, t, mode);
      if (v != null) vals.push(v);
    }
  }
  let dom;
  if (mode === 'anom') {
    const m = quantile(vals.map(Math.abs), 0.97) || 1e-6;
    dom = [-m, m];
  } else {
    dom = [quantile(vals, 0.02), quantile(vals, 0.98)];
  }
  return (state.domains[id] = dom);
}

function rampFor(key, mode) {
  const kind = VAR_KIND[key];
  if (mode === 'anom') return kind === 'temp' || kind === 'sun' ? RAMPS.anomTemp : RAMPS.anomWet;
  return RAMPS[kind];
}

function rampExpr(prop, colors, [lo, hi]) {
  const stops = colors.flatMap((c, i) => [lo + (hi - lo) * i / (colors.length - 1), c]);
  return ['case', ['==', ['typeof', ['feature-state', prop]], 'number'],
    ['interpolate', ['linear'], ['feature-state', prop], ...stops], 'rgba(0,0,0,0)'];
}

function rampHtml(colors, [lo, hi], units, nd) {
  const pre = (v) => (state.climateMode === 'anom' && v > 0 ? '+' : '');
  return `<span>${pre(lo)}${fmt(lo, nd)}</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i>` +
    `<span>${pre(hi)}${fmt(hi, nd)} ${esc(units)}</span>`;
}

const varDigits = (key) => (state.meta.vars[key].scale < 0.01 ? 2 : state.meta.vars[key].scale < 0.1 ? 1 : 0);

// ---------------------------------------------------------------------------
// Painting
// ---------------------------------------------------------------------------
// Feature state can be set as soon as the source exists (MapLibre keeps it for tiles still loading).
// Don't also require isSourceLoaded: it is briefly false during flyTo/zoom, and skipping updates then
// left stale match highlights and unpainted months behind.
const mapReady = () => !!map.getSource('ed');

function paintAll() {
  paintClimate();
  paintCrops();
  paintYield();
  paintSeeded();
  paintFinance();
  paintIrrigation();
}

function paintClimate() {
  const key = state.climateVar, mode = state.climateMode;
  if (!(state.bins[key] instanceof Int16Array)) return;
  const dom = climateDomain(key, mode, state.t % 12);
  const colors = rampFor(key, mode);
  const v = state.meta.vars[key];
  $('#climate-ramp').innerHTML = rampHtml(colors, dom, mode === 'anom' ? `${v.units} vs normal` : v.units, Math.max(0, varDigits(key) - (mode === 'anom' ? 0 : 1)));
  const note = $('#climate-note');
  $('#climate-info')?.classList.toggle('warn', isExt(state.t) && !v.forecast);
  if (isExt(state.t)) {
    note.innerHTML = !v.forecast
      ? `<b>No forecast for this variable.</b> NASA POWER has it up to ${tLabel(state.nObs - 1)}.`
      : isFuture(state.t)
        ? '<b>Forecast:</b> ECMWF seasonal forecast via Meteomatics, bias-corrected to NASA POWER for each ecodistrict.'
        : '<b>Recent month</b> not yet in NASA POWER: Meteomatics analysis, bias-corrected to NASA POWER.';
  } else note.innerHTML = '<b>Observed:</b> NASA POWER monthly data, averaged over each ecodistrict.';
  if (!mapReady()) return;
  map.setPaintProperty('climate-fill', 'fill-color', rampExpr('v', colors, dom));
  state.ids.forEach((id, r) => map.setFeatureState({ source: 'ed', id }, { v: climateValue(key, r, state.t) }));
}

function paintSoil() {
  const key = state.soilVar;
  const box = $('#soil-ramp');
  const recs = Object.entries(state.eco.d);
  if (key === 'order') {
    const used = new Set(recs.map(([, r]) => r.soil?.order).filter(Boolean));
    box.innerHTML = `<div class="cats">${[...used].sort().map((o) =>
      `<span><i class="sw" style="background:${SOIL_ORDER_COLORS[o]}"></i>${esc(state.eco.soil_orders[o])}</span>`).join('')}</div>`;
    if (!mapReady()) return;
    map.setPaintProperty('soil-fill', 'fill-color', ['match', ['coalesce', ['feature-state', 's'], ''],
      ...Object.entries(SOIL_ORDER_COLORS).flat(), 'rgba(0,0,0,0)']);
    for (const [id, r] of recs) map.setFeatureState({ source: 'ed', id: Number(id) }, { s: r.soil?.order ?? null });
    return;
  }
  const vals = recs.map(([, r]) => r.soil?.[key]).filter((v) => v != null);
  const dom = [quantile(vals, 0.02), quantile(vals, 0.98)];
  const colors = RAMPS[SOIL_KIND[key]];
  const units = { awhc: 'mm', sand: '%', silt: '%', clay: '%', oc: '%', ph: '', drainage: '' }[key];
  box.innerHTML = `<span>${fmt(dom[0], key === 'oc' ? 1 : 0)}</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i>` +
    `<span>${fmt(dom[1], key === 'oc' ? 1 : 0)} ${units}</span>`;
  if (!mapReady()) return;
  map.setPaintProperty('soil-fill', 'fill-color', rampExpr('s', colors, dom));
  for (const [id, r] of recs) map.setFeatureState({ source: 'ed', id: Number(id) }, { s: r.soil?.[key] ?? null });
}

// crop year that goes with the slider month (nearest year with inventory data)
function cropYear() {
  const ys = state.eco.crop_years;
  const y = tYear(state.t);
  return ys.length ? Math.max(ys[0], Math.min(ys[ys.length - 1], y)) : null;
}

function cropRec(id, year = cropYear()) {
  const c = state.eco.d[id]?.crops?.[year];
  if (!c) return null;
  const f = state.eco.crop_fields;
  const groups = f.slice(3).map((g, i) => [g, c[3 + i]]).sort((a, b) => b[1] - a[1]);
  return { crop: c[0], pasture: c[1], top: c[2], groups };
}

function paintCrops() {
  const y = cropYear();
  const ys = state.eco.crop_years;
  const exact = y === tYear(state.t);
  $('#crops-text').innerHTML = y == null ? 'No crop data yet (run scripts/fetch_crops.py).'
    : `Bubbles: share of land in crops for <b>${y}</b>${exact ? '' : ` (nearest year to ${tYear(state.t)}; inventory covers ${ys[0]}–${ys[ys.length - 1]})`}, ` +
      'coloured by the largest crop group.' + (y <= 2010 ? ' Before 2011 the inventory only covers the Prairies.' : '');
  if (!mapReady() || !map.getSource('crop-pts')) return;
  for (const [id, r] of Object.entries(state.eco.d)) {
    if (!r.crops) continue;
    const c = cropRec(id, y);
    map.setFeatureState({ source: 'crop-pts', id: Number(id) }, { crop: c ? c.crop : null, grp: c && c.crop > 0 ? c.groups[0][0] : null });
  }
}

// ---------------------------------------------------------------------------
// Crop yield (per ecodistrict and year; compared with each district's own average)
// ---------------------------------------------------------------------------
// year with yield data that goes with the slider month (clamped to the record)
function yieldYear() {
  const y = state.yield;
  return y ? Math.max(y.y0, Math.min(y.y1, tYear(state.t))) : null;
}

// crop series for one ecodistrict, or null
function yieldSeries(id, code = state.yieldCrop) {
  const rows = state.yield?.d[id];
  const i = state.yieldIdx[code];
  return rows && i != null ? rows[i] : null;
}

// each ecodistrict's long-term mean yield for a crop (the "average" we compare years against)
function yieldMean(id, code) {
  const key = `${id}.${code}`;
  if (key in state.yieldMeans) return state.yieldMeans[key];
  const s = yieldSeries(id, code);
  let sum = 0, c = 0;
  if (s) for (const v of s) if (v != null) { sum += v; c++; }
  return (state.yieldMeans[key] = c ? sum / c : null);
}

// value for a year: raw kg/ha, or the % above/below that district's average
function yieldValue(id, year, code = state.yieldCrop, mode = state.yieldMode) {
  const s = yieldSeries(id, code);
  if (!s) return null;
  const v = s[year - state.yield.y0];
  if (v == null || mode === 'value') return v;
  const m = yieldMean(id, code);
  return m ? (v - m) / m * 100 : null;
}

// colour range for the picked crop + mode, over every ecodistrict and year, cached
function yieldDomain(code, mode) {
  const key = `${code}.${mode}`;
  if (state.yieldDomains[key]) return state.yieldDomains[key];
  const vals = [];
  for (const id of Object.keys(state.yield.d)) {
    for (let year = state.yield.y0; year <= state.yield.y1; year++) {
      const v = yieldValue(id, year, code, mode);
      if (v != null) vals.push(v);
    }
  }
  let dom = [0, 1];
  if (vals.length) {
    dom = mode === 'anom'
      ? (() => { const m = Math.max(1, quantile(vals.map(Math.abs), 0.97)); return [-m, m]; })()
      : [quantile(vals, 0.02), quantile(vals, 0.98)];
  }
  return (state.yieldDomains[key] = dom);
}

// Bivariate "did the effort pay off" palette. index = resultClass*3 + effortClass.
//   effort (how much was seeded in the region): 0 little, 1 some, 2 lots  -> left to right
//   result (yield vs the ecodistrict's own average): 0 below, 1 near, 2 above -> bottom to top
// So the bottom-right (planted lots, yielded poorly) is the loud red; top-right (lots + good)
// is the strong green; the left column (barely planted) stays pale.
const BIV = [
  '#e3cac9', '#d98c86', '#c0202a', // below average: little -> lots seeded
  '#e2e2e2', '#bdbdbd', '#8a8a8a', // near average
  '#cfe6cf', '#86c08a', '#1a9641', // above average
];
const bivEffortCuts = {};

// terciles of seeded hectares for a crop, pooled over every region and year
function effortCuts(code) {
  if (bivEffortCuts[code]) return bivEffortCuts[code];
  const i = state.seeded ? state.seededIdx[code] : null;
  const vals = [];
  if (i != null) for (const rows of Object.values(state.seeded.cars)) for (const v of rows[i]) if (v != null && v > 0) vals.push(v);
  return (bivEffortCuts[code] = vals.length ? [quantile(vals, 0.34), quantile(vals, 0.67)] : null);
}

// bivariate class 0..8, or null where the crop isn't grown / has no seeded data
function bivClass(id, year, code) {
  const cuts = effortCuts(code);
  if (!cuts) return null;
  const sv = seededValue(id, year, code);
  if (sv == null || sv <= 0) return null;
  const e = sv < cuts[0] ? 0 : sv < cuts[1] ? 1 : 2;
  const pct = yieldValue(id, year, code, 'anom');
  const r = pct == null ? 1 : pct < -5 ? 0 : pct > 5 ? 2 : 1;
  return r * 3 + e;
}

function bivLegendHtml() {
  let cells = '';
  for (const r of [2, 1, 0]) for (const e of [0, 1, 2]) {
    cells += `<i style="display:block;width:13px;height:13px;background:${BIV[r * 3 + e]}"></i>`;
  }
  return `<div style="display:flex;align-items:center;gap:7px;font-size:11px;line-height:1.3">` +
    `<div style="display:grid;grid-template-columns:repeat(3,13px);grid-auto-rows:13px;gap:1px">${cells}</div>` +
    `<div><div>▲ yield above average</div><div>▶ more seeded</div>` +
    `<div><b style="color:#c0202a">red</b> tried hard, poor · <b style="color:#1a9641">green</b> tried hard, good</div></div></div>`;
}

const YIELD_FADE = ['interpolate', ['linear'], ['coalesce', ['feature-state', 'yg'], 1], 0, 0.12, 0.05, 0.78];

function paintYield() {
  if (!state.yield) { $('#yield-text').textContent = 'No yield data yet (run scripts/build_yield.py).'; return; }
  const code = state.yieldCrop, mode = state.yieldMode;
  const label = state.yield.crops[state.yieldIdx[code]][1];
  const year = yieldYear();
  const exact = year === tYear(state.t);
  const seededHere = state.seeded && (code in state.seededIdx);
  const nearStr = `${year}${exact ? '' : ` (nearest year to ${tYear(state.t)}; record is ${state.yield.y0}–${state.yield.y1})`}`;

  if (mode === 'biv') {
    $('#yield-ramp').innerHTML = bivLegendHtml();
    $('#yield-text').innerHTML = `<b>${esc(label)}</b>, ${nearStr}: colour crosses <b>how much was seeded</b> in the ` +
      'region (pale → saturated) with <b>yield vs the ecodistrict’s own average</b> (red below, green above). ' +
      'Red = they planted a lot but it yielded poorly; green = planted a lot and did well; pale = barely grown.' +
      (seededHere ? '' : ' No seeded-area data for this crop, so this view is blank.');
  } else {
    const dom = yieldDomain(code, mode);
    const colors = mode === 'anom' ? RAMPS.anomWet : RAMPS.awhc;
    $('#yield-ramp').innerHTML = mode === 'anom'
      ? `<span>${signed(dom[0], 0)}%</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>${signed(dom[1], 0)}% vs avg</span>`
      : `<span>${fmt(dom[0], 0)}</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>${fmt(dom[1], 0)} kg/ha</span>`;
    $('#yield-text').innerHTML = `<b>${esc(label)}</b> yield for <b>${nearStr}</b>, ` +
      (mode === 'anom'
        ? 'shown as % above (teal) or below (brown) each ecodistrict’s own long-term average.'
        : 'averaged across the Soil Landscape polygons in each ecodistrict.') +
      (seededHere ? ' Regions where the crop is <b>barely seeded</b> are faded out — the yield there is modelled, not meaningful.' : '');
  }

  if (!mapReady() || !map.getLayer('yield-fill') || !$('#lyr-yield').checked) return;
  if (mode === 'biv') {
    map.setPaintProperty('yield-fill', 'fill-opacity', 0.82);
    map.setPaintProperty('yield-fill', 'fill-color',
      ['match', ['coalesce', ['feature-state', 'yb'], -1], ...BIV.flatMap((c, i) => [i, c]), 'rgba(0,0,0,0)']);
    for (const id of state.ids) map.setFeatureState({ source: 'ed', id }, { yb: bivClass(id, year, code) });
  } else {
    const dom = yieldDomain(code, mode);
    const colors = mode === 'anom' ? RAMPS.anomWet : RAMPS.awhc;
    map.setPaintProperty('yield-fill', 'fill-opacity', YIELD_FADE);
    map.setPaintProperty('yield-fill', 'fill-color', rampExpr('y', colors, dom));
    for (const id of state.ids) {
      map.setFeatureState({ source: 'ed', id }, { y: yieldValue(id, year), yg: grownFrac(id, year, code) });
    }
  }
}

// ---------------------------------------------------------------------------
// Seeded area (how much of a crop was actually planted; region-level context for yield)
// StatCan publishes it by Small Area Data Region / Census Agricultural Region, so every
// ecodistrict takes its region's figure (data/seeded.json maps ecodistrict -> region).
// ---------------------------------------------------------------------------
function seededYear() {
  const s = state.seeded;
  return s ? Math.max(s.y0, Math.min(s.y1, tYear(state.t))) : null;
}

// seeded-area series (ha per year) for an ecodistrict's region and a crop, or null
function seededSeries(id, code) {
  const s = state.seeded;
  if (!s) return null;
  const car = s.eco2car[id];
  const i = state.seededIdx[code];
  const rows = car == null ? null : s.cars[car];
  return rows && i != null ? rows[i] : null;
}

function seededValue(id, year, code = state.seededCrop) {
  const ser = seededSeries(id, code);
  return ser ? (ser[year - state.seeded.y0] ?? null) : null;
}

// the region's own peak planting of this crop, as a yardstick for "barely grown"
function seededPeak(id, code) {
  const car = state.seeded?.eco2car[id];
  if (car == null) return null;
  const key = `${car}.${code}`;
  if (key in state.seededMaxCache) return state.seededMaxCache[key];
  const ser = seededSeries(id, code);
  let mx = 0;
  if (ser) for (const v of ser) if (v != null && v > mx) mx = v;
  return (state.seededMaxCache[key] = mx || null);
}

// how much of the crop was planted this year, as a share of the region's own peak:
//   null  -> the ecodistrict has no seeded-area region (unknown; don't fade the yield)
//   0     -> region is covered but the crop is never/barely grown there (fade the yield)
//   0..1  -> this year's planting relative to the region's busiest year
function grownFrac(id, year, code) {
  if (!state.seeded || !(code in state.seededIdx)) return null;  // no seeded data for this crop
  const car = state.seeded.eco2car[id];
  if (car == null) return null;              // outside the seeded-area coverage
  const mx = seededPeak(id, code);
  if (!mx) return 0;                         // region grows essentially none of this crop
  return (seededValue(id, year, code) || 0) / mx;
}

// colour range (hectares) for a crop over every region and year, cached
function seededDomain(code) {
  if (state.seededDomains[code]) return state.seededDomains[code];
  const i = state.seededIdx[code];
  const vals = [];
  for (const rows of Object.values(state.seeded.cars)) {
    for (const v of rows[i]) if (v != null) vals.push(v);
  }
  let dom = [0, 1];
  if (vals.length) dom = [0, Math.max(1, quantile(vals, 0.98))];
  return (state.seededDomains[code] = dom);
}

const areaFmt = (v) => (v == null ? '–' : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M ha`
  : v >= 1e3 ? `${Math.round(v / 1e3)}k ha` : `${Math.round(v)} ha`);

function paintSeeded() {
  if (!state.seeded) { $('#seeded-text').textContent = 'No seeded-area data yet (run scripts/build_seeded.py).'; return; }
  const code = state.seededCrop;
  const label = state.seeded.crops[state.seededIdx[code]][1];
  const year = seededYear();
  const exact = year === tYear(state.t);
  const dom = seededDomain(code);
  const colors = RAMPS.awhc;
  $('#seeded-ramp').innerHTML = `<span>0</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i>` +
    `<span>${areaFmt(dom[1])}</span>`;
  $('#seeded-text').innerHTML = `<b>${esc(label)}</b> seeded area in <b>${year}</b>` +
    `${exact ? '' : ` (nearest year to ${tYear(state.t)}; record is ${state.seeded.y0}–${state.seeded.y1})`}, ` +
    'by Census Agricultural Region (Prairies, BC, Ontario, Quebec). Every ecodistrict shares its region’s total.';
  if (!mapReady() || !map.getLayer('seeded-fill') || !$('#lyr-seeded').checked) return;
  map.setPaintProperty('seeded-fill', 'fill-color', rampExpr('sd', colors, dom));
  for (const id of state.ids) map.setFeatureState({ source: 'ed', id }, { sd: seededValue(id, year) });
}

// ---------------------------------------------------------------------------
// Farm support payments (province-level, annual; a proxy for weather losses)
// ---------------------------------------------------------------------------
const moneyFmt = (v) => {
  if (v == null || Number.isNaN(v)) return '–';
  const a = Math.abs(v), s = v < 0 ? '−' : '';
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${s}$${Math.round(a / 1e6)}M`;
  if (a >= 1e3) return `${s}$${Math.round(a / 1e3)}k`;
  return `${s}$${Math.round(a)}`;
};

// sample a hex colour ramp at t in [0,1]
function lerpHex(a, b, f) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const ch = (sh) => Math.round(((pa >> sh) & 255) + (((pb >> sh) & 255) - ((pa >> sh) & 255)) * f);
  return `#${((1 << 24) | (ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).slice(1)}`;
}
function rampColor(colors, t) {
  t = Math.max(0, Math.min(1, t));
  const x = t * (colors.length - 1), i = Math.floor(x);
  return i >= colors.length - 1 ? colors[colors.length - 1] : lerpHex(colors[i], colors[i + 1], x - i);
}

// annual year with payment data that goes with the slider month (clamped to record)
function financeYear() {
  const f = state.finance;
  return f ? Math.max(f.y0, Math.min(f.y1, tYear(state.t))) : null;
}

// payment for an ecodistrict = its province's total for that year, or null
function financeValue(id, year, metric = state.financeMetric) {
  const f = state.finance;
  const prov = state.eco.d[id]?.prov;
  if (!f || !prov) return null;
  const arr = f.metrics[metric]?.data[prov];
  return arr ? (arr[year - f.y0] ?? null) : null;
}

// each province's own average over the record - the baseline the shading compares to
function financeMean(metric) {
  if (state.financeMeans[metric]) return state.financeMeans[metric];
  const out = {};
  for (const [prov, arr] of Object.entries(state.finance.metrics[metric].data)) {
    let s = 0, c = 0;
    for (const v of arr) if (v != null) { s += v; c++; }
    out[prov] = c ? s / c : null;
  }
  return (state.financeMeans[metric] = out);
}

// one label anchor per province: area-weighted centre of its ecodistrict label points
function provincePoints() {
  if (state.provPts) return state.provPts;
  const acc = {};
  for (const r of Object.values(state.eco.d)) {
    if (!r.prov || !r.lp) continue;
    const w = r.area || 1;
    (acc[r.prov] ||= { x: 0, y: 0, w: 0 });
    acc[r.prov].x += r.lp[0] * w; acc[r.prov].y += r.lp[1] * w; acc[r.prov].w += w;
  }
  const out = {};
  for (const [p, a] of Object.entries(acc)) out[p] = [a.x / a.w, a.y / a.w];
  return (state.provPts = out);
}

function paintFinance() {
  if (!state.finance) { $('#finance-text').textContent = 'No financial data yet (run scripts/build_financials.py).'; return; }
  const metric = state.financeMetric, m = state.finance.metrics[metric];
  const year = financeYear();
  const exact = year === tYear(state.t);
  const colors = RAMPS.money;
  $('#finance-ramp').innerHTML = `<span>below avg</span>` +
    `<i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>above avg</span>`;
  $('#finance-text').innerHTML = `<b>${esc(m.label)}</b> paid to farmers, by province, in <b>${year}</b>` +
    `${exact ? '' : ` (nearest year to ${tYear(state.t)}; record is ${state.finance.y0}–${state.finance.y1})`}. ` +
    `${esc(m.desc)} Darker = more than that province's own ${state.finance.y0}–${state.finance.y1} average; drag the timeline to watch spikes.`;
  if (!mapReady() || !map.getSource('finance-pts')) return;
  const pts = provincePoints(), means = financeMean(metric);
  const features = Object.entries(pts).map(([prov, lp]) => {
    const val = state.finance.metrics[metric].data[prov]?.[year - state.finance.y0];
    if (val == null) return null;
    const mean = means[prov];
    const ratio = mean && mean > 0 ? val / mean : 1;
    const color = rampColor(colors, (ratio - 0.4) / 1.6); // 0.4x avg -> light, 2.0x -> darkest
    return { type: 'Feature', properties: { label: moneyFmt(val), color }, geometry: { type: 'Point', coordinates: lp } };
  }).filter(Boolean);
  map.getSource('finance-pts').setData({ type: 'FeatureCollection', features });
}

// ---------------------------------------------------------------------------
// Irrigation water use (province-level, by growing-season period; census years)
// Provincial volumes colour the map; the Canada-wide crop breakdown rides along.
// ---------------------------------------------------------------------------
const volFmt = (v) => {
  if (v == null || Number.isNaN(v)) return '–';
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)} bn m³`;
  if (a >= 1e6) return `${Math.round(v / 1e6)}M m³`;
  if (a >= 1e3) return `${Math.round(v / 1e3)}k m³`;
  return `${Math.round(v)} m³`;
};
const irrDomainCache = {};

// which season the layer shows: the picker, or (on 'auto') the one the slider month falls in
function irrigationPeriodKey() {
  if (state.irrigationPeriod !== 'auto') return state.irrigationPeriod;
  return IRR_MONTH_PERIOD[state.t % 12] || 'total';
}

// nearest surveyed (even) year to the slider's year
function irrigationYear() {
  const ys = state.irrigation.years;
  const y = tYear(state.t);
  return ys.reduce((best, yy) => (Math.abs(yy - y) < Math.abs(best - y) ? yy : best), ys[0]);
}

const irrMeanCache = {};
// the area's series (m³ per survey year) for a geography + season
function irrigationSeries(geo, period, key) {
  return state.irrigation[geo === 'basin' ? 'basin' : 'prov'][period]?.[key] || null;
}
// the area's own average over the surveyed years - the baseline 'anom' compares to
function irrigationMean(geo, period, key) {
  const ck = `${geo}.${period}.${key}`;
  if (ck in irrMeanCache) return irrMeanCache[ck];
  const arr = irrigationSeries(geo, period, key);
  let s = 0, c = 0;
  if (arr) for (const v of arr) if (v != null) { s += v; c++; }
  return (irrMeanCache[ck] = c ? s / c : null);
}
// value for a year: raw m³, or the % above/below that area's own average
function irrigationValue(geo, period, key, yi, mode = state.irrigationMode) {
  const arr = irrigationSeries(geo, period, key);
  const v = arr ? (arr[yi] ?? null) : null;
  if (v == null || mode === 'value') return v;
  const m = irrigationMean(geo, period, key);
  return m ? (v - m) / m * 100 : null;
}

// colour ceiling (98th pct) over every area and year for a season + geography, cached.
// value mode: [0, hi] m³; anom mode: a symmetric ±hi %.
function irrigationDomain(period, geo, mode = state.irrigationMode) {
  const ck = `${mode}.${geo}.${period}`;
  if (irrDomainCache[ck]) return irrDomainCache[ck];
  const series = state.irrigation[geo === 'basin' ? 'basin' : 'prov'][period] || {};
  const vals = [];
  for (const key of Object.keys(series)) {
    for (let yi = 0; yi < state.irrigation.years.length; yi++) {
      const v = irrigationValue(geo, period, key, yi, mode);
      if (v != null) vals.push(v);
    }
  }
  const hi = mode === 'anom'
    ? (vals.length ? Math.max(5, quantile(vals.map(Math.abs), 0.97)) : 50)
    : (vals.length ? Math.max(1, quantile(vals, 0.98)) : 1);
  return (irrDomainCache[ck] = hi);
}

// --- drainage-basin geometry helpers (label anchors + which basin an ecodistrict sits in) ---
function ringCentroid(ring) {
  let x = 0, y = 0, a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    a += f; x += (ring[j][0] + ring[i][0]) * f; y += (ring[j][1] + ring[i][1]) * f;
  }
  if (Math.abs(a) < 1e-12) {
    let sx = 0, sy = 0; for (const p of ring) { sx += p[0]; sy += p[1]; }
    return [sx / ring.length, sy / ring.length];
  }
  return [x / (3 * a), y / (3 * a)];
}
// label point per basin: centroid of its largest ring
function basinPoints() {
  if (state.basinPts) return state.basinPts;
  const out = {};
  for (const f of state.drainageGeo?.features || []) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    let best = null, bestA = -1;
    for (const poly of polys) {
      let a = 0, r = poly[0];
      for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += r[j][0] * r[i][1] - r[i][0] * r[j][1];
      if (Math.abs(a) > bestA) { bestA = Math.abs(a); best = r; }
    }
    if (best) out[f.id] = ringCentroid(best);
  }
  return (state.basinPts = out);
}
function pointInRing(pt, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
}
// which drainage basin a lon/lat falls in (outer ring hit, not in a hole), or null
function basinOf(id) {
  if (id in state.eco2basin) return state.eco2basin[id];
  const lp = state.eco.d[id]?.lp;
  let key = null;
  if (lp) for (const f of state.drainageGeo?.features || []) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) {
      if (pointInRing(lp, poly[0]) && !poly.slice(1).some((h) => pointInRing(lp, h))) { key = f.id; break; }
    }
    if (key) break;
  }
  return (state.eco2basin[id] = key);
}

// Alberta dwarfs every other province, so spread the colour on a sqrt scale
function irrRampExpr(prop, colors, hi) {
  const n = colors.length;
  const stops = colors.flatMap((c, i) => [Math.pow(i / (n - 1), 2) * hi, c]);
  return ['case', ['==', ['typeof', ['feature-state', prop]], 'number'],
    ['interpolate', ['linear'], ['feature-state', prop], ...stops], 'rgba(0,0,0,0)'];
}

// Canada-wide split of the season's water by crop type, as a stacked bar + legend
function irrigationCropBar(period, year) {
  const irr = state.irrigation;
  const yi = irr.years.indexOf(year);
  const parts = irr.cropTypes.map((c) => [c, irr.crops[period]?.[c]?.[yi]]).filter(([, v]) => v != null && v > 0);
  const total = parts.reduce((s, [, v]) => s + v, 0);
  if (!total) return '<p class="small muted">No Canada-wide crop breakdown for this season and year.</p>';
  const bar = parts.map(([c, v]) =>
    `<i style="width:${(v / total * 100).toFixed(2)}%;background:${IRR_CROP_COLORS[c] || '#999'}" title="${esc(c)}: ${volFmt(v)}"></i>`).join('');
  const legend = [...parts].sort((a, b) => b[1] - a[1]).map(([c, v]) =>
    `<span><i class="sw" style="background:${IRR_CROP_COLORS[c] || '#999'}"></i>${esc(c)} ${(v / total * 100).toFixed(0)}%</span>`).join('');
  return `<div class="muted small">Canada-wide, by crop (${volFmt(total)} total):</div>` +
    `<div class="irr-bar">${bar}</div><div class="cats">${legend}</div>`;
}

function paintIrrigation() {
  if (!state.irrigation) { $('#irrigation-text').textContent = 'No irrigation data yet (run scripts/build_irrigation.py).'; return; }
  const irr = state.irrigation;
  const basin = state.irrigationGeo === 'basin' && state.drainageGeo;
  const geo = basin ? 'basin' : 'prov';
  const mode = state.irrigationMode;
  const period = irrigationPeriodKey();
  const year = irrigationYear();
  const yi = irr.years.indexOf(year);
  const exact = year === tYear(state.t);
  const plabel = irr.periods[period];
  const hi = irrigationDomain(period, geo, mode);
  // value: sequential blue ramp [0,hi], sqrt-scaled; anom: diverging ramp ±hi %, linear
  const colors = mode === 'anom' ? RAMPS.anomWet : RAMPS.wet;
  const label = (key) => { const v = irrigationValue(geo, period, key, yi, mode); return v == null ? null : mode === 'anom' ? `${signed(v, 0)}%` : volFmt(v); };
  $('#irrigation-ramp').innerHTML = mode === 'anom'
    ? `<span>${signed(-hi, 0)}%</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>${signed(hi, 0)}% vs avg</span>`
    : `<span>0</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>${volFmt(hi)}</span>`;
  $('#irrigation-crops').innerHTML = irrigationCropBar(period, year);
  $('#irrigation-text').innerHTML = `Irrigation water applied, <b>${esc(plabel)}</b>${period === 'total' ? '' : ' of the growing season'}, in <b>${year}</b>` +
    `${exact ? '' : ` (nearest survey year to ${tYear(state.t)}; surveyed ${irr.years[0]}–${irr.years[irr.years.length - 1]}, every 2nd year)`}. ` +
    (mode === 'anom'
      ? `Shown as % above (teal) or below (brown) each ${basin ? 'basin' : 'province'}’s own ${irr.years[0]}–${irr.years[irr.years.length - 1]} average for this season. `
      : (state.irrigationPeriod === 'auto'
        ? `The season tracks the timeline — ${MONTHS[state.t % 12]} shows ${period === 'total' ? 'the full-season total (outside the irrigation season)' : esc(plabel)}. ` : '')) +
    (basin
      ? 'By <b>drainage basin</b> (watershed) — a finer, sub-provincial cut that isolates e.g. the South Saskatchewan. Surveyed basins cover the farmed south only.'
      : 'Each ecodistrict shares its province’s total.');
  if (!mapReady() || !$('#lyr-irrigation').checked) return;
  const rampExprFor = mode === 'anom' ? rampExpr('irr', colors, [-hi, hi]) : irrRampExpr('irr', colors, hi);
  if (basin) {
    if (map.getLayer('drainage-fill')) map.setPaintProperty('drainage-fill', 'fill-color', rampExprFor);
    for (const k of Object.keys(irr.basins)) map.setFeatureState({ source: 'drainage', id: k }, { irr: irrigationValue(geo, period, k, yi, mode) });
  } else if (map.getLayer('irrigation-fill')) {
    map.setPaintProperty('irrigation-fill', 'fill-color', rampExprFor);
    for (const id of state.ids) {
      const prov = state.eco.d[id]?.prov;
      map.setFeatureState({ source: 'ed', id }, { irr: prov ? irrigationValue(geo, period, prov, yi, mode) : null });
    }
  }
  if (map.getSource('irrigation-pts')) {
    const anchors = basin ? basinPoints() : provincePoints();
    const features = Object.entries(anchors).map(([k, lp]) => {
      const txt = lp ? label(k) : null;
      if (txt == null) return null;
      return { type: 'Feature', properties: { label: txt }, geometry: { type: 'Point', coordinates: lp } };
    }).filter(Boolean);
    map.getSource('irrigation-pts').setData({ type: 'FeatureCollection', features });
  }
}

function syncLegends() {
  for (const el of document.querySelectorAll('.legend[data-for]')) el.hidden = !$('#' + el.dataset.for).checked;
}

function applyLayers() {
  syncLegends();
  if ($('#lyr-yield').checked) paintYield(); // legend + text even before the map is ready
  if (!map.getLayer('climate-fill')) return;
  const vis = (id, on) => map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
  vis('climate-fill', $('#lyr-climate').checked);
  vis('soil-fill', $('#lyr-soil').checked);
  vis('yield-fill', $('#lyr-yield').checked);
  vis('seeded-fill', $('#lyr-seeded').checked);
  vis('finance-labels', $('#lyr-finance').checked);
  const irrOn = $('#lyr-irrigation').checked, basin = state.irrigationGeo === 'basin' && state.drainageGeo;
  vis('irrigation-fill', irrOn && !basin);
  vis('irrigation-labels', irrOn);
  if (map.getLayer('drainage-fill')) { vis('drainage-fill', irrOn && !!basin); vis('drainage-line', irrOn && !!basin); }
  vis('crops', $('#lyr-crops').checked);
  vis('lines', $('#lyr-lines').checked);
  if ($('#lyr-soil').checked) paintSoil();
  if ($('#lyr-yield').checked) paintYield();
  if ($('#lyr-seeded').checked) paintSeeded();
  if ($('#lyr-finance').checked) paintFinance();
  if ($('#lyr-irrigation').checked) paintIrrigation();
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------
function districtName(id) {
  const r = state.eco.d[id];
  return r ? `${r.region_name || 'Ecoregion ' + r.region}${r.prov ? ', ' + r.prov : ''}` : '';
}

function showTip(id, pt) {
  const r = state.eco.d[id];
  if (!r) return;
  const row = state.rowOf[id];
  let h = `<b>Ecodistrict ${id}</b><div class="muted">${esc(districtName(id))}</div>`;
  if ($('#lyr-climate').checked) {
    const k = state.climateVar, v = state.meta.vars[k];
    const val = climateValue(k, row, state.t);
    h += `<div>${esc(v.label)}: <b>${state.climateMode === 'anom' ? signed(val, varDigits(k)) : fmt(val, varDigits(k))}</b> ${esc(v.units)}` +
      `${state.climateMode === 'anom' ? ' vs normal' : ''}</div>`;
  }
  if ($('#lyr-soil').checked && r.soil) {
    const k = state.soilVar;
    const val = k === 'order' ? state.eco.soil_orders[r.soil.order] : r.soil[k];
    h += `<div>${esc(state.eco.soil_fields[k])}: <b>${esc(val ?? '–')}</b></div>`;
  }
  if ($('#lyr-crops').checked) {
    const c = cropRec(id);
    if (c) {
      h += `<div>Cropland ${fmt(c.crop, 0)}% of land, pasture ${fmt(c.pasture, 0)}%</div>`;
      if (c.crop > 0) h += `<div>Top crop: <b>${esc(state.classes[c.top]?.[0] ?? '–')}</b> · ${esc(CROP_GROUPS[c.groups[0][0]][0])} ${fmt(c.groups[0][1], 0)}% of crops</div>`;
    }
  }
  if ($('#lyr-yield').checked && state.yield) {
    const year = yieldYear(), code = state.yieldCrop;
    const label = state.yield.crops[state.yieldIdx[code]][1];
    const raw = yieldValue(id, year, code, 'value');
    if (raw != null) {
      const pct = yieldValue(id, year, code, 'anom');
      h += `<div>${esc(label)} yield ${year}: <b>${fmt(raw, 0)}</b> kg/ha` +
        (pct == null ? '' : ` <span class="muted">(${signed(pct, 0)}% vs avg)</span>`) + '</div>';
      const sv = seededValue(id, year, code), fr = grownFrac(id, year, code);
      if (fr != null && fr < 0.05) h += `<div class="muted"><b>Barely grown here</b> (${sv == null ? '~0' : areaFmt(sv)} seeded) — the yield is modelled noise</div>`;
      else if (sv != null) h += `<div class="muted">Seeded in region: ${areaFmt(sv)}</div>`;
    }
  }
  if ($('#lyr-seeded').checked && state.seeded) {
    const year = seededYear(), code = state.seededCrop;
    const label = state.seeded.crops[state.seededIdx[code]][1];
    const sv = seededValue(id, year, code);
    const car = state.seeded.eco2car[id];
    h += `<div>${esc(label)} seeded ${year}: <b>${sv == null ? '–' : areaFmt(sv)}</b>` +
      (car == null ? ' <span class="muted">(no region data)</span>' : '') + '</div>';
  }
  if ($('#lyr-finance').checked && state.finance) {
    const prov = state.eco.d[id]?.prov;
    const year = financeYear();
    const val = financeValue(id, year);
    if (prov) h += `<div>${esc(state.finance.metrics[state.financeMetric].label)}, ${esc(state.finance.provinces[prov] || prov)} ${year}: <b>${moneyFmt(val)}</b></div>`;
  }
  if ($('#lyr-irrigation').checked && state.irrigation) {
    const geo = state.irrigationGeo === 'basin' && state.drainageGeo ? 'basin' : 'prov';
    const period = irrigationPeriodKey();
    const year = irrigationYear();
    const yi = state.irrigation.years.indexOf(year);
    const pl = esc(state.irrigation.periods[period]);
    const key = geo === 'basin' ? basinOf(id) : state.eco.d[id]?.prov;
    if (geo === 'basin' && !key) h += '<div class="muted">Outside the surveyed irrigation basins</div>';
    else if (key) {
      const raw = irrigationValue(geo, period, key, yi, 'value');
      const pct = irrigationValue(geo, period, key, yi, 'anom');
      const where = geo === 'basin' ? `, ${esc(state.irrigation.basins[key])} basin` : '';
      h += `<div>Irrigation (${pl}) ${year}${where}: <b>${volFmt(raw)}</b>` +
        (pct == null ? '' : ` <span class="muted">(${signed(pct, 0)}% vs avg)</span>`) + '</div>';
    }
  }
  const m = state.matches.find((x) => x.id === id);
  if (m) h += `<div class="tip-match">Match #${m.rank}: ${tLabel(m.t)}, similarity <b>${m.score}</b></div>`;
  h += '<div class="muted">Click to find places like this</div>';
  const tip = $('#tip');
  tip.innerHTML = h;
  tip.hidden = false;
  const w = tip.offsetWidth, hgt = tip.offsetHeight;
  const x = pt.x + 14 + w > innerWidth ? pt.x - w - 14 : pt.x + 14;
  const y = pt.y + 14 + hgt > innerHeight ? pt.y - hgt - 14 : pt.y + 14;
  tip.style.transform = `translate(${x}px, ${y}px)`;
}

// ---------------------------------------------------------------------------
// Similarity ("places like yours")
// ---------------------------------------------------------------------------
async function selectDistrict(id, { fly = true } = {}) {
  id = Number(id);
  if (!state.eco.d[id]) return;
  if (state.sel != null && mapReady()) map.setFeatureState({ source: 'ed', id: state.sel }, { sel: false });
  state.sel = id;
  $('#sim').classList.remove('collapsed');
  $('#sim-search').value = `${id} · ${districtName(id)}`;
  if (mapReady()) map.setFeatureState({ source: 'ed', id }, { sel: true });
  if (fly) map.flyTo({ center: state.eco.d[id].lp, zoom: Math.max(map.getZoom(), 5.5) });
  const url = new URL(location.href);
  url.searchParams.set('d', id);
  history.replaceState(null, '', url);

  await Promise.all(['T2M', 'PRECIP', 'GWETROOT'].map(loadVar));
  const pool = state.simMeta?.pool;
  if (pool && pool.includes(id) && !state.simCache[id]) {
    $('#sim-results').innerHTML = '<p class="small">Loading…</p>';
    state.simCache[id] = await fetch(withV(`data/similarity/${id}.bin`)).then((r) => (r.ok ? r.arrayBuffer() : null)).catch(() => null);
  }
  renderSim();
}

function simMatches(id, t) {
  const buf = state.simCache[id];
  if (!buf) return [];
  const { k, pool, start } = state.simMeta;
  const y0 = Number(start.slice(0, 4));
  const dv = new DataView(buf, t * k * 4, k * 4);
  const out = [];
  for (let i = 0; i < k; i++) {
    const idx = dv.getUint16(i * 4, true), yOff = dv.getUint8(i * 4 + 2), score = dv.getUint8(i * 4 + 3);
    out.push({ rank: i + 1, id: pool[idx], t: (y0 + yOff - state.y0) * 12 + (t % 12), score });
  }
  return out;
}

function snapshot(id, t) {
  const row = state.rowOf[id];
  return {
    temp: climate('T2M', row, t), tempA: climateValue('T2M', row, t, 'anom'),
    precip: climate('PRECIP', row, t), precipA: climateValue('PRECIP', row, t, 'anom'),
    wet: climate('GWETROOT', row, t),
  };
}

function ensoChip(t) {
  const ph = state.enso[t];
  return ph ? `<span class="chip ${ph}">${ENSO[ph].label}</span>` : '';
}

function renderSim() {
  const id = state.sel;
  const you = $('#sim-you'), res = $('#sim-results');
  // clear old highlights: every id we actually highlighted, kept until it is really cleared
  if (mapReady()) {
    for (const mid of state.shownMatches) map.setFeatureState({ source: 'ed', id: mid }, { match: null });
    state.shownMatches.clear();
  }
  state.matches = [];
  if (id == null) {
    you.innerHTML = '';
    res.innerHTML = '<p class="small">Pick your ecodistrict to see where, and when, conditions were most like yours this month.</p>';
    return;
  }
  const r = state.eco.d[id];
  const s = snapshot(id, state.t);
  const c = cropRec(id);
  you.innerHTML = `<div class="you">
    <div class="you-head"><b>Ecodistrict ${id}</b> in <b>${tLabel(state.t)}</b>${isFuture(state.t) ? ' <span class="fc-tag">forecast</span>' : ''} ${ensoChip(state.t)}
      ${infoHtml(`In brackets: difference from the ${NORMAL[0]}–${NORMAL[1]} normal for ${MONTHS[state.t % 12]}.`)}</div>
    <div class="muted">${esc(districtName(id))} · ${Number(r.area).toLocaleString()} km²</div>
    <dl>
      <dt>Mean temp</dt><dd>${fmt(s.temp)} °C <span class="muted">(${signed(s.tempA)})</span></dd>
      <dt>Precip</dt><dd>${fmt(s.precip, 0)} mm <span class="muted">(${signed(s.precipA, 0)})</span></dd>
      <dt>Root-zone wetness</dt><dd>${fmt(s.wet, 2)}</dd>
      ${r.soil ? `<dt>Soil</dt><dd>${esc(state.eco.soil_orders[r.soil.order] ?? '–')}, ${fmt(r.soil.awhc, 0)} mm water holding</dd>` : ''}
      ${c && c.crop > 0 ? `<dt>Crops ${cropYear()}</dt><dd>${fmt(c.crop, 0)}% of land · mostly ${esc(state.classes[c.top]?.[0] ?? '–')}</dd>` : ''}
    </dl>
  </div>`;

  if (!state.simMeta) {
    res.innerHTML = '<p class="small">No similarity file yet (run scripts/similarity.py).</p>';
    return;
  }
  if (!state.simMeta.pool.includes(id)) {
    res.innerHTML = '<p class="small">Similarity is only computed for farmland ecodistricts (where soil survey data exists). Pick one further south.</p>';
    return;
  }
  state.matches = simMatches(id, state.t);
  if (mapReady()) {
    for (const m of state.matches) {
      map.setFeatureState({ source: 'ed', id: m.id }, { match: m.score });
      state.shownMatches.add(m.id);
    }
  }
  const head = isExt(state.t)
    ? `<h2>${isFuture(state.t) ? 'Forecast' : 'This month'} is most like ${infoHtml('Compared on what Meteomatics provides (temperature, precipitation, humidity, wind, sun, snow depth, frost days) plus soil; soil wetness and evapotranspiration are not forecast.')}</h2>`
    : `<h2>Most similar ${MONTHS[state.t % 12]}s</h2>`;
  res.innerHTML = `${head}<ol class="matches">` + state.matches.map((m) => {
    const q = snapshot(m.id, m.t);
    return `<li data-id="${m.id}" data-t="${m.t}">
      <div class="m-top"><span class="rank">${m.rank}</span><b>${tLabel(m.t)}</b> ${ensoChip(m.t)}<span class="score">${m.score}</span></div>
      <div class="bar"><i style="width:${m.score}%"></i></div>
      <div class="muted">Ecodistrict ${m.id} · ${esc(districtName(m.id))}</div>
      <div class="m-vals">${fmt(q.temp)} °C · ${fmt(q.precip, 0)} mm · wetness ${fmt(q.wet, 2)}</div>
    </li>`;
  }).join('') + '</ol>';
}

// ---------------------------------------------------------------------------
// Info icons: hover, focus or tap shows the hidden text in one floating popover
// ---------------------------------------------------------------------------
const infoHtml = (html) => `<span class="info" tabindex="0" role="button" aria-label="More info">i<span class="info-src">${html}</span></span>`;

function buildInfo() {
  const pop = document.createElement('div');
  pop.id = 'info-pop';
  pop.hidden = true;
  document.body.appendChild(pop);
  let cur = null, pinned = false, hideT = null;
  const show = (el) => {
    clearTimeout(hideT);
    cur = el;
    pop.innerHTML = el.querySelector('.info-src').innerHTML;
    pop.hidden = false;
    const b = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    const x = Math.max(8, Math.min(innerWidth - w - 8, b.left + b.width / 2 - w / 2));
    const y = b.bottom + 8 + h > innerHeight ? b.top - h - 8 : b.bottom + 8;
    pop.style.left = `${x}px`;
    pop.style.top = `${y}px`;
    document.querySelectorAll('.info.open').forEach((e) => e.classList.remove('open'));
    el.classList.add('open');
  };
  const hide = () => { pop.hidden = true; pinned = false; cur?.classList.remove('open'); cur = null; };
  const later = () => { if (!pinned) hideT = setTimeout(hide, 150); };
  document.addEventListener('mouseover', (e) => {
    const el = e.target.closest('.info');
    if (el && el !== cur) { pinned = false; show(el); } else if (!el && !e.target.closest('#info-pop') && cur) later();
    else if (e.target.closest('#info-pop')) clearTimeout(hideT);
  });
  document.addEventListener('click', (e) => {
    const el = e.target.closest('.info');
    if (el) { e.preventDefault(); e.stopPropagation(); if (cur === el && pinned) hide(); else { show(el); pinned = true; } }
    else if (!e.target.closest('#info-pop')) hide();
  }, true);
  document.addEventListener('focusin', (e) => { const el = e.target.closest?.('.info'); if (el) show(el); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
  document.addEventListener('scroll', hide, true);
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------
function buildUI() {
  const slider = $('#month');
  slider.max = state.n - 1;
  $('#tmin').textContent = tLabel(0);
  $('#tmax').textContent = tLabel(state.n - 1) + (isFuture(state.n - 1) ? ' (forecast)' : '');
  slider.addEventListener('input', () => setMonth(Number(slider.value)));
  drawOni();

  buildTimeControls();

  // play
  let timer = null;
  const stop = () => { clearInterval(timer); timer = null; $('#play').textContent = '▶'; $('#play').classList.remove('on'); };
  $('#play').onclick = () => {
    if (timer) return stop();
    $('#play').textContent = '❚❚';
    $('#play').classList.add('on');
    if (state.t >= state.n - 1) setMonth(0);
    timer = setInterval(() => (state.t >= state.n - 1 ? stop() : setMonth(state.t + 1)), 350);
  };

  // climate variable picker
  const sel = $('#climate-var');
  sel.innerHTML = Object.entries(state.meta.vars).map(([k, v]) => `<option value="${k}">${esc(v.label)} (${esc(v.units)})</option>`).join('');
  sel.value = state.climateVar;
  sel.addEventListener('change', async () => {
    state.climateVar = sel.value;
    const url = new URL(location.href);
    url.searchParams.set('v', sel.value);
    history.replaceState(null, '', url);
    await loadVar(sel.value);
    paintClimate();
  });
  $('#climate-mode').addEventListener('change', (e) => { state.climateMode = e.target.value; paintClimate(); });

  // soil picker
  const ss = $('#soil-var');
  ss.innerHTML = Object.entries(state.eco.soil_fields).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  ss.value = state.soilVar;
  ss.addEventListener('change', () => { state.soilVar = ss.value; paintSoil(); });

  // crop legend
  $('#crop-legend').innerHTML = Object.values(CROP_GROUPS).map(([n, c]) => `<span><i class="sw" style="background:${c}"></i>${esc(n)}</span>`).join('');

  // crop-yield pickers
  const yc = $('#yield-crop');
  if (state.yield) {
    yc.innerHTML = state.yield.crops.map(([code, label]) => `<option value="${code}">${esc(label)}</option>`).join('');
    yc.value = state.yieldCrop;
  }
  yc.addEventListener('change', () => { state.yieldCrop = yc.value; paintYield(); });
  $('#yield-mode').addEventListener('change', (e) => { state.yieldMode = e.target.value; paintYield(); });

  // seeded-area crop picker
  const sc = $('#seeded-crop');
  if (state.seeded) {
    sc.innerHTML = state.seeded.crops.map(([code, label]) => `<option value="${code}">${esc(label)}</option>`).join('');
    sc.value = state.seededCrop;
  }
  sc.addEventListener('change', () => { state.seededCrop = sc.value; paintSeeded(); });

  // farm-support payment metric picker
  const fm = $('#finance-metric');
  if (state.finance) {
    fm.innerHTML = Object.entries(state.finance.metrics).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join('');
    fm.value = state.financeMetric;
  }
  fm.addEventListener('change', () => { state.financeMetric = fm.value; paintFinance(); });

  // irrigation season + geography pickers
  const ip = $('#irrigation-period');
  if (ip) ip.addEventListener('change', () => { state.irrigationPeriod = ip.value; paintIrrigation(); });
  const ig = $('#irrigation-geo');
  if (ig) {
    if (!state.drainageGeo) { ig.value = 'prov'; ig.disabled = true; }
    else ig.value = state.irrigationGeo;
    ig.addEventListener('change', () => { state.irrigationGeo = ig.value; applyLayers(); });
  }
  const im = $('#irrigation-mode');
  if (im) im.addEventListener('change', () => { state.irrigationMode = im.value; paintIrrigation(); });

  for (const id of ['lyr-climate', 'lyr-soil', 'lyr-crops', 'lyr-yield', 'lyr-seeded', 'lyr-finance', 'lyr-irrigation', 'lyr-lines']) {
    $('#' + id).addEventListener('change', () => { applyLayers(); if (id === 'lyr-crops') paintCrops(); });
  }
  syncLegends();
  for (const b of document.querySelectorAll('.expand')) {
    b.addEventListener('click', () => {
      const open = b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', open);
      $('#' + b.getAttribute('aria-controls')).hidden = !open;
    });
  }
  buildInfo();

  for (const b of document.querySelectorAll('.collapse')) {
    b.onclick = () => {
      const p = $('#' + b.dataset.target);
      p.classList.toggle('collapsed');
      b.textContent = p.classList.contains('collapsed') ? '+' : '–';
    };
  }

  // ecodistrict search
  const pool = new Set(state.simMeta?.pool || []);
  $('#sim-list').innerHTML = Object.keys(state.eco.d).filter((id) => pool.has(Number(id)))
    .sort((a, b) => districtName(a).localeCompare(districtName(b)) || a - b)
    .map((id) => `<option value="${id} · ${esc(districtName(id))}"></option>`).join('');
  $('#sim-search').addEventListener('change', (e) => {
    const m = /^\s*(\d+)/.exec(e.target.value);
    if (m) selectDistrict(Number(m[1]));
  });
  $('#sim-search').addEventListener('focus', (e) => e.target.select());

  const results = $('#sim-results');
  results.addEventListener('click', (e) => {
    const li = e.target.closest('li[data-id]');
    if (li) map.flyTo({ center: state.eco.d[li.dataset.id].lp, zoom: Math.max(map.getZoom(), 5.5) });
  });
  results.addEventListener('dblclick', (e) => {
    const li = e.target.closest('li[data-id]');
    if (li) setMonth(Number(li.dataset.t));
  });
  results.addEventListener('mouseover', (e) => {
    const li = e.target.closest('li[data-id]');
    const id = li ? Number(li.dataset.id) : null;
    if (id === state.hover || !mapReady()) return;
    if (state.hover != null) map.setFeatureState({ source: 'ed', id: state.hover }, { hover: false });
    state.hover = id;
    if (id != null) map.setFeatureState({ source: 'ed', id }, { hover: true });
  });
  results.addEventListener('mouseleave', () => {
    if (state.hover != null && mapReady()) map.setFeatureState({ source: 'ed', id: state.hover }, { hover: false });
    state.hover = null;
  });
  renderSim();
}
