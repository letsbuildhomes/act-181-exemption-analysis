"""
build_map_data.py

Builds three GeoJSON files for the interactive Leaflet.js map in index.html:

  exemption_union.geojson       — simplified union of all 5 Act 181 exemption
                                   area layers, for the polygon overlay
  dhcd_inside_exemption.geojson — DHCD project points inside the exemption area
  dhcd_outside_exemption.geojson — DHCD project points outside the exemption area

Points are split into two files so that Leaflet.markercluster never groups
inside-exemption and outside-exemption projects into the same cluster.

Run after add_exemption_areas.py (requires in_exemption_area column in DB).
"""

import json
import os
import sqlite3

import geopandas as gpd
from shapely.ops import unary_union

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = os.path.join(HERE, 'housing_dev.db')
MAPS   = os.path.join(HERE, 'data', 'exemption-areas')
OUTPUT = os.path.join(HERE, 'output')
os.makedirs(OUTPUT, exist_ok=True)

EXEMPTION_FILES = [
    'downtown_district.geojson',
    'town_growth_centers.geojson',
    'village_center_buffer.geojson',
    'priority_housing_projects.geojson',
    'urbanized_transit_buffer.geojson',
]

# ── 1. Build exemption_union.geojson ─────────────────────────────────────────

print("Loading exemption area layers…")
gdfs = []
for fname in EXEMPTION_FILES:
    path = os.path.join(MAPS, fname)
    gdf = gpd.read_file(path).set_crs('EPSG:4326', allow_override=True)
    gdfs.append(gdf)
    print(f"  {fname.replace('.geojson','')}: {len(gdf)} features")

import pandas as pd
all_geoms = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs='EPSG:4326')
print(f"\nUnioning {len(all_geoms)} total features…")
union = unary_union(all_geoms.geometry)

# Simplify to reduce file size (~10m tolerance in degrees at VT latitude)
simplified = union.simplify(0.0001, preserve_topology=True)
print(f"  Geometry type after union: {simplified.geom_type}")

exemption_geojson = {
    "type": "Feature",
    "geometry": simplified.__geo_interface__,
    "properties": {"name": "Act 181 Exemption Areas (Union of 5 Layers)"}
}

out_path = os.path.join(OUTPUT, 'exemption_union.geojson')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(exemption_geojson, f, separators=(',', ':'))
size_kb = os.path.getsize(out_path) / 1024
print(f"  Written: exemption_union.geojson ({size_kb:.0f} KB)")

# ── 2. Build dhcd point GeoJSON files ────────────────────────────────────────

print("\nLoading DHCD points from DB…")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute("""
    SELECT
        latitude,
        longitude,
        site_type_general,
        unit_count,
        year_built,
        address,
        affordable,
        in_exemption_area
    FROM dhcd_new_housing
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND in_exemption_area IS NOT NULL
      AND LOWER(COALESCE(site_type, '')) NOT IN (
          'camp', 'seasonal home', 'seasonal camp', 'camp/seasonal home', 'seasonal')
""").fetchall()
con.close()

print(f"  Total records with coords + exemption status: {len(rows):,}")

inside_features  = []
outside_features = []

for r in rows:
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [r['longitude'], r['latitude']]
        },
        "properties": {
            "type":       r['site_type_general'] or 'Other',
            "units":      int(r['unit_count'] or 1),
            "year":       int(r['year_built'] or 0),
            "addr":       r['address'] or '',
            "affordable": 1 if str(r['affordable'] or '').upper() == 'YES' else 0,
        }
    }
    if r['in_exemption_area'] == 1:
        inside_features.append(feature)
    else:
        outside_features.append(feature)

print(f"  Inside exemption area:  {len(inside_features):,} points")
print(f"  Outside exemption area: {len(outside_features):,} points")

for fname, features in [
    ('dhcd_inside_exemption.geojson',  inside_features),
    ('dhcd_outside_exemption.geojson', outside_features),
]:
    fc = {"type": "FeatureCollection", "features": features}
    out_path = os.path.join(OUTPUT, fname)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, separators=(',', ':'))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Written: {fname} ({size_kb:.0f} KB)")

print("\nDone.")
