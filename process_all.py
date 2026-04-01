"""
Process all raw data sources into housing_dev.db

Sources:
  bps_permits        ← already loaded by process_bps.py
  act250_permits     ← act250_permits.csv
  dhcd_new_housing   ← dhcd_housing.csv
  rpc_targets        ← rpc_housing_targets.csv
  stormwater_permits ← stormwater_permits.csv
  vt_towns           ← vt_towns.geojson  (+ spatial join → county/RPC lookup)
  vt_counties        ← vt_counties.geojson

Also builds:
  town_lookup        ← clean town → county → RPC reference table
"""

import json, re, sqlite3
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

RAW = 'data'
DB  = 'housing_dev.db'

con = sqlite3.connect(DB)

# ─────────────────────────────────────────────────────────────────────────────
# 1. ACT 250 GIS LAYER
# ─────────────────────────────────────────────────────────────────────────────
print("Loading Act 250 permits…")
act = pd.read_csv(f'{RAW}/act250_permits.csv', dtype=str)
act.columns = [c.lower() for c in act.columns]

# Rename to snake_case
act = act.rename(columns={
    'projectid': 'project_id',
    'appnum':    'app_num',
    'apptype':   'app_type',
    'projectname': 'project_name',
    'projecttown': 'project_town',
    'gislatitude':  'latitude',
    'gislongitude': 'longitude',
    'link': 'permit_url',
})

# Clean / cast
for c in ['latitude', 'longitude']:
    act[c] = pd.to_numeric(act[c], errors='coerce')
act['project_id'] = pd.to_numeric(act['project_id'], errors='coerce')

# Standardise town name to Title Case for joining
act['project_town_clean'] = act['project_town'].str.strip().str.title()

act.to_sql('act250_permits', con, if_exists='replace', index=False)
con.execute('CREATE INDEX IF NOT EXISTS idx_act_town ON act250_permits(project_town_clean)')
con.execute('CREATE INDEX IF NOT EXISTS idx_act_status ON act250_permits(status)')
print(f"  → {len(act):,} Act 250 records")

# ─────────────────────────────────────────────────────────────────────────────
# 2. GEOGRAPHIC REFERENCE: towns + counties
# ─────────────────────────────────────────────────────────────────────────────
print("Loading town / county boundaries…")
towns_gdf   = gpd.read_file(f'{RAW}/vt_towns.geojson')
counties_gdf = gpd.read_file(f'{RAW}/vt_counties.geojson')

# Build county number → name lookup
cnty_map = dict(zip(counties_gdf['CNTY'].astype(str),
                    counties_gdf['CNTYNAME']))

# Towns table (non-geometry attributes + county name)
towns_df = towns_gdf[['FIPS6','TOWNNAME','TOWNNAMEMC','CNTY','TOWNGEOID']].copy()
towns_df.columns = ['fips6','townname','townname_mc','cnty_code','town_geoid']
towns_df['county_name'] = towns_df['cnty_code'].astype(str).map(cnty_map)
towns_df['townname_title'] = towns_df['townname_mc'].str.strip()

towns_df.to_sql('vt_towns', con, if_exists='replace', index=False)
print(f"  → {len(towns_df)} towns, {len(counties_gdf)} counties")

# Counties table
counties_df = counties_gdf[['CNTY','CNTYNAME','CNTYGEOID']].copy()
counties_df.columns = ['cnty_code','county_name','county_geoid']
counties_df.to_sql('vt_counties', con, if_exists='replace', index=False)

# ─────────────────────────────────────────────────────────────────────────────
# 3. RPC HOUSING TARGETS
# ─────────────────────────────────────────────────────────────────────────────
print("Loading RPC housing targets…")
rpc = pd.read_csv(f'{RAW}/rpc_housing_targets.csv')
rpc.columns = [c.lower() for c in rpc.columns]
rpc = rpc.rename(columns={
    'lower2025_2030': 'target_lower_2025_2030',
    'upper2025_2030': 'target_upper_2025_2030',
    'lower2025_2050': 'target_lower_2025_2050',
    'upper2025_2050': 'target_upper_2025_2050',
    'total2020':      'total_units_2020',
})
rpc.to_sql('rpc_targets', con, if_exists='replace', index=False)
print(f"  → {len(rpc)} RPC regions")

