# Oscillation Nation: map layers and data pipeline

Product overview: [client/README.md](../client/README.md). This file documents the map layers, the data
pipeline and the data caveats.

**Layout.** The web app and every file it loads live in `client/` (data in `client/data/`); the scripts that
build them are in `pipeline/`; downloads and caches go in git-ignored `raw/` folders (`data/raw/` locally).

> **Path note (after the `client/` + `pipeline/` move):** most pipeline scripts still use `ROOT / "data"`,
> so they write to `data/` at the repo root while the app reads `client/data/`. Copy their outputs into
> `client/data/` or update those paths before re-running them.

## Map layers (client/)

- **Monthly El Niño timeline.** A slider over every month from Jan 1981 to Dec 2025, with the ONI chart and a strip underneath coloured by phase: red = El Niño, green = neutral, blue = La Niña. A month counts as El Niño / La Niña when it is part of a run of at least 5 overlapping seasons beyond ±0.5 °C (NOAA's definition).
- **Datasets, each with its own checkbox** and all averaged per ecodistrict:
  - *NASA POWER climate* – 15 monthly variables (temperature, precipitation, snow, humidity, solar, wind, evapotranspiration, soil wetness, frost days), as the monthly value or the difference from the 1991–2020 normal.
  - *Soil* – water holding capacity, texture, organic carbon, pH, drainage and dominant soil order from the Soil Landscapes of Canada (farmland only).
  - *AAFC crops planted* – bubbles sized by the share of land in crops for the slider's year, coloured by the largest crop group.
  - *Crop yield* – estimated yield (kg/ha) per ecodistrict for the slider's year, for 15 major field crops, shown as the raw value *or* as the % above/below that ecodistrict's own long-term average.
  - *Irrigation water use* – cubic metres of irrigation water applied, for the growing-season period the slider's month falls in, mapped either **by province** or **by drainage basin** (a finer, sub-provincial watershed cut — e.g. isolating the South Saskatchewan). Shown as the raw volume *or* as the % above/below each area's own survey-period average for that season. Surveyed every second year, 2010–2024. A Canada-wide split of that water by crop type rides along in the panel.
  - *Ecodistrict boundaries.*
- **Places like yours** (right panel). Pick your ecodistrict (type it or click the map). For the slider's month it lists the 10 ecodistricts whose conditions in the same calendar month of another year were most similar, using every climate variable plus soil, and highlights them on the map.

### Factors already on the map

Everything a user can currently see or select, grouped by map layer. This is the "already done" list — add new factors as new entries here (and as new layers/variables in `client/index.html`, `client/app.js`, and the data pipeline).

**El Niño timeline** (always on, top-left panel)
- [x] Oceanic Niño Index (ONI) value per month, Jan 1981 – Dec 2025
- [x] ENSO phase strip (El Niño / Neutral / La Niña, NOAA's ≥5-season rule)

**NASA POWER climate** (`lyr-climate`) — 15 monthly variables, shown as the raw value *or* the anomaly vs the 1991–2020 normal:
- [x] Mean temperature (`T2M`, °C)
- [x] Max temperature (`T2M_MAX`, °C)
- [x] Min temperature (`T2M_MIN`, °C)
- [x] Dew point (`T2MDEW`, °C)
- [x] Precipitation (`PRECIP`, mm)
- [x] Snowfall, water equiv. (`SNOWFALL`, mm)
- [x] Snow depth (`SNODP`, cm)
- [x] Relative humidity (`RH2M`, %)
- [x] Solar radiation (`SOLAR`, MJ/m²/day)
- [x] Wind speed (`WS2M`, m/s)
- [x] Evapotranspiration (`ET`, mm)
- [x] Surface soil wetness (`GWETTOP`, 0–1)
- [x] Root-zone soil wetness (`GWETROOT`, 0–1)
- [x] Profile soil wetness (`GWETPROF`, 0–1)
- [x] Frost days (`FROST_DAYS`, days)

**Soil** (`lyr-soil`, farmland ecodistricts only) — 8 properties from the Soil Landscapes of Canada:
- [x] Available water holding capacity, 0–100 cm (`awhc`, mm)
- [x] Sand, 0–30 cm (`sand`, %)
- [x] Silt, 0–30 cm (`silt`, %)
- [x] Clay, 0–30 cm (`clay`, %)
- [x] Organic carbon, 0–30 cm (`oc`, %)
- [x] pH (CaCl₂), 0–30 cm (`ph`)
- [x] Drainage class, 1 very rapid – 7 very poor (`drainage`)
- [x] Dominant soil order (`order`, categorical)

**AAFC crops planted** (`lyr-crops`)
- [x] Share of land in crops for the slider's year (bubble size)
- [x] Largest crop group for that year (bubble colour)

**Crop yield** (`lyr-yield`) — estimated yield per ecodistrict (kg/ha), averaged across the Soil Landscape polygons, for the slider's year. Three views: the raw value; the % difference from that ecodistrict's own long-term average; or **Seeded area vs result** — a bivariate map crossing how much was seeded in the region (pale → saturated) with yield vs the ecodistrict's own average (red below, green above), so you can spot where a lot was planted but it yielded poorly, and the reverse. 15 major field crops:
- [x] Spring wheat (`WHTSPG`), Durum wheat (`WHTDUR`), Winter wheat (`WHTWINT`)
- [x] Barley (`BARLEY`), Oats (`OATS`)
- [x] Canola (`CANOLA`), Flaxseed (`FLAXSD`), Sunflower seed (`SUNFLS`)
- [x] Soybeans (`SOYBNS`), Grain corn (`CORNGR`)
- [x] Dry peas (`DFPEAS`), Lentils (`LENTIL`)
- [x] Potatoes (`POTATS`)
- [x] Hay & fodder (`OHAYFD`), Alfalfa (`ALFALFA`)

**Financial effect of weather** (`lyr-finance`, province-level) — what the weather cost, from StatCan direct payments to producers joined to observed yields and growing-season weather. Province-year, 2007–2025:
- [x] Crop Insurance gross payments (`crop_ins`, $k nominal)
- [x] Private hail insurance (`hail`), AgriRecovery (`agrirecovery`), Crop Loss Compensation (`crop_loss`)
- [x] All weather-driven programs combined (`weather_prog` = the four above)
- [x] AgriStability (`agristability`) and Provincial Stabilization (`prov_stab`), for contrast — margin-based, they do *not* track yield
- [x] Total direct payments (`total`)
- [x] Two-year claim window (`*_2y` = calendar year *t* + *t+1*), because crop-year claims are largely paid the following calendar year
- [x] Payment anomaly (`*_anom`, % vs that province's own log-linear trend — strips inflation and the growth in insured liability)
- [x] Observed yield anomaly (`yield_pct`, % vs trend, from Census Agricultural Region yields)
- [x] Dollar sensitivity per province (`sensitivity_m_per_yield_point`): $M of weather-program payments per percentage point of yield shortfall

**Base layer**
- [x] Ecodistrict boundaries (`lyr-lines`)

### Data pipeline

All outputs live in `data/`; downloads and caches go to `data/raw/` (git-ignored). Run in this order:

```bash
python pipeline/fetch_data.py            # ONI + crop class table
python pipeline/fetch_forecast.py        # extend climate past POWER (ERA5) + ECMWF seasonal forecast and ONI forecast via Meteomatics (needs METEOMATICS_USER / METEOMATICS_PASSWORD in .env)
python pipeline/build_ecodistricts.py    # ecodistrict boundaries + sample points
python pipeline/fetch_power.py           # NASA POWER monthly climate -> data/climate/*.bin (~20 min first time)
python pipeline/fetch_soil.py            # Soil Landscapes of Canada -> data/raw/soil.json (needs `pip install dbfread`)
python pipeline/fetch_crops.py           # AAFC crop inventory per ecodistrict and year -> data/raw/crops.json (~25 min)
python pipeline/build_client_data.py     # merges boundaries, soil and crops -> data/ecodistricts.json
python pipeline/build_yield.py           # SLC crop-yield CSV -> data/yield.json (per ecodistrict/year/crop)
python pipeline/similarity.py            # precomputed matches -> data/similarity/<id>.bin (needs numpy)
python pipeline/build_finance.py         # payments + yields + weather -> data/finance.json
bash   pipeline/build_drainage.sh        # StatCan drainage regions -> data/drainage.min.geojson (needs npx mapshaper)
python pipeline/build_irrigation.py      # StatCan irrigation volume by province + basin + crop -> data/irrigation.json
```

| File sent to the browser | What it holds |
| --- | --- |
| `client/data/ecodistricts.min.geojson` | simplified ecodistrict polygons |
| `client/data/ecodistricts.json` | per ecodistrict: names, label point, soil, crops by year |
| `client/data/yield.json` | per ecodistrict: estimated yield (kg/ha) by crop and year, for 15 major field crops |
| `client/data/climate/<VAR>.bin` + `meta.json` | Int16 `[ecodistrict][month]` per climate variable, loaded when picked |
| `client/data/similarity/<id>.bin` + `meta.json` | top 10 matches per month for one ecodistrict, loaded when picked |
| `client/data/oni.json` | NOAA Oceanic Niño Index |
| `client/data/oni_forecast.json` | forecast ONI seasons from ECMWF seasonal sea-surface temperature (`fetch_forecast.py`) |
| `client/data/finance.json` | per province/year: direct payments by program, observed yield anomaly, growing-season weather anomaly, ENSO phase, and the $/yield-point sensitivity |
| `client/data/irrigation.json` | irrigation volume (m³) by season period, for each province, each drainage basin, and Canada-by-crop, per survey year |
| `client/data/drainage.min.geojson` | simplified StatCan drainage-basin polygons (13 units, feature id = basin key) for the basin geography |

`build_finance.py` additionally needs two files in `data/`: `financials.csv` (StatCan
32-10-0106, all geographies, long format) and `historical_actual_crop_yield_by_CAR.csv`
(observed yields by Census Agricultural Region).

### Data quality notes

- **`data/historicalEstimatedCropYieldSlc.csv`: the 2024 rows are a copy of 2021.** Spring
  wheat, durum, peas, lentils, hay, soybeans, grain corn and potatoes are identical to
  2021 for all 3,390 soil-landscape polygons, and barley/oats/canola for ~56% of them;
  every other adjacent year pair shares 0%. Exclude 2024 from anything built on this file
  until it is re-pulled. `build_yield.py` should filter it out of `yield.json` too.
- These are *estimated* (modelled) yields. The money layer therefore uses the **observed**
  CAR yields instead, so that weather → yield → payment is not partly circular.
- **`farmcashreceipts.csv` stops at 2015 Q1**, so it cannot normalise payments across the
  2007–2025 window. Re-pull it if you want payments as a share of farm receipts.
- Payments are **nominal** dollars. `*_anom` fields handle this by detrending in logs;
  if you want real dollars, add a CPI series rather than comparing levels across years.

**Similarity method (kept simple for now).** Each ecodistrict-month is a vector of the 15 climate values plus 5 soil properties, z-scored (climate within each calendar month) and weighted (weights in `pipeline/similarity.py`). Candidates are the same calendar month in a *different* year, in another ecodistrict; each ecodistrict's best year is kept. Score = 100·exp(−2d²/Σw): 100 is identical and a random pair scores about 2. Only farmland ecodistricts (those with soil survey data) are included.