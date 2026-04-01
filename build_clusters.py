"""
build_project_clusters.py

Groups individual DHCD housing sites into likely "development projects" using:
  1. PARCELNUM duplicates from ESITE layer (definitive — same parcel = same project)
  2. DBSCAN spatial clustering on DHCD coordinates (approximate — nearby + same period)

Adds a `project_cluster_id` column to dhcd_new_housing and creates a
`project_groups` summary table.

Cluster logic:
  - Single-family sites within 300m of each other AND built within a 3-year window
  - Minimum cluster size: 4 sites  (smaller groups treated as independent)
  - Multi-unit sites always kept as independent projects (already rolled up)
"""

import pandas as pd
import numpy as np
import sqlite3
import geopandas as gpd
from sklearn.cluster import DBSCAN

DB = 'housing_dev.db'

# ── 1. Load DHCD data with coordinates ──────────────────────────────────────
con = sqlite3.connect(DB)
dhcd = pd.read_sql_query('''
    SELECT d.esite_id, d.town_name_title, d.latitude, d.longitude,
           d.unit_count, d.year_built, d.site_type, d.site_type_general,
           d.address, t.urban_rural_tier, t.county_name
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
''', con)
con.close()

print(f"DHCD records loaded: {len(dhcd):,}")

# ── 2. ESITE parcel-based groups (definitive) ────────────────────────────────
esite = pd.read_csv('data/esite_parcels.csv', dtype=str)
esite['GPSX']      = pd.to_numeric(esite['GPSX'], errors='coerce')
esite['GPSY']      = pd.to_numeric(esite['GPSY'], errors='coerce')
esite['YEARBUILT'] = pd.to_numeric(esite['YEARBUILT'], errors='coerce')
esite['UNITCOUNT'] = pd.to_numeric(esite['UNITCOUNT'], errors='coerce')
esite['parcelnum_clean'] = esite['PARCELNUM'].fillna('').str.strip().str.upper()

# Build parcel groups: town + parcelnum with ≥2 sites
parcel_groups = (esite[esite['parcelnum_clean'] != '']
    .groupby(['TOWNNAME', 'parcelnum_clean'])
    .agg(parcel_site_count=('ESITEID','count'),
         parcel_units=('UNITCOUNT','sum'),
         parcel_year_min=('YEARBUILT','min'),
         parcel_year_max=('YEARBUILT','max'),
         parcel_lat=('GPSY','mean'),
         parcel_lon=('GPSX','mean'),
         parcel_category=('ParcelCategory','first'))
    .reset_index())

esite_parcel_groups_db = parcel_groups.rename(columns={
    'TOWNNAME':          'town_name',
    'parcelnum_clean':   'parcelnum',
    'parcel_site_count': 'site_count',
    'parcel_year_min':   'year_min',
    'parcel_year_max':   'year_max',
})

parcel_subdivisions = parcel_groups[parcel_groups['parcel_site_count'] >= 4].copy()
parcel_subdivisions['parcel_group_id'] = ['PARCEL_' + str(i+1).zfill(4)
                                           for i in range(len(parcel_subdivisions))]
print(f"\nParcel-based subdivisions (≥4 sites same parcel): {len(parcel_subdivisions)}")
print(f"Sites in parcel groups: {parcel_subdivisions['parcel_site_count'].sum():.0f}")
print(f"Units in parcel groups: {parcel_subdivisions['parcel_units'].sum():.0f}")

# ── 3. DBSCAN spatial clustering on DHCD ────────────────────────────────────
# Only cluster single-family records (multi-unit already represent a project)
# Use 3-year rolling windows to group by period
# Radius: 300m  |  Min samples: 4

sf_mask = (dhcd['unit_count'] == 1) & dhcd['latitude'].notna() & dhcd['longitude'].notna()
sf = dhcd[sf_mask].copy()
multi = dhcd[~sf_mask].copy()
print(f"\nSingle-family records (for clustering): {len(sf):,}")
print(f"Multi-unit records (kept as-is):        {len(multi):,}")

# Reproject to Vermont State Plane (EPSG:32145) for meter-based distances
sf_gdf = gpd.GeoDataFrame(sf, geometry=gpd.points_from_xy(sf['longitude'], sf['latitude']),
                           crs='EPSG:4326').to_crs('EPSG:32145')
sf['x_m'] = sf_gdf.geometry.x
sf['y_m'] = sf_gdf.geometry.y

# DBSCAN parameters
RADIUS_M   = 300    # meters — typical SFH subdivision lot spacing
MIN_SITES  = 4      # minimum homes to call it a cluster/project
YEAR_SCALE = 100    # scale factor to give year window comparable weight to distance
# Each year of difference costs 100 "distance units" — so 3-year spread ≈ 300m radius

sf['year_scaled'] = sf['year_built'].fillna(sf['year_built'].median()) * YEAR_SCALE

coords = sf[['x_m', 'y_m', 'year_scaled']].values
# Normalize: 300m radius in space, 300 in time (= 3 year window)
# Epsilon = 300 in all dimensions simultaneously
db = DBSCAN(eps=300, min_samples=MIN_SITES, metric='chebyshev', n_jobs=-1).fit(coords)
sf['cluster_label'] = db.labels_  # -1 = noise (not in any cluster)

