"""
build_felt_parcels_burnaby.py

Produces a Felt-ready GeoJSON for Burnaby R1 parcels.
Each parcel gets:
  - zone_code       from spatial join with Zoning.shp
  - area_m2         computed from parcel geometry (LOT_AREA field is null)
  - is_laned        True if parcel touches a lane
  - is_corner       True if parcel touches 2+ distinct streets
  - rule_* columns  all rules for the zone
  - rules_tooltip   filtered to rules relevant to this specific parcel, clean format

Usage:
    python build_felt_parcels_burnaby.py

Output:
    felt_parcels_burnaby.geojson
"""

import re
import numpy as np
import geopandas as gpd
import pandas as pd
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).resolve().parents[3]
GIS     = ROOT / "code" / "gis_files" / "burnaby"
VIZ     = Path(__file__).parent

PARCELS_SHP  = GIS / "parcels" / "Legal_Parcels.shp"
ZONING_SHP   = GIS / "zoning"  / "Zoning.shp"
LANES_ZIP    = GIS / "lane"    / "Lane.zip"
STREETS_ZIP  = GIS / "streets" / "Street.zip"
RULES_CSV    = VIZ / "burnaby_r1_rules.csv"
OUTPUT       = VIZ / "felt_parcels_burnaby.geojson"

# EPSG:26910 — NAD83 UTM Zone 10N, native CRS for Burnaby data (meters)

# ── 1. Load data ───────────────────────────────────────────────────────────────
print("Loading parcels ...")
parcels = gpd.read_file(PARCELS_SHP)

print("Loading zoning ...")
zoning = gpd.read_file(ZONING_SHP)[["ZONECODE", "geometry"]]
if parcels.crs != zoning.crs:
    zoning = zoning.to_crs(parcels.crs)

print("Loading lanes and streets ...")
lanes   = gpd.read_file(f"/vsizip/{LANES_ZIP}")
streets = gpd.read_file(f"/vsizip/{STREETS_ZIP}")
if lanes.crs != parcels.crs:
    lanes = lanes.to_crs(parcels.crs)
if streets.crs != parcels.crs:
    streets = streets.to_crs(parcels.crs)

print("Loading rules ...")
rules = pd.read_csv(RULES_CSV)

# ── 2. Spatial join: add zone_code via centroid ────────────────────────────────
print("Joining zone codes ...")
cents = parcels.copy()
cents["geometry"] = parcels.geometry.centroid

joined = gpd.sjoin(
    cents[["LOT_ID", "ADDRESS", "LOT_WIDTH", "LOT_DEPTH", "geometry"]],
    zoning, how="left", predicate="within"
).rename(columns={"ZONECODE": "zone_code"}).drop(columns=["index_right"])

joined = joined.set_index("LOT_ID")
parcels_out = parcels.set_index("LOT_ID")[["ADDRESS", "LOT_WIDTH", "LOT_DEPTH", "geometry"]].copy()
parcels_out["zone_code"] = joined["zone_code"]
parcels_out = parcels_out.reset_index()

# Compute parcel area in m² from geometry (LOT_AREA column is null)
parcels_out["area_m2"] = parcels_out.geometry.area.round(1)

print(f"Parcels with zone assigned: {parcels_out['zone_code'].notna().sum():,} / {len(parcels_out):,}")

# ── 3. Detect laned and corner parcels ────────────────────────────────────────
print("Detecting laned and corner parcels ...")
buffered = parcels_out.copy()
buffered["geometry"] = parcels_out.geometry.buffer(2)
buffered10 = parcels_out.copy()
buffered10["geometry"] = parcels_out.geometry.buffer(10)

# is_laned: touches any lane (2m buffer)
lane_join = gpd.sjoin(buffered[["geometry"]], lanes[["geometry"]],
                      how="left", predicate="intersects")
has_lane  = lane_join.groupby(lane_join.index).size() > 0
parcels_out["is_laned"] = parcels_out.index.map(lambda i: bool(has_lane.get(i, False)))

# is_corner: street segments in 2+ different directions (angle-based)
streets_geom = streets[["geometry"]].reset_index(drop=True)

def _seg_angle(geom):
    try:
        if hasattr(geom, "geoms"):          # MultiLineString
            parts = list(geom.geoms)
            p0 = list(parts[0].coords)[0]
            p1 = list(parts[-1].coords)[-1]
        else:
            c  = list(geom.coords)
            p0, p1 = c[0], c[-1]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        return float(np.degrees(np.arctan2(abs(dy), abs(dx))))
    except Exception:
        return -1.0

def _has_two_dirs(angles, threshold=30):
    valid = [a for a in angles if a >= 0]
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            diff = abs(valid[i] - valid[j])
            diff = min(diff, 90 - diff) if diff <= 90 else min(diff, 180 - diff)
            if diff > threshold:
                return True
    return False

seg_angles = streets_geom["geometry"].apply(_seg_angle)
st_join10  = gpd.sjoin(buffered10[["geometry"]], streets_geom,
                       how="left", predicate="intersects")
