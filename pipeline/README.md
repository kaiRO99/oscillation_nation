# Oscillation Nation: map layers and data pipeline

Product overview: [README.md](../README.md). This file documents the map layers, the data
pipeline and the data caveats.

**Layout.** The web app and every file it loads live at the repo root (data in `data/`); the scripts that
build them are in `pipeline/`; downloads and caches go in git-ignored `raw/` folders (`data/raw/` locally).

## Map layers

- **Monthly El Niño timeline.** A slider over every month from Jan 1981 to Dec 2025, with the ONI chart and a strip underneath coloured by phase: red = El Niño, green = neutral, blue = La Niña. A month counts as El Niño / La Niña when it is part of a run of at least 5 overlapping seasons beyond ±0.5 °C (NOAA's definition).
- **Datasets, each with its own checkbox** and all averaged per ecodistrict. **Temperature** and **Precipitation** sit at the top with their pickers always visible, plus one **Difference from 1991–2020 normal** switch for every monthly variable; everything else is under a collapsed **Advanced** section (its header counts the layers switched on inside it):
  - *Temperature* / *Precipitation* / *Other climate* (Advanced) – NASA POWER monthly climate. The three share one map fill, so switching one on (or picking in it) switches the others off. In forecast months the tooltip, the selected-ecodistrict panel and the comparison report give an **80% range** for temperature and precipitation (see *Forecast ranges* below).
  - *Soil* (Advanced) – one picker for monthly soil moisture (NASA POWER, follows the timeline) and the fixed soil properties: water holding capacity, texture, organic carbon, pH, drainage and dominant soil order from the Soil Landscapes of Canada (farmland only).
  - *AAFC crops planted* – bubbles sized by the share of land in crops for the slider's year, coloured by the largest crop group.
  - *Crop yield* – estimated yield (kg/ha) per ecodistrict for the slider's year, for 15 major field crops, shown as the raw value, as the % above/below that ecodistrict's own long-term average, or crossed with seeded area. Non-farm ecodistricts are left blank and places where the crop is barely grown are faded (see below).
  - *Seeded area* – hectares of a crop actually planted, by Census Agricultural Region, for the slider's year.
  - *Irrigation water use* – cubic metres of irrigation water applied, for the growing-season period the slider's month falls in, mapped either **by province** or **by drainage basin** (a finer, sub-provincial watershed cut — e.g. isolating the South Saskatchewan). Shown as the raw volume *or* as the % above/below each area's own survey-period average for that season. Surveyed every second year, 2010–2024. A Canada-wide split of that water by crop type rides along in the panel.
  - *Ecodistrict boundaries.*
- **Places like yours** (right panel). Pick your ecodistrict (type it or click the map). For the slider's month it lists the 10 ecodistricts whose conditions in the same calendar month of another year were most similar, using every climate variable plus soil, and highlights them on the map.

### Factors already on the map

Everything a user can currently see or select, grouped by map layer. This is the "already done" list — add new factors as new entries here (and as new layers/variables in `index.html`, `app.js`, and the data pipeline).

**El Niño timeline** (always on, top-left panel)
- [x] Oceanic Niño Index (ONI) value per month, Jan 1981 – Dec 2025
- [x] ENSO phase strip (El Niño / Neutral / La Niña, NOAA's ≥5-season rule)

**Climate** — monthly variables, each shown as the raw value *or* (one shared switch, `climate-anom`) the anomaly vs the 1991–2020 normal. Three pickers draw into one map fill; only one is on at a time. `?v=<key>` opens the map on a variable.

*Temperature* (`lyr-temp`, top of the panel):
- [x] Mean (`T2M`, °C)
- [x] Hottest of the month (`T2M_MAX`, °C; the month's single warmest reading, not the average daily high)
- [x] Coldest of the month (`T2M_MIN`, °C)
- [x] Frost days (`FROST_DAYS`, days)

*Precipitation* (`lyr-precip`, top of the panel):
- [x] Total (`PRECIP`, mm)
- [x] Average per day (`PRECIP_DAILY`, mm/day; total ÷ days in the month, computed in the browser. Same map pattern as the total within a month; it only matters when comparing months of different length)
- [x] Wet days, ≥ 1 mm of rain or melted snow (`WET_DAYS`, days; NASA POWER **daily**, `build_wet_days.py`)
- [x] Average per wet day (`WET_DAY_PRECIP`, mm; precipitation *on* wet days ÷ wet days, the "simple daily intensity index". Not the month's total ÷ wet days: drizzle on days under 1 mm is ~9% of the total (median), which would inflate it)
- Wet days and per-wet-day: farmland ecodistricts only (the 454 that `fetch_power_daily.py` covers), observed months only (no forecast: counting wet days in an ensemble *mean* would count its drizzle). Counts are averaged over an ecodistrict's sample points, so they can be fractional. Spot-checked: annual totals and seasonality are right (Abbotsford wet winters, Regina's June peak), and wet-day counts run high, with less on each day, as reanalysis does relative to a rain gauge.

*Other climate* (`lyr-other`, Advanced): dew point (`T2MDEW`), snowfall water equiv. (`SNOWFALL`), snow depth (`SNODP`), relative humidity (`RH2M`), solar radiation (`SOLAR`), wind speed (`WS2M`), evapotranspiration (`ET`).

**Forecast ranges** (`climate-range.js`, shared by the map and the report) — in forecast months, an 80% range for mean / hottest / coldest temperature, frost days, and total / per-day precipitation:
- [x] Tooltip, selected-ecodistrict panel and comparison report; the map itself shows the middle estimate, tagged *forecast*
- Method: the forecast is ECMWF's ensemble **mean** only (no members, no re-forecasts), so the forecast's skill can't be measured. The range is the forecast plus the 10th–90th percentile of how far that calendar month has strayed in that ecodistrict over the observed record (temperatures, frost days: departures from the ecodistrict's own linear trend; precipitation: the month's total ÷ its mean, so the range is skewed and stays above zero). It gives the forecast no credit for skill, and it can't allow for the forecast itself being off.
- Checked: the browser's ranges match an independent numpy computation exactly (Regina, Jan 2027).
- Caveat on the current forecast (issued 2026-11-14): its Nov–Feb precipitation is unusually dry for an ensemble mean (median farmland ecodistrict 55–68% of normal; 33–43% of them under half of normal, a level only 11% of observed months reach). The ERA5 → POWER correction is not the cause (Oct 2026 corrected ERA5 is 93% of POWER daily). More likely the seasonal model's own drift, which `fetch_forecast.py` doesn't remove (no re-forecasts), or a real El Niño signal. The ranges inherit whatever bias the centre has.

**Soil** (`lyr-soil`, Advanced) — one picker:
- [x] Soil moisture, monthly from NASA POWER, following the timeline (`GWETTOP` surface, `GWETROOT` root zone, `GWETPROF` profile; 0–1; no forecast)

and 8 fixed properties from the Soil Landscapes of Canada (farmland ecodistricts only):
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

Where a yield is drawn (the source gives *every* Soil Landscape polygon a yield, farmed or not, so the Nass Basin "has" a wheat yield):
- [x] **Not drawn** where the ecodistrict isn't farmland: crops + pasture/forage under 1% of its land at its peak year in the AAFC crop inventory (2009–2025), or no inventory record (only agricultural ecodistricts were fetched). Removes 64 of 394.
- [x] **Faded** where the crop's inventory group (cereals, oilseeds, soybeans, corn, pulses, vegetables, pasture/forage) is under 0.25% of the land; where the province seeded under 1,000 ha of that crop that year, or published no figure (StatCan 32-10-0359); or where the region's *published* seeded area that year was under 5% of its own peak (StatCan 32-10-0002). A missing regional figure is treated as unknown, not zero.
- [x] Resolution is stated per crop: wheat (all three), peas and lentils are one value per Census Agricultural Region; sunflower, potatoes and hay one value per province; barley, oats, canola, flax, soybeans, corn and alfalfa vary within regions (`res` in `yield.json`, measured by `build_yield.py`).
- [x] The last year is 2023 for every crop except alfalfa: the source's 2024 rows copy 2021 and are dropped (see Data quality notes).
- Limits: the crop inventory's groups can't separate, e.g., durum from barley, or grain from silage corn; the province check catches the big cases (no durum or lentils shown in Ontario/Quebec), but within a province a crop can still be drawn in an ecodistrict that only grows its cousin.

**Seeded area** (`lyr-seeded`) — hectares planted per crop and year, by Small Area Data Region / Census Agricultural Region (StatCan 32-10-0002). Every ecodistrict shows its whole region's total. The ecodistrict → region link is **per year**, because regions were redrawn: Saskatchewan's 20 regions became 17 census-division regions in 2017 (kept as separate series, not spliced), Quebec was renumbered in 1993, 1998 and 2003. Coverage: Prairies and Ontario 1976–2025, BC 1991–2025, Quebec 2007–2025, nothing for Atlantic Canada. 12 crops (no potatoes, hay or alfalfa). Blank means StatCan published no figure (`..` not available, `F` unreliable, `x` confidential), not zero. Also the "effort" axis of the yield layer's **Seeded area vs result** view.

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

**Crop yield forecast** (part of `lyr-yield`; `yield-forecast.js`) — when the timeline reaches the
forecast season (2027; Jan–May 2027 are the forecast months on the slider), the Crop yield layer shows next
season's forecast, tagged *forecast* like the climate forecast. One figure per Census Agricultural Region,
for the 12 crops with observed regional yields. Method and accuracy: *Yield forecast* below.
- [x] Map: middle estimate (kg/ha, same colour scale as the recorded years) or % vs a normal year
- [x] Tooltip: middle estimate, 80% range, % vs a normal year, chance below normal, region
- [x] Selected ecodistrict: 80% and 95% ranges, normal year, chance below normal and of a ≥20% shortfall (vs usual), last-5-year average, and a chart of the ranges forecast before each season 2001–2025 vs what happened
- [x] Info popovers: what moves the season (fall soil moisture, ECMWF Oct–May precipitation, El Niño), closest past El Niño seasons, warming sensitivity (+1 / +2 °C), per-crop track record
- [x] Says why when there is no forecast: not farmland; no regional statistics (Atlantic Canada); StatCan doesn't publish the crop for the region (no wheat or canola for Ontario / Quebec regions); too little grown

**Base layer**
- [x] Ecodistrict boundaries (`lyr-lines`)

### Data pipeline

The app loads `data/`; downloads and caches go to `data/raw/` (git-ignored). Run in this order:

```bash
python pipeline/fetch_data.py            # ONI + crop class table
python pipeline/fetch_forecast.py        # extend climate past POWER (ERA5) + ECMWF seasonal forecast and ONI forecast via Meteomatics (needs METEOMATICS_USER / METEOMATICS_PASSWORD in .env)
python pipeline/build_ecodistricts.py    # ecodistrict boundaries + sample points
python pipeline/fetch_power.py           # NASA POWER monthly climate -> data/climate/*.bin (~20 min first time)
python pipeline/fetch_soil.py            # Soil Landscapes of Canada -> data/raw/soil.json (needs `pip install dbfread`)
python pipeline/fetch_crops.py           # AAFC crop inventory per ecodistrict and year -> data/raw/crops.json (~25 min)
python pipeline/build_client_data.py     # merges boundaries, soil and crops -> data/ecodistricts.json
python pipeline/build_yield.py           # SLC crop-yield CSV -> data/yield.json (per ecodistrict/year/crop; needs numpy)
python pipeline/build_seeded.py          # StatCan seeded area by region + province -> data/seeded.json (downloads both tables)
python pipeline/fetch_power_daily.py     # daily NASA POWER for farmland ecodistricts -> data/raw/power_daily_indices.npz (heat degree-days, dry spells, downpours, frost, wet days; ~20 min first time at the default 60 requests/min, then only the current year; ~3 min from cache)
python pipeline/build_wet_days.py        # wet days + precipitation per wet day -> data/climate/WET_DAYS.bin, WET_DAY_PRECIP.bin (run after fetch_power.py and fetch_forecast.py: fetch_power.py rewrites meta.json without them)
python pipeline/build_yield_forecast.py  # next-season yield forecast -> data/yield_forecast.json (needs numpy; ~1 min; run after fetch_forecast.py; --compare re-scores model forms)
python pipeline/evaluate_yield_forecast.py  # walk-forward accuracy test of that forecast (~1 min)
python pipeline/similarity.py            # precomputed matches -> data/similarity/<id>.bin (needs numpy)
python pipeline/build_finance.py         # payments + yields + weather -> data/finance.json
bash   pipeline/build_drainage.sh        # StatCan drainage regions -> data/drainage.min.geojson (needs npx mapshaper)
python pipeline/build_irrigation.py      # StatCan irrigation volume by province + basin + crop -> data/irrigation.json
```

| File sent to the browser | What it holds |
| --- | --- |
| `data/ecodistricts.min.geojson` | simplified ecodistrict polygons |
| `data/ecodistricts.json` | per ecodistrict: names, label point, soil, crops by year |
| `data/yield.json` | per ecodistrict: estimated yield (kg/ha) by crop and year, for 15 major field crops; per crop: resolution (`res`), last real year (`last`), dropped copied years (`dropped`), and single-crop repeats kept but flagged (`suspect`) |
| `data/seeded.json` | per region series: hectares seeded by crop and year (12 crops); ecodistrict → region links as runs of years; province totals per crop and year |
| `data/climate/<VAR>.bin` + `meta.json` | Int16 `[ecodistrict][month]` per climate variable, loaded when picked; `WET_DAYS` / `WET_DAY_PRECIP` (from daily data, `coverage: "farmland"`) come from `build_wet_days.py` |
| `data/similarity/<id>.bin` + `meta.json` | top 10 matches per month for one ecodistrict, loaded when picked |
| `data/oni.json` | NOAA Oceanic Niño Index |
| `data/oni_forecast.json` | forecast ONI seasons from ECMWF seasonal sea-surface temperature (`fetch_forecast.py`) |
| `data/finance.json` | per province/year: direct payments by program, observed yield anomaly, growing-season weather anomaly, ENSO phase, and the $/yield-point sensitivity |
| `data/irrigation.json` | irrigation volume (m³) by season period, for each province, each drainage basin, and Canada-by-crop, per survey year |
| `data/drainage.min.geojson` | simplified StatCan drainage-basin polygons (13 units, feature id = basin key) for the basin geography |
| `data/yield_forecast.json` | next-season outlook per crop and region: quantiles (2.5–97.5%) with and without El Niño weighting, normal year, chance below normal / of a ≥20% shortfall, warming scenarios, per-analog effects; hindcasts 2001–2025 per region; skill per crop (incl. `r2_weather`, the share of the swing the known summer explains); the weather model used (`weather_model`); ecodistrict → region; the ENSO input used |

`data/enso_forecast.json` is a hand-maintained **input** to `build_yield_forecast.py`: NOAA CPC's RONI
outlook (5/50/95 percentiles and strength probabilities per season). CPC updates it on the second
Thursday of each month; copy the new numbers from the
[outlook](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/outlook/) and
[strength](https://cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/strengths/) pages, set
`issued` / `target_year`, and re-run the script. The RONI history it needs is downloaded to `data/raw/enso/`.

`build_finance.py` additionally needs two files in `data/`: `financials.csv` (StatCan
32-10-0106, all geographies, long format) and `historical_actual_crop_yield_by_CAR.csv`
(observed yields by Census Agricultural Region).

`build_yield.py` and `build_seeded.py` read the 47 MB SLC yield CSV from `data/raw/` (git-ignored; it
was removed from the repo). Recover it with
`git show 43d0c3e:data/historicalEstimatedCropYieldSlc.csv > data/raw/historicalEstimatedCropYieldSlc.csv`.

### Data quality notes

- **`historicalEstimatedCropYieldSlc.csv`: the 2024 rows are a copy of 2021.** Spring
  wheat, durum, peas, lentils, hay, soybeans, grain corn and potatoes are identical to
  2021 for all 3,390 soil-landscape polygons, and barley/oats/canola for ~56% of them;
  every other adjacent year pair shares 0%. Exclude 2024 from anything built on this file
  until it is re-pulled. `build_yield.py` now detects this (a year is dropped when at least half
  its polygons repeat the same earlier year for at least half the crops) and nulls 2024 for 14 crops;
  alfalfa's 2024 is genuine and kept. Peas, lentils and sunflower also repeat earlier years in single
  crops (listed under `suspect` in `yield.json`); those are kept, since one provincial figure covers
  most of their polygons and can match an earlier year by chance.
- **The SLC yields are not local for most crops.** The source downscales provincial / regional
  statistics to every polygon, farmed or not; wheat, peas and lentils are one figure per Census
  Agricultural Region, sunflower, potatoes and hay one per province. Treat the yield map as regional
  for those crops, and don't read a yield in a non-farm ecodistrict as real (the map hides those).
- **"Difference from average" compares with the ecodistrict's 1971–2023 mean, which is not
  detrended.** Yields rose steadily, so 87–93% of recent ecodistrict-years are "above average" and
  only 10–33% of 1980s years; against each ecodistrict's own linear trend it is ~45–65% both ways.
  Comparing an El Niño year in the 1980s with one in the 2010s mostly shows the trend.
- These are *estimated* (modelled) yields. The money layer therefore uses the **observed**
  CAR yields instead, so that weather → yield → payment is not partly circular.
- **`farmcashreceipts.csv` stops at 2015 Q1**, so it cannot normalise payments across the
  2007–2025 window. Re-pull it if you want payments as a share of farm receipts.
- Payments are **nominal** dollars. `*_anom` fields handle this by detrending in logs;
  if you want real dollars, add a CPI series rather than comparing levels across years.

### Yield forecast: method and accuracy

Full detail in the docstring of `pipeline/build_yield_forecast.py`. Run it after `fetch_forecast.py`, so it
sees the latest observed months and the ECMWF seasonal forecast. In short, per crop:

1. **Target: observed yields**, StatCan 32-10-0002 by Small Area Data Region (Census Agricultural
   Region), 1981–2025, region-years seeded ≥ 1,000 ha. Not the SLC yields: those are modelled from the
   same regional statistics, so they add nothing below the region and would make a weather model
   partly circular. Saskatchewan's post-2017 regions are separate series that borrow the province's trend.
2. **Weather → yield.** log yield = region level + technology trend + weather effect. The trend is linear
   with year weights halving every 15 years. Weather is *not* detrended, so warming acts through
   temperature rather than hiding in the trend. Only NASA POWER (observed) months train the model.
   - *Weather columns* (cropland-weighted per region): growing-season mean daily high and root-zone soil
     wetness (anomalies vs 1991–2020, monthly data), plus from **daily** data (`fetch_power_daily.py`)
     heat degree-days above 30 °C, the longest dry spell, the wettest 5 days and killing-frost days.
     Grain corn keeps only the first two (see the experiments below).
   - *Weather effect* = half **regression** (crop-wide response plus a shrunk provincial deviation, with
     curvature: heat and drought hurt non-linearly and together) and half **conditions-based analogs**:
     the 80 region-years, from *any* region, whose summer (daily highs and soil wetness vs normal) and
     location (normal heat, wetness and rain) were most similar, and how far *their* yields fell from
     *their own* normal. Anomalies, not kg/ha, travel between places: soil, management and irrigation
     make a similar summer worth different yields in different places.
3. **Possible summers.** Every past observed summer (1981–2026) is a possible summer for the coming year.
   - *Climate change:* its temperature is moved onto today's climate along the region's own warming
     trend, and its heat degree-days are re-read at a threshold lowered by the same warming (above 30 °C
     in a season 1 °C warmer = above 29 °C as it was; the daily file stores 26–33 °C). The +1 °C / +2 °C
     scenarios add warming on top (a sensitivity, not a projection; values beyond the observed range are
     clipped, so they *understate* unprecedented heat).
   - *Starting conditions* (from `fetch_forecast.py`'s data): its soil moisture is moved onto this
     season's starting point. The **observed Aug–Sep root-zone wetness** of the year before replaces
     the analog's own, via a per-province regression of summer soil moisture on it. The **Oct–May
     precipitation** (ERA5 for October, the **ECMWF seasonal forecast** for Nov–May) only shifts the
     centre and keeps every analog's spread, because the forecast's skill is unknown (we only have its
     ensemble mean and no re-forecasts). Shifted soil moisture is clipped to the training range.
4. **El Niño.** Past seasons are weighted by how close their winter (DJF) and summer (JJA) RONI were
   to CPC's forecast, blended with equal weights (blend and kernel width picked by hindcast; currently
   25% kernel). ECMWF's own Niño 3.4 forecast (`oni_forecast.json`) is used as a sensitivity check, not
   instead of CPC: CPC's outlook already blends dynamical models including ECMWF, gives a spread and
   covers the summer, which the ECMWF file does not.
5. **Confidence.** Ranges come from the weighted ensemble plus the unexplained spread, then widened or
   narrowed symmetrically so that, in forward-chaining hindcasts (fit on years before *t*, forecast *t*
   with only what was known in November, 2001–2025), the 80% range held 80% of outcomes and the 95%
   range 95%. Only the spread is calibrated, not the centre.

What the hindcasts showed (build of 2026-11-15; reprinted on every run, `--compare` for the variants):

| Check | Result |
| --- | --- |
| Out-of-sample coverage, 80% / 95% ranges | 78.4–80.5% / 93.4–95.1% across the 12 crops |
| vs a naive "last 5 years' average" forecast (CRPS) | better for **all 12 crops**: +1.5% lentils, +2.2% soybeans, +5–9% canola, oats, flax, barley, corn, peas, sunflower, +10–11% the wheats |
| Share of the year-to-year swing the summer's weather explains, if known (out of sample) | **26%** all crops (was 17% with the two monthly columns): spring wheat 34%, durum 31%, peas 36%, barley 26%, lentils 26%, canola 25%, oats 23%, flax 22%, winter wheat 10%; ~0 for soybeans, sunflower and grain corn |
| Trend form | recency-weighted linear beat plain linear by 1.8% and a post-2000 hinge by 5.5% |
| Observed fall soil moisture as a starting condition | **+1.2% CRPS** on top of that (+2.9% vs the plain linear model); better for 10 crops, winter wheat unchanged, grain corn slightly worse |
| Oct–May precipitation if it were known perfectly (upper bound) | a further +2.4%: what a skilful winter–spring forecast could add at most |
| Value of El Niño weighting, all crops (CRPS) | **+0.06%, 90% CI −0.3 to +0.5%**: not distinguishable from zero once soil state is in |
| Direct ENSO term in the yield regression | no gain (−0.1%); left out |
| Recent drift (share of 2017–2025 outcomes below the middle estimate) | ~46–53% for spring wheat, barley, oats, soybeans, peas; 57–59% durum and flax; **60–70% for winter wheat, canola, lentils, grain corn** (middle estimate optimistic lately); 26% for sunflower |

**Accuracy on the walk-forward test** (`evaluate_yield_forecast.py`): every year 2001–2025 re-forecast from
earlier years only, with what was known the November before, and scored against StatCan's recorded regional
yield; 7,432 region-crop-years.

| | All crops | Spring wheat | Durum | Canola | Barley | Grain corn | Soybeans | Lentils |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Typical miss of the middle estimate (median) | 14.4% (was 14.5%) | 11.8% (12.2%) | 15.1% (16.7%) | 16.4% (15.9%) | 12.9% (12.7%) | 6.2% (6.3%) | 9.3% (9.4%) | 26.2% (28.4%) |
| Same for "last 5 years' average" | 15.9% | 14.2% | 18.1% | 15.9% | 14.4% | 6.9% | 9.9% | 24.3% |
| Within 10% / within 20% of actual | 37% / 64% | 42% / 72% | 36% / 59% | 35% / 59% | 40% / 71% | 67% / 94% | 53% / 81% | 19% / 39% |
| 80% / 95% range held the actual yield | 78–81% / 93–95% (every crop) | | | | | | | |
| Calls above vs below normal (correlation; Brier skill) | 0.22; +1.4% | 0.30; +2.3% | 0.24; +3.1% | 0.20; +0.9% | 0.24; +0.9% | −0.01; +0.1% | 0.00; −0.1% | 0.28; +4.0% |
| Typical miss if the summer weather were known | 12.9% (was 13.9%) | 10.8% | 14.3% | 14.7% | 11.3% | 7.1% | 8.1% | 21.2% |

**In El Niño seasons** (`evaluate_yield_forecast.py` prints this split; phase by the winter before the
season, DJF RONI). The standard test has only 3 strong El Niño winters, so `--from 1991` also re-forecasts
1991–2000 (from 10–19 training years; compare phases within that run):

| 1991–2025 test | Seasons | Typical miss | "Last 5 years" rule | 80% / 95% range held | Actual vs middle (median) |
| --- | --- | --- | --- | --- | --- |
| Strong El Niño (DJF ≥ +1.0) | 6 | 13.7% | 14.3% | 83% / 97% | +6.0% |
| Any El Niño (≥ +0.5) | 13 | 14.7% | 15.6% | 80% / 96% | +4.9% |
| Neutral | 6 | 12.6% | 13.9% | 84% / 94% | +2.7% |
| La Niña (≤ −0.5) | 16 | 15.1% | 15.9% | 78% / 94% | +5.0% |
| Very strong, like 2027 (+2.1): 1992 / 1998 / 2016 | 3 | 17.1% / 11.4% / 15.5% | 22.5% / 9.7% / 19.0% | 80% / 90% / 82% (80% range) | +10% / +7% / +13% |

So the forecast is about as accurate after an El Niño winter as after any other, its ranges hold, and the
El Niño weighting lowers the typical miss by only 0.3 points over the strong El Niño seasons (by 2 points in
1991 and 1992, by ≤ 0.5 in every later one). In all three seasons most like 2027 yields came
in 7–13% *above* the middle estimate (vs +4.5% in all seasons: the trend lagged in the 1990s–2000s), so if
anything the 2027 outlook leans cautious; three seasons cannot show more than that. **Grain corn is the
exception:** in El Niño seasons its typical miss was 11.8% (5.2% otherwise) and its 80% range held only 61%
of outcomes, driven by 2010, 2015 and 2016 (yields 12–13% above the forecast) and 2019 (a wet-spring planting
delay, 13% below). Treat corn's ±13% range for 2027 as too narrow. Winter wheat also does worse after El Niño
winters (19% vs 17%).

What that means: the forecast gets the *level* right a bit better than the rule of thumb and its ranges are
honest, but it **still cannot tell a good year from a bad one in November** (direction skill ≈ none): what
decides the year is the summer, and nothing known in November predicts the summer well. The November 2026
work made the *summer → yield* link much stronger (it explains 26% of the swing instead of 17%; 31–36% for
spring and durum wheat and peas), which makes the El Niño analog and +1/+2 °C numbers more credible and
would let the forecast tighten in-season as observed months replace possible summers. It moved the
November forecast itself only a little (above). The model form was chosen on this same test (about 15
variants tried), so the scores are slightly optimistic, and the test holds only three strong El Niño winters
(2010, 2016, 2024).

**Weather-model experiments (Nov 2026).** All on the walk-forward test above, scored by CRPS after the same
range recalibration (lower is better; differences under ~0.5% are within the noise of trying many forms;
rows marked * were scored before recalibration, on raw CRPS) and by the share of the swing the known summer
explains:

| Variant | CRPS vs the old model | Weather explains |
| --- | --- | --- |
| Old model: monthly daily-high + soil wetness anomalies, regression | — | 17% |
| Weather averaged over the crop's own fields (AAFC inventory crop groups) instead of all cropland* | +0.1% | 18% |
| + growing-season precipitation* | ±0% | 16% |
| + vapour-pressure deficit / month-by-month columns* | −0.2% / −0.1% | 12% / 21% |
| Absolute conditions (°C, wetness) instead of anomalies, pooled across regions | ±0% | 23% |
| Conditions-based analogs only (2 columns + location) | −0.2% | 20% (21% with location weighted ×2; **15% with no location**) |
| Daily-weather regression (heat degree-days, dry spell, downpours, frost) | **−0.8%** | 22% |
| Analogs on all six daily columns | +2.4% | 19% |
| **Shipped:** daily regression ½ + 2-column analogs with location ½ (corn: 2 columns) | −0.4% | **26%** |

Location matters for the analogs: matching on weather alone (any region with a similar summer) explains 15%;
adding *where* (normal heat, wetness, rain) explains 20–21%. Region-level persistence of misses (a region
that ran below the model for 3 years runs below again) is ~0 (correlation −0.08 to +0.07 by crop), so no
"recent level" correction was added.

For the 2027 season the outlook is **within a few percent of a normal year** for every crop (mean per
crop −0.3% to +3.0%; chance of a below-normal year 37–64% by region). The pieces, averaged per crop:

- **Fall soil moisture** (Aug–Sep 2026 was wet in most regions, median +0.9 SD; central Alberta and a
  few other regions set records beyond the 1981–2025 range): −1.3% to +3.7%, largest for winter wheat and durum.
- **Oct–May precipitation** (ECMWF forecasts about 89–96% of normal on the Prairies, typical of an
  El Niño winter): −1.4% to +0.6%.
- **El Niño weighting** (very strong winter, neutral-to-La Niña summer per CPC): about 0. Using ECMWF's
  even stronger winter instead of CPC's changes the outlook by 0–0.2%.

Read it as "no sign of an El Niño-driven shortfall", not as a confident bump: the 80% ranges are about
±13% (eastern corn) to ±60% (some winter-wheat regions), mostly ±18–38%. Summer daily highs on the
Prairies have barely trended since 1981 (reduced summer-fallow raised crop transpiration; warming has
been mostly in winter and at night), so warming so far shifts a normal year by only about −1 to +1%. A
summer 2 °C hotter than today's trend would cost (median over regions) about 8% for spring wheat, 13% durum,
11% barley, oats and canola, 15% flax, 6–8% peas and lentils and 3% winter wheat; soybeans and corn about
1%. With daily heat degree-days the cost now depends on *where*: −5% for Peace River canola (summers rarely
pass 30 °C) but −12% in southern Manitoba, and Quebec soybeans gain ~4%.

**Data that would make it better** (availability checked Nov 2026):

1. **Saskatchewan yields by Rural Municipality**, 1938–2025, ~290 RMs, free CSV
   (`dashboard.saskatchewan.ca/export/rm-yields-data/4950.csv`; downloaded to `data/raw/sk_rm/`), plus RM
   boundaries from the Saskatchewan GeoHub (`gis.saskatchewan.ca` Administrative MapServer layer 4). About
   15× more yield units than SK's regions, at roughly ecodistrict scale. In that file ~60% of an RM's
   year-to-year swing is local rather than province-wide, and typical yields differ ~2× between RMs (spring
   wheat 25–56 bu/ac, 10th–90th percentile): real sub-regional signal the regional statistics average away.
   Units are bu/ac except lentils (lb/ac); some cells are suppressed.
2. **Ontario county field-crop estimates** (data.ontario.ca, OMAFRA): corn, soybeans, winter wheat by
   county, 1949–2022 series plus 2004–2025 area and yield, XLSX. The only sub-regional source for corn and
   soybeans, where StatCan publishes just a few Ontario regions.
3. **Manitoba MMPP** (masc.mb.ca) yields by RM / risk area (insured farms; the browser blocks scripted
   download) and **Quebec FADQ** actual yields by zone (PDF tables, 2001–2024).
4. **Finer daily weather for training:** Daymet v4 (1 km, 1980–2025, no in-season data) or ERA5-Land
   (0.1°, via Open-Meteo or Copernicus). MERRA-2's 0.5° cannot see a local thunderstorm or hailstorm,
   which is much of that "local" 60%.
5. **In-season:** MODIS NDVI (ORNL REST API, 250 m, 2000–now) and the AAFC Canadian Drought Monitor
   history, to update the forecast through June–August.

**Similarity method (kept simple for now).** Each ecodistrict-month is a vector of the 15 climate values plus 5 soil properties, z-scored (climate within each calendar month) and weighted (weights in `pipeline/similarity.py`). Candidates are the same calendar month in a *different* year, in another ecodistrict; each ecodistrict's best year is kept. Score = 100·exp(−2d²/Σw): 100 is identical and a random pair scores about 2. Only farmland ecodistricts (those with soil survey data) are included.