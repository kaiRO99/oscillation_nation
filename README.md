# Oscillation Nation

## Vision

El Niño changes growing conditions across Canada, but every farm feels it differently. Oscillation Nation lets farmers look back at past El Niño years and see what happened on their own land, so they can plan ahead instead of reacting. That will include soil moisture and other growing conditions, El Niño strength forecasts, and a tool for finding places with similar soil and climate, so a farmer can learn from places that have already been through the same conditions.

## How it works

The map divides Canada into **ecodistricts**, each shown as a bubble. Every bubble holds the average of several datasets for that area, including precipitation, temperature, soil type and the crops planted there.

A slider driven by the **El Niño index** (the Oceanic Niño Index) lets you move through historical data. You can use the tool in two ways:

1. **Explore conditions by date.** Scrub to any point in history and see what these variables looked like across the map.
2. **Find places like yours.** Select your location, such as your farm, and the tool uses these variables to find locations with similar conditions across the map and throughout history.

As El Niño years come and go, the bubbles shift to show which places your location resembles. Scrub to a historical El Niño and you can see that your location looked like another region does in an average year. That shows you where to look for crops, practices and lessons that already work under those conditions.

## Current prototype (branch `search-similarity-test`)

- **Monthly El Niño timeline.** A slider over every month from Jan 1981 to Dec 2025, with the ONI chart and a strip underneath coloured by phase: red = El Niño, green = neutral, blue = La Niña. A month counts as El Niño / La Niña when it is part of a run of at least 5 overlapping seasons beyond ±0.5 °C (NOAA's definition).
- **Datasets, each with its own checkbox** and all averaged per ecodistrict:
  - *NASA POWER climate* – 15 monthly variables (temperature, precipitation, snow, humidity, solar, wind, evapotranspiration, soil wetness, frost days), as the monthly value or the difference from the 1991–2020 normal.
  - *Soil* – water holding capacity, texture, organic carbon, pH, drainage and dominant soil order from the Soil Landscapes of Canada (farmland only).
  - *AAFC crops planted* – bubbles sized by the share of land in crops for the slider's year, coloured by the largest crop group.
  - *Ecodistrict boundaries.*
- **Places like yours** (right panel). Pick your ecodistrict (type it or click the map). For the slider's month it lists the 10 ecodistricts whose conditions in the same calendar month of another year were most similar, using every climate variable plus soil, and highlights them on the map.

### Data pipeline

All outputs live in `data/`; downloads and caches go to `data/raw/` (git-ignored). Run in this order:

```bash
python scripts/fetch_data.py            # ONI + crop class table
python scripts/build_ecodistricts.py    # ecodistrict boundaries + sample points
python scripts/fetch_power.py           # NASA POWER monthly climate -> data/climate/*.bin (~20 min first time)
python scripts/fetch_soil.py            # Soil Landscapes of Canada -> data/raw/soil.json (needs `pip install dbfread`)
python scripts/fetch_crops.py           # AAFC crop inventory per ecodistrict and year -> data/raw/crops.json (~25 min)
python scripts/build_client_data.py     # merges boundaries, soil and crops -> data/ecodistricts.json
python scripts/similarity.py            # precomputed matches -> data/similarity/<id>.bin (needs numpy)
```

| File sent to the browser | What it holds |
| --- | --- |
| `data/ecodistricts.min.geojson` | simplified ecodistrict polygons |
| `data/ecodistricts.json` | per ecodistrict: names, label point, soil, crops by year |
| `data/climate/<VAR>.bin` + `meta.json` | Int16 `[ecodistrict][month]` per climate variable, loaded when picked |
| `data/similarity/<id>.bin` + `meta.json` | top 10 matches per month for one ecodistrict, loaded when picked |
| `data/oni.json` | NOAA Oceanic Niño Index |

**Similarity method (kept simple for now).** Each ecodistrict-month is a vector of the 15 climate values plus 5 soil properties, z-scored (climate within each calendar month) and weighted (weights in `scripts/similarity.py`). Candidates are the same calendar month in a *different* year, in another ecodistrict; each ecodistrict's best year is kept. Score = 100·exp(−2d²/Σw): 100 is identical and a random pair scores about 2. Only farmland ecodistricts (those with soil survey data) are included.