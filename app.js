'use strict';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const ACI = 'https://agriculture.canada.ca/imagery-images/rest/services/annual_crop_inventory';
// Lon/lat extent of the crop inventory rasters (from the ImageServer extent)
const ACI_BOUNDS = [-144.3, 40.4, -49.7, 66.5];
// Precipitation anomaly colour ramp (% of the 1991-2020 normal), brown = drier, teal = wetter
const PRECIP_RAMP = [-50, '#8c510a', -25, '#d8b365', 0, '#f6f3ea', 25, '#5ab4ac', 50, '#01665e'];
const PRECIP_SEASONS = { gs: 'growing season (May–Sep)', djf: 'winter (Dec–Feb)' };

// Ecozone names and colours (ids from the National Ecological Framework)
const ZONES = {
  1: ['Arctic Cordillera', '#a9b8cf'], 2: ['Northern Arctic', '#d3dde8'], 3: ['Southern Arctic', '#9fcbc0'],
  4: ['Taiga Plains', '#8db37f'], 5: ['Taiga Shield', '#c9b67a'], 6: ['Boreal Shield', '#4e8160'],
  7: ['Atlantic Maritime', '#5aa3a8'], 8: ['Mixedwood Plains', '#dc8a5a'], 9: ['Boreal Plains', '#7fa856'],
  10: ['Prairies', '#e8c55a'], 11: ['Taiga Cordillera', '#a394c2'], 12: ['Boreal Cordillera', '#7b68a6'],
  13: ['Pacific Maritime', '#3e7fb0'], 14: ['Montane Cordillera', '#b06a82'], 15: ['Hudson Plains', '#6a9f8a'],
};

// Crop inventory classes (values from the "annual_crop_inventory" raster function) grouped for the legend
const GROUPS = [
  { name: 'Cereals', on: true, vals: [15, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 66, 67] },
  { name: 'Corn', on: true, vals: [29] },
  { name: 'Canola & oilseeds', on: true, vals: [35, 32, 33, 34, 36, 37, 38, 39, 41] },
  { name: 'Soybeans', on: true, vals: [40] },
  { name: 'Pulses', on: true, vals: [42, 43, 44, 45, 46, 47, 48, 69] },
  { name: 'Vegetables & potatoes', on: true, vals: [49, 50, 51, 52, 53] },
  { name: 'Fruit, berries & vines', on: true, vals: [54, 55, 56, 57, 58, 59, 60, 61, 62] },
  { name: 'Other crops', on: true, vals: [10, 11, 24, 30, 31, 63, 64, 65, 68, 70] },
  { name: 'Pasture, forage & fallow', on: false, vals: [12, 13, 14] },
  { name: 'Other land cover', on: false, vals: [1, 2, 3, 4, 5, 6, 7, 8, 9, 71, 72, 73, 74] },
];

// Reuse the ?v= from this script's URL (set in index.html) so data files are cache-busted together
const V = new URL(document.currentScript.src).searchParams.get('v') || '0';
const withV = (path) => `${path}?v=${V}`;

const $ = (s) => document.querySelector(s);
const state = {
  year: 2025, years: [], classes: {}, oni: {}, oniList: [], point: null, history: {},
  precip: null, precipSeason: 'gs',
};

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/positron',
  center: [-100, 54],
  zoom: 3.3,
  maxZoom: 15,
  attributionControl: { compact: true, customAttribution: 'Crops & ecoregions © AAFC (OGL-Canada) · ONI © NOAA CPC · Precipitation: NASA POWER' },
});
map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

const dataReady = Promise.all([
  fetch(withV('data/aci_classes.json')).then((r) => r.json()),
  fetch(withV('data/oni.json')).then((r) => r.json()),
  // optional until scripts/fetch_precipitation.py has been run
  fetch(withV('data/precip.json')).then((r) => (r.ok ? r.json() : null)).catch(() => null),
]);

