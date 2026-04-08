"""
add_exemption_areas.py

Adds `in_exemption_area` (INTEGER 0/1) to dhcd_new_housing, indicating whether
each project falls within one of Vermont's Act 181 temporary exemption overlays.

The five exemption layers are:
  I.   Downtown District Area
  II.  Town and Growth Centers & Development Areas
  III. Village Center & Buffer
  IV.  Priority Housing Projects within Buffer
  V.   Urbanized Area within Transit Route Buffer

All layers are unioned into a single geometry before the point-in-polygon test,
so a project inside any layer counts as in_exemption_area = 1.

Note: towns with no exemption polygons are legitimately "not designated" —
this is different from being outside a growth area. That distinction should
be communicated in editorial copy.
"""

import os
import shutil
import sqlite3
import tempfile
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import Point
from config import START_YEAR, END_YEAR

HERE    = os.path.dirname(os.path.abspath(__file__))
DB_SRC  = os.path.join(HERE, 'housing_dev.db')
DB_DEST = os.path.join(HERE, 'housing_dev.db')
MAPS    = os.path.join(HERE, 'data', 'exemption-areas')

# Work on a local /tmp copy to avoid SQLite locking issues on FUSE mounts
_tmpfile = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmpfile.close()
DB = _tmpfile.name

EXEMPTION_FILES = [
    'downtown_district.geojson',
    'town_growth_centers.geojson',
    'village_center_buffer.geojson',
    'priority_housing_projects.geojson',
    'urbanized_transit_buffer.geojson',
]

# ── 1. Load and union all exemption layers ───────────────────────────────────
print("Loading exemption area GeoJSON layers…")
gdfs = []
for fname in EXEMPTION_FILES:
    path = os.path.join(MAPS, fname)
    gdf = gpd.read_file(path)
    gdf = gdf.set_crs('EPSG:4326', allow_override=True)
    layer_label = fname.replace('.geojson', '')
    gdf['exemption_layer'] = layer_label
    gdfs.append(gdf)
    print(f"  {layer_label}: {len(gdf)} features")

all_exemptions = gpd.GeoDataFrame(
    pd.concat(gdfs, ignore_index=True),
    crs='EPSG:4326'
)
print(f"\nTotal exemption features: {len(all_exemptions)}")

# Dissolve into a single unified geometry for fast point-in-polygon
exemption_union = unary_union(all_exemptions.geometry)
print("Exemption layers unioned into single geometry.")

# ── 2. Load DHCD housing points ──────────────────────────────────────────────
# Copy source DB to temp working file
shutil.copy2(DB_SRC, DB)

print("\nLoading DHCD housing records from DB…")
con = sqlite3.connect(DB)

dhcd = pd.read_sql_query(
    "SELECT rowid, esite_id, latitude, longitude FROM dhcd_new_housing",
    con
)
print(f"  Total records: {len(dhcd):,}")

has_coords = dhcd.dropna(subset=['latitude', 'longitude'])
missing_coords = len(dhcd) - len(has_coords)
print(f"  With coordinates: {len(has_coords):,}")
print(f"  Missing coordinates (will be NULL): {missing_coords}")

# ── 3. Point-in-polygon test ─────────────────────────────────────────────────
print("\nRunning point-in-polygon test…")
pts = gpd.GeoDataFrame(
    has_coords.copy(),
    geometry=gpd.points_from_xy(has_coords['longitude'], has_coords['latitude']),
    crs='EPSG:4326'
)

# Single vectorised within() call against the unioned geometry
pts['in_exemption_area'] = pts.geometry.within(exemption_union).astype(int)

# Merge results back onto the full dhcd frame (missing coords → NULL)
dhcd = dhcd.merge(
    pts[['rowid', 'in_exemption_area']],
    on='rowid',
    how='left'
)

inside  = pts['in_exemption_area'].sum()
outside = len(pts) - inside
pct     = inside / len(pts) * 100
print(f"  Inside exemption areas:  {inside:,} ({pct:.1f}%)")
print(f"  Outside exemption areas: {outside:,} ({100-pct:.1f}%)")
print(f"  No coordinates (excluded): {missing_coords}")

# ── 4. Write column back to SQLite ───────────────────────────────────────────
print("\nWriting in_exemption_area column to dhcd_new_housing…")
cur = con.cursor()

# Add column if not present
try:
    cur.execute("ALTER TABLE dhcd_new_housing ADD COLUMN in_exemption_area INTEGER")
    print("  Column added.")
except sqlite3.OperationalError:
    print("  Column already exists — updating.")

# Bulk update via rowid
updates = dhcd.dropna(subset=['in_exemption_area'])
cur.executemany(
    "UPDATE dhcd_new_housing SET in_exemption_area = ? WHERE rowid = ?",
    [(int(row['in_exemption_area']), int(row['rowid'])) for _, row in updates.iterrows()]
)
con.commit()
print(f"  Updated {len(updates):,} rows.")

# ── 5. Verification queries ───────────────────────────────────────────────────
print("\n── Summary: units by exemption area status ─────────────────────────")
summary = pd.read_sql_query("""
    SELECT
        CASE in_exemption_area
            WHEN 1 THEN 'Inside exemption area'
            WHEN 0 THEN 'Outside exemption area'
            ELSE 'No coordinates'
        END AS status,
        COUNT(*) AS projects,
        SUM(unit_count) AS units
    FROM dhcd_new_housing
    GROUP BY in_exemption_area
    ORDER BY in_exemption_area DESC
""", con)
print(summary.to_string(index=False))

print("\n── Inside vs outside by housing type ───────────────────────────────")
by_type = pd.read_sql_query("""
    SELECT
        site_type_general,
        SUM(CASE WHEN in_exemption_area = 1 THEN 1 ELSE 0 END) AS inside_projects,
        SUM(CASE WHEN in_exemption_area = 0 THEN 1 ELSE 0 END) AS outside_projects,
        SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
        SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
    GROUP BY site_type_general
    ORDER BY inside_units DESC
""", con)
print(by_type.to_string(index=False))

print(f"\n── Inside vs outside by year ({START_YEAR}–{END_YEAR}) ────────────────────────────")
by_year = pd.read_sql_query(f"""
    SELECT
        CAST(year_built AS INTEGER) AS year,
        SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
        SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units,
        COUNT(*) AS total_projects
    FROM dhcd_new_housing
    WHERE year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND in_exemption_area IS NOT NULL
    GROUP BY year_built
    ORDER BY year_built
""", con)
print(by_year.to_string(index=False))

con.close()

# Write enriched DB back to workspace and clean up temp file
with open(DB, 'rb') as src, open(DB_DEST, 'wb') as dst:
    dst.write(src.read())
    dst.flush()
    os.fsync(dst.fileno())
os.unlink(DB)
print(f"\n✓ Done. in_exemption_area column written → {DB_DEST}")
