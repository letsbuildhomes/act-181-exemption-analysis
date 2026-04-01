"""
add_rural_urban.py
Adds population, area, density, and rural/urban tier to town_lookup table.
Population source: 2020 Census county subdivisions via VCGI FeatureServer.
Classification method: population density quintiles + size thresholds.
"""
import pandas as pd
import geopandas as gpd
import sqlite3
import numpy as np

DB = 'housing_dev.db'

# ── 1. Load population data ──────────────────────────────────────────────────
pop = pd.read_csv('data/town_population_2020.csv',
                  dtype={'GEOID': str})

# Build a clean lookup from raw Census NAME → {population, housing_units}
# The raw NAME format is "Barre city", "St. Albans town", etc.
# We'll use raw names and build explicit mapping to GeoJSON town names.

census_lookup = {}
for _, row in pop.iterrows():
    census_lookup[row['NAME']] = {
        'population_2020': row['population_2020'],
        'housing_units_2020': row['housing_units_2020'],
        'geoid': row['GEOID'],
    }

# ── 2. Load towns GeoJSON and compute area ───────────────────────────────────
towns = gpd.read_file('data/vt_towns.geojson')
towns_m = towns.to_crs('EPSG:32145')
towns['area_km2'] = towns_m.geometry.area / 1_000_000

# ── 3. Map GeoJSON TOWNNAMEMC → Census NAME ──────────────────────────────────
# Most towns: "Burlington" → "Burlington city" or "Addison town"
# Special cases handled explicitly below.

# Build a map from lower-cased Census names for fuzzy matching
census_by_lower = {k.lower(): k for k in census_lookup}

# Explicit GeoJSON → Census name overrides
CENSUS_MAP = {
    # Cities/towns with same-named municipality pairs
    "Barre City":       "Barre city",
    "Barre Town":       "Barre town",
    "Newport City":     "Newport city",
    "Newport Town":     "Newport town",
    "Rutland City":     "Rutland city",
    "Rutland Town":     "Rutland town",
    "St. Albans City":  "St. Albans city",
    "St. Albans Town":  "St. Albans town",
    # Saint → St. fixes
    "Saint Albans City":  "St. Albans city",
    "Saint Albans Town":  "St. Albans town",
    "Saint Johnsbury":    "St. Johnsbury town",
    "Saint George":       "St. George town",
    # Essex Junction became a city in 2022; in 2020 Census it was part of Essex town
    "Essex Junction":   "Essex town",
    # Gores / Grants
    "Averys Gore":      "Avery's gore",
    "Avery'S Gore":     "Avery's gore",
    "Warrens Gore":     "Warren's gore",
    "Warren'S Gore":    "Warren's gore",
    "Warners Grant":    "Warner's grant",
    "Warner'S Grant":   "Warner's grant",
    "Buels Gore":       "Buels gore",
}

def lookup_census(geoname):
    """Map a GeoJSON TOWNNAMEMC to a Census population record."""
    # Try explicit override first
    if geoname in CENSUS_MAP:
        cname = CENSUS_MAP[geoname]
        return census_lookup.get(cname, {})
    # Try "{name} town" (most common VT case)
    candidate_town = geoname.lower() + " town"
    if candidate_town in census_by_lower:
        return census_lookup[census_by_lower[candidate_town]]
    # Try "{name} city"
    candidate_city = geoname.lower() + " city"
    if candidate_city in census_by_lower:
        return census_lookup[census_by_lower[candidate_city]]
    # Try exact match
    if geoname.lower() in census_by_lower:
        return census_lookup[census_by_lower[geoname.lower()]]
    return {}

# ── 4. Build enriched towns dataframe ────────────────────────────────────────
records = []
unmatched = []
for _, row in towns.iterrows():
    geoname = row['TOWNNAMEMC'].strip().title()
    rec = lookup_census(geoname)
    if not rec:
        unmatched.append(geoname)
    records.append({
        'town_name':          geoname,
        'towngeoid':          row['TOWNGEOID'],
        'fips6':              row['FIPS6'],
        'area_km2':           round(row['area_km2'], 2),
        'population_2020':    rec.get('population_2020', None),
        'housing_units_2020': rec.get('housing_units_2020', None),
        'census_geoid':       rec.get('geoid', None),
    })

