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
  meta: null, eco: null, ids: [], rowOf: {}, bins: {}, normals: {}, domains: {},
  oni: [], enso: [], oniFc: [], classes: {},
  nObs: 0, nowT: null, kinds: [], // months < nObs are NASA POWER; later ones come from Meteomatics
  simMeta: null, simCache: {}, sel: null, matches: [], hover: null,
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
]);

const monthIndex = (ym, y0) => (Number(ym.slice(0, 4)) - y0) * 12 + Number(ym.slice(5, 7)) - 1;

const uiReady = dataReady.then(async ([oni, eco, meta, aci, simMeta, oniFc, yieldData]) => {
  state.eco = eco;
  state.meta = meta;
  state.simMeta = simMeta;
  state.yield = yieldData;
  if (yieldData) {
    yieldData.crops.forEach(([code], i) => { state.yieldIdx[code] = i; });
    if (!(state.yieldCrop in state.yieldIdx)) state.yieldCrop = yieldData.crops[0][0];
    const first = yieldData.d[Object.keys(yieldData.d)[0]];
    yieldData.y1 = yieldData.y0 + (first ? first[0].length - 1 : 0);
  }
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
  map.addLayer({ id: 'yield-fill', type: 'fill', source: 'ed', layout: { visibility: 'none' },
    paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.78 } }, firstLabel);
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

// ---- precise time controls: steppers, pickers, a zoomed 3-year slider, keyboard, chart drag
const ZW = 36; // months in the zoom window

function syncTimeControls(fromFine = false) {
  const t = state.t;
  $('#pick-month').value = t % 12;
  $('#pick-year').value = tYear(t);
  const fine = $('#month-fine');
  if (!fine) return;
  const n = state.n, w = Math.min(ZW, n);
  // re-centre the window unless the user is dragging the zoomed slider itself
  if (!fromFine && (state.z0 == null || t < state.z0 + 3 || t > state.z0 + w - 4)) {
    state.z0 = Math.max(0, Math.min(n - w, t - Math.floor(w / 2)));
  }
  const z0 = state.z0;
  fine.min = z0;
  fine.max = z0 + w - 1;
  fine.value = t;
  $('#zmin').textContent = tLabel(z0);
  $('#zmax').textContent = tLabel(z0 + w - 1);
  drawZoom();
}

function drawZoom() {
  const svg = $('#oni-zoom');
  const W = 360, H = 34, mid = H / 2, w = Math.min(ZW, state.n), bw = W / w, z0 = state.z0;
  const vals = state.oni.slice(z0, z0 + w).filter((v) => v != null).map(Math.abs);
  const sc = (mid - 2) / Math.max(1.5, ...vals);
  let s = '';
  for (let i = 0; i < w; i++) {
    const t = z0 + i, v = state.oni[t];
    if (t % 12 === 0 && i > 0) s += `<line x1="${i * bw}" x2="${i * bw}" y1="0" y2="${H}" class="yr"/>`;
    if (v == null) continue;
    const h = v * sc;
    s += `<rect x="${(i * bw + 0.6).toFixed(2)}" width="${(bw - 1.2).toFixed(2)}" y="${(h >= 0 ? mid - h : mid).toFixed(2)}" ` +
      `height="${Math.max(0.6, Math.abs(h)).toFixed(2)}" fill="${ENSO[state.enso[t]].color}"${state.oniFc[t] ? ' fill-opacity="0.45"' : ''}/>`;
  }
  const i = state.t - z0;
  s += `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" class="zero"/>` +
    `<rect x="${(i * bw).toFixed(2)}" width="${bw.toFixed(2)}" y="0.5" height="${H - 1}" class="cur"/>`;
  svg.innerHTML = s;
}

function hoverLabel(t) {
  const v = state.oni[t];
  return t == null ? '' : `${tLabel(t)}${v == null ? '' : ` · ONI ${signed(v, 2)}`}${isFuture(t) ? ' (forecast)' : ''}`;
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
  for (const b of document.querySelectorAll('.step[data-step]')) {
    b.addEventListener('click', () => setMonth(state.t + Number(b.dataset.step)));
  }
  $('#go-now').addEventListener('click', () => setMonth(state.nowT ?? state.n - 1));
  $('#go-now').hidden = state.nowT == null;

  const fine = $('#month-fine');
  fine.addEventListener('input', () => { setMonthFrom(Number(fine.value), true); });
  fine.addEventListener('change', () => syncTimeControls()); // re-centre once the drag ends

  // drag / hover on both ONI charts
  const scrub = (el, toT) => {
    let down = false;
    const at = (e) => toT(e, el.getBoundingClientRect());
    el.addEventListener('pointerdown', (e) => { down = true; el.setPointerCapture(e.pointerId); setMonthFrom(at(e), el.id === 'oni-zoom'); });
    el.addEventListener('pointermove', (e) => {
      const t = clampT(at(e));
      $('#thover').textContent = hoverLabel(t);
      if (down) setMonthFrom(t, el.id === 'oni-zoom');
    });
    el.addEventListener('pointerup', () => { down = false; if (el.id === 'oni-zoom') syncTimeControls(); });
    el.addEventListener('pointerleave', () => { if (!down) $('#thover').textContent = ''; });
  };
  scrub($('#oni-chart'), (e, b) => Math.floor((e.clientX - b.left) / b.width * state.n));
  scrub($('#oni-zoom'), (e, b) => state.z0 + Math.floor((e.clientX - b.left) / b.width * Math.min(ZW, state.n)));

  // keyboard: arrows step a month, Shift + arrows a year (when not typing in a field)
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      setMonth(state.t + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 12 : 1));
    }
  });
}

