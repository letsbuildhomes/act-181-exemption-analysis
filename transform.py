"""
transform.py

Reads data/dhcd_housing.csv and produces housing.db with a single table
`housing`, enriched with an in_exemption_area column.

Steps:
  1. Load and clean the raw DHCD CSV
  2. Drop seasonal records (they never enter the DB)
  3. Union the five Act 181 exemption-area GeoJSON layers
  4. Run point-in-polygon test → in_exemption_area (1/0/NULL)
  5. Write to housing.db
"""

import os
import sqlite3

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "dhcd_housing.csv")
DB   = os.path.join(HERE, "housing.db")
MAPS = os.path.join(HERE, "data", "exemption-areas")

EXEMPTION_FILES = [
    "downtown_district.geojson",
    "town_growth_centers.geojson",
    "village_center_buffer.geojson",
    "priority_housing_projects.geojson",
    "urbanized_transit_buffer.geojson",
]

SEASONAL = {"camp", "seasonal home", "seasonal camp", "camp/seasonal home", "seasonal"}

# ── 1. Load and clean raw CSV ─────────────────────────────────────────────────

print("Loading DHCD housing CSV...")
df = pd.read_csv(RAW, dtype=str, low_memory=False)
df.columns = [c.lower() for c in df.columns]

# Drop pre-2016 records flagged by source
if "pre2016" in df.columns:
    before = len(df)
    df = df[df["pre2016"] != "Likely"]
    print(f"  Dropped {before - len(df):,} pre-2016 records")

# Rename to snake_case
df = df.rename(columns={
    "esiteid":          "esite_id",
    "townname":         "town_name",
    "sitetype":         "site_type",
    "sitetype_general": "site_type_general",
    "unitcount":        "unit_count",
    "yearbuilt":        "year_built",
    "affordable":       "affordable",
    "primaryaddress":   "address",
    "sourceofdata":     "data_source",
})

# Keep only the columns we need
keep = [c for c in [
    "esite_id", "town_name", "county", "rpc",
    "site_type", "site_type_general",
    "unit_count", "year_built", "affordable",
    "longitude", "latitude", "address", "data_source",
] if c in df.columns]
df = df[keep]

for c in ["unit_count", "year_built"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
for c in ["latitude", "longitude"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")

# ── 2. Drop seasonal records entirely ────────────────────────────────────────

before = len(df)
df = df[~df["site_type"].str.strip().str.lower().isin(SEASONAL)]
dropped = before - len(df)
print(f"  Dropped {dropped:,} seasonal records (will not appear in housing.db)")
print(f"  Remaining: {len(df):,} records")

# ── 3. Load and union exemption-area layers ───────────────────────────────────

print("\nLoading exemption-area GeoJSON layers...")
gdfs = []
for fname in EXEMPTION_FILES:
    path = os.path.join(MAPS, fname)
    gdf = gpd.read_file(path).set_crs("EPSG:4326", allow_override=True)
    gdfs.append(gdf)
    print(f"  {fname.replace('.geojson','')}: {len(gdf)} features")

all_geoms = gpd.GeoDataFrame(
    pd.concat(gdfs, ignore_index=True), crs="EPSG:4326"
)
exemption_union = unary_union(all_geoms.geometry)
print(f"  Unioned {len(all_geoms)} features into single geometry")

# ── 4. Point-in-polygon test ──────────────────────────────────────────────────

print("\nRunning point-in-polygon test...")
df = df.reset_index(drop=True)
has_coords_mask = df["latitude"].notna() & df["longitude"].notna()
has_coords = df[has_coords_mask].copy()
missing = (~has_coords_mask).sum()

pts = gpd.GeoDataFrame(
    has_coords,
    geometry=gpd.points_from_xy(has_coords["longitude"], has_coords["latitude"]),
    crs="EPSG:4326",
)
pts["in_exemption_area"] = pts.geometry.within(exemption_union).astype(int)

# Assign back using index alignment (avoids cartesian product from non-unique keys)
df["in_exemption_area"] = pts["in_exemption_area"].reindex(df.index)

inside  = int(pts["in_exemption_area"].sum())
outside = len(pts) - inside
print(f"  Inside:  {inside:,}")
print(f"  Outside: {outside:,}")
print(f"  Missing coords (in_exemption_area=NULL): {missing:,}")

# ── 5. Write to housing.db ────────────────────────────────────────────────────

print(f"\nWriting to {DB}...")
if os.path.exists(DB):
    os.remove(DB)

con = sqlite3.connect(DB)
df.to_sql("housing", con, if_exists="replace", index=False)
con.execute("CREATE INDEX IF NOT EXISTS idx_year ON housing(year_built)")
con.execute("CREATE INDEX IF NOT EXISTS idx_type ON housing(site_type_general)")
con.commit()

# Quick summary
summary = pd.read_sql_query("""
    SELECT
        site_type_general,
        COUNT(*) AS records,
        SUM(unit_count) AS units
    FROM housing
    GROUP BY site_type_general
    ORDER BY units DESC
""", con)
print("\n── Records by site_type_general ─────────────────────────────────────")
print(summary.to_string(index=False))

con.close()
print(f"\n✓ Done → {DB}")
