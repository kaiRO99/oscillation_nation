"""Soil properties per ecodistrict from the Soil Landscapes of Canada (SLC) v3.2.

Usage:  python scripts/fetch_soil.py
Reads   data/raw/slc/   (downloaded automatically: SLC v3.2 tables + National Soil DataBase name/layer tables)
Writes  data/raw/soil.json   per ecodistrict: available water holding capacity, topsoil texture, organic carbon,
                             pH, dominant soil order, drainage, province

How it works: every SLC polygon nests inside one ecodistrict (polygon table ECO_ID). Each polygon lists its
soil components with a percentage; each component points to a soil profile with measured layers. Values
are weighted by polygon land area x component percent. Water holding capacity is the field capacity minus
the wilting point (KP33 - KP1500, % by volume) summed over 0-100 cm, minus coarse fragments; when those
are missing they are estimated from texture and organic matter (Saxton & Rawls 2006).

Source: AAFC CanSIS, Soil Landscapes of Canada v3.2, Open Government Licence - Canada. Needs `dbfread`.
"""
import collections
import json
import urllib.request
import zipfile
from pathlib import Path

from dbfread import DBF

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "slc"
DST = ROOT / "data" / "raw" / "soil.json"
ZIP_URL = "https://sis.agr.gc.ca/nsdb/ca/cac003/cac003.20110308.v3.2/ca_all_slc_v3r2.zip"
UA = {"User-Agent": "oscillation-nation-data-script"}
DEPTH = 100  # cm, for water holding capacity
TOP = 30     # cm, for topsoil texture / carbon / pH

ORDERS = {
    "BR": "Brunisolic", "CH": "Chernozemic", "CY": "Cryosolic", "GL": "Gleysolic", "LU": "Luvisolic",
    "OR": "Organic", "PZ": "Podzolic", "RG": "Regosolic", "SZ": "Solonetzic", "VE": "Vertisolic",
}
DRAINAGE = {"VR": 1, "R": 2, "W": 3, "MW": 4, "I": 5, "P": 6, "VP": 7}  # very rapid .. very poor


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    z = RAW / "ca_all_slc_v3r2.zip"
    if not z.exists():
        print("downloading", ZIP_URL)
        with urllib.request.urlopen(urllib.request.Request(ZIP_URL, headers=UA), timeout=600) as r:
            z.write_bytes(r.read())
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            if n.endswith(".dbf") and not (RAW / n).exists():
                zf.extract(n, RAW)


def table(pattern):
    return list(DBF(next(RAW.glob(pattern)), char_decode_errors="replace"))


def saxton_rawls(sand, clay, om):
    """Volumetric water (%) at 33 kPa and 1500 kPa from sand/clay (%) and organic matter (%)."""
    s, c = sand / 100, clay / 100
    t15 = -0.024 * s + 0.487 * c + 0.006 * om + 0.005 * s * om - 0.013 * c * om + 0.068 * s * c + 0.031
    w15 = t15 + (0.14 * t15 - 0.02)
    t33 = -0.251 * s + 0.195 * c + 0.011 * om + 0.006 * s * om - 0.027 * c * om + 0.452 * s * c + 0.299
    w33 = t33 + (1.283 * t33 * t33 - 0.374 * t33 - 0.015)
    return w33 * 100, w15 * 100


def ok(v):
    return v is not None and v >= 0