// The panel only needs the small data files, so build it straight away, without waiting for the basemap.
const uiReady = dataReady.then(([aci, oni, precip]) => {
  state.precip = precip;
  state.years = aci.years;
  state.classes = aci.classes;
  state.oniList = oni.data;
  for (const d of oni.data) (state.oni[d.year] ||= {})[d.season] = d.anom;

  const q = new URLSearchParams(location.search);
  const qy = Number(q.get('year'));
  state.year = state.years.includes(qy) ? qy : state.years[state.years.length - 1];

  buildUI();
  setYear(state.year);
}).catch((e) => {
  console.error(e);
  $('#oni-text').textContent = 'Could not load data files (data/aci_classes.json, data/oni.json).';
});

map.on('load', async () => {
  await uiReady;
  if (!state.years.length) return;

  const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;

  // ecoregion polygons
  map.addSource('ecoregions', { type: 'geojson', data: withV('data/ecoregions.min.geojson'), promoteId: 'id' });
  const zoneColor = ['match', ['get', 'zone']];
  for (const [id, [, c]] of Object.entries(ZONES)) zoneColor.push(Number(id), c);
  zoneColor.push('#999');
  map.addLayer({
    id: 'eco-fill', type: 'fill', source: 'ecoregions',
    layout: { visibility: 'none' },
    paint: { 'fill-color': zoneColor, 'fill-opacity': 0.45 },
  }, firstLabel);

  // crop inventory raster, streamed from AAFC
  map.addSource('aci', {
    type: 'raster', tiles: [cropTileUrl()], tileSize: 256, bounds: ACI_BOUNDS,
    attribution: '',
  });
  map.addLayer({
    id: 'aci', type: 'raster', source: 'aci',
    paint: { 'raster-opacity': 0.9, 'raster-resampling': 'nearest', 'raster-fade-duration': 150 },
  }, firstLabel);

  // precipitation anomaly per ecoregion, driven by feature-state (see paintPrecip)
  map.addLayer({
    id: 'precip-fill', type: 'fill', source: 'ecoregions',
    layout: { visibility: 'none' },
    paint: {
      'fill-color': ['case', ['==', ['typeof', ['feature-state', 'precip']], 'number'],
        ['interpolate', ['linear'], ['feature-state', 'precip'], ...PRECIP_RAMP], 'rgba(0,0,0,0)'],
      'fill-opacity': 0.7,
    },
  }, firstLabel);

  map.addLayer({
    id: 'eco-lines', type: 'line', source: 'ecoregions',
    paint: {
      'line-color': '#3b4a42',
      'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.5, 8, 1.4],
      'line-opacity': 0.55,
    },
  }, firstLabel);

  // point marker
  map.addSource('pt', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({
    id: 'pt', type: 'circle', source: 'pt',
    paint: { 'circle-radius': 6, 'circle-color': '#fff', 'circle-stroke-color': '#1d2420', 'circle-stroke-width': 2.5 },
  });

  // apply anything the user changed in the panel before the map finished loading
  // (the crop source above was created from the current year and filters, so it needs no refresh)
  applyEcoToggles();
  paintPrecip();
  if (!enabledValues().length) map.setLayoutProperty('aci', 'visibility', 'none');
  map.on('click', (e) => openPoint(e.lngLat));
});

function applyEcoToggles() {
  if (!map.getLayer('eco-lines')) return;
  map.setLayoutProperty('eco-lines', 'visibility', $('#eco-lines').checked ? 'visible' : 'none');
  map.setLayoutProperty('eco-fill', 'visibility', $('#eco-fill').checked ? 'visible' : 'none');
  map.setLayoutProperty('precip-fill', 'visibility', $('#precip-on').checked ? 'visible' : 'none');
}

// ---------------------------------------------------------------------------
// Crop tiles
// ---------------------------------------------------------------------------
function hexToRgb(h) {
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function enabledValues() {
  return GROUPS.filter((g) => g.on).flatMap((g) => g.vals);
}

function cropTileUrl() {
  const vals = enabledValues();
  // A Colormap on top of AAFC's class remap: classes not listed come back transparent.
  const colormap = (vals.length ? vals : [0]).map((v) => {
    const c = state.classes[v];
    return [v, ...(c ? hexToRgb(c[1]) : [0, 0, 0])];
  });
  const rule = {
    rasterFunction: 'Colormap',
    rasterFunctionArguments: { Colormap: colormap, Raster: { rasterFunction: 'annual_crop_inventory' } },
  };
  return `${ACI}/${state.year}/ImageServer/exportImage?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857` +
    `&size=256,256&format=png32&transparent=true&interpolation=RSP_NearestNeighbor&f=image` +
    `&renderingRule=${encodeURIComponent(JSON.stringify(rule))}`;
}

function refreshCrops() {
  const src = map.getSource('aci');
  if (!src) return;
  const any = enabledValues().length > 0;
  map.setLayoutProperty('aci', 'visibility', any ? 'visible' : 'none');
  const url = cropTileUrl();
  if (any && src.tiles?.[0] !== url) src.setTiles([url]);
}

// ---------------------------------------------------------------------------
// Precipitation
// ---------------------------------------------------------------------------
// Ecoregion precipitation for a year: { mm, pct } where pct is the anomaly vs the 1991-2020 normal
function precipFor(id, year, season = state.precipSeason) {
  const p = state.precip;
  const r = p?.eco[id];
  const mm = r?.[season][year - p.first_year];
  const norm = r?.norm[season];
  if (mm == null || !norm) return null;
  return { mm, pct: (mm / norm - 1) * 100 };
}

function paintPrecip() {
  const p = state.precip;
  if (!p) return;
  if (map.getSource('ecoregions')) {
    for (const id of Object.keys(p.eco)) {
      map.setFeatureState({ source: 'ecoregions', id: Number(id) }, { precip: precipFor(id, state.year)?.pct ?? null });
    }
  }
  const hasYear = state.year >= p.first_year && state.year <= p.last_year;
  $('#precip-text').textContent = hasYear
    ? `${state.year} ${PRECIP_SEASONS[state.precipSeason]} total compared with the ${p.normal[0]}–${p.normal[1]} average. ` +
      'Click an ecoregion for the yearly history.'
    : `No precipitation data for ${state.year} yet (have ${p.first_year}–${p.last_year}).`;
}

const pctText = (v) => (v >= 0.5 ? '+' : v <= -0.5 ? '−' : '') + Math.abs(Math.round(v)) + '%';

// ---------------------------------------------------------------------------
// ENSO helpers
// ---------------------------------------------------------------------------
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;

function oniFor(year) {
  const y = state.oni[year] || {};
  const summerVals = ['MJJ', 'JJA', 'JAS'].map((s) => y[s]).filter((v) => v != null);
  return { winter: y.DJF ?? null, summer: summerVals.length ? mean(summerVals) : null };
}

function phase(v) {
  if (v == null) return { label: 'n/a', cls: '' };
  if (v >= 0.5) return { label: 'El Niño', cls: 'nino' };
  if (v <= -0.5) return { label: 'La Niña', cls: 'nina' };
  return { label: 'Neutral', cls: '' };
}

const sign = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2);

function drawOniChart() {
  const svg = $('#oni-chart');
  const y0 = state.years[0];
  const y1 = Math.max(state.years[state.years.length - 1], state.oniList[state.oniList.length - 1].year);
  const rows = state.oniList.filter((d) => d.year >= y0 && d.year <= y1);
  const W = 300, H = 96, top = 6, bottom = 14, mid = top + (H - top - bottom) / 2;
  const range = Math.max(2.5, ...rows.map((d) => Math.abs(d.anom)));
  const scale = (H - top - bottom) / 2 / range;
  const n = (y1 - y0 + 1) * 12;
  const bw = W / n;
  const x = (yr, si) => ((yr - y0) * 12 + si) * bw;
  const seasons = ['DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ', 'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ'];

  let s = `<rect id="oni-sel" y="${top - 4}" height="${H - top - bottom + 8}" fill="#2f6b4f" opacity=".12" rx="2"/>`;
  for (const v of [0.5, -0.5]) {
    s += `<line x1="0" x2="${W}" y1="${mid - v * scale}" y2="${mid - v * scale}" stroke="#b9b6aa" stroke-dasharray="2 2" stroke-width=".6"/>`;
  }
  for (const d of rows) {
    const h = d.anom * scale;
    const c = d.anom >= 0.5 ? 'var(--nino)' : d.anom <= -0.5 ? 'var(--nina)' : '#b9b6aa';
    s += `<rect x="${x(d.year, seasons.indexOf(d.season)).toFixed(2)}" width="${(bw + 0.05).toFixed(2)}" ` +
         `y="${(h >= 0 ? mid - h : mid).toFixed(2)}" height="${Math.max(0.5, Math.abs(h)).toFixed(2)}" fill="${c}"/>`;
  }
  s += `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="#7d8a82" stroke-width=".6"/>`;
  for (let yr = y0; yr <= y1; yr++) {
    if ((yr - y0) % 4 === 0) s += `<text x="${x(yr, 6)}" y="${H - 2}" text-anchor="middle">${yr}</text>`;
  }
  s += `<text x="2" y="${top + 6}">El Niño +</text><text x="2" y="${H - bottom - 2}">La Niña −</text>`;
  svg.innerHTML = s;
  svg.dataset.y0 = y0;
  svg.dataset.bw = bw * 12;
}

function updateOniChart() {
  const svg = $('#oni-chart');
  const r = svg.querySelector('#oni-sel');
  const yw = Number(svg.dataset.bw);
  r.setAttribute('x', (state.year - Number(svg.dataset.y0)) * yw);
  r.setAttribute('width', yw);
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------
function buildUI() {
  // year slider
  const slider = $('#year');
  slider.min = state.years[0];
  slider.max = state.years[state.years.length - 1];
  $('#ymin').textContent = slider.min;
  $('#ymax').textContent = slider.max;
  slider.addEventListener('input', () => setYear(Number(slider.value)));

  // play
  let timer = null;
  $('#play').onclick = () => {
    if (timer) return stop();
    $('#play').textContent = '❚❚';
    $('#play').classList.add('on');
    if (state.year === state.years[state.years.length - 1]) setYear(state.years[0]);
    timer = setInterval(() => {
      const i = state.years.indexOf(state.year);
      if (i >= state.years.length - 1) return stop();
      setYear(state.years[i + 1]);
    }, 1800);
  };
  function stop() {
    clearInterval(timer);
    timer = null;
    $('#play').textContent = '▶';
    $('#play').classList.remove('on');
  }

  // ONI chart: click to jump to a year
  drawOniChart();
  $('#oni-chart').addEventListener('click', (e) => {
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const yr = Number(svg.dataset.y0) + Math.floor(p.x / Number(svg.dataset.bw));
    if (state.years.includes(yr)) setYear(yr);
  });

  // crop groups
  const box = $('#groups');
  GROUPS.forEach((g, gi) => {
    const det = document.createElement('details');
    det.className = 'group';
    const sws = g.vals.slice(0, 8).map((v) => `<i style="background:${state.classes[v][1]}"></i>`).join('');
    det.innerHTML = `<summary><input type="checkbox" ${g.on ? 'checked' : ''} aria-label="Show ${g.name}">` +
      `<span class="sws">${sws}</span><span class="nm"></span><span class="chev">▶</span></summary><ul></ul>`;
    det.querySelector('.nm').textContent = g.name;
    const ul = det.querySelector('ul');
    for (const v of g.vals) {
      const li = document.createElement('li');
      li.innerHTML = `<span class="sw" style="background:${state.classes[v][1]}"></span>`;
      li.append(state.classes[v][0]);
      ul.appendChild(li);
    }
    const cb = det.querySelector('input');
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => { GROUPS[gi].on = cb.checked; refreshCrops(); });
    box.appendChild(det);
  });

  // ecoregion toggles
  const zl = $('#zones');
  for (const [name, c] of Object.values(ZONES)) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="sw" style="background:${c}"></span>`;
    li.append(name);
    zl.appendChild(li);
  }
  $('#eco-lines').onchange = applyEcoToggles;
  $('#eco-fill').onchange = (e) => {
    applyEcoToggles();
    zl.hidden = !e.target.checked;
  };

  // precipitation
  if (!state.precip) {
    $('#precip-on').disabled = true;
    $('#precip-text').textContent = 'No data/precip.json yet: run python scripts/fetch_precipitation.py.';
  }
  $('#precip-on').onchange = (e) => {
    applyEcoToggles();
    $('#precip-opts').hidden = !e.target.checked;
  };
  $('#precip-season').onchange = (e) => {
    state.precipSeason = e.target.value;
    paintPrecip();
    if (state.point) renderPoint();
  };

  // panels
  $('#collapse').onclick = () => {
    const c = $('#panel').classList.toggle('collapsed');
    $('#collapse').textContent = c ? '+' : '–';
  };
  $('#close-point').onclick = closePoint;
  $('#point').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-year]');
    if (tr) setYear(Number(tr.dataset.year));
  });
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' && e.target.type !== 'range') return;
    if (e.key === 'Escape') closePoint();
    const i = state.years.indexOf(state.year);
    if (e.key === 'ArrowRight' && e.target !== $('#year') && i < state.years.length - 1) setYear(state.years[i + 1]);
    if (e.key === 'ArrowLeft' && e.target !== $('#year') && i > 0) setYear(state.years[i - 1]);
  });
}

function setYear(y) {
  state.year = y;
  $('#year').value = y;
  $('#year-label').textContent = y;

  const o = oniFor(y);
  const ph = phase(o.summer);
  const badge = $('#enso-badge');
  badge.textContent = o.summer == null ? 'ONI n/a' : `${ph.label} summer`;
  badge.className = 'badge ' + ph.cls;
  const w = phase(o.winter);
  $('#oni-text').innerHTML =
    `<b>${y}</b> · winter (DJF) ONI <b class="${o.winter > 0 ? 'pos' : 'neg'}">${o.winter == null ? 'n/a' : sign(o.winter)}</b> (${w.label}), ` +
    `growing season (May–Sep) ONI <b class="${o.summer > 0 ? 'pos' : 'neg'}">${o.summer == null ? 'n/a' : sign(o.summer)}</b> (${ph.label}). ` +
    `Threshold ±0.5 °C. Click the chart to jump to a year.`;
  updateOniChart();
  refreshCrops();
  paintPrecip();

  const url = new URL(location.href);
  url.searchParams.set('year', y);
  history.replaceState(null, '', url);
  if (state.point) renderPoint();
}

// ---------------------------------------------------------------------------
// Point history: what was grown here each year
// ---------------------------------------------------------------------------
async function openPoint(lngLat) {
  $('#hint').style.opacity = 0;
  const eco = map.queryRenderedFeatures(map.project(lngLat), { layers: ['eco-fill', 'precip-fill', 'eco-lines'] })[0]
    || pointInEcoregion(lngLat);
  const token = {};
  state.point = { lngLat, eco, token };
  state.history = {};
  map.getSource('pt').setData({ type: 'Point', coordinates: [lngLat.lng, lngLat.lat] });
  renderPoint();

  const geom = encodeURIComponent(JSON.stringify({ x: lngLat.lng, y: lngLat.lat, spatialReference: { wkid: 4326 } }));
  const rr = encodeURIComponent(JSON.stringify({ rasterFunction: 'annual_crop_inventory' }));
  await Promise.all(state.years.map(async (y) => {
    let val = 'error';
    try {
      const r = await fetch(`${ACI}/${y}/ImageServer/identify?geometry=${geom}&geometryType=esriGeometryPoint` +
        `&renderingRule=${rr}&returnGeometry=false&returnCatalogItems=false&f=json`);
      const j = await r.json();
      val = j.value;
    } catch (e) { /* leave as error */ }
    if (state.point?.token !== token) return; // a newer click replaced this one
    state.history[y] = val;
    renderPoint();
  }));
}

// fallback when ecoregion layers are hidden: test the point against the loaded source
function pointInEcoregion(ll) {
  const feats = map.querySourceFeatures('ecoregions');
  const inside = (ring) => {
    let c = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > ll.lat) !== (yj > ll.lat) && ll.lng < ((xj - xi) * (ll.lat - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  for (const f of feats) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    if (polys.some((p) => inside(p[0]) && !p.slice(1).some(inside))) return f;
  }
  return null;
}

function renderPoint() {
  const { lngLat, eco } = state.point;
  const el = $('#point-content');
  const p = eco?.properties;
  const head = document.createElement('div');
  const h3 = document.createElement('h3');
  h3.textContent = p ? p.name_en : 'Outside mapped ecoregions';
  const where = document.createElement('p');
  where.className = 'where';
  where.textContent = (p ? `${ZONES[p.zone][0]} ecozone · ` : '') +
    `${lngLat.lat.toFixed(4)}°, ${lngLat.lng.toFixed(4)}°`;
  head.append(h3, where);

  let rows = '';
  for (const y of state.years) {
    const v = state.history[y];
    const o = oniFor(y).summer;
    let crop;
    if (v === undefined) crop = '<span class="load">…</span>';
    else if (v === 'NoData' || v === 'error' || state.classes[v] == null) crop = '<span class="load">no data</span>';
    else crop = `<span class="sw" style="background:${state.classes[v][1]}"></span>${escapeHtml(state.classes[v][0])}`;
    const pr = p && state.precip ? precipFor(p.id, y) : null;
    const prCell = state.precip
      ? `<td class="pr ${pr && pr.pct >= 0 ? 'wet' : 'dry'}" title="${pr ? Math.round(pr.mm) + ' mm' : ''}">${pr ? pctText(pr.pct) : ''}</td>`
      : '';
    rows += `<tr data-year="${y}" class="${y === state.year ? 'cur' : ''}"><td>${y}</td><td class="crop">${crop}</td>` +
      prCell + `<td class="oni ${o > 0 ? 'pos' : 'neg'}">${o == null ? '' : sign(o)}</td></tr>`;
  }
  const prHead = state.precip ? '<th style="text-align:right">Precip†</th>' : '';
  const prNote = state.precip
    ? ` †Ecoregion ${PRECIP_SEASONS[state.precipSeason]} precipitation vs the ${state.precip.normal[0]}–${state.precip.normal[1]} average (hover for mm).`
    : '';
  el.innerHTML = '';
  el.append(head);
  el.insertAdjacentHTML('beforeend',
    `<table><thead><tr><th>Year</th><th>Crop / cover at this point</th>${prHead}<th style="text-align:right">ONI*</th></tr></thead>` +
    `<tbody>${rows}</tbody></table><p class="small">*Growing-season (May–Sep) ONI. Red = El Niño side, blue = La Niña side. Click a row to show that year.${prNote}</p>`);
  $('#point').hidden = false;
}

function closePoint() {
  state.point = null;
  $('#point').hidden = true;
  map.getSource('pt')?.setData({ type: 'FeatureCollection', features: [] });
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
