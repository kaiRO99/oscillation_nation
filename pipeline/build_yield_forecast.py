"""Seasonal crop-yield outlook per region and crop, conditioned on the ENSO forecast and a warming climate.

Usage:  python pipeline/build_yield_forecast.py [--target 2027] [--compare]
          --compare  also hindcast the alternative model forms (trend shape, direct ENSO term, starting
                     conditions) and print their scores, so the choices below can be re-checked
Reads   data/raw/sad_crops.zip                       StatCan 32-10-0002: OBSERVED yield + seeded area by Small
                                                     Area Data Region (SADR), 1976-2025 (build_seeded.py downloads it)
        data/raw/historicalEstimatedCropYieldSlc.csv only for the ecodistrict -> SADR crosswalk, per year
        data/climate/*.bin + meta.json               NASA POWER monthly climate per ecodistrict (fetch_power.py), extended
                                                     by fetch_forecast.py with ERA5 + the ECMWF seasonal forecast
        data/raw/power_daily_indices.npz             daily-weather indices per ecodistrict and month: heat degree-days,
                                                     dry spells, downpours, killing frost (fetch_power_daily.py)
        data/ecodistricts.json                       ecodistrict area and cropland share (climate weights)
        data/oni.json, oni_forecast.json             ONI history and ECMWF's ONI forecast (sensitivity check only)
        data/raw/enso/RONI.ascii.txt                 NOAA CPC Relative Oceanic Nino Index history (auto-downloaded)
        data/enso_forecast.json                      CPC's RONI outlook for the coming seasons (hand-updated monthly)
Writes  data/yield_forecast.json                     see the "doc" dict at the end of main()

Why observed regional yields: data/yield.json is AAFC's *modelled* yield, downscaled from these same
regional statistics, so it adds no information below the region and would make a weather model partly
circular. The forecast is therefore per SADR (Census Agricultural Region); every ecodistrict shows its
region's forecast.

Model, per crop (12 principal field crops; potatoes / hay / alfalfa have no observed regional yields):

  1. Weather -> yield.  log(yield[r,t]) = a[r] + trend[r](t) + g_r(weather[r,t]) + e[r,t]
       * weather columns, cropland-weighted over the region's ecodistricts (class Col):
           dT    growing-season mean daily high (deg C vs the 1991-2020 normal, monthly NASA POWER)
           zS    root-zone soil wetness (standardised vs the normal)
           heat  sqrt of heat degree-days above 30 C over the same months (daily NASA POWER)
           dry   longest dry spell (days < 1 mm) and p5 the wettest 5 days, early-to-mid season
           frost killing-frost days (Tmin <= -2 C) before harvest (late spring for winter wheat)
       * g = regression and conditions-based analogs, blended (ANALOG_BLEND):
           regression: theta . f(columns), f = linear terms + dT^2, zS^2, dT*zS, heat^2 (heat and drought
             hurt non-linearly and together); theta = crop-wide response (lightly ridged) + ridge-shrunk
             provincial deviation
           analogs: the mean yield anomaly (vs each region's own trend) of the ANALOG_K region-years, from
             ANY region, whose summer (ANALOG_COLS: daily highs and soil wetness vs normal) and location
             (normal heat, wetness and rain: what kind of farming country it is) were most similar.
             Anomalies, not yields, travel between places: a similar summer elsewhere says how far that
             place fell below its own normal, not what this place's kg/ha will be. Comparing on all six
             columns made the matches worse (too many dimensions for ~1,000 region-years per crop)
       Chosen on the walk-forward test (README): the blend explains the most of the year-to-year swing when
       the summer is known (26 % vs 17 % for the old two-column regression) and forecasts at least as well.
       * a[r] per region; trend = province trend + a ridge-shrunk regional deviation, so short series
         (Saskatchewan's post-2017 regions, Quebec from 2007) borrow the province's trend. TREND picks
         its shape; the default "recency" is a linear trend fitted with year weights that halve every
         15 years, which beat a plain linear trend (and a post-2000 hinge) in hindcast (--compare)
     Weather is NOT detrended, so the yield trend is the technology trend and warming acts through dT
     and the heat degree-days.

  2. Seasonal ensemble.  Each past observed summer s (1981..last observed) is a possible weather outcome
     for the target year T. Climate change: its temperature is moved onto the target year's climate,
     dT_s + warming_rate[r] * (T - s) (rate = the region's own 1981-2025 trend, half-shrunk to the
     province's), and its heat degree-days are re-read at the threshold lowered by the same warming
     (degree-days above 30 C in a season 1 C warmer = above 29 C as it was); frost days follow their own
     trend. Starting conditions: its soil moisture is moved onto T's starting point (observed
     fall root-zone wetness; plus the ECMWF Oct-May precipitation forecast, centre only), see
     Model.soil_shift. Soil moisture is not shifted for climate change (its reanalysis trend is not robust).
     Member s predicts log yield ~ Normal(a + trend(T) + g(shifted weather_s), sigma_r^2 + trend var).

  3. ENSO.  Members are weighted by how close their winter (DJF) and summer (JJA) RONI were to CPC's
     forecast for the target year (Gaussian kernel, forecast spread + bandwidth h), blended with equal
     weights: w = (1-lam)/N + lam*kernel. h and lam are chosen by hindcast CRPS; lam = 0 means ENSO adds
     nothing and the outlook is just climatology in today's climate.

  4. Confidence.  The forecast is the weighted mixture. Its central ranges are widened or narrowed
     (symmetrically about the median) using hindcast PIT values (forward-chaining 2001-2025: fit on
     years < t, "forecast" t with a statistical November ENSO forecast, score against what happened),
     so a nominal 80 % range covers ~80 % of past outcomes. Only the spread is calibrated, not the
     centre: a centre shift learned over 2001-2025 would carry 2009-2016's run of above-trend yields
     into a period where it has not held. Hindcast skill per crop ships with the data.

Caveats (also in the output's "method"): regional yields, not farm; no CO2 fertilisation, adaptation or
new varieties beyond the trend; the warming scenarios extrapolate a statistical model (feature values
are clipped to the observed range, so they understate unprecedented heat); a very strong El Nino has
only ~4 historical analogs (1983, 1992, 1998, 2016).
"""
import argparse
import csv
import datetime
import io
import json
import math
import re
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"             # downloads / caches (git-ignored)
CDATA = ROOT / "data"                   # what the map loads
ZIP = RAW / "sad_crops.zip"
SLC_NAME = "historicalEstimatedCropYieldSlc.csv"
SLC = next((p for p in (RAW / SLC_NAME, ROOT / "data" / SLC_NAME) if p.exists()), RAW / SLC_NAME)
CLIM = CDATA / "climate"
ECO = CDATA / "ecodistricts.json"
ONI = CDATA / "oni.json"
ONI_FC = CDATA / "oni_forecast.json"    # ECMWF Nino 3.4 forecast (pipeline/fetch_forecast.py)
RONI = RAW / "enso" / "RONI.ascii.txt"
RONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"
FCST = CDATA / "enso_forecast.json"
DAILY = RAW / "power_daily_indices.npz"  # daily-weather indices per ecodistrict (pipeline/fetch_power_daily.py)
OUT = CDATA / "yield_forecast.json"

YIELD_D = "Average yield (kilograms per hectare)"
SEED_D = "Seeded area (hectares)"
NORMAL = (1991, 2020)
HIND0 = 2001            # first hindcast year
RECENT0 = 2017          # "lately" for the recent-bias check reported per crop
MIN_HA = 1000           # drop region-crop-years seeded on less than this (yield on a sliver of land is noise)
MIN_FIT_YEARS = 5       # a region needs this many training years before it gets a forecast
LAM_TREND = 30.0        # ridge on regional trend deviations (log yield per decade)
LAM_THETA = 300.0       # ridge on provincial deviations of the weather response
SIG_K = 8.0             # residual SD shrinkage toward the province (pseudo-years)
KNOT = 2000             # "hinge" trend: the province trend may change slope here
HALF_LIFE = 15.0        # "recency" trend: a year's weight halves every this many years back
LEVELS = [0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975]
GRID_H = [0.3, 0.6, 1.0]                # ENSO kernel bandwidth (RONI deg C)
GRID_LAM = [0.0, 0.25, 0.5, 0.75, 1.0]  # weight on the ENSO kernel vs equal weights
WARMING = [1.0, 2.0]                    # extra summer warming scenarios (deg C beyond today's trend)

# Model form. Re-check with --compare when the data change; the scores that picked these are in the README.
TREND = "recency"       # "linear" | "hinge" (province slope may change at KNOT) | "recency" (linear, recent years count more)
ENSO_TERM = False       # also regress yield directly on DJF/JJA RONI (non-weather pathways)?
ANTE = "fall+wspr"      # starting conditions that move each past summer's soil moisture (see Model.members):
                        #   "none" | "fall" (observed Aug-Sep root-zone wetness of the year before)
                        #   | "fall+wspr" (+ Oct-May precipitation; the ECMWF forecast for the coming season)
LAM_CROP = 2.0          # ridge on the crop-wide weather response (features are standardised)
# Conditions-based analogs ("places and years like this one"): the weather part of a season's yield is
# ANALOG_BLEND x the mean anomaly of the ANALOG_K most similar region-years of any region (similar weather
# columns, plus similar location: normal heat, wetness and rain, weight ANALOG_LOC) + (1 - ANALOG_BLEND) x the
# regression. 0 = regression only. Chosen by walk-forward test (README "Yield forecast").
ANALOG_BLEND = 0.5
ANALOG_K = 80
ANALOG_LOC = 1.0
ANALOG_COLS = ("dT", "zS")  # weather columns the analogs compare (more dimensions made matches worse)
N_BOOT = 2000           # bootstrap resamples of hindcast years for the ENSO-skill confidence interval
N_ANALOG_SHOW = 4       # per-region "what each closest past El Nino season would mean today" values exported

# StatCan name, code, label, temperature months, soil-moisture months
CROPS = [
    ("Wheat, spring", "WHTSPG", "Spring wheat", (6, 7, 8), (6, 7)),
    ("Wheat, durum", "WHTDUR", "Durum wheat", (6, 7, 8), (6, 7)),
    ("Wheat, winter remaining", "WHTWINT", "Winter wheat", (5, 6, 7), (5, 6)),
    ("Barley", "BARLEY", "Barley", (6, 7, 8), (6, 7)),
    ("Oats", "OATS", "Oats", (6, 7, 8), (6, 7)),
    ("Canola", "CANOLA", "Canola", (6, 7, 8), (6, 7)),
    ("Flaxseed", "FLAXSD", "Flaxseed", (6, 7, 8), (6, 7)),
    ("Soybeans", "SOYBNS", "Soybeans", (7, 8), (7, 8)),
    ("Corn for grain", "CORNGR", "Grain corn", (7, 8), (7, 8)),
    ("Peas, dry", "DFPEAS", "Dry peas", (6, 7), (6, 7)),
    ("Lentils", "LENTIL", "Lentils", (6, 7), (6, 7)),
    ("Sunflower seed", "SUNFLS", "Sunflower seed", (7, 8), (7, 8)),
]
NAME_TO_CODE = {c[0]: c[1] for c in CROPS}
# months for the daily-weather columns: dry spells and downpours (PMON), killing frost (FMON: before
# harvest for spring-sown crops, late spring for winter wheat); heat degree-days use the temperature months
PMON = {"WHTWINT": (4, 5, 6), "SOYBNS": (6, 7, 8), "CORNGR": (6, 7, 8), "SUNFLS": (6, 7, 8)}
PMON_DEFAULT = (5, 6, 7)
FMON = {"WHTWINT": (5, 6)}
FMON_DEFAULT = (8, 9)
HEAT_BASE = 30          # heat degree-days above this (deg C); fetch_power_daily.py stores 26..33 for warming shifts
# Crops that keep only the two monthly columns (daily highs, soil wetness). Grain corn: weather explains none
# of its regional year-to-year swing in any form tested (heat above 30 C is rare where it grows), and the
# extra daily columns only added noise (walk-forward CRPS vs the 5-year average +4 % instead of +9 %)
SIMPLE_COLS = {"CORNGR"}
PROV_SGC = {"Québec": 24, "Quebec": 24, "Ontario": 35, "Manitoba": 46,
            "Saskatchewan": 47, "Alberta": 48, "British Columbia": 59}
SGC_PROV = {24: "QC", 35: "ON", 46: "MB", 47: "SK", 48: "AB", 59: "BC"}
PROV_NAME = {"QC": "Quebec", "ON": "Ontario", "MB": "Manitoba", "SK": "Saskatchewan", "AB": "Alberta",
             "BC": "British Columbia"}
SQRT2 = math.sqrt(2.0)


# ---------------------------------------------------------------- maths helpers

def ndtr(x):
    """Standard normal CDF (Abramowitz & Stegun 7.1.26, |error| < 1.5e-7)."""
    x = np.asarray(x, dtype=np.float64)
    z = np.abs(x) / SQRT2
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    return 0.5 * (1.0 + np.sign(x) * (1.0 - poly * np.exp(-z * z)))


def npdf(x):
    return np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _A(m, s):
    z = m / s
    return m * (2 * ndtr(z) - 1) + 2 * s * npdf(z)


def crps_mix(y, mu, w, s):
    """CRPS of the Gaussian mixture sum_j w_j N(mu[u,j], s[u]^2) at y[u]  (Grimit et al. 2006).
    y (U,), mu (U,S), w (S,), s (U,) -> (U,)"""
    t1 = (w[None, :] * _A(y[:, None] - mu, s[:, None])).sum(1)
    d = mu[:, :, None] - mu[:, None, :]
    t2 = (w[None, :, None] * w[None, None, :] * _A(d, s[:, None, None] * SQRT2)).sum((1, 2))
    return t1 - 0.5 * t2


def crps_norm(y, m, s):
    return _A(y - m, s) - s / math.sqrt(math.pi)


def mix_cdf(x, mu, w, s):
    """P(X <= x[u]) for each unit's mixture. x (U,) or (U,K) -> same shape."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        return (w[None, :] * ndtr((x[:, None] - mu) / s[:, None])).sum(1)
    return (w[None, None, :] * ndtr((x[:, :, None] - mu[:, None, :]) / s[:, None, None])).sum(2)


def mix_quantiles(mu, w, s, levels, n=800):
    """Quantiles (U, len(levels)) of each unit's mixture, by inverting the CDF on a grid."""
    lo = mu.min(1) - 6 * s
    hi = mu.max(1) + 6 * s
    g = lo[:, None] + (hi - lo)[:, None] * np.linspace(0, 1, n)[None, :]
    F = mix_cdf(g, mu, w, s)
    return np.array([np.interp(levels, F[u], g[u]) for u in range(len(mu))])


# ---------------------------------------------------------------- inputs

def geo_key(geo):
    """StatCan GEO label -> SADR series key ('4841'; Saskatchewan 2017+ regions get a 'b' suffix,
    same convention as build_seeded.py), or None for provinces / unrecognised labels."""
    if " - " not in geo:
        return None
    head, prov = geo.rsplit(" - ", 1)
    prov = prov.strip()
    later = "(" in prov
    sgc = PROV_SGC.get(re.sub(r"\s*\(.*\)\s*$", "", prov))
    nums = re.findall(r"\d+", head)
    if sgc is None or not nums:
        return None
    return f"{sgc * 100 + int(nums[-1])}{'b' if later else ''}"


def region_name(key, geo):
    """'4840' -> 'Alberta region 40'; '4705b' -> 'Saskatchewan census division 5';
    'Montérégie Nord-est, 9 - Québec' -> 'Montérégie Nord-est (QC)'."""
    prov = SGC_PROV[int(key[:2])]
    n = int(key[2:4])
    if key.endswith("b"):
        return f"Saskatchewan census division {n}"
    head = geo.rsplit(" - ", 1)[0].strip()
    if head.lower().startswith("small area data region"):
        return f"{PROV_NAME[prov]} region {n}"
    head = re.sub(r"(,\s*|\s+Region\s+)\d+$", "", head)
    return f"{head} ({prov})"


def load_statcan():
    if not ZIP.exists():
        raise SystemExit(f"missing {ZIP.relative_to(ROOT)}: run scripts/build_seeded.py first (it downloads it)")
    yld, ha, names = defaultdict(dict), defaultdict(dict), {}
    with zipfile.ZipFile(ZIP) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv") and "MetaData" not in n)
        for row in csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")):
            disp = row["Harvest disposition"]
            if disp not in (YIELD_D, SEED_D):
                continue
            code = NAME_TO_CODE.get(row["Type of crop"])
            key = geo_key(row["GEO"]) if code else None
            v = row["VALUE"].strip()
            if key is None or not v:
                continue
            try:
                x = float(v)
            except ValueError:
                continue
            (yld if disp == YIELD_D else ha)[(key, code)][int(row["REF_DATE"])] = x
            names.setdefault(key, row["GEO"])
    return yld, ha, names


def crosswalk():
    """members[key][eco] = share of the ecodistrict's polygons in that region (over the region's years);
    latest[eco] = region key in the most recent year (what the map shows)."""
    counts = defaultdict(lambda: defaultdict(Counter))
    with SLC.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = row.get("SADREGION", "").strip()
            if s:
                counts[int(row["ECODISTRIC"])][int(row["YEAR"])][int(s)] += 1

    def key_of(sadr, year):
        return f"{sadr}{'b' if sadr // 100 == 47 and year >= 2017 else ''}"

    num = defaultdict(Counter)
    den = defaultdict(Counter)
    latest = {}
    for eco, by_year in counts.items():
        for year, c in by_year.items():
            tot = sum(c.values())
            for sadr, n in c.items():
                num[key_of(sadr, year)][eco] += n
            for k in {key_of(s, year) for s in c}:
                den[k][eco] += tot
        ly = max(by_year)
        top = min(by_year[ly].items(), key=lambda kv: (-kv[1], kv[0]))[0]
        latest[eco] = key_of(top, ly)
    members = {k: {e: num[k][e] / den[k][e] for e in num[k]} for k in num}
    return members, latest


def load_roni():
    if not RONI.exists():
        RONI.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {RONI_URL} ...")
        urllib.request.urlretrieve(RONI_URL, RONI)
    out = {}
    for line in RONI.read_text().splitlines()[1:]:
        p = line.split()
        if len(p) == 3:
            out[(p[0], int(p[1]))] = float(p[2])
    return out


def load_climate(meta, keys):
    n_d, n_m = len(meta["ids"]), meta["months"]
    out = {}
    for k in keys:
        a = np.frombuffer((CLIM / f"{k}.bin").read_bytes(), dtype="<i2").reshape(n_d, n_m).astype(np.float64)
        a[a == -32768] = np.nan
        out[k] = a * meta["vars"][k]["scale"]
    return out