def profile(layers):
    """Summarise one soil profile (its layers) into a few numbers."""
    awhc, top = 0.0, collections.defaultdict(float)
    covered = topw = 0.0
    for L in layers:
        u, l = max(L["UDEPTH"], 0), min(L["LDEPTH"], DEPTH)
        if l <= u:
            continue
        frag = L["COFRAG"] / 100 if ok(L["COFRAG"]) else 0
        fc, wp = L["KP33"], L["KP1500"]
        if not (ok(fc) and ok(wp) and fc >= wp) and ok(L["TSAND"]) and ok(L["TCLAY"]):
            om = L["ORGCARB"] * 1.724 if ok(L["ORGCARB"]) else 2.0
            fc, wp = saxton_rawls(L["TSAND"], L["TCLAY"], min(om, 8))
        if ok(fc) and ok(wp) and fc >= wp:
            awhc += (fc - wp) / 100 * (l - u) * 10 * (1 - frag)  # mm
            covered += l - u
        tu, tl = u, min(l, TOP)
        if tl > tu:
            w = tl - tu
            for k, src in (("sand", "TSAND"), ("silt", "TSILT"), ("clay", "TCLAY"), ("oc", "ORGCARB"), ("ph", "PHCA")):
                if ok(L[src]):
                    top[k] += L[src] * w
                    top[k + "_w"] += w
            topw += w
    out = {"awhc": awhc * DEPTH / covered if covered >= DEPTH / 2 else None}  # scale up partially described profiles
    for k in ("sand", "silt", "clay", "oc", "ph"):
        out[k] = top[k] / top[k + "_w"] if top[k + "_w"] else None
    return out


def main():
    download()
    polys = table("ca_all_slc_v3r2.dbf")
    land = {r["POLY_ID"]: r["LAND_AREA"] for r in table("ca_all_slc_v3r2_lat.dbf")}
    cmp = table("ca_all_slc_v3r2_cmp.dbf")
    names = {r["SOIL_ID"]: r for r in table("soil_name_canada_*.dbf")}
    layers = collections.defaultdict(list)
    for r in table("soil_layer_canada_*.dbf"):
        layers[r["SOIL_ID"]].append(r)
    profiles = {sid: profile(sorted(ls, key=lambda r: r["LAYER_NO"])) for sid, ls in layers.items()}

    poly_eco = {r["POLY_ID"]: int(r["ECO_ID"]) for r in polys}
    acc = collections.defaultdict(lambda: collections.defaultdict(float))
    for c in cmp:
        eco = poly_eco.get(c["POLY_ID"])
        if eco is None:
            continue
        w = land.get(c["POLY_ID"], 0) * c["PERCENT"] / 100
        if w <= 0:
            continue
        a = acc[eco]
        a["_w"] += w
        a["prov:" + c["PROVINCE"]] += w
        n = names.get(c["SOIL_ID"])
        if n is None:
            continue
        a["order:" + (n["ORDER3"] if n["ORDER3"] in ORDERS else "-")] += w
        if n["DRAINAGE"] in DRAINAGE:
            a["drain"] += DRAINAGE[n["DRAINAGE"]] * w
            a["drain_w"] += w
        for k, v in profiles.get(c["SOIL_ID"], {}).items():
            if v is not None:
                a[k] += v * w
                a[k + "_w"] += w

    out = {}
    for eco, a in sorted(acc.items()):
        rec = {}
        for k, nd in (("awhc", 0), ("sand", 0), ("silt", 0), ("clay", 0), ("oc", 2), ("ph", 1)):
            rec[k] = round(a[k] / a[k + "_w"], nd) if a[k + "_w"] > 0.25 * a["_w"] else None
        rec["drainage"] = round(a["drain"] / a["drain_w"], 1) if a["drain_w"] else None
        orders = {k[6:]: v for k, v in a.items() if k.startswith("order:") and k != "order:-"}
        rec["order"] = max(orders, key=orders.get) if orders else None
        rec["order_pct"] = round(100 * orders[rec["order"]] / a["_w"]) if orders else 0
        provs = {k[5:]: v for k, v in a.items() if k.startswith("prov:")}
        rec["province"] = max(provs, key=provs.get)
        out[str(eco)] = rec

    DST.write_text(json.dumps({"orders": ORDERS, "eco": out}, separators=(",", ":")), encoding="utf-8")
    have = sum(1 for r in out.values() if r["awhc"] is not None)
    print(f"{len(out)} ecodistricts with soil components, {have} with water holding capacity; wrote {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