// setMonth, telling the zoom window not to re-centre while it is being dragged
function setMonthFrom(t, fromFine) {
  state.fromFine = fromFine;
  setMonth(t);
  state.fromFine = false;
}

function setMonth(t) {
  state.t = clampT(t);
  const slider = $('#month');
  slider.value = state.t;
  syncTimeControls(state.fromFine);
  $('#month-label').innerHTML = esc(tLabel(state.t)) + (isFuture(state.t) ? ' <span class="fc-tag">forecast</span>' : '');
  const ph = state.enso[state.t], v = state.oni[state.t], fc = state.oniFc[state.t];
  const badge = $('#enso-badge');
  badge.textContent = ph ? `${ENSO[ph].label} · ONI ${signed(v, 2)}` : 'ONI n/a';
  badge.className = 'badge ' + (ph || '') + (fc ? ' fc' : '');
  badge.title = fc ? 'Forecast ONI' : 'Observed ONI';
  $('#oni-text').innerHTML = (fc
    ? `<b>Forecast</b> ONI for the ${ONI_SEASONS[state.t % 12]} season centred on ${tLabel(state.t)}, from the ECMWF seasonal ` +
      'forecast of Niño 3.4 sea temperature (via Meteomatics), anchored to NOAA\'s latest observation. '
    : `ONI for the ${ONI_SEASONS[state.t % 12]} season centred on ${tLabel(state.t)}. `) +
    'Coloured as an El Niño / La Niña episode when it stays beyond ±0.5 °C for 5+ overlapping seasons; the shaded end is forecast. Click or drag the chart, use the arrows, or the zoomed slider for single months.';
  const sel = $('#oni-sel');
  if (sel) {
    const x = (state.t + 0.5) * 300 / state.n;
    sel.setAttribute('x1', x); sel.setAttribute('x2', x);
  }
  const url = new URL(location.href);
  url.searchParams.set('m', `${tYear(state.t)}-${String(state.t % 12 + 1).padStart(2, '0')}`);
  history.replaceState(null, '', url);
  paintAll();
  renderSim();
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
const mapReady = () => map.getSource('ed') && map.isSourceLoaded('ed');

function paintAll() {
  paintClimate();
  paintCrops();
  paintYield();
}

function paintClimate() {
  const key = state.climateVar, mode = state.climateMode;
  if (!(state.bins[key] instanceof Int16Array)) return;
  const dom = climateDomain(key, mode, state.t % 12);
  const colors = rampFor(key, mode);
  const v = state.meta.vars[key];
  $('#climate-ramp').innerHTML = rampHtml(colors, dom, mode === 'anom' ? `${v.units} vs normal` : v.units, Math.max(0, varDigits(key) - (mode === 'anom' ? 0 : 1)));
  const note = $('#climate-note');
  if (isExt(state.t)) {
    note.hidden = false;
    note.innerHTML = !v.forecast
      ? `<b>No forecast for ${esc(v.label.toLowerCase())}.</b> Meteomatics' seasonal forecast does not include it; ` +
        `NASA POWER has it up to ${tLabel(state.nObs - 1)}.`
      : isFuture(state.t)
        ? '<b>Forecast:</b> ECMWF seasonal forecast via Meteomatics, bias-corrected to NASA POWER for each ecodistrict.'
        : '<b>Recent month</b> not yet in NASA POWER: Meteomatics analysis, bias-corrected to NASA POWER.';
  } else note.hidden = true;
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

function paintYield() {
  if (!state.yield) { $('#yield-text').textContent = 'No yield data yet (run scripts/build_yield.py).'; return; }
  const code = state.yieldCrop, mode = state.yieldMode;
  const label = state.yield.crops[state.yieldIdx[code]][1];
  const year = yieldYear();
  const exact = year === tYear(state.t);
  const dom = yieldDomain(code, mode);
  const colors = mode === 'anom' ? RAMPS.anomWet : RAMPS.awhc;
  $('#yield-ramp').innerHTML = mode === 'anom'
    ? `<span>${signed(dom[0], 0)}%</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>${signed(dom[1], 0)}% vs avg</span>`
    : `<span>${fmt(dom[0], 0)}</span><i style="background:linear-gradient(90deg,${colors.join(',')})"></i><span>${fmt(dom[1], 0)} kg/ha</span>`;
  $('#yield-text').innerHTML = `<b>${esc(label)}</b> yield for <b>${year}</b>` +
    `${exact ? '' : ` (nearest year to ${tYear(state.t)}; record is ${state.yield.y0}–${state.yield.y1})`}, ` +
    (mode === 'anom'
      ? 'shown as % above (teal) or below (brown) each ecodistrict’s own long-term average.'
      : 'averaged across the Soil Landscape polygons in each ecodistrict.');
  if (!mapReady() || !map.getLayer('yield-fill') || !$('#lyr-yield').checked) return;
  map.setPaintProperty('yield-fill', 'fill-color', rampExpr('y', colors, dom));
  for (const id of state.ids) {
    map.setFeatureState({ source: 'ed', id }, { y: yieldValue(id, year) });
  }
}

function applyLayers() {
  for (const el of document.querySelectorAll('.opts')) el.hidden = !$('#' + el.dataset.for).checked;
  if ($('#lyr-yield').checked) paintYield(); // legend + text even before the map is ready
  if (!map.getLayer('climate-fill')) return;
  const vis = (id, on) => map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
  vis('climate-fill', $('#lyr-climate').checked);
  vis('soil-fill', $('#lyr-soil').checked);
  vis('yield-fill', $('#lyr-yield').checked);
  vis('crops', $('#lyr-crops').checked);
  vis('lines', $('#lyr-lines').checked);
  if ($('#lyr-soil').checked) paintSoil();
  if ($('#lyr-yield').checked) paintYield();
  for (const el of document.querySelectorAll('.opts')) el.hidden = !$('#' + el.dataset.for).checked;
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
  // clear old highlights
  if (mapReady()) for (const m of state.matches) map.setFeatureState({ source: 'ed', id: m.id }, { match: null });
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
    <div class="you-head"><b>Ecodistrict ${id}</b> in <b>${tLabel(state.t)}</b>${isFuture(state.t) ? ' <span class="fc-tag">forecast</span>' : ''} ${ensoChip(state.t)}</div>
    <div class="muted">${esc(districtName(id))} · ${Number(r.area).toLocaleString()} km²</div>
    <dl>
      <dt>Mean temp</dt><dd>${fmt(s.temp)} °C <span class="muted">(${signed(s.tempA)})</span></dd>
      <dt>Precip</dt><dd>${fmt(s.precip, 0)} mm <span class="muted">(${signed(s.precipA, 0)})</span></dd>
      <dt>Root-zone wetness</dt><dd>${fmt(s.wet, 2)}</dd>
      ${r.soil ? `<dt>Soil</dt><dd>${esc(state.eco.soil_orders[r.soil.order] ?? '–')}, ${fmt(r.soil.awhc, 0)} mm water holding</dd>` : ''}
      ${c && c.crop > 0 ? `<dt>Crops ${cropYear()}</dt><dd>${fmt(c.crop, 0)}% of land · mostly ${esc(state.classes[c.top]?.[0] ?? '–')}</dd>` : ''}
    </dl>
    <div class="muted small">(in brackets: difference from the ${NORMAL[0]}–${NORMAL[1]} normal for ${MONTHS[state.t % 12]})</div>
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
  if (mapReady()) for (const m of state.matches) map.setFeatureState({ source: 'ed', id: m.id }, { match: m.score });
  const head = isExt(state.t)
    ? `<h2>${isFuture(state.t) ? 'The forecast' : 'This month'} looks most like these past ${MONTHS[state.t % 12]}s</h2>` +
      '<p class="small">Compared on what Meteomatics provides (temperature, precipitation, humidity, wind, sun, snow depth, frost days) plus soil; soil wetness and evapotranspiration are not forecast.</p>'
    : `<h2>Most similar: ${MONTHS[state.t % 12]} in other years</h2>`;
  res.innerHTML = `${head}<ol class="matches">` + state.matches.map((m) => {
    const q = snapshot(m.id, m.t);
    return `<li data-id="${m.id}" data-t="${m.t}">
      <div class="m-top"><span class="rank">${m.rank}</span><b>${tLabel(m.t)}</b> ${ensoChip(m.t)}<span class="score">${m.score}</span></div>
      <div class="bar"><i style="width:${m.score}%"></i></div>
      <div class="muted">Ecodistrict ${m.id} · ${esc(districtName(m.id))}</div>
      <div class="m-vals">${fmt(q.temp)} °C · ${fmt(q.precip, 0)} mm · wetness ${fmt(q.wet, 2)}</div>
    </li>`;
  }).join('') + '</ol><p class="small">Click a match to zoom to it. Double-click to also jump the timeline to that month.</p>';
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

  for (const id of ['lyr-climate', 'lyr-soil', 'lyr-crops', 'lyr-yield', 'lyr-lines']) {
    $('#' + id).addEventListener('change', () => { applyLayers(); if (id === 'lyr-crops') paintCrops(); });
  }
  for (const el of document.querySelectorAll('.opts')) el.hidden = !$('#' + el.dataset.for).checked;

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
  renderSim();
}