class Ctx:
    """Everything the model needs, aligned on (region, climate year)."""

    def __init__(self, target=None):
        self.fjson = json.loads(FCST.read_text(encoding="utf-8"))
        self.T = target or self.fjson["target_year"]
        z95 = 1.6448536
        sea = self.fjson["seasons"]
        self.fc_now = {"mD": sea["DJF"]["p50"], "sD": (sea["DJF"]["p95"] - sea["DJF"]["p05"]) / (2 * z95),
                       "mJ": sea["JJA"]["p50"], "sJ": (sea["JJA"]["p95"] - sea["JJA"]["p05"]) / (2 * z95)}

        yld, ha, self.geo_names = load_statcan()
        self.yld_keys = set(yld)  # (region key, crop code) pairs with any published yield
        members, self.latest = crosswalk()
        self.roni = load_roni()
        meta = json.loads((CLIM / "meta.json").read_text(encoding="utf-8"))
        clim = load_climate(meta, ["T2M_MAX", "GWETROOT", "PRECIP"])
        self.eco = json.loads(ECO.read_text(encoding="utf-8"))["d"]
        row_of = {d: i for i, d in enumerate(meta["ids"])}
        self.cy0 = int(meta["start"][:4])
        n_m = meta["months"]
        n_years = -(-n_m // 12)  # whole years; the last one is padded with NaN
        self.years = np.arange(self.cy0, self.cy0 + n_years)
        # Months up to "power_last" are NASA POWER (observed). fetch_forecast.py appends ERA5 analysis
        # ("analysis") and the ECMWF seasonal forecast ("forecast") after it; those only feed the
        # starting-condition features, never the weather the model was trained on.
        pl = meta.get("power_last")
        self.n_obs = ((int(pl[:4]) - self.cy0) * 12 + int(pl[5:7])) if pl else n_m
        ext = meta.get("extension") or {}
        self.kinds = (["obs"] * self.n_obs + list(ext.get("kinds", []))[:n_m - self.n_obs]
                      + ["none"] * (n_years * 12 - n_m))
        self.ext = ext
        self.Y1 = min(int(self.years[-1]), max(y for s in yld.values() for y in s))  # last year with yields
        # last year whose growing season (to August) is fully observed: it can be an analog summer
        self.W1 = max(int(y) for y in self.years if (y - self.cy0) * 12 + 8 <= self.n_obs)

        def cropland(e):
            d = self.eco.get(str(e), {})
            shares = [v[0] for v in d.get("crops", {}).values() if v and v[0] is not None]
            return d.get("area", 0) * (np.mean(shares) if shares else 0.0) / 100

        keys = sorted({k for k, _ in yld if k in members})
        W = {}  # key -> (rows into climate arrays, weights): cropland-weighted share of each ecodistrict
        for k in keys:
            rows, ws = [], []
            for e, frac in members[k].items():
                w = frac * cropland(e) if e in row_of else 0
                if w > 0:
                    rows.append(row_of[e])
                    ws.append(w)
            if rows:
                W[k] = (np.array(rows), np.array(ws) / sum(ws))
        self.keys = [k for k in keys if k in W]
        self.provs = sorted({SGC_PROV[int(k[:2])] for k in self.keys})
        self.p_of_r = np.array([self.provs.index(SGC_PROV[int(k[:2])]) for k in self.keys])
        R = self.R = len(self.keys)
        print(f"{R} regions with yields + climate, provinces {self.provs}; yields to {self.Y1}, "
              f"observed climate to {pl or self.years[-1]}, analog summers to {self.W1}"
              + (f", forecast months from {ext.get('first')} (issued {ext.get('issued')})" if ext else ""))

        def region_monthly(var, observed_only=True):
            out = np.full((R, n_years * 12), np.nan)
            for i, k in enumerate(self.keys):
                rows, ws = W[k]
                x = clim[var][rows]
                m = ~np.isnan(x)
                wsum = (m * ws[:, None]).sum(0)
                out[i, :n_m] = np.where(wsum > 0, (np.nan_to_num(x) * ws[:, None]).sum(0) / np.maximum(wsum, 1e-12), np.nan)
            if observed_only:
                out[:, self.n_obs:] = np.nan
            return out.reshape(R, n_years, 12)

        tmax_m = region_monthly("T2M_MAX")
        gwet_m = region_monthly("GWETROOT")
        nmask = (self.years >= NORMAL[0]) & (self.years <= NORMAL[1])
        self.roni_d = np.array([self.roni.get(("DJF", int(y)), np.nan) for y in self.years])
        self.roni_j = np.array([self.roni.get(("JJA", int(y)), np.nan) for y in self.years])

        # Starting conditions for season y, standardised per region against 1991-2020:
        #   fall[r, y] = root-zone soil wetness in Aug-Sep of y-1 (observed)
        #   wspr[r, y] = precipitation Oct of y-1 to May of y (observed, or ERA5 + ECMWF forecast for the
        #                coming season); wspr_fc[y] = True when any of those months is a forecast
        prec_m = region_monthly("PRECIP", observed_only=False)
        fall = np.full((R, n_years), np.nan)
        fall[:, 1:] = gwet_m[:, :-1, 7:9].mean(2)
        wspr = np.full((R, n_years), np.nan)
        wspr[:, 1:] = prec_m[:, :-1, 9:12].sum(2) + prec_m[:, 1:, 0:5].sum(2)
        kinds = np.array(self.kinds).reshape(n_years, 12)
        self.wspr_fc = np.zeros(n_years, bool)
        self.wspr_fc[1:] = (kinds[:-1, 9:12] == "forecast").any(1) | (kinds[1:, 0:5] == "forecast").any(1)
        self.wspr_raw = wspr

        def zscore(a):
            mu, sd = np.nanmean(a[:, nmask], 1), np.nanstd(a[:, nmask], 1)
            return (a - mu[:, None]) / np.where(sd > 1e-9, sd, np.nan)[:, None]

        self.fall, self.wspr = zscore(fall), zscore(wspr)
        self.wspr_pct = 100 * wspr / np.nanmean(wspr[:, nmask], 1)[:, None]  # % of the 1991-2020 normal

        # Daily-weather indices (fetch_power_daily.py), aggregated to regions with the same cropland weights.
        # Only observed months: the daily file is NASA POWER too, and is cut at the monthly file's last month.
        if not DAILY.exists():
            raise SystemExit(f"missing {DAILY.relative_to(ROOT)}: run pipeline/fetch_power_daily.py first")
        dz = np.load(DAILY)
        if str(dz["start"]) != meta["start"]:
            raise SystemExit(f"{DAILY.name} starts {dz['start']}, climate/meta.json {meta['start']}: re-run fetch_power_daily.py")
        d_row = {int(e): i for i, e in enumerate(dz["ids"])}
        n_dm = int(dz["months"])
        self.kdd_bases = [int(n[3:]) for n in dz["indices"] if str(n).startswith("KDD")]

        def region_daily(var):
            src = dz[var].astype(np.float64)
            out = np.full((R, n_years * 12), np.nan)
            for i, k in enumerate(self.keys):
                rows, ws = W[k]
                pick = [(d_row[meta["ids"][r]], w) for r, w in zip(rows, ws) if meta["ids"][r] in d_row]
                if not pick:
                    continue
                dr = np.array([p[0] for p in pick])
                dw = np.array([p[1] for p in pick])
                x = src[dr]
                m = ~np.isnan(x)
                wsum = (m * dw[:, None]).sum(0)
                out[i, :n_dm] = np.where(wsum > 0, (np.nan_to_num(x) * dw[:, None]).sum(0) / np.maximum(wsum, 1e-12), np.nan)
            out[:, self.n_obs:] = np.nan
            return out.reshape(R, n_years, 12)

        daily = {v: region_daily(v) for v in [f"KDD{b}" for b in self.kdd_bases] + ["DRY", "P5MAX", "KFROST"]}
        prec_obs = region_monthly("PRECIP")
        last_daily = str(dz["last_day"])
        print(f"daily-weather indices to {last_daily[:4]}-{last_daily[4:6]}-{last_daily[6:]}")
        if int(last_daily[:4]) < self.W1:
            print(f"  WARNING: no daily weather for {self.W1}'s summer; re-run fetch_power_daily.py, "
                  f"or {self.W1} drops out of the possible summers")

        self.crop = {}
        for name, code, label, tmon, smon in CROPS:
            # strict means: a season with any month missing (not yet observed) has no value
            tm, pm = [m - 1 for m in tmon], [m - 1 for m in PMON.get(code, PMON_DEFAULT)]
            fm = [m - 1 for m in FMON.get(code, FMON_DEFAULT)]
            tx = tmax_m[:, :, tm].mean(axis=2)       # (R, Y) deg C
            sm = gwet_m[:, :, [m - 1 for m in smon]].mean(axis=2)       # (R, Y) 0-1
            tx_n = np.nanmean(tx[:, nmask], 1)
            sm_n = np.nanmean(sm[:, nmask], 1)
            sm_sd = np.nanstd(sm[:, nmask], 1)
            sm_sd = np.where(sm_sd > 1e-4, sm_sd, np.nan)
            dT = tx - tx_n[:, None]
            zS = (sm - sm_n[:, None]) / sm_sd[:, None]
            # heat degree-days over the temperature months at every stored threshold (R, Y, n_bases), so a
            # season can be warmed exactly: above 30 C in a season d C warmer = above (30 - d) C as it was
            kdd = np.stack([daily[f"KDD{b}"][:, :, tm].sum(2) for b in self.kdd_bases], -1)
            heat = np.sqrt(kdd[:, :, self.kdd_bases.index(HEAT_BASE)])  # sqrt: most seasons have little
            cols = [Col("dT", dT, "T"),                                               # mean daily high, anomaly
                    Col("zS", zS, "S"),                                               # root-zone wetness, z
                    Col("heat", heat, "H", stack=kdd),                                # sqrt heat degree-days > 30 C
                    Col("dry", daily["DRY"][:, :, pm].max(2), "P"),                   # longest dry spell (days)
                    Col("p5", np.log1p(daily["P5MAX"][:, :, pm].max(2)), "P"),        # wettest 5 days, log mm
                    Col("frost", np.sqrt(daily["KFROST"][:, :, fm].sum(2)), "V")]     # killing-frost days, sqrt
            if code in SIMPLE_COLS:
                cols = cols[:2]
            # where the region is, agronomically (for the analogs): its 1991-2020 growing-season daily high,
            # root-zone wetness and log precipitation
            loc = np.stack([tx_n, sm_n, np.nanmean(np.log(np.maximum(prec_obs[:, :, pm].sum(2), 1.0))[:, nmask], 1)], 1)
            loc = np.nan_to_num((loc - np.nanmean(loc, 0)) / np.nanstd(loc, 0))
            obs = np.full((R, n_years), np.nan)
            for i, k in enumerate(self.keys):
                ys, hs = yld.get((k, code), {}), ha.get((k, code), {})
                for y, v in ys.items():
                    if self.cy0 <= y <= self.Y1 and v > 0 and hs.get(y, 0) >= MIN_HA:
                        obs[i, y - self.cy0] = math.log(v)
            ok = ~np.isnan(obs) & ~np.isnan(np.stack([c.a for c in cols], -1)).any(-1)
            if ok.sum() < 100:
                print(f"{code}: too little data, skipped")
                continue
            self.crop[code] = dict(name=name, label=label, tx=tx, dT=dT, zS=zS, cols=cols, loc=loc, obs=obs, ok=ok)


# ---------------------------------------------------------------- model pieces

class Col:
    """One weather column (R, Y) and how a past season's value is moved onto the target season:
      'T' temperature anomaly: along the region's summer-warming trend, plus any extra warming
      'H' heat degree-days (sqrt): recomputed at the threshold lowered by the same warming (needs `stack`,
          the degree-days at every stored threshold)
      'V' other trending column (frost days): along its own regional trend
      'S' soil wetness (z): onto this season's starting conditions (Model.soil_shift)
      'P' not moved (dry spells, downpours, ENSO indices)"""

    def __init__(self, name, a, kind, stack=None):
        self.name, self.a, self.kind, self.stack = name, a, kind, stack


def poly_terms(names):
    """Linear terms for every column, plus the curvature the agronomy calls for: squares of heat (dT),
    wetness (zS) and heat degree-days, and heat x wetness (heat hurts more in a dry year)."""
    ix = {n: i for i, n in enumerate(names)}
    out = [(i,) for i in range(len(names))]
    out += [(ix["dT"], ix["dT"]), (ix["zS"], ix["zS"]), (ix["dT"], ix["zS"])]
    if "heat" in ix:
        out.append((ix["heat"], ix["heat"]))
    return out


def feats(B, terms):
    """B (..., n_cols) -> (..., n_terms)"""
    return np.stack([B[..., t[0]] if len(t) == 1 else B[..., t[0]] * B[..., t[1]] for t in terms], -1)


def trend_basis(tau, trend):
    """Province-level trend columns for tau = (year - 2000) / 10. The first column also gets a
    ridge-shrunk regional deviation."""
    cols = [tau]
    if trend == "hinge":
        cols.append(np.maximum(tau - (KNOT - 2000) / 10.0, 0.0))
    return np.stack(cols, -1)


class Fit:
    """Ridge fit of log yield on region intercepts, province + regional trends and the weather response
    (crop-wide, lightly ridged; provincial deviations, strongly ridged). Optional row weights (recency
    weighting) multiply each row's squared error."""

    def __init__(self, r_idx, p_of_r, tau, X, y, n_r, n_p, trend, wts=None):
        n, k = X.shape
        B = trend_basis(tau, trend)
        nb = B.shape[1]
        p_idx = p_of_r[r_idx]
        i = np.arange(n)
        o_tr = n_r                      # province trend coefficients, nb per province
        o_dev = o_tr + n_p * nb         # regional deviation of the linear trend
        o = o_dev + n_r                 # crop-wide weather response
        cols = o + k + n_p * k
        A = np.zeros((n, cols))
        A[i, r_idx] = 1.0
        for b in range(nb):
            A[i, o_tr + p_idx * nb + b] = B[:, b]
        A[i, o_dev + r_idx] = tau
        A[:, o:o + k] = X
        for j in range(k):
            A[i, o + k + p_idx * k + j] = X[:, j]
        pen = np.zeros(cols)
        pen[o_dev:o] = LAM_TREND
        pen[o:o + k] = LAM_CROP
        pen[o + k:] = LAM_THETA
        w = np.ones(n) if wts is None else wts
        Aw = A * np.sqrt(w)[:, None]
        AtA = Aw.T @ Aw
        Minv = np.linalg.inv(AtA + np.diag(pen + 1e-9))
        self.c = Minv @ (Aw.T @ (y * np.sqrt(w)))
        self.cov = Minv @ AtA @ Minv  # ridge sandwich covariance, per unit residual variance
        res = y - A @ self.c
        self.n_r, self.n_p, self.k, self.o, self.o_tr, self.o_dev, self.nb = n_r, n_p, k, o, o_tr, o_dev, nb
        self.trend_kind = trend
        self.p_of_r = p_of_r
        # residual variance per region (weighted, small-sample corrected), shrunk toward its province's
        n_raw = np.bincount(r_idx, None, n_r)
        ss = np.bincount(r_idx, w * res * res, n_r)
        nw = np.bincount(r_idx, w, n_r)
        corr = n_raw / np.maximum(n_raw - 1.5, 1)
        msr = np.where(nw > 0, ss / np.maximum(nw, 1e-12) * corr, 0)
        s2p = np.bincount(p_of_r, ss, n_p) / np.maximum(np.bincount(p_of_r, nw, n_p), 1e-12)
        s2p = s2p * (np.bincount(p_of_r, n_raw, n_p) / np.maximum(np.bincount(p_of_r, n_raw, n_p) - 1.5 * np.bincount(p_of_r, n_raw > 0, n_p), 1))
        self.sig2 = (nw * msr + SIG_K * s2p[p_of_r]) / (nw + SIG_K)
        self.n_years = n_raw

    def theta(self, r):
        p = self.p_of_r[r]
        o, k = self.o, self.k
        return self.c[o:o + k] + self.c[o + k + p * k:o + k + (p + 1) * k]

    def trend(self, r, tau):
        """(log-yield trend value at tau, its variance) for region r."""
        x = np.zeros(len(self.c))
        x[r] = 1.0
        B = trend_basis(np.array([tau]), self.trend_kind)[0]
        p = self.p_of_r[r]
        x[self.o_tr + p * self.nb:self.o_tr + (p + 1) * self.nb] = B
        x[self.o_dev + r] = tau
        return float(x @ self.c), float(x @ self.cov @ x) * self.sig2[r]


def warming_rates(tx, p_of_r, yrs_mask, years):
    """Per-region trend of growing-season Tmax (deg C / yr) over the masked years, half-shrunk to the
    province mean (single-region trends over a few decades are noisy)."""
    t = years[yrs_mask].astype(np.float64)
    X = tx[:, yrs_mask]
    ok = ~np.isnan(X)
    rate = np.zeros(len(tx))
    for r in range(len(tx)):
        if ok[r].sum() >= 10:
            rate[r] = np.polyfit(t[ok[r]], X[r, ok[r]], 1)[0]
    prov = np.array([rate[p_of_r == p].mean() for p in range(p_of_r.max() + 1)])
    return 0.5 * rate + 0.5 * prov[p_of_r]


def enso_weights(d, j, fc, h, lam):
    sd = math.hypot(fc["sD"], h)
    sj = math.hypot(fc["sJ"], h)
    k = np.exp(-0.5 * ((d - fc["mD"]) / sd) ** 2 - 0.5 * ((j - fc["mJ"]) / sj) ** 2)
    k = k / k.sum()
    return (1 - lam) / len(d) + lam * k


def stat_enso_forecast(roni, target):
    """What a November statistical forecast would have said about DJF and JJA of `target`:
    linear regression on Aug-Oct RONI of the year before, fitted on 1951..target-1."""
    ys = [y for y in range(1951, target) if ("ASO", y - 1) in roni and ("JJA", y) in roni]
    x = np.array([roni[("ASO", y - 1)] for y in ys])
    out = {}
    for seas, m, s in (("DJF", "mD", "sD"), ("JJA", "mJ", "sJ")):
        v = np.array([roni[(seas, y)] for y in ys])
        b, a = np.polyfit(x, v, 1)
        out[m] = a + b * roni[("ASO", target - 1)]
        out[s] = float(np.std(v - (a + b * x), ddof=2))
    return out


def ecmwf_enso_alternative(ctx):
    """ECMWF's winter Nino 3.4 forecast (data/oni_forecast.json, from fetch_forecast.py) as an
    alternative to CPC's DJF median, for a sensitivity check. It is on the ONI scale, so it is moved to
    RONI with the mean ONI - RONI difference over the last 3 seasons both indices have. CPC's spread and
    its summer (JJA) forecast are kept: the ECMWF file has neither (ensemble mean, ends in spring).
    Not used as the main input: CPC's outlook already blends dynamical models including ECMWF."""
    if not (ONI_FC.exists() and ONI.exists()):
        return None
    fc = json.loads(ONI_FC.read_text(encoding="utf-8"))
    oni = json.loads(ONI.read_text(encoding="utf-8"))["data"]
    djf = next((r["anom"] for r in fc.get("data", []) if r["season"] == "DJF" and r["year"] == ctx.T), None)
    both = [r["anom"] - ctx.roni[(r["season"], r["year"])] for r in oni if (r["season"], r["year"]) in ctx.roni]
    if djf is None or len(both) < 3:
        return None
    offset = float(np.mean(both[-3:]))
    return {"source": fc.get("source", "ECMWF seasonal forecast"), "issued": fc.get("issued"),
            "djf_oni": djf, "offset": round(offset, 2), "djf_roni": round(djf - offset, 2),
            "fc": dict(ctx.fc_now, mD=djf - offset)}


class Model:
    """One crop's fitted model on years <= t_last, plus how to build its seasonal ensemble.

    Weather part of log yield for a season with weather columns B (see Col):
        g(B) = ANALOG_BLEND * analog(B) + (1 - ANALOG_BLEND) * theta . f(B)
    f = poly_terms of the standardised columns (regression, crop-wide + shrunk provincial deviation);
    analog(B) = tricube-weighted mean yield anomaly (log yield minus the region's own trend) of the ANALOG_K
    region-years, any region, whose weather columns and location (normal heat, wetness, rain) are closest."""

    def __init__(self, ctx, code, t_last, trend=TREND, enso=ENSO_TERM, ante=ANTE, pool_last=None):
        """Fit on yields of years <= t_last; past summers up to pool_last (default t_last) are the
        ensemble's possible weather (a summer can be observed before its yields are published)."""
        self.ctx, self.code, self.enso, self.ante = ctx, code, enso, ante
        d = ctx.crop[code]
        years = ctx.years
        self.cols = list(d["cols"])
        if enso:
            R = ctx.R
            self.cols += [Col("roni_djf", np.broadcast_to(ctx.roni_d, (R, len(years))), "P"),
                          Col("roni_jja", np.broadcast_to(ctx.roni_j, (R, len(years))), "P")]
        self.terms = poly_terms([c.name for c in self.cols])
        self.B = np.stack([c.a for c in self.cols], -1)  # (R, Y, n_cols)
        ok = d["ok"] & ~np.isnan(self.B).any(-1) & (years[None, :] <= t_last)
        rr, yy = np.nonzero(ok)
        self.valid = len(rr) >= 60
        if not self.valid:
            return
        used = np.unique(rr)
        self.remap = -np.ones(ctx.R, int)
        self.remap[used] = np.arange(len(used))
        pp = sorted(set(ctx.p_of_r[used]))
        pmap = {p: i for i, p in enumerate(pp)}
        p_loc = np.array([pmap[ctx.p_of_r[r]] for r in used])
        tau = (years[yy] - 2000) / 10.0
        Bt = self.B[rr, yy]
        X = feats(Bt, self.terms)
        self.xm, self.xs = X.mean(0), np.where(X.std(0) > 1e-9, X.std(0), 1.0)  # standardise for the ridge
        wts = 0.5 ** ((t_last - years[yy]) / HALF_LIFE) if trend == "recency" else None
        self.fit = Fit(self.remap[rr], p_loc, tau, (X - self.xm) / self.xs, d["obs"][rr, yy], len(used), len(pp),
                       "linear" if trend == "recency" else trend, wts)
        self.lo, self.hi = Bt.min(0), Bt.max(0)  # training range: moved seasons are clipped to it
        last = t_last if pool_last is None else pool_last
        self.pool = (years <= last) & ~np.isnan(self.B).any(-1).all(0)
        self.rate = warming_rates(d["tx"], ctx.p_of_r, self.pool, years)  # summer daily highs, deg C / yr
        self.vrate = {i: warming_rates(c.a, ctx.p_of_r, self.pool, years)
                      for i, c in enumerate(self.cols) if c.kind == "V"}

        # analog library: every training region-year's weather columns (scaled by their spread) and location
        self.analog = ANALOG_BLEND > 0
        if self.analog:
            self.an_c = [i for i, c in enumerate(self.cols) if c.name in ANALOG_COLS]
            base = np.array([self.level(self.remap[r], years[y]) for r, y in zip(rr, yy)])
            self.an_y = d["obs"][rr, yy] - base
            sc = Bt[:, self.an_c].std(0)
            self.an_s = np.where(sc > 1e-9, sc, 1.0)
            self.loc = d["loc"]
            self.an_Z = np.concatenate([Bt[:, self.an_c] / self.an_s, ANALOG_LOC * self.loc[rr]], 1)

        # How starting conditions carry into the summer: per province, regress the crop's summer
        # soil-moisture anomaly on the fall / winter-spring indices (seasons <= last, all observed).
        self.rho = np.zeros((ctx.p_of_r.max() + 1, 2))
        if ante != "none":
            cols = [ctx.fall] + ([ctx.wspr] if ante == "fall+wspr" else [])
            for p in range(len(self.rho)):
                rp = np.nonzero(ctx.p_of_r == p)[0]
                Y = d["zS"][rp][:, self.pool].ravel()
                X = np.stack([c[rp][:, self.pool].ravel() for c in cols], 1)
                ok_ = ~np.isnan(Y) & ~np.isnan(X).any(1)
                if ok_.sum() >= 30:
                    A = np.column_stack([np.ones(ok_.sum()), X[ok_]])
                    self.rho[p, :len(cols)] = np.linalg.lstsq(A, Y[ok_], rcond=None)[0][1:]

    def regions(self, mask):
        return [r for r in range(self.ctx.R) if mask[r] and self.remap[r] >= 0
                and self.fit.n_years[self.remap[r]] >= MIN_FIT_YEARS]

    def soil_shift(self, r, T, use=("fall", "wspr")):
        """Shift (S,) to add to each past summer's soil-moisture anomaly so that it starts from season
        T's conditions. Observed indices replace the analog's own (rho * (now - then)). A forecast index
        (ECMWF winter-spring precipitation) only moves the centre (rho * forecast anomaly) and keeps every
        analog's own variation, because the forecast's skill is unknown: deliberately conservative."""
        ctx = self.ctx
        ti = T - ctx.cy0
        p = ctx.p_of_r[r]
        out = np.zeros(self.pool.sum())
        if self.ante == "none" or not 0 <= ti < len(ctx.years):
            return out
        f_now = ctx.fall[r, ti]
        if "fall" in use and not np.isnan(f_now):
            out += self.rho[p, 0] * (f_now - np.nan_to_num(ctx.fall[r, self.pool]))
        w_now = ctx.wspr[r, ti]
        if self.ante == "fall+wspr" and "wspr" in use and not np.isnan(w_now):
            if ctx.wspr_fc[ti]:
                out += self.rho[p, 1] * w_now
            else:
                out += self.rho[p, 1] * (w_now - np.nan_to_num(ctx.wspr[r, self.pool]))
        return out

    def level(self, j, year):
        """log yield of (fitted) region j in `year` with every weather term at its training mean"""
        return self.fit.trend(j, (year - 2000) / 10.0)[0]

    def theta(self, j):
        return self.fit.theta(j) / self.xs

    def weather_effect(self, r, Bv):
        """Weather part of log yield for region r and seasons Bv (n, n_cols), relative to level()."""
        j = self.remap[r]
        g = (feats(Bv, self.terms) - self.xm) @ self.theta(j)
        if not self.analog:
            return g
        Z = np.concatenate([Bv[:, self.an_c] / self.an_s, np.repeat(ANALOG_LOC * self.loc[r][None], len(Bv), 0)], 1)
        d2 = ((Z[:, None, :] - self.an_Z[None]) ** 2).sum(-1)
        k = min(ANALOG_K, d2.shape[1] - 1)
        idx = np.argpartition(d2, k, 1)[:, :k]
        dk = np.take_along_axis(d2, idx, 1)
        w = (1 - (dk / np.maximum(dk.max(1, keepdims=True), 1e-9)) ** 1.5) ** 3 + 1e-6  # tricube on distance
        a = (w * self.an_y[idx]).sum(1) / w.sum(1)
        return ANALOG_BLEND * a + (1 - ANALOG_BLEND) * g

    def season_cols(self, r, T, extra_dT=0.0, climate_of=None, ante_use=("fall", "wspr")):
        """Every past season's weather columns (S, n_cols) for region r, moved onto season T: temperatures
        onto the climate of `climate_of` (default T) along the warming trend (+ extra_dT), soil wetness onto
        T's starting conditions. Clipped to the training range; also returns how many temperatures were."""
        s_years = self.ctx.years[self.pool]
        to = T if climate_of is None else climate_of
        Bs = np.nan_to_num(self.B[r][self.pool]).copy()
        warm = self.rate[r] * (to - s_years) + extra_dT
        clipped = 0
        for i, c in enumerate(self.cols):
            if c.kind == "T":
                Bs[:, i] += warm
                clipped = int(((Bs[:, i] < self.lo[i]) | (Bs[:, i] > self.hi[i])).sum())
            elif c.kind == "H":
                bases = self.ctx.kdd_bases
                pos = np.clip(HEAT_BASE - warm - bases[0], 0, len(bases) - 1)
                i0 = np.minimum(np.floor(pos).astype(int), len(bases) - 2)
                f = pos - i0
                st = np.nan_to_num(c.stack[r][self.pool])
                rows = np.arange(len(st))
                Bs[:, i] = np.sqrt(np.maximum(st[rows, i0] * (1 - f) + st[rows, i0 + 1] * f, 0))
            elif c.kind == "V":
                Bs[:, i] += self.vrate[i][r] * (to - s_years)
            elif c.kind == "S":
                Bs[:, i] += self.soil_shift(r, T, ante_use)
        return np.clip(Bs, self.lo, self.hi), clipped

    def members(self, regions, T, extra_dT=0.0, climate_of=None, ante_use=("fall", "wspr")):
        """Ensemble member means (U, S) and total SD (U,) for target season T (see season_cols), and the
        share of moved temperatures that fell outside the training range."""
        fit = self.fit
        mu = np.zeros((len(regions), self.pool.sum()))
        sd = np.zeros(len(regions))
        clipped = 0
        for u, r in enumerate(regions):
            j = self.remap[r]
            Bs, c = self.season_cols(r, T, extra_dT, climate_of, ante_use)
            clipped += c
            _, tv = fit.trend(j, (T - 2000) / 10.0)
            mu[u] = self.level(j, T) + self.weather_effect(r, Bs)
            sd[u] = math.sqrt(fit.sig2[j] + tv)
        return mu, sd, clipped / max(mu.size, 1)

    def predict_known(self, r, ti):
        """log yield the model gives region r in year index ti if that season's weather were known."""
        Bv = np.clip(self.B[r, ti], self.lo, self.hi)[None]
        return self.level(self.remap[r], self.ctx.years[ti]) + self.weather_effect(r, Bv)[0]


def hindcast(ctx, configs, trend=TREND, enso=ENSO_TERM, codes=None, verbose=True, ante=ANTE, ante_use=("fall",)):
    """Forward-chaining hindcast: for each year t >= HIND0, fit on years < t and forecast t.
    Returns {code: [record per year]} with CRPS and PIT per ENSO weighting config.
    By default only the starting conditions known in November are used (the fall soil moisture);
    ante_use=("fall", "wspr") also feeds the observed Oct-May precipitation, i.e. a perfect seasonal
    precipitation forecast: an upper bound on what that forecast could add, not a fair test."""
    out = {}
    for code in codes or ctx.crop:
        d = ctx.crop[code]
        recs = []
        for t in range(HIND0, ctx.Y1 + 1):
            m = Model(ctx, code, t - 1, trend, enso, ante)
            if not m.valid:
                continue
            ti = t - ctx.cy0
            regions = m.regions(d["ok"][:, ti])
            if not regions:
                continue
            mu, sd, _ = m.members(regions, t, ante_use=ante_use)
            yv = d["obs"][regions, ti]
            fc = stat_enso_forecast(ctx.roni, t)
            # if the summer's weather had been known: for the "share of the swing explained by weather" score
            mu0 = m.members(regions, t, ante_use=())[0]
            normal = mix_quantiles(mu0, np.full(mu0.shape[1], 1 / mu0.shape[1]), sd, [0.5])[:, 0]
            known = np.array([m.predict_known(r, ti) if not np.isnan(m.B[r, ti]).any() else np.nan for r in regions])
            rec = dict(year=t, regions=regions, y=yv, mu=mu, sd=sd, fc=fc, crps={}, pit={}, normal=normal, known=known)
            for cfg in configs:
                w = enso_weights(ctx.roni_d[m.pool], ctx.roni_j[m.pool], fc, *cfg)
                rec["crps"][cfg] = crps_mix(yv, mu, w, sd)
                rec["pit"][cfg] = mix_cdf(yv, mu, w, sd)
            # naive baseline: mean of the last 5 observed years, spread of the last 15
            nv = []
            for r, y_ in zip(regions, yv):
                past = d["obs"][r, :ti][~np.isnan(d["obs"][r, :ti])]
                nv.append(crps_norm(y_, past[-5:].mean(), max(past[-15:].std(ddof=1), 0.05))
                          if len(past) >= 5 else np.nan)
            rec["naive"] = np.array(nv)
            recs.append(rec)
        out[code] = recs
        if verbose:
            print(f"  hindcast {code}: {sum(len(r['regions']) for r in recs)} region-years", flush=True)
    return out


def total_crps(hind, cfg):
    return sum(r["crps"][cfg].sum() for recs in hind.values() for r in recs)


def compare(ctx):
    """Score the alternative model forms on the same hindcast (ENSO-blind and best ENSO weighting)."""
    cfgs = [(h, lam) for h in GRID_H for lam in GRID_LAM if not (lam == 0 and h != GRID_H[0])]
    base = None
    print("\nmodel-form comparison (total hindcast CRPS, log-yield units; lower is better)")
    variants = [("linear", False, "none", ("fall",)), ("hinge", False, "none", ("fall",)),
                ("recency", False, "none", ("fall",)), ("linear", True, "none", ("fall",)),
                ("recency", False, "fall", ("fall",)),
                ("recency", False, "fall+wspr", ("fall", "wspr"))]  # last: perfect Oct-May precipitation
    for trend, enso, ante, use in variants:
        h = hindcast(ctx, cfgs, trend, enso, verbose=False, ante=ante, ante_use=use)
        blind = total_crps(h, (GRID_H[0], 0.0))
        best = min(cfgs, key=lambda c: total_crps(h, c))
        naive = sum(np.nansum(r["naive"]) for recs in h.values() for r in recs)
        base = base or blind
        bias = np.concatenate([r["pit"][best] for recs in h.values() for r in recs]).mean()
        tag = ante + (" (perfect Oct-May precip)" if "wspr" in use and ante == "fall+wspr" else "")
        print(f"  trend={trend:7s} enso_term={enso!s:5s} start={tag:34s} no-ENSO {blind:8.2f} ({100 * (1 - blind / base):+.2f}%)"
              f"  best ENSO {total_crps(h, best):8.2f} at h={best[0]} lam={best[1]}"
              f"  naive {naive:8.2f}  mean PIT {bias:.3f}")
        per = {}
        for c, recs in h.items():
            if recs:
                m = np.concatenate([r["crps"][best] for r in recs])
                nv = np.concatenate([r["naive"] for r in recs])
                ok = ~np.isnan(nv)
                per[c] = 100 * (1 - m[ok].sum() / nv[ok].sum())
        print("      vs naive by crop: " + "  ".join(f"{c} {v:+.1f}" for c, v in per.items()))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=None, help="growing season to forecast (default: enso_forecast.json)")
    ap.add_argument("--compare", action="store_true", help="also score alternative model forms")
    a = ap.parse_args()
    ctx = Ctx(a.target)
    if a.compare:
        compare(ctx)
    T, years, cy0, Y1, R = ctx.T, ctx.years, ctx.cy0, ctx.Y1, ctx.R

    configs = [(h, lam) for h in GRID_H for lam in GRID_LAM if not (lam == 0 and h != GRID_H[0])]
    print(f"\nhindcast {HIND0}-{Y1} (trend={TREND}, enso_term={ENSO_TERM})")
    hind = hindcast(ctx, configs)
    blind = (GRID_H[0], 0.0)
    crps_tot = {c: total_crps(hind, c) for c in configs}
    best = min(configs, key=lambda c: crps_tot[c])
    print("hindcast CRPS by ENSO weighting (h, lam), lower is better:")
    for cfg in configs:
        print(f"  h={cfg[0]:.1f} lam={cfg[1]:.2f}: {crps_tot[cfg]:.3f}"
              f"  ({100 * (1 - crps_tot[cfg] / crps_tot[blind]):+.2f}% vs no ENSO)")
    print(f"chosen h={best[0]} lam={best[1]}")

    def weights_for(rec):
        pool = years < rec["year"]
        return enso_weights(ctx.roni_d[pool], ctx.roni_j[pool], rec["fc"], *best)

    # ------------------------------------------------------------------ calibration from hindcast PIT
    # Spread only, symmetric about the model median: we learn how far from 0.5 the hindcast PITs fall
    # (|PIT - 0.5|), not where they centre. A location correction learned on 2001-2025 would import
    # 2009-2016's run of yields beating the trend, which has not held since (see "recent_below").
    def dev_of(pits):
        return np.sort(np.abs(np.clip(pits, 1e-6, 1 - 1e-6) - 0.5))

    all_dev = dev_of(np.concatenate([r["pit"][best] for recs in hind.values() for r in recs]))
    cal = {}
    for code, recs in hind.items():
        pc = np.concatenate([r["pit"][best] for r in recs]) if recs else np.array([])
        # per-crop deviations, shrunk toward the all-crop distribution by mixing in 400 pseudo-samples
        cal[code] = np.sort(np.concatenate([dev_of(pc), np.quantile(all_dev, np.linspace(0, 1, 400))]))

    def level_map(dev, levels):
        """Nominal level -> model level with the same central coverage in hindcast."""
        levels = np.asarray(levels, dtype=np.float64)
        a = np.quantile(dev, np.abs(2 * levels - 1))
        return 0.5 + np.sign(levels - 0.5) * a

    def recal_levels(code, levels):
        """So a nominal 80 % range covers ~80 % of hindcast outcomes."""
        return level_map(cal[code], levels)

    def recal_prob(code, p):
        p = np.asarray(p, dtype=np.float64)
        c = np.searchsorted(cal[code], np.abs(p - 0.5)) / len(cal[code])
        return 0.5 + np.sign(p - 0.5) * c / 2

    # skill summary per crop (coverage uses leave-that-year-out recalibration, so it is out of sample)
    skill = {}
    rng = np.random.default_rng(0)
    # all crops together, resampling years: is the ENSO gain distinguishable from zero?
    yrs_all = sorted({r["year"] for recs in hind.values() for r in recs})
    by_b = np.array([sum(r["crps"][best].sum() for recs in hind.values() for r in recs if r["year"] == y) for y in yrs_all])
    by_0 = np.array([sum(r["crps"][blind].sum() for recs in hind.values() for r in recs if r["year"] == y) for y in yrs_all])
    idx = rng.integers(0, len(yrs_all), (N_BOOT, len(yrs_all)))
    g_all = 100 * (1 - by_b[idx].sum(1) / by_0[idx].sum(1))
    enso_gain = {"crpss": round(100 * (1 - by_b.sum() / by_0.sum()), 2),
                 "ci90": [round(float(np.percentile(g_all, 5)), 2), round(float(np.percentile(g_all, 95)), 2)],
                 "p_gain_le_0": round(float((g_all <= 0).mean()), 3)}
    print(f"ENSO weighting gain, all crops: {enso_gain['crpss']:+.2f}% CRPS, 90% CI {enso_gain['ci90']}, "
          f"P(gain <= 0) = {enso_gain['p_gain_le_0']}")
    for code, recs in hind.items():
        if not recs:
            continue
        c_b = np.concatenate([r["crps"][best] for r in recs])
        c_0 = np.concatenate([r["crps"][blind] for r in recs])
        c_n = np.concatenate([r["naive"] for r in recs])
        okn = ~np.isnan(c_n)
        raw_pit = np.concatenate([r["pit"][best] for r in recs])
        cov80 = cov95 = n_ = 0
        abs_err, by_year = [], []
        for r in recs:
            others = dev_of(np.concatenate([o["pit"][best] for o in recs if o["year"] != r["year"]]))
            lv = level_map(others, [0.025, 0.1, 0.5, 0.9, 0.975])
            p = r["pit"][best]
            cov80 += int(((p >= lv[1]) & (p <= lv[3])).sum())
            cov95 += int(((p >= lv[0]) & (p <= lv[4])).sum())
            n_ += len(p)
            med = mix_quantiles(r["mu"], weights_for(r), r["sd"], [lv[2]])[:, 0]
            abs_err.append(np.abs(np.exp(r["y"] - med) - 1))
            by_year.append([r["year"], round(100 * (1 - r["crps"][best].sum() / r["crps"][blind].sum()), 1)])
        abs_err = np.concatenate(abs_err)
        # bootstrap over hindcast years (regions within a year share its weather, so years are the unit)
        yb = np.array([r["crps"][best].sum() for r in recs])
        y0_ = np.array([r["crps"][blind].sum() for r in recs])
        idx = rng.integers(0, len(recs), (N_BOOT, len(recs)))
        g = 100 * (1 - yb[idx].sum(1) / y0_[idx].sum(1))
        # share of the year-to-year swing around a normal year that the summer's weather explains, out of
        # sample (each year's model fitted on earlier years): the ceiling for any seasonal weather forecast
        yy_ = np.concatenate([r["y"] for r in recs])
        kn_ = np.concatenate([r["known"] for r in recs])
        no_ = np.concatenate([r["normal"] for r in recs])
        okw = ~np.isnan(kn_)
        r2w = 100 * (1 - np.sum((yy_[okw] - kn_[okw]) ** 2) / np.sum((yy_[okw] - no_[okw]) ** 2))
        strong = [r for r in recs if ctx.roni_d[r["year"] - cy0] >= 1.0]
        sk_strong = None
        if strong:
            sb = np.concatenate([r["crps"][best] for r in strong]).sum()
            s0 = np.concatenate([r["crps"][blind] for r in strong]).sum()
            sk_strong = round(100 * (1 - sb / s0), 1)
        skill[code] = {
            "n": int(len(c_b)), "years": [recs[0]["year"], recs[-1]["year"]],
            "crpss_enso": round(100 * (1 - c_b.sum() / c_0.sum()), 1),
            "crpss_enso_90ci": [round(float(np.percentile(g, 5)), 1), round(float(np.percentile(g, 95)), 1)],
            "crpss_naive": round(100 * (1 - c_b[okn].sum() / c_n[okn].sum()), 1),
            "crpss_enso_strong_nino": sk_strong,
            "strong_nino_years": [r["year"] for r in strong],
            "cov80": round(100 * cov80 / n_, 1), "cov95": round(100 * cov95 / n_, 1),
            "cov80_raw": round(100 * float(((raw_pit >= 0.1) & (raw_pit <= 0.9)).mean()), 1),
            "cov95_raw": round(100 * float(((raw_pit >= 0.025) & (raw_pit <= 0.975)).mean()), 1),
            "mape": round(100 * float(np.median(abs_err)), 1),
            "r2_weather": round(float(r2w)),
            "mean_pit": round(float(raw_pit.mean()), 3),
            # recent drift: share of outcomes since RECENT0 below the (recalibrated) middle estimate.
            # ~50% = unbiased; well above 50% = the middle estimate has been optimistic lately
            "recent_from": RECENT0,
            "recent_below": round(100 * float(np.mean(np.concatenate(
                [r["pit"][best] for r in recs if r["year"] >= RECENT0] or [np.array([np.nan])]) < 0.5)), 1),
        }
        s = skill[code]
        print(f"  {code:7s} n={s['n']:4d}  ENSO skill {s['crpss_enso']:+5.1f}% {s['crpss_enso_90ci']}  vs naive {s['crpss_naive']:+5.1f}%  "
              f"strong-Nino {sk_strong}  cover80 {s['cov80']} (raw {s['cov80_raw']})  cover95 {s['cov95']} "
              f"(raw {s['cov95_raw']})  median |err| {s['mape']}%  weather explains {s['r2_weather']}%  mean PIT {s['mean_pit']}  "
              f"below middle since {RECENT0}: {s['recent_below']}%")

    # ------------------------------------------------------------------ the real forecast
    # past summers up to the last fully observed one (it may not have published yields yet)
    pool = (years <= ctx.W1) & ~np.isnan(ctx.roni_d) & ~np.isnan(ctx.roni_j)
    w_now = enso_weights(ctx.roni_d[pool], ctx.roni_j[pool], ctx.fc_now, *best)
    w_blind = np.full(pool.sum(), 1.0 / pool.sum())
    ess = float(1 / (w_now ** 2).sum())
    order = np.argsort(-w_now)
    analogs = [{"year": int(years[pool][i]), "djf": float(ctx.roni_d[pool][i]), "jja": float(ctx.roni_j[pool][i]),
                "w": round(float(w_now[i]), 4)} for i in order[:8]]
    print(f"\nforecast {T}: ENSO weights ESS={ess:.1f} of {pool.sum()} seasons; top analogs " +
          ", ".join(f"{x['year']} ({100 * x['w']:.0f}%)" for x in analogs[:5]))
    lv_nom = np.array(LEVELS)
    normal_mid = (NORMAL[0] + NORMAL[1]) / 2
    last5 = slice(Y1 - cy0 - 4, Y1 - cy0 + 1)   # the last 5 years with yields
    ti_T = T - cy0
    wspr_fc = bool(0 <= ti_T < len(years) and ctx.wspr_fc[ti_T])
    alt = ecmwf_enso_alternative(ctx)
    w_alt = enso_weights(ctx.roni_d[pool], ctx.roni_j[pool], alt["fc"], *best) if alt else None
    if alt:
        print(f"ECMWF (fetch_forecast.py) DJF ONI {alt['djf_oni']:+.2f} = RONI {alt['djf_roni']:+.2f} after the "
              f"recent ONI-RONI offset {alt['offset']:+.2f}; CPC DJF RONI median {ctx.fc_now['mD']:+.2f}")

    forecasts, hind_out, used_keys = {}, {}, set()
    for code, d in ctx.crop.items():
        m = Model(ctx, code, Y1, pool_last=ctx.W1)
        if not m.valid or code not in cal:
            continue
        assert (m.pool == pool).all(), "analog seasons differ between crops"
        # regions that still grow the crop: observed in >= 3 of the last 5 years
        regions = m.regions(d["ok"][:, last5].sum(1) >= 3)
        if not regions:
            continue
        lv = recal_levels(code, lv_nom)
        lv_med = lv[LEVELS.index(0.5)]
        mu, sd, _ = m.members(regions, T)
        mu_0, _, _ = m.members(regions, T, ante_use=())       # no starting conditions
        mu_n, _, _ = m.members(regions, T, climate_of=normal_mid, ante_use=())
        # what each starting condition does to the middle estimate (ENSO-weighted)
        mu_f, _, _ = m.members(regions, T, ante_use=("fall",))
        med_0, med_f = (mix_quantiles(x, w_now, sd, [lv_med])[:, 0] for x in (mu_0, mu_f))
        q = mix_quantiles(mu, w_now, sd, lv)
        qb = mix_quantiles(mu, w_blind, sd, lv)          # same, without the El Nino weighting
        # "normal year" = calibrated median with no seasonal information at all (every past summer
        # equally likely, no starting conditions), in today's climate and with today's farming
        normal = mix_quantiles(mu_0, w_blind, sd, [lv_med])[:, 0]
        normal_raw = mix_quantiles(mu_0, w_blind, sd, [0.5])[:, 0]
        normal_9120 = mix_quantiles(mu_n, w_blind, sd, [lv_med])[:, 0]
        med_alt = mix_quantiles(mu, w_alt, sd, [lv_med])[:, 0] if alt else None
        p_below = recal_prob(code, mix_cdf(normal, mu, w_now, sd))
        p_short = recal_prob(code, mix_cdf(normal + math.log(0.8), mu, w_now, sd))
        p_short_usual = recal_prob(code, mix_cdf(normal + math.log(0.8), mu_0, w_blind, sd))
        scen = []
        for x in WARMING:
            mu_w, _, clip_share = m.members(regions, T, extra_dT=x)
            scen.append((mix_quantiles(mu_w, w_now, sd, lv), clip_share))
        out = {}
        for u, r in enumerate(regions):
            k = ctx.keys[r]
            used_keys.add(k)
            out[k] = {
                "q": [int(round(math.exp(v))) for v in q[u]],
                "qb": [int(round(math.exp(v))) for v in qb[u]],
                "normal": int(round(math.exp(normal[u]))),
                "normal9120": int(round(math.exp(normal_9120[u]))),
                "p_below": round(float(p_below[u]), 3),
                "p_short": round(float(p_short[u]), 3),
                "p_short_usual": round(float(p_short_usual[u]), 3),
                "warm": [[int(round(math.exp(v))) for v in sq[0][u]] for sq in scen],
                "dT_now": round(float(m.rate[r] * (T - normal_mid)), 2),
                "last5": int(round(float(np.nanmean(np.exp(d["obs"][r, last5]))))),
                # starting conditions: fall soil moisture (z vs 1991-2020) and Oct-May precipitation
                # (% of normal; mostly the ECMWF forecast), and what each does to the middle estimate (%)
                "fall_z": None if np.isnan(ctx.fall[r, ti_T]) else round(float(ctx.fall[r, ti_T]), 2),
                "wspr_pct": None if np.isnan(ctx.wspr_pct[r, ti_T]) else round(float(ctx.wspr_pct[r, ti_T])),
                "fx_fall": round(100 * (math.exp(med_f[u] - med_0[u]) - 1), 1),
                "fx_wspr": round(100 * (math.exp(q[u][LEVELS.index(0.5)] - med_f[u]) - 1), 1),
                "years": int(m.fit.n_years[m.remap[r]]),
                # "if this summer's weather repeated analog year s, in today's climate": % vs a normal year,
                # for the most heavily weighted analogs (same order as enso.analogs)
                "an": [round(100 * (math.exp(mu[u, i] - normal_raw[u]) - 1), 1) for i in order[:N_ANALOG_SHOW]],
            }
            if alt:
                out[k]["alt_med"] = int(round(math.exp(med_alt[u])))
        forecasts[code] = out
        clip_note = ", ".join(f"+{x:g}C {100 * s[1]:.0f}%" for x, s in zip(WARMING, scen))
        med = np.array([v["q"][3] / v["normal"] - 1 for v in out.values()])
        cc = np.array([v["normal"] / v["normal9120"] - 1 for v in out.values()])
        ff = np.array([v["fx_fall"] for v in out.values()])
        fw = np.array([v["fx_wspr"] for v in out.values()])
        alt_note = (f"; with ECMWF DJF instead {100 * np.mean([v['alt_med'] / v['normal'] - 1 for v in out.values()]):+.1f}%"
                    if alt else "")
        print(f"  {code:7s} {len(out):3d} regions; vs normal {100 * med.min():+.1f}..{100 * med.max():+.1f}% "
              f"(mean {100 * med.mean():+.1f}%{alt_note}); fall soil {ff.mean():+.1f}%, Oct-May precip {fw.mean():+.1f}%; "
              f"warming since 1991-2020 {100 * cc.mean():+.1f}%; clipped: {clip_note}")

        # hindcast series for the map panel: recalibrated 10/50/90 % + what happened
        hs = {}
        lv3 = recal_levels(code, [0.1, 0.5, 0.9])
        for rec in hind.get(code, []):
            qq = mix_quantiles(rec["mu"], weights_for(rec), rec["sd"], lv3)
            for u, r in enumerate(rec["regions"]):
                k = ctx.keys[r]
                if k in out:
                    hs.setdefault(k, []).append([rec["year"]] + [int(round(math.exp(v))) for v in qq[u]]
                                                + [int(round(math.exp(rec["y"][u])))])
        hind_out[code] = hs

    eco_out = {str(e): k for e, k in ctx.latest.items() if k in used_keys and str(e) in ctx.eco}
    regions_out = {k: {"name": region_name(k, ctx.geo_names.get(k, "")), "prov": SGC_PROV[int(k[:2])]}
                   for k in sorted(used_keys)}

    doc = {
        "issued": datetime.date.today().isoformat(),
        "target": T,
        "units": "kg/ha",
        "levels": LEVELS,
        "crops": [[c[1], c[2]] for c in CROPS if c[1] in forecasts],
        "enso": {
            "source": "NOAA CPC ENSO outlook (RONI), issued " + ctx.fjson["issued"],
            "status": ctx.fjson.get("status", ""),
            "djf": {"median": ctx.fc_now["mD"], "sd": round(ctx.fc_now["sD"], 2)},
            "jja": {"median": ctx.fc_now["mJ"], "sd": round(ctx.fc_now["sJ"], 2)},
            "strength_bins": ctx.fjson.get("strength_bins"),
            "strength_probs": {s: ctx.fjson["strength_probs"][s] for s in ("DJF", "JJA")
                               if s in ctx.fjson.get("strength_probs", {})},
            "kernel_h": best[0], "lam": best[1], "ess": round(ess, 1), "n_seasons": int(pool.sum()),
            "analogs": analogs, "hindcast_gain": enso_gain,
            "ecmwf": None if not alt else {k: v for k, v in alt.items() if k != "fc"},
        },
        "start": {
            "fall": "root-zone soil wetness Aug-Sep %d (NASA POWER, observed), z vs 1991-2020" % (T - 1),
            "wspr": "precipitation Oct %d - May %d, %% of 1991-2020 normal" % (T - 1, T)
                    + (" (ERA5 + ECMWF seasonal forecast via Meteomatics, issued %s)" % ctx.ext.get("issued")
                       if wspr_fc else " (observed)"),
            "wspr_is_forecast": wspr_fc,
            "mode": ANTE,
        },
        "warming": WARMING,
        # how the weather part of yield is computed (the map's "How" text reads this)
        "weather_model": {"columns": {c: [x.name for x in d["cols"]] for c, d in ctx.crop.items() if c in forecasts},
                          "analog_blend": ANALOG_BLEND, "analog_k": ANALOG_K, "analog_cols": list(ANALOG_COLS)},
        "method": {
            "target": "Observed average yield by Statistics Canada Small Area Data Region (table 32-10-0002), "
                      "region-years seeded >= %d ha, %d-%d" % (MIN_HA, cy0, Y1),
            "weather": "NASA POWER, cropland-weighted per region: growing-season mean daily high and root-zone soil "
                       "wetness (anomalies vs %d-%d, monthly data), heat degree-days above 30 C, longest dry spell, "
                       "wettest 5 days and killing-frost days (daily data)" % NORMAL,
            "model": f"log yield = region level + technology trend ({TREND}: province trend + shrunk regional deviation) "
                     f"+ weather effect: {ANALOG_BLEND:g} x conditions-based analogs (mean yield anomaly of the "
                     f"{ANALOG_K} most similar region-years in any region, by summer heat, soil wetness and "
                     "location) + "
                     f"{1 - ANALOG_BLEND:g} x regression (crop-wide + shrunk provincial response, with heat and "
                     "drought curvature)" + (" + RONI DJF/JJA" if ENSO_TERM else ""),
            "climate_change": "each past season's temperature is moved onto the target year's climate along the region's "
                              "observed %d-%d warming trend, and its heat degree-days re-read at the threshold lowered "
                              "by the same warming" % (cy0, ctx.W1),
            "starting_conditions": "each past summer's soil moisture is moved onto this season's starting point: "
                                   "the observed fall root-zone wetness replaces the analog's own (per-province "
                                   "regression of summer soil moisture on it); a forecast of Oct-May precipitation "
                                   "only shifts the centre and keeps every analog's spread (its skill is unknown)",
            "enso": "past seasons weighted by closeness of their DJF and JJA RONI to the CPC forecast, "
                    "kernel bandwidth and blend chosen by hindcast",
            "confidence": "mixture quantiles widened/narrowed symmetrically about the median so that central ranges "
                          "match their coverage in forward-chaining hindcasts (%d-%d)" % (HIND0, Y1),
            "normal": "median of the same model with every past season weighted equally (no ENSO information), "
                      "in today's climate: what an average year would bring with today's farming and climate",
            "caveats": [
                "Regional (Census Agricultural Region) yields: every ecodistrict in a region shows the same forecast.",
                "A very strong El Nino has only ~4 analogs since 1981 (1983, 1992, 1998, 2016); 1992 also had the "
                "Pinatubo cooling.",
                "No CO2 fertilisation, adaptation or variety change beyond the fitted technology trend.",
                "Warming scenarios extrapolate a statistical model; temperatures beyond the observed range are clipped, "
                "so damage from unprecedented heat is understated.",
                "Hindcasts used a simple statistical ENSO forecast; CPC's real forecasts are at least as good, "
                "so hindcast skill is a conservative guide.",
                "Hail, frost, disease, harvest weather and prices are not modelled; they sit in the residual spread.",
            ],
        },
        "skill": skill,
        "regions": regions_out,
        "eco": eco_out,
        # regions where StatCan publishes the crop at all (any year), so the map can tell "not published
        # here" (e.g. no regional wheat or canola for Ontario / Quebec) from "too little grown to forecast"
        "published": {c[1]: sorted({k for (k, code) in ctx.yld_keys if code == c[1] and k in regions_out})
                      for c in CROPS if c[1] in forecasts},
        "f": forecasts,
        "hind": hind_out,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} kB): {len(forecasts)} crops, "
          f"{len(regions_out)} regions, {len(eco_out)} ecodistricts")


if __name__ == "__main__":
    main()
