#!/usr/bin/env bash
# Build data/drainage.min.geojson - the sub-provincial watershed basins used by the
# irrigation layer's "drainage basin" geography.
#
# Source: Statistics Canada, "Drainage regions of Canada" (Map 1.1, cat. 16-201-X),
# 25 drainage regions, Open Government Licence - Canada.
#   https://open.canada.ca/data/en/dataset/b1c2dffa-c2ba-4d0e-b803-a483eef0f579
#
# The irrigation table (monthly_irrigation_volume.csv) reports 13 drainage units,
# some of which merge several of the 25 StatCan regions. We dissolve the shapefile
# into those 13 units (keyed to match BASIN in build_irrigation.py), simplify, drop
# tiny islands and re-emit as WGS84 GeoJSON with the basin key as the feature id.
#
# Needs: curl, unzip, and mapshaper (via `npx mapshaper`, no install required).
set -euo pipefail
cd "$(dirname "$0")/.."

RAW=data/raw/drainage
SHP="$RAW/Drainage_regions_Regions_de_drainage.shp"
URL="https://www150.statcan.gc.ca/n1/en/pub/16-201-x/2017000/sec-1/m-c/m-c-1.1.zip"

mkdir -p "$RAW"
if [ ! -f "$SHP" ]; then
  curl -sSL -o "$RAW/drainage.zip" "$URL"
  unzip -o "$RAW/drainage.zip" -d "$RAW" >/dev/null
fi

# DR_Code (01-25) -> basin key. 13/14/15 and 22/23/24/25 are merged to match the table.
MAP='({"01":"pacific_coastal","02":"fraser","03":"okanagan","04":"columbia","09":"missouri","10":"n_sask","11":"s_sask","12":"assiniboine","13":"winnipeg_nelson","14":"winnipeg_nelson","15":"winnipeg_nelson","19":"great_lakes","20":"ottawa","21":"st_lawrence","22":"atlantic_coastal","23":"atlantic_coastal","24":"atlantic_coastal","25":"atlantic_coastal"})[DR_Code] || "drop"'

npx -y mapshaper "$SHP" \
  -each "basin = $MAP" \
  -filter 'basin !== "drop"' \
  -dissolve basin \
  -simplify visvalingam 2.5% keep-shapes \
  -filter-islands min-area=200km2 \
  -clean \
  -o data/drainage.min.geojson format=geojson id-field=basin precision=0.001

echo "wrote data/drainage.min.geojson"