st_join10["_angle"] = st_join10["index_right"].map(seg_angles)

corner_flags = {}
for idx, grp in st_join10.dropna(subset=["index_right"]).groupby(level=0):
    corner_flags[idx] = _has_two_dirs(grp["_angle"].tolist())
parcels_out["is_corner"] = parcels_out.index.map(lambda i: bool(corner_flags.get(i, False)))

print(f"  Laned parcels : {parcels_out['is_laned'].sum():,} / {len(parcels_out):,}")
print(f"  Corner parcels: {parcels_out['is_corner'].sum():,} / {len(parcels_out):,}")

# ── 4. Build per-zone rule columns (all rules for zone) ───────────────────────
def fmt_rule(row):
    applies = str(row.get("applies_to", "") or "").strip()
    cond    = str(row.get("condition", "") or "").strip()
    if applies.lower() in ("all", "nan", ""):
        applies = ""
    if cond.lower() in ("nan", ""):
        cond = ""
    if len(applies) > 40:
        applies = applies[:38] + "…"
    if len(cond) > 50:
        cond = cond[:48] + "…"
    line = f"{row['operator']} {row['value']} {row['unit']}"
    if applies:
        line += f" — {applies}"
    if cond:
        line += f" ({cond})"
    return line

rules["_fmt"] = rules.apply(fmt_rule, axis=1)

zone_cols = {}
for zone, grp in rules.groupby("zone_code"):
    row = {}
    for obj, sub in grp.groupby("rule_object"):
        col = f"rule_{obj.replace(' ', '_')}"
        row[col] = "\n".join(f"  * {f}" for f in sub["_fmt"])
    zone_cols[zone] = row

zone_rules_df = (pd.DataFrame.from_dict(zone_cols, orient="index")
                   .reset_index().rename(columns={"index": "zone_code"}))
parcels_out = parcels_out.merge(zone_rules_df, on="zone_code", how="left")

rule_col_names = [c for c in parcels_out.columns if c.startswith("rule_")]
parcels_out[rule_col_names] = parcels_out[rule_col_names].fillna("no rules extracted")

# ── 5. Build per-parcel filtered tooltip ──────────────────────────────────────
def is_applicable(condition, applies_to, is_laned, is_corner, lot_area_m2):
    text = ((str(condition) or "") + " " + (str(applies_to) or "")).lower()
    if "not located on a corner" in text or "not on a corner" in text:
        return not is_corner
    if "corner parcel" in text or "corner lot" in text:
        return is_corner
    if "flanking" in text:
        return is_corner
    if "laned or corner" in text:
        return is_laned or is_corner
    if "laned parcel" in text or "on a laned" in text:
        return is_laned
    m = re.search(r"lots?\s*<\s*(\d+)", text)
    if m:
        return lot_area_m2 is not None and lot_area_m2 < float(m.group(1))
    m = re.search(r"lots?\s*>\s*(\d+)", text)
    if m:
        return lot_area_m2 is not None and lot_area_m2 > float(m.group(1))
    return True

def build_tooltip(parcel_row):
    zone       = parcel_row["zone_code"]
    is_laned   = bool(parcel_row.get("is_laned", False))
    is_corner  = bool(parcel_row.get("is_corner", False))
    lot_area   = parcel_row.get("area_m2")

    zone_rules = rules[rules["zone_code"] == zone]
    if zone_rules.empty:
        return "no rules for this zone"

    sections = []
    for obj, grp in zone_rules.groupby("rule_object"):
        bullets = []
        for _, r in grp.iterrows():
            if is_applicable(r.get("condition", ""), r.get("applies_to", ""),
                             is_laned, is_corner, lot_area):
                bullets.append("  * " + fmt_rule(r))
        if bullets:
            header = obj.upper().replace("_", " ")
            sections.append(header + "\n" + "\n".join(bullets))

    return "\n\n".join(sections) if sections else "no applicable rules"

print("Building per-parcel tooltips ...")
parcels_out["rules_tooltip"] = parcels_out.apply(build_tooltip, axis=1)

# ── 6. Export to GeoJSON (WGS84) ───────────────────────────────────────────────
parcels_out = parcels_out.to_crs(epsg=4326)
print(f"Writing {OUTPUT} ...")
parcels_out.to_file(OUTPUT, driver="GeoJSON")

# ── Sample output ──────────────────────────────────────────────────────────────
sample_r1 = parcels_out[parcels_out["zone_code"] == "R1"]
if len(sample_r1):
    sample = sample_r1.iloc[0]
    print(f"\n=== Sample R1 parcel: {sample['ADDRESS']} ===")
    print(f"area={sample['area_m2']} m2  laned={sample['is_laned']}  corner={sample['is_corner']}")
    print(sample["rules_tooltip"].encode("ascii", errors="replace").decode("ascii"))

print(f"\nRule columns: {rule_col_names}")
print(f"Done. Upload {OUTPUT.name} to Felt.")