# ─────────────────────────────────────────────────────────────────────────────
# 4. DHCD / VERMONT NEW HOUSING
# ─────────────────────────────────────────────────────────────────────────────
print("Loading DHCD new housing data…")
dhcd = pd.read_csv(f'{RAW}/dhcd_housing.csv', dtype=str, low_memory=False)
dhcd.columns = [c.lower() for c in dhcd.columns]
dhcd = dhcd.rename(columns={
    'esiteid':        'esite_id',
    'townname':       'town_name',
    'sitetype':       'site_type',
    'sitetype_general': 'site_type_general',
    'unitcount':      'unit_count',
    'yearbuilt':      'year_built',
    'affordable':     'affordable',
    'gpsx':           'longitude',
    'gpsy':           'latitude',
    'primaryaddress': 'address',
    'sourceofdata':   'data_source',
})
for c in ['unit_count', 'year_built']:
    dhcd[c] = pd.to_numeric(dhcd[c], errors='coerce')
for c in ['latitude', 'longitude']:
    dhcd[c] = pd.to_numeric(dhcd[c], errors='coerce')

dhcd['town_name_title'] = dhcd['town_name'].str.strip().str.title()

dhcd.to_sql('dhcd_new_housing', con, if_exists='replace', index=False)
con.execute('CREATE INDEX IF NOT EXISTS idx_dhcd_town  ON dhcd_new_housing(town_name_title)')
con.execute('CREATE INDEX IF NOT EXISTS idx_dhcd_year  ON dhcd_new_housing(year_built)')
print(f"  → {len(dhcd):,} DHCD housing records")
print(f"     Year range: {dhcd['year_built'].min():.0f}–{dhcd['year_built'].max():.0f}")
print(f"     Total units: {dhcd['unit_count'].sum():,.0f}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. STORMWATER PERMITS  (with spatial join to assign town)
# ─────────────────────────────────────────────────────────────────────────────
print("Loading stormwater permits…")
sw = pd.read_csv(f'{RAW}/stormwater_permits.csv', dtype=str)
sw.columns = [c.lower() for c in sw.columns]
sw = sw.rename(columns={
    'objectid':     'object_id',
    'permitnumber': 'permit_number',
    'projectid':    'project_id',
    'permitgroup':  'permit_group',
    'permitstatus': 'permit_status',
    'statusdate':   'status_date_ms',
    'expdate':      'exp_date_ms',
    'pdf_link':     'permit_url',
})

# Convert epoch-ms timestamps to year
for col, newcol in [('status_date_ms','status_year'), ('exp_date_ms','exp_year')]:
    ms = pd.to_numeric(sw[col], errors='coerce')
    sw[newcol] = (ms / 1000 / 86400 / 365.25 + 1970).round(0).astype('Int64')

for c in ['latitude', 'longitude']:
    sw[c] = pd.to_numeric(sw[c], errors='coerce')

# Spatial join: assign VT town to each stormwater permit using lat/lon
sw_valid = sw.dropna(subset=['latitude','longitude']).copy()
sw_pts = gpd.GeoDataFrame(
    sw_valid,
    geometry=[Point(lon, lat) for lon, lat in zip(sw_valid['longitude'], sw_valid['latitude'])],
    crs='EPSG:4326'
)
towns_for_join = towns_gdf[['TOWNNAME','TOWNNAMEMC','CNTY','geometry']].copy()
towns_for_join = towns_for_join.rename(columns={
    'TOWNNAME': 'sw_town', 'TOWNNAMEMC': 'sw_town_mc', 'CNTY': 'sw_cnty'
})
sw_joined = gpd.sjoin(sw_pts, towns_for_join, how='left', predicate='within')
sw['town_name']  = sw_joined['sw_town_mc'].reindex(sw.index)
sw['cnty_code']  = sw_joined['sw_cnty'].reindex(sw.index)
sw['county_name'] = sw['cnty_code'].astype(str).map(cnty_map)

sw_out = sw.drop(columns=['status_date_ms','exp_date_ms'], errors='ignore')
sw_out.to_sql('stormwater_permits', con, if_exists='replace', index=False)
con.execute('CREATE INDEX IF NOT EXISTS idx_sw_town ON stormwater_permits(town_name)')
print(f"  → {len(sw):,} stormwater permits")
print(f"     Town assigned to: {sw['town_name'].notna().sum()} of {len(sw_valid)} geocoded permits")

# ─────────────────────────────────────────────────────────────────────────────
# 6. TOWN LOOKUP TABLE  (town → county → RPC)
# ─────────────────────────────────────────────────────────────────────────────
print("Building town → county → RPC lookup…")

# Derive town→RPC from DHCD data (most comprehensive source for this mapping)
rpc_lookup = (
    dhcd[dhcd['rpc'].notna() & dhcd['town_name_title'].notna()]
    .groupby('town_name_title')['rpc']
    .agg(lambda x: x.mode()[0])   # most common RPC assignment per town
    .reset_index()
    .rename(columns={'town_name_title': 'townname_title', 'rpc': 'rpc_name'})
)

# Also get RPC short code from rpc_targets table
rpc_code_map = {str(k).strip(): v for k, v in zip(rpc['longname'], rpc['initials']) if pd.notna(k)}

town_lookup = towns_df[['townname_title','county_name','cnty_code','fips6','town_geoid']].merge(
    rpc_lookup, on='townname_title', how='left'
)
town_lookup['rpc_initials'] = town_lookup['rpc_name'].map(
    lambda x: next((v for k, v in rpc_code_map.items() if x and isinstance(k, str) and x.lower() in k.lower()), None)
    if x and isinstance(x, str) else None
)

town_lookup.to_sql('town_lookup', con, if_exists='replace', index=False)
con.execute('CREATE INDEX IF NOT EXISTS idx_tl_name ON town_lookup(townname_title)')
print(f"  → {len(town_lookup)} towns in lookup")
print(f"     RPC assigned: {town_lookup['rpc_name'].notna().sum()}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. QUICK SANITY CHECKS
# ─────────────────────────────────────────────────────────────────────────────
print("\n── Database table summary ──────────────────────────────────────────")
tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", con)
for tbl in tables['name']:
    count = pd.read_sql(f"SELECT COUNT(*) as n FROM [{tbl}]", con)['n'][0]
    print(f"  {tbl:<30} {count:>8,} rows")

print("\n── DHCD: units by year (2021–2025) ────────────────────────────────")
yr = pd.read_sql_query("""
    SELECT year_built,
           COUNT(*) AS sites,
           SUM(unit_count) AS units,
           SUM(CASE WHEN site_type_general LIKE '%SINGLE%' THEN unit_count ELSE 0 END) AS sf_units,
           SUM(CASE WHEN site_type_general LIKE '%MULTI%'  THEN unit_count ELSE 0 END) AS mf_units
    FROM dhcd_new_housing
    WHERE year_built BETWEEN 2021 AND 2025
    GROUP BY year_built ORDER BY year_built
""", con)
print(yr.to_string(index=False))

print("\n── Act 250: application type breakdown ─────────────────────────────")
a250 = pd.read_sql_query("""
    SELECT app_type, status, COUNT(*) as n
    FROM act250_permits
    GROUP BY app_type, status ORDER BY n DESC LIMIT 12
""", con)
print(a250.to_string(index=False))

print("\n── Stormwater: permit status breakdown ─────────────────────────────")
sw_sum = pd.read_sql_query("""
    SELECT permit_status, COUNT(*) as n
    FROM stormwater_permits GROUP BY permit_status ORDER BY n DESC
""", con)
print(sw_sum.to_string(index=False))

con.commit()
con.close()
print(f"\n✓ All tables written → {DB}")
