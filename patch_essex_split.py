"""
patch_essex_split.py — normalise Essex / Essex Junction after municipal split

Essex Junction incorporated as a separate city from Essex Town in 2022, after
the 2020 Census was taken. The original town_lookup records shared the combined
2020 Census population (22,094) for both rows. This script:

  1. Renames 'Essex' → 'Essex Town' in town_lookup
  2. Splits the 2020 population and housing units evenly between the two towns
  3. Recomputes population density and urban_rural_tier for both
  4. Normalises Essex name variants in dhcd_new_housing using point-in-polygon:
       ESSEX JUNCTION CITY  → Essex Junction
       ESSEX                → Essex Town or Essex Junction based on lat/lon
                              (checks Essex Junction polygon first; falls back
                               to Essex Town if not inside Junction boundary)
  5. Normalises Essex name variants in project_groups using centroid lat/lon
     with the same polygon-first logic

Requires: shapely (pip install shapely)

Safe to re-run after process_all.py rebuilds the database from source data;
checks current state before applying each change.

Note: the vt_towns.geojson already reflects the post-2022 split — the two
polygons are mutually exclusive (Essex Town has Essex Junction carved out).
We still check Essex Junction first as a defensive measure.
"""

import json
import os
import sqlite3

from shapely.geometry import Point, shape

HERE     = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(HERE, 'housing_dev.db')
GEOJSON  = os.path.join(HERE, 'data', 'vt_towns.geojson')

TOTAL_POP   = 22094
TOTAL_UNITS = 9588
HALF_POP    = TOTAL_POP   // 2   # 11,047
HALF_UNITS  = TOTAL_UNITS // 2   # 4,794


def classify(pop, density):
    if pop is None or density is None:
        return 'rural'
    if pop >= 5000 and density >= 100:
        return 'urban'
    elif pop >= 2500 or density >= 40:
        return 'suburban'
    return 'rural'


def assign_essex_town(lon, lat, essex_town_poly, essex_junction_poly):
    """Return 'Essex Junction' or 'Essex Town' for a given coordinate.
    Checks Essex Junction first; anything not inside the Junction boundary
    is assigned to Essex Town."""
    if lon is None or lat is None:
        return None
    pt = Point(lon, lat)
    if essex_junction_poly.contains(pt):
        return 'Essex Junction'
    return 'Essex Town'


# ── Load polygons ──────────────────────────────────────────────────────────────
print("Loading town polygons from GeoJSON…")
with open(GEOJSON) as f:
    gj = json.load(f)

essex_polys = {
    feat['properties']['TOWNNAMEMC']: shape(feat['geometry'])
    for feat in gj['features']
    if 'essex' in feat['properties'].get('TOWNNAMEMC', '').lower()
}
et_poly = essex_polys['Essex']
ej_poly = essex_polys['Essex Junction']
print(f"  Essex Town polygon loaded  (area ≈ {et_poly.area * 111**2:.1f} km²)")
print(f"  Essex Junction polygon loaded (area ≈ {ej_poly.area * 111**2:.1f} km²)")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── 1. town_lookup: rename and split ──────────────────────────────────────────
print("\n=== town_lookup ===")
if con.execute("SELECT 1 FROM town_lookup WHERE townname_title='Essex'").fetchone():
    con.execute("UPDATE town_lookup SET townname_title='Essex Town' WHERE townname_title='Essex'")
    print("  Renamed 'Essex' → 'Essex Town'")
else:
    print("  'Essex' already renamed — skipping")

for town in ('Essex Town', 'Essex Junction'):
    row = con.execute(
        "SELECT area_km2, population_2020 FROM town_lookup WHERE townname_title=?", (town,)
    ).fetchone()
    if row is None:
        print(f"  WARNING: '{town}' not found in town_lookup")
        continue
    area    = row['area_km2']
    density = round(HALF_POP / area, 2) if area else None
    tier    = classify(HALF_POP, density)
    con.execute("""
        UPDATE town_lookup
           SET population_2020    = ?,
               housing_units_2020 = ?,
               pop_density_km2    = ?,
               urban_rural_tier   = ?
         WHERE townname_title = ?
    """, (HALF_POP, HALF_UNITS, density, tier, town))
    print(f"  {town}: pop={HALF_POP:,}, density={density:.2f}/km², tier={tier}")