df = pd.DataFrame(records)
print(f"Matched: {df['population_2020'].notna().sum()} / {len(df)}")
if unmatched:
    print(f"Unmatched ({len(unmatched)}):", unmatched)

# ── 5. Population density (persons / km²) ───────────────────────────────────
df['pop_density_km2'] = (df['population_2020'] / df['area_km2']).round(2)

# ── 6. Rural/Urban classification ───────────────────────────────────────────
# Tier definitions (Vermont-specific, policy-aligned):
#   urban      : pop >= 5,000 AND density >= 100/km²  (functional urban core)
#   suburban   : pop >= 2,500 OR density >= 40/km²    (developed town)
#   rural      : everything else
# Note: some small-population "cities" (Newport, Barre) qualify as urban by
#        density even if pop < 10k. Gores/grants with pop ~0 → rural.

def classify(row):
    pop = row['population_2020']
    den = row['pop_density_km2']
    if pd.isna(pop) or pd.isna(den):
        return 'rural'
    if pop >= 5000 and den >= 100:
        return 'urban'
    elif pop >= 2500 or den >= 40:
        return 'suburban'
    else:
        return 'rural'

df['urban_rural_tier'] = df.apply(classify, axis=1)

tier_counts = df['urban_rural_tier'].value_counts()
print("\nTier distribution:")
print(tier_counts.to_string())
print("\nUrban towns:")
print(df[df['urban_rural_tier']=='urban'][['town_name','population_2020','pop_density_km2']].sort_values('population_2020', ascending=False).to_string(index=False))
print("\nSuburban towns:")
print(df[df['urban_rural_tier']=='suburban'][['town_name','population_2020','pop_density_km2']].sort_values('population_2020', ascending=False).to_string(index=False))

# ── 7. Update town_lookup in SQLite ─────────────────────────────────────────
con = sqlite3.connect(DB)

# Check existing town_lookup columns
existing = pd.read_sql_query("SELECT * FROM town_lookup LIMIT 1", con)
print("\nExisting town_lookup columns:", list(existing.columns))

# Add new columns if not present
cur = con.cursor()
for col, dtype in [
    ('population_2020',    'INTEGER'),
    ('housing_units_2020', 'INTEGER'),
    ('area_km2',           'REAL'),
    ('pop_density_km2',    'REAL'),
    ('urban_rural_tier',   'TEXT'),
    ('census_geoid',       'TEXT'),
]:
    try:
        cur.execute(f'ALTER TABLE town_lookup ADD COLUMN {col} {dtype}')
    except sqlite3.OperationalError:
        pass  # column already exists

# Update each town
updates = 0
for _, row in df.iterrows():
    cur.execute('''
        UPDATE town_lookup
        SET population_2020    = ?,
            housing_units_2020 = ?,
            area_km2           = ?,
            pop_density_km2    = ?,
            urban_rural_tier   = ?,
            census_geoid       = ?
        WHERE UPPER(townname_title) = UPPER(?)
    ''', (
        None if pd.isna(row['population_2020']) else int(row['population_2020']),
        None if pd.isna(row['housing_units_2020']) else int(row['housing_units_2020']),
        row['area_km2'],
        None if pd.isna(row['pop_density_km2']) else row['pop_density_km2'],
        row['urban_rural_tier'],
        row['census_geoid'],
        row['town_name'],
    ))
    updates += cur.rowcount

con.commit()
print(f"\nUpdated {updates} rows in town_lookup")

# Verify
result = pd.read_sql_query('''
    SELECT townname_title, population_2020, area_km2, pop_density_km2, urban_rural_tier
    FROM town_lookup
    WHERE urban_rural_tier IS NOT NULL
    ORDER BY population_2020 DESC
    LIMIT 15
''', con)
print("\nTop 15 towns in town_lookup:")
print(result.to_string(index=False))

# Summary by tier
summary = pd.read_sql_query('''
    SELECT urban_rural_tier, COUNT(*) as towns,
           SUM(population_2020) as total_pop
    FROM town_lookup
    GROUP BY urban_rural_tier
''', con)
print("\nSummary by tier:")
print(summary.to_string(index=False))

con.close()
print(f"\nDone.")
