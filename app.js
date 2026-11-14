// Ecozone names and colours (ids from the National Ecological Framework)
const ZONES = {
  1: ['Arctic Cordillera', '#a9b8cf'],
  2: ['Northern Arctic', '#d3dde8'],
  3: ['Southern Arctic', '#9fcbc0'],
  4: ['Taiga Plains', '#8db37f'],
  5: ['Taiga Shield', '#c9b67a'],
  6: ['Boreal Shield', '#4e8160'],
  7: ['Atlantic Maritime', '#5aa3a8'],
  8: ['Mixedwood Plains', '#dc8a5a'],
  9: ['Boreal Plains', '#7fa856'],
  10: ['Prairies', '#e8c55a'],
  11: ['Taiga Cordillera', '#a394c2'],
  12: ['Boreal Cordillera', '#7b68a6'],
  13: ['Pacific Maritime', '#3e7fb0'],
  14: ['Montane Cordillera', '#b06a82'],
  15: ['Hudson Plains', '#6a9f8a'],
};

// Legend
const list = document.getElementById('zones');
for (const [name, color] of Object.values(ZONES)) {
  const li = document.createElement('li');
  li.innerHTML = `<span style="background:${color}"></span>`;
  li.append(name);
  list.appendChild(li);
}

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/positron',
  center: [-96, 62],
  zoom: 2.6,
  attributionControl: { compact: true, customAttribution: 'Ecoregions © AAFC (OGL-Canada)' },
});
map.addControl(new maplibregl.NavigationControl(), 'bottom-right');

map.on('load', () => {
  map.addSource('ecoregions', {
    type: 'geojson',
    data: 'data/ecoregions.min.geojson',
    promoteId: 'id',
  });

  const colorByZone = ['match', ['get', 'zone']];
  for (const [id, [, color]] of Object.entries(ZONES)) colorByZone.push(Number(id), color);
  colorByZone.push('#999');

  // put polygons under the basemap's place labels
  const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;

  map.addLayer({
    id: 'ecoregions-fill',
    type: 'fill',
    source: 'ecoregions',
    paint: {
      'fill-color': colorByZone,
      'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.9, 0.65],
    },
  }, firstLabel);

  map.addLayer({
    id: 'ecoregions-line',
    type: 'line',
    source: 'ecoregions',
    paint: { 'line-color': '#fff', 'line-width': 0.7 },
  }, firstLabel);

  // hover highlight
  let hovered = null;
  map.on('mousemove', 'ecoregions-fill', (e) => {
    const id = e.features[0].id;
    if (id === hovered) return;
    if (hovered !== null) map.setFeatureState({ source: 'ecoregions', id: hovered }, { hover: false });
    hovered = id;
    map.setFeatureState({ source: 'ecoregions', id }, { hover: true });
    map.getCanvas().style.cursor = 'pointer';
  });
  map.on('mouseleave', 'ecoregions-fill', () => {
    if (hovered !== null) map.setFeatureState({ source: 'ecoregions', id: hovered }, { hover: false });
    hovered = null;
    map.getCanvas().style.cursor = '';
  });

  // click popup
  map.on('click', 'ecoregions-fill', (e) => {
    const p = e.features[0].properties;
    const el = document.createElement('div');
    const b = document.createElement('b');
    b.textContent = p.name_en;
    const fr = document.createElement('small');
    fr.textContent = p.name_fr;
    const info = document.createElement('div');
    info.textContent = `${ZONES[p.zone][0]} ecozone · ≈${Number(p.area_km2).toLocaleString('en-CA')} km²`;
    el.append(b, fr, info);
    new maplibregl.Popup({ maxWidth: '260px' }).setLngLat(e.lngLat).setDOMContent(el).addTo(map);
  });
});