# ── 2. dhcd_new_housing: normalise name variants ──────────────────────────────
print("\n=== dhcd_new_housing ===")

# ESSEX JUNCTION CITY → Essex Junction
n = con.execute("""
    UPDATE dhcd_new_housing
       SET town_name='ESSEX JUNCTION', town_name_title='Essex Junction'
     WHERE UPPER(TRIM(town_name_title))='ESSEX JUNCTION CITY'
""").rowcount
print(f"  'Essex Junction City' → 'Essex Junction': {n} records updated")

# All ambiguous ESSEX records + any already-split records: re-assign by lat/lon
# We re-run this on ALL Essex-area records so the script is fully idempotent
rows = con.execute("""
    SELECT rowid, latitude, longitude, town_name_title
      FROM dhcd_new_housing
     WHERE UPPER(TRIM(town_name_title)) IN ('ESSEX','ESSEX TOWN','ESSEX JUNCTION')
""").fetchall()

town_ids  = []
junct_ids = []
no_coords = []

for r in rows:
    assigned = assign_essex_town(r['longitude'], r['latitude'], et_poly, ej_poly)
    if assigned is None:
        no_coords.append(r['rowid'])
    elif assigned == 'Essex Town':
        town_ids.append(r['rowid'])
    else:
        junct_ids.append(r['rowid'])

if town_ids:
    con.execute(
        f"UPDATE dhcd_new_housing "
        f"SET town_name='ESSEX TOWN', town_name_title='Essex Town' "
        f"WHERE rowid IN ({','.join('?'*len(town_ids))})",
        town_ids
    )
if junct_ids:
    con.execute(
        f"UPDATE dhcd_new_housing "
        f"SET town_name='ESSEX JUNCTION', town_name_title='Essex Junction' "
        f"WHERE rowid IN ({','.join('?'*len(junct_ids))})",
        junct_ids
    )
if no_coords:
    print(f"  WARNING: {len(no_coords)} records have no coordinates — left unchanged")

print(f"  → Essex Town: {len(town_ids)} records")
print(f"  → Essex Junction: {len(junct_ids)} records")

# ── 3. project_groups: normalise using centroid lat/lon ───────────────────────
print("\n=== project_groups ===")

n = con.execute("""
    UPDATE project_groups SET town='Essex Junction'
     WHERE town='Essex Junction City'
""").rowcount
print(f"  'Essex Junction City' → 'Essex Junction': {n} records")

pg_rows = con.execute("""
    SELECT rowid, centroid_lat, centroid_lon, town
      FROM project_groups
     WHERE town IN ('Essex', 'Essex Town', 'Essex Junction')
""").fetchall()

pg_town  = []
pg_junct = []

for r in pg_rows:
    assigned = assign_essex_town(r['centroid_lon'], r['centroid_lat'], et_poly, ej_poly)
    if assigned == 'Essex Town':
        pg_town.append(r['rowid'])
    else:
        pg_junct.append(r['rowid'])

if pg_town:
    con.execute(
        f"UPDATE project_groups SET town='Essex Town' "
        f"WHERE rowid IN ({','.join('?'*len(pg_town))})", pg_town
    )
if pg_junct:
    con.execute(
        f"UPDATE project_groups SET town='Essex Junction' "
        f"WHERE rowid IN ({','.join('?'*len(pg_junct))})", pg_junct
    )
print(f"  → Essex Town: {len(pg_town)}, Essex Junction: {len(pg_junct)}")

con.commit()
con.close()
print("\nAll changes committed.")