n_clusters = (sf['cluster_label'] >= 0).sum()
n_clustered = len(sf[sf['cluster_label'] >= 0])
print(f"\nDBSCAN results:")
print(f"  Distinct clusters found:  {sf['cluster_label'].max() + 1:,}")
print(f"  Sites in clusters:        {n_clustered:,}  ({n_clustered/len(sf)*100:.1f}% of SFH)")
print(f"  Isolated (noise) sites:   {(sf['cluster_label'] == -1).sum():,}")

# ── 4. Build cluster-level summary ───────────────────────────────────────────
# Assign project IDs
sf['project_id'] = sf['cluster_label'].apply(
    lambda x: f'CLUSTER_{x+1:05d}' if x >= 0 else None)
multi['project_id'] = None

# Combine back
dhcd_out = pd.concat([sf, multi], ignore_index=True)

# Cluster summary
clustered = sf[sf['cluster_label'] >= 0]
cluster_summary = (clustered.groupby('cluster_label')
    .agg(
        site_count=('esite_id','count'),
        total_units=('unit_count','sum'),
        year_min=('year_built','min'),
        year_max=('year_built','max'),
        town=('town_name_title', lambda x: x.mode().iloc[0] if len(x) > 0 and len(x.mode()) > 0 else ''),
        urban_rural_tier=('urban_rural_tier', lambda x: x.mode().iloc[0] if len(x) > 0 and len(x.mode()) > 0 else ''),
        centroid_lat=('latitude','mean'),
        centroid_lon=('longitude','mean'),
    )
    .reset_index())
cluster_summary['project_id'] = cluster_summary['cluster_label'].apply(
    lambda x: f'CLUSTER_{x+1:05d}')
cluster_summary['method'] = 'spatial_cluster'

print(f"\nCluster size distribution:")
bins  = [3, 4, 5, 10, 20, 50, 100, 9999]
labels = ['4','5-9','10-19','20-49','50-99','100+']
cluster_summary['size_bin'] = pd.cut(cluster_summary['site_count'], bins=bins,
                                     labels=['3-4'] + labels)
print(cluster_summary['size_bin'].value_counts().sort_index().to_string())

# Top 20 largest clusters
print(f"\nTop 20 largest spatial clusters:")
top = cluster_summary.nlargest(20, 'site_count')[
    ['project_id','town','site_count','total_units','year_min','year_max','urban_rural_tier']]
print(top.to_string(index=False))

# ── 5. Validate: compare top ESITE parcel groups to DBSCAN clusters ──────────
print(f"\n=== Validation: ESITE parcel groups vs DBSCAN clusters ===")
print("Top ESITE parcel groups (≥20 sites):")
top_parcel = parcel_subdivisions[parcel_subdivisions['parcel_site_count'] >= 20].sort_values(
    'parcel_site_count', ascending=False)
print(top_parcel[['TOWNNAME','parcelnum_clean','parcel_site_count','parcel_year_min','parcel_year_max','parcel_lat','parcel_lon']].to_string(index=False))

# ── 6. Write project_groups table to SQLite ──────────────────────────────────
con = sqlite3.connect(DB)
cur = con.cursor()

# Drop and recreate project_groups
cur.execute('DROP TABLE IF EXISTS project_groups')
con.commit()

cluster_summary_db = cluster_summary[[
    'project_id','town','urban_rural_tier','site_count','total_units',
    'year_min','year_max','centroid_lat','centroid_lon','method'
]].copy()
cluster_summary_db.to_sql('project_groups', con, if_exists='replace', index=False)
esite_parcel_groups_db.to_sql('esite_parcel_groups', con, if_exists='replace', index=False)

# Add project_id column to dhcd_new_housing
try:
    cur.execute('ALTER TABLE dhcd_new_housing ADD COLUMN project_id TEXT')
except sqlite3.OperationalError:
    pass  # already exists

# Update project_ids
update_map = dhcd_out.set_index('esite_id')['project_id'].dropna().to_dict()
for esite_id, pid in update_map.items():
    cur.execute('UPDATE dhcd_new_housing SET project_id = ? WHERE esite_id = ?',
                (pid, int(esite_id) if str(esite_id).isdigit() else esite_id))

con.commit()
total_tagged = cur.execute("SELECT COUNT(*) FROM dhcd_new_housing WHERE project_id IS NOT NULL").fetchone()[0]
print(f"\nTagged {total_tagged:,} DHCD records with project_id")

# Summary query
summary = pd.read_sql_query('''
    SELECT urban_rural_tier,
           COUNT(*) as clusters,
           SUM(site_count) as total_sfh_sites,
           ROUND(AVG(site_count),1) as avg_cluster_size,
           MAX(site_count) as max_cluster_size
    FROM project_groups
    GROUP BY urban_rural_tier
    ORDER BY avg_cluster_size DESC
''', con)
print("\nCluster summary by urban/rural tier:")
print(summary.to_string(index=False))

con.close()
print(f"\nDatabase updated → {DB}")
