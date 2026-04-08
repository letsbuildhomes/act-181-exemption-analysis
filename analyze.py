"""
analyze.py

Reads housing.db and produces:
  output/index.html                  — HTML report with charts and map
  output/exemption_union.geojson     — union of all 5 exemption-area layers
  output/dhcd_inside_exemption.geojson  — DHCD points inside exemption area
  output/dhcd_outside_exemption.geojson — DHCD points outside exemption area

Usage:
    python3 analyze.py
"""

import json
import os
import sqlite3

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from config import START_YEAR, END_YEAR, PROJ_START_YEAR, PROJ_END_YEAR

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = os.path.join(HERE, "housing.db")
MAPS   = os.path.join(HERE, "data", "exemption-areas")
OUTPUT = os.path.join(HERE, "output")
os.makedirs(OUTPUT, exist_ok=True)

STATE_TARGET_LOWER = 5573   # Act 47 (2023) minimum annual housing target
STATE_TARGET_UPPER = 8237   # Act 47 (2023) upper annual housing target
VAPDA_INSIDE_PCT   = 0.60   # VAPDA projection: share of future housing inside growth areas

EXEMPTION_FILES = [
    "downtown_district.geojson",
    "town_growth_centers.geojson",
    "village_center_buffer.geojson",
    "priority_housing_projects.geojson",
    "urbanized_transit_buffer.geojson",
]

EXEMPTION_LAYER_NAMES = [
    "Downtown District Area",
    "Town and Growth Centers & Development Areas",
    "Village Center & Buffer",
    "Priority Housing Projects within Buffer",
    "Urbanized Area within Transit Route Buffer",
]

# Friendly display names for site_type_general values
TYPE_DISPLAY = {
    "SINGLE FAMILY DWELLING": "Single Family",
    "MULTI-FAMILY DWELLING":  "Multi Family",
    "OTHER RESIDENTIAL":      "Other",
}

SEASONAL_EXCLUDED = [
    "Camp", "Seasonal Home", "Seasonal Camp",
    "Camp/Seasonal Home", "Seasonal",
]

# ── 1. Query data ─────────────────────────────────────────────────────────────

print("Querying housing.db...")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

YEAR_FILTER = f"""
    year_built BETWEEN {START_YEAR} AND {END_YEAR}
    AND in_exemption_area IS NOT NULL
"""

# Q1: Annual inside/outside totals
annual_rows = con.execute(f"""
    SELECT
        CAST(year_built AS INTEGER) AS yr,
        SUM(CASE WHEN in_exemption_area=1 THEN unit_count ELSE 0 END) AS inside,
        SUM(CASE WHEN in_exemption_area=0 THEN unit_count ELSE 0 END) AS outside
    FROM housing
    WHERE {YEAR_FILTER}
    GROUP BY yr
    ORDER BY yr
""").fetchall()

years = list(range(START_YEAR, END_YEAR + 1))
annual = {y: {"inside": 0, "outside": 0} for y in years}
for r in annual_rows:
    if r["yr"] in annual:
        annual[r["yr"]]["inside"]  = int(r["inside"]  or 0)
        annual[r["yr"]]["outside"] = int(r["outside"] or 0)

hist_inside  = [annual[y]["inside"]  for y in years]
hist_outside = [annual[y]["outside"] for y in years]
hist_total   = [annual[y]["inside"] + annual[y]["outside"] for y in years]
grand_total  = sum(hist_total)

# Q2: Per-type inside/outside totals
type_rows = con.execute(f"""
    SELECT
        site_type_general,
        SUM(CASE WHEN in_exemption_area=1 THEN unit_count ELSE 0 END) AS inside,
        SUM(CASE WHEN in_exemption_area=0 THEN unit_count ELSE 0 END) AS outside
    FROM housing
    WHERE {YEAR_FILTER}
    GROUP BY site_type_general
    ORDER BY (inside + outside) DESC
""").fetchall()

# Q3: Per-type per-year (for stats table)
type_year_rows = con.execute(f"""
    SELECT
        CAST(year_built AS INTEGER) AS yr,
        site_type_general,
        SUM(CASE WHEN in_exemption_area=1 THEN unit_count ELSE 0 END) AS inside,
        SUM(CASE WHEN in_exemption_area=0 THEN unit_count ELSE 0 END) AS outside
    FROM housing
    WHERE {YEAR_FILTER}
    GROUP BY yr, site_type_general
    ORDER BY yr, site_type_general
""").fetchall()

# Count records missing coordinates (for data notes)
missing_coords = con.execute("""
    SELECT COUNT(*) FROM housing WHERE latitude IS NULL OR longitude IS NULL
""").fetchone()[0]

con.close()
print(f"  Annual totals: {grand_total:,} units ({START_YEAR}–{END_YEAR})")
print(f"  Missing coords: {missing_coords:,} records excluded from map/exemption analysis")

# ── 2. Derived stats ──────────────────────────────────────────────────────────

total_inside  = sum(hist_inside)
total_outside = sum(hist_outside)
inside_pct    = round(total_inside  / grand_total * 100, 1) if grand_total else 0
outside_pct   = round(total_outside / grand_total * 100, 1) if grand_total else 0

# Annual percentage stats (for table)
annual_stats = []
for y in years:
    t = annual[y]["inside"] + annual[y]["outside"]
    annual_stats.append({
        "year":    y,
        "inside":  annual[y]["inside"],
        "outside": annual[y]["outside"],
        "total":   t,
        "in_pct":  round(annual[y]["inside"]  / t * 100, 1) if t else 0,
        "out_pct": round(annual[y]["outside"] / t * 100, 1) if t else 0,
    })

# Type stats
types_ordered = [r["site_type_general"] for r in type_rows]
type_inside  = {r["site_type_general"]: int(r["inside"]  or 0) for r in type_rows}
type_outside = {r["site_type_general"]: int(r["outside"] or 0) for r in type_rows}

# Type-year breakdown for stats table
type_year = {}  # type → year → {inside, outside}
for r in type_year_rows:
    tp = r["site_type_general"]
    yr = r["yr"]
    if tp not in type_year:
        type_year[tp] = {}
    type_year[tp][yr] = {"inside": int(r["inside"] or 0), "outside": int(r["outside"] or 0)}

# ── 3. Projection data ────────────────────────────────────────────────────────

target_mid          = (STATE_TARGET_LOWER + STATE_TARGET_UPPER) / 2
proj_annual_inside  = round(target_mid * VAPDA_INSIDE_PCT)
proj_annual_outside = round(target_mid * (1 - VAPDA_INSIDE_PCT))
proj_years          = list(range(PROJ_START_YEAR, PROJ_END_YEAR + 1))

all_labels     = [str(y) for y in years] + [str(y) for y in proj_years]
chart_h_inside  = hist_inside  + [None] * len(proj_years)
chart_h_outside = hist_outside + [None] * len(proj_years)
chart_p_inside  = [None] * len(years) + [proj_annual_inside]  * len(proj_years)
chart_p_outside = [None] * len(years) + [proj_annual_outside] * len(proj_years)

# ── 4. Build GeoJSON files ────────────────────────────────────────────────────

print("\nBuilding exemption_union.geojson...")
gdfs = []
for fname in EXEMPTION_FILES:
    path = os.path.join(MAPS, fname)
    gdf = gpd.read_file(path).set_crs("EPSG:4326", allow_override=True)
    gdfs.append(gdf)

all_geoms = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")
union = unary_union(all_geoms.geometry)
simplified = union.simplify(0.0001, preserve_topology=True)

exemption_geojson = {
    "type": "Feature",
    "geometry": simplified.__geo_interface__,
    "properties": {"name": "Act 181 Exemption Areas (Union of 5 Layers)"},
}
with open(os.path.join(OUTPUT, "exemption_union.geojson"), "w") as f:
    json.dump(exemption_geojson, f, separators=(",", ":"))
print(f"  Written: exemption_union.geojson ({os.path.getsize(os.path.join(OUTPUT, 'exemption_union.geojson')) / 1024:.0f} KB)")

print("Building DHCD point GeoJSON files...")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
point_rows = con.execute("""
    SELECT latitude, longitude, site_type_general, unit_count, year_built,
           address, affordable, in_exemption_area
    FROM housing
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND in_exemption_area IS NOT NULL
""").fetchall()
con.close()

inside_features  = []
outside_features = []
for r in point_rows:
    feat = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [r["longitude"], r["latitude"]],
        },
        "properties": {
            "type":       r["site_type_general"] or "Other",
            "units":      int(r["unit_count"] or 1),
            "year":       int(r["year_built"] or 0),
            "addr":       r["address"] or "",
            "affordable": 1 if str(r["affordable"] or "").upper() == "YES" else 0,
        },
    }
    if r["in_exemption_area"] == 1:
        inside_features.append(feat)
    else:
        outside_features.append(feat)

for fname, features in [
    ("dhcd_inside_exemption.geojson",  inside_features),
    ("dhcd_outside_exemption.geojson", outside_features),
]:
    fc = {"type": "FeatureCollection", "features": features}
    path = os.path.join(OUTPUT, fname)
    with open(path, "w") as f:
        json.dump(fc, f, separators=(",", ":"))
    print(f"  Written: {fname} ({len(features):,} points, {os.path.getsize(path) / 1024:.0f} KB)")

# ── 5. Build HTML stats table rows ────────────────────────────────────────────

def pct(n, d):
    return f"{round(n / d * 100, 1):.1f}%" if d else "—"

# Annual stats rows
annual_table_rows = ""
for s in annual_stats:
    annual_table_rows += f"""<tr>
      <td>{s['year']}</td>
      <td class="num">{s['inside']:,}</td>
      <td class="num">{s['outside']:,}</td>
      <td class="num">{s['total']:,}</td>
      <td class="num">{pct(s['inside'], s['total'])}</td>
      <td class="num">{pct(s['outside'], s['total'])}</td>
    </tr>"""
annual_table_rows += f"""<tr class="total-row">
  <td><strong>Total</strong></td>
  <td class="num"><strong>{total_inside:,}</strong></td>
  <td class="num"><strong>{total_outside:,}</strong></td>
  <td class="num"><strong>{grand_total:,}</strong></td>
  <td class="num"><strong>{inside_pct}%</strong></td>
  <td class="num"><strong>{outside_pct}%</strong></td>
</tr>"""

# Type stats rows
type_table_rows = ""
for tp in types_ordered:
    label = TYPE_DISPLAY.get(tp, tp or "Unknown")
    ti = type_inside.get(tp, 0)
    to_ = type_outside.get(tp, 0)
    tt = ti + to_
    # yearly breakdown
    for y in years:
        yd = type_year.get(tp, {}).get(y, {"inside": 0, "outside": 0})
        yt = yd["inside"] + yd["outside"]
        type_table_rows += f"""<tr>
          <td>{label}</td>
          <td>{y}</td>
          <td class="num">{yd['inside']:,}</td>
          <td class="num">{yd['outside']:,}</td>
          <td class="num">{yt:,}</td>
          <td class="num">{pct(yd['inside'], yt)}</td>
          <td class="num">{pct(yd['outside'], yt)}</td>
        </tr>"""
    type_table_rows += f"""<tr class="total-row">
      <td><strong>{label} — Total</strong></td>
      <td></td>
      <td class="num"><strong>{ti:,}</strong></td>
      <td class="num"><strong>{to_:,}</strong></td>
      <td class="num"><strong>{tt:,}</strong></td>
      <td class="num"><strong>{pct(ti, tt)}</strong></td>
      <td class="num"><strong>{pct(to_, tt)}</strong></td>
    </tr>"""

# Seasonal types list for data notes
seasonal_list = ", ".join(SEASONAL_EXCLUDED)

# Exemption layer names for data notes
exemption_layer_list = "".join(f"<li>{n}</li>" for n in EXEMPTION_LAYER_NAMES)

# ── 6. Serialize chart data ───────────────────────────────────────────────────

chart_labels_js        = json.dumps(all_labels)
chart_h_inside_js      = json.dumps(chart_h_inside)
chart_h_outside_js     = json.dumps(chart_h_outside)
chart_p_inside_js      = json.dumps(chart_p_inside)
chart_p_outside_js     = json.dumps(chart_p_outside)

type_labels_js    = json.dumps([TYPE_DISPLAY.get(t, t) for t in types_ordered])
type_inside_js    = json.dumps([type_inside.get(t, 0)  for t in types_ordered])
type_outside_js   = json.dumps([type_outside.get(t, 0) for t in types_ordered])

# ── 7. Write HTML ─────────────────────────────────────────────────────────────

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vermont Housing Production: Tier 1 Exemption Area Analysis</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet.fullscreen/dist/Control.FullScreen.css"/>
<script src="https://unpkg.com/leaflet.fullscreen/dist/Control.FullScreen.umd.js"></script>
<style>
  :root {{
    --green:  #074B41;
    --blue:   #8ED4DA;
    --orange: #F89C45;
    --red:    #F2644A;
    --cream:  #FAF7F2;
    --text:   #1a1a1a;
    --muted:  #5a5a5a;
    --border: #ddd;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    background: var(--cream);
    color: var(--text);
    line-height: 1.7;
    font-size: 16px;
  }}
  nav {{
    background: var(--green);
    padding: 0.65rem 2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
  }}
  .nav-logo {{ color: #fff; font-weight: bold; font-family: system-ui, sans-serif; font-size: 1rem; }}
  .nav-sub  {{ color: var(--blue); font-family: system-ui, sans-serif; font-size: 0.82rem; }}
  .hero {{
    background: var(--green);
    color: #fff;
    padding: 3rem 2rem 2.5rem;
    text-align: center;
  }}
  .hero h1 {{
    font-size: clamp(1.7rem, 3.5vw, 2.4rem);
    line-height: 1.2;
    max-width: 760px;
    margin: 0 auto 0.9rem;
  }}
  .hero p {{
    font-size: 1rem;
    max-width: 620px;
    margin: 0 auto;
    opacity: 0.87;
  }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 0 1.5rem; }}
  section {{ padding: 2.5rem 0; border-bottom: 1px solid var(--border); }}
  section:last-of-type {{ border-bottom: none; }}
  h2 {{ font-size: 1.45rem; color: var(--green); margin-bottom: 0.35rem; line-height: 1.25; }}
  h3 {{ font-size: 1.05rem; color: var(--green); margin: 1.4rem 0 0.4rem; }}
  .intro {{
    font-size: 0.95rem;
    color: var(--muted);
    max-width: 720px;
    margin-bottom: 1.4rem;
    line-height: 1.65;
    font-family: system-ui, sans-serif;
  }}
  .chart-wrap {{
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 1.2rem 1.2rem 0.8rem;
    margin: 1.2rem 0;
  }}
  .chart-label {{
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted);
    font-family: system-ui, sans-serif;
    margin-bottom: 0.6rem;
  }}
  .chart-container {{ position: relative; }}
  .chart-container.h340 {{ height: 340px; }}
  .chart-container.h260 {{ height: 260px; }}
  .table-wrap {{ overflow-x: auto; margin: 1.2rem 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; font-family: system-ui, sans-serif; }}
  thead th {{
    background: var(--green); color: #fff;
    padding: 0.55rem 0.8rem; text-align: left;
    font-weight: 600; white-space: nowrap;
  }}
  tbody tr:nth-child(even) {{ background: #f5f4ef; }}
  tbody td {{ padding: 0.45rem 0.8rem; border-bottom: 1px solid #e5e4df; vertical-align: middle; }}
  tr.total-row td {{ background: #eef4f2; font-weight: 600; border-top: 2px solid var(--green); }}
  .num {{ font-variant-numeric: tabular-nums; text-align: right; }}
  .note {{
    background: #fff;
    border-left: 4px solid var(--blue);
    padding: 0.8rem 1.1rem;
    margin: 0.9rem 0;
    font-size: 0.875rem;
    color: var(--muted);
    font-family: system-ui, sans-serif;
    border-radius: 0 3px 3px 0;
  }}
  .note strong {{ color: var(--text); }}
  #vt-map {{ height: 540px; border-radius: 5px; border: 1px solid var(--border); }}
  footer {{
    background: var(--green);
    color: rgba(255,255,255,0.7);
    text-align: center;
    padding: 1.8rem 1.5rem;
    font-size: 0.83rem;
    font-family: system-ui, sans-serif;
    margin-top: 1.5rem;
  }}
  footer a {{ color: var(--blue); }}
  a {{ color: var(--green); }}
  a:hover {{ color: var(--red); }}
  .data-notes ul {{ padding-left: 1.4rem; margin: 0.5rem 0; font-size: 0.9rem; font-family: system-ui, sans-serif; color: var(--muted); }}
  .data-notes li {{ margin: 0.3rem 0; line-height: 1.55; }}
  .data-notes p {{ font-size: 0.9rem; font-family: system-ui, sans-serif; color: var(--muted); margin: 0.6rem 0; line-height: 1.6; }}
</style>
</head>
<body>

<nav>
  <span class="nav-logo">Vermont Housing Development</span>
  <span class="nav-sub">Tier 1 Exemption Area Analysis · {START_YEAR}–{END_YEAR}</span>
</nav>

<div class="hero">
  <h1>Vermont New Housing Production:<br>Inside vs. Outside Tier 1 Areas</h1>
  <p>Unit counts from the DHCD housing database ({START_YEAR}–{END_YEAR}), classified by
     whether each site falls within Vermont's Act 181 tier 1 exemption area boundaries.</p>
</div>

<div class="container">

<!-- ── Section 1: Annual Production ──────────────────────────────────────── -->
<section>
  <h2>Annual Housing Production, {START_YEAR}–{END_YEAR}</h2>
  <p class="intro">The following chart shows the total number of housing units permitted
  each year, split by whether the site is inside or outside the Act 181 tier 1
  exemption areas. The shaded bars for {PROJ_START_YEAR}–{PROJ_END_YEAR} show projected
  production based on the Act 47 (2023) statewide housing target range
  ({STATE_TARGET_LOWER:,}–{STATE_TARGET_UPPER:,} units/year), with the VAPDA estimate
  that {round(VAPDA_INSIDE_PCT*100)}% of future housing will be built inside growth areas.
  Data source: DHCD Vermont New Housing database.</p>

  <div class="chart-wrap">
    <div class="chart-label">Annual units — inside vs. outside exemption areas (with {PROJ_START_YEAR}–{PROJ_END_YEAR} projections)</div>
    <div class="chart-container h340">
      <canvas id="annualChart"></canvas>
    </div>
  </div>

  <h3>Year-by-year breakdown</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Year</th>
          <th class="num">Inside units</th>
          <th class="num">Outside units</th>
          <th class="num">Total units</th>
          <th class="num">Inside %</th>
          <th class="num">Outside %</th>
        </tr>
      </thead>
      <tbody>
        {annual_table_rows}
      </tbody>
    </table>
  </div>
</section>

<!-- ── Section 2: Housing Types ──────────────────────────────────────────── -->
<section>
  <h2>Housing Types Inside vs. Outside Exemption Areas</h2>
  <p class="intro">The following chart breaks down units by housing type (using the
  <code>SiteType_General</code> field from the DHCD source data), split by exemption
  area status. Totals cover {START_YEAR}–{END_YEAR}; the per-year table below shows the
  same breakdown for each year individually.</p>

  <div class="chart-wrap">
    <div class="chart-label">Total units by type — inside vs. outside exemption areas ({START_YEAR}–{END_YEAR})</div>
    <div class="chart-container h260">
      <canvas id="typeChart"></canvas>
    </div>
  </div>

  <h3>Per-type, per-year breakdown</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Type</th>
          <th>Year</th>
          <th class="num">Inside units</th>
          <th class="num">Outside units</th>
          <th class="num">Total units</th>
          <th class="num">Inside %</th>
          <th class="num">Outside %</th>
        </tr>
      </thead>
      <tbody>
        {type_table_rows}
      </tbody>
    </table>
  </div>
</section>

<!-- ── Section 3: Map ─────────────────────────────────────────────────────── -->
<section>
  <h2>Geographic Distribution</h2>
  <p class="intro">Each point represents a housing site from the DHCD database
  ({START_YEAR}–{END_YEAR}). The green shaded polygon shows the union of all five Act 181
  tier 1 exemption area layers. Points are colored by housing type; cluster circles show
  the total unit count across all sites in that cluster. Use the layer toggle (top right)
  to show or hide inside/outside groups. Sites missing coordinates are excluded from the
  map.</p>

  <div id="vt-map"></div>
</section>

<!-- ── Section 4: Data Notes ─────────────────────────────────────────────── -->
<section class="data-notes">
  <h2>Data Notes</h2>
  <p><strong>Primary data source:</strong> Vermont DHCD New Housing database, downloaded
  from the Vermont ArcGIS REST API (Vermont_New_Housing FeatureServer). Analysis covers
  permit years {START_YEAR}–{END_YEAR}.</p>

  <p><strong>Seasonal exclusions:</strong> The following site types are excluded from
  all analysis and do not appear in the database: {seasonal_list}.</p>

  <p><strong>Records missing coordinates:</strong> {missing_coords:,} records in the
  full database have no latitude/longitude and are therefore excluded from the map
  and from the inside/outside exemption area classification. They are not included in
  any unit count totals shown above.</p>

  <p><strong>Exemption area definition:</strong> "Inside the exemption area" means a
  site's coordinates fall within the union of the following five Act 181 tier 1
  exemption-area layers:</p>
  <ul>
    {exemption_layer_list}
  </ul>

  <p><strong>Housing type classification:</strong> Types are taken directly from the
  <code>SiteType_General</code> field in the DHCD source data. No custom remapping
  is applied.</p>

  <p><strong>Projection methodology:</strong> The {PROJ_START_YEAR}–{PROJ_END_YEAR}
  projected bars use the midpoint of the Act 47 (2023) statewide housing target
  ({STATE_TARGET_LOWER:,}–{STATE_TARGET_UPPER:,} units/year =
  {round((STATE_TARGET_LOWER + STATE_TARGET_UPPER) / 2):,} units/year midpoint),
  split {round(VAPDA_INSIDE_PCT*100)}/{round((1-VAPDA_INSIDE_PCT)*100)} inside/outside
  per the VAPDA estimate. These are illustrative targets, not forecasts.</p>
</section>

</div><!-- /container -->

<footer>
  Vermont Housing Development Analysis &mdash; Data: DHCD Vermont New Housing Database &amp;
  Vermont Act 181 Exemption Area GIS layers.
</footer>

<script>
// ── Annual production chart (stacked vertical bar) ────────────────────────
(function () {{
  const labels   = {chart_labels_js};
  const hInside  = {chart_h_inside_js};
  const hOutside = {chart_h_outside_js};
  const pInside  = {chart_p_inside_js};
  const pOutside = {chart_p_outside_js};

  new Chart(document.getElementById('annualChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          label:           'Inside (historical)',
          data:            hInside,
          backgroundColor: '#074B41',
          stack:           'hist',
        }},
        {{
          label:           'Outside (historical)',
          data:            hOutside,
          backgroundColor: '#8ED4DA',
          stack:           'hist',
        }},
        {{
          label:           'Inside (projected)',
          data:            pInside,
          backgroundColor: 'rgba(7,75,65,0.35)',
          borderColor:     '#074B41',
          borderWidth:     1.5,
          borderDash:      [4, 3],
          stack:           'proj',
        }},
        {{
          label:           'Outside (projected)',
          data:            pOutside,
          backgroundColor: 'rgba(142,212,218,0.35)',
          borderColor:     '#8ED4DA',
          borderWidth:     1.5,
          stack:           'proj',
        }},
      ],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ family: 'system-ui' }}, boxWidth: 14 }} }},
        tooltip: {{
          callbacks: {{
            label: ctx => ctx.parsed.y != null ? ` ${{ctx.dataset.label}}: ${{ctx.parsed.y.toLocaleString()}} units` : null,
          }},
        }},
      }},
      scales: {{
        x: {{ stacked: true }},
        y: {{ stacked: true, beginAtZero: true, ticks: {{ font: {{ family: 'system-ui' }} }} }},
      }},
    }},
  }});
}})();

// ── Type chart (stacked horizontal bar) ──────────────────────────────────
(function () {{
  const labels  = {type_labels_js};
  const inside  = {type_inside_js};
  const outside = {type_outside_js};

  new Chart(document.getElementById('typeChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          label:           'Inside exemption area',
          data:            inside,
          backgroundColor: '#074B41',
        }},
        {{
          label:           'Outside exemption area',
          data:            outside,
          backgroundColor: '#8ED4DA',
        }},
      ],
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ family: 'system-ui' }}, boxWidth: 14 }} }},
        tooltip: {{
          callbacks: {{
            label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.x.toLocaleString()}} units`,
          }},
        }},
      }},
      scales: {{
        x: {{ stacked: true, beginAtZero: true, ticks: {{ font: {{ family: 'system-ui' }} }} }},
        y: {{ stacked: true }},
      }},
    }},
  }});
}})();

// ── Leaflet map ────────────────────────────────────────────────────────────
(function () {{
  const map = L.map('vt-map', {{ zoomSnap: 0.5 }}).setView([44.0, -72.7], 8);

  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }}).addTo(map);

  new L.Control.FullScreen().addTo(map);

  // Color by site_type_general
  const TYPE_COLORS = {{
    'SINGLE FAMILY DWELLING': '#F89C45',
    'MULTI-FAMILY DWELLING':  '#8ED4DA',
    'OTHER RESIDENTIAL':      '#F2644A',
  }};
  const TYPE_LABELS = {{
    'SINGLE FAMILY DWELLING': 'Single Family',
    'MULTI-FAMILY DWELLING':  'Multi Family',
    'OTHER RESIDENTIAL':      'Other',
  }};

  function dotColor(type) {{
    return TYPE_COLORS[type] || '#aaaaaa';
  }}

  // Cluster icon: sum of unit_count across child markers, log-scaled saturation
  function makeClusterIcon(cluster, isInside) {{
    const total = cluster.getAllChildMarkers()
      .reduce((sum, m) => sum + (m._units || 1), 0);
    const label = total >= 1000 ? (total / 1000).toFixed(1) + 'k' : String(total);
    const size  = total >= 500 ? 44 : total >= 100 ? 36 : 30;
    const t = Math.min(Math.log10(Math.max(total, 1)) / Math.log10(500), 1.0);
    const bg = isInside
      ? `hsl(10,${{Math.round(22 + t * 64)}}%,60%)`
      : `hsl(158,${{Math.round(15 + t * 50)}}%,42%)`;
    return L.divIcon({{
      html: `<div style="width:${{size}}px;height:${{size}}px;background:${{bg}};color:#fff;
        border-radius:50%;border:2px solid #fff;display:flex;align-items:center;
        justify-content:center;font-family:system-ui,sans-serif;
        font-size:${{size >= 40 ? 11 : 10}}px;font-weight:700;line-height:1;
        box-shadow:0 1px 4px rgba(0,0,0,0.35);">${{label}}</div>`,
      className: '',
      iconSize: L.point(size, size),
      iconAnchor: L.point(size / 2, size / 2),
    }});
  }}

  const insideCluster = L.markerClusterGroup({{
    chunkedLoading: true, maxClusterRadius: 40,
    iconCreateFunction: c => makeClusterIcon(c, true),
  }});
  const outsideCluster = L.markerClusterGroup({{
    chunkedLoading: true, maxClusterRadius: 40,
    iconCreateFunction: c => makeClusterIcon(c, false),
  }});

  function makeMarker(feature, isInside) {{
    const p      = feature.properties;
    const color  = dotColor(p.type);
    const latlng = [feature.geometry.coordinates[1], feature.geometry.coordinates[0]];
    const marker = L.circleMarker(latlng, {{
      radius: 5, fillColor: color,
      color: isInside ? '#ffffff' : '#333333',
      weight: 1.5, fillOpacity: 0.88,
    }});
    const typeLabel = TYPE_LABELS[p.type] || (p.type || 'Other');
    marker._units = p.units;
    marker.bindPopup(
      `<b style="font-family:system-ui,sans-serif">${{p.addr || 'Address unknown'}}</b><br>
       <span style="font-family:system-ui,sans-serif;font-size:0.88em">
         ${{typeLabel}} &middot; ${{p.units}} unit${{p.units !== 1 ? 's' : ''}}<br>
         Year built: ${{p.year || 'unknown'}}<br>
         ${{isInside
           ? '<span style="color:#074B41">&#10003; Inside exemption area</span>'
           : '<span style="color:#F2644A">&#10007; Outside exemption area</span>'}}
       </span>`,
      {{ maxWidth: 240 }}
    );
    return marker;
  }}

  fetch('exemption_union.geojson')
    .then(r => r.json())
    .then(data => {{
      L.geoJSON(data, {{
        style: {{ color: '#074B41', weight: 1.5, fillColor: '#074B41', fillOpacity: 0.12 }},
      }}).addTo(map);
    }})
    .catch(() => console.warn('exemption_union.geojson not found'));

  Promise.all([
    fetch('dhcd_inside_exemption.geojson').then(r => r.json()),
    fetch('dhcd_outside_exemption.geojson').then(r => r.json()),
  ]).then(([inside, outside]) => {{
    inside.features.forEach(f  => insideCluster.addLayer(makeMarker(f, true)));
    outside.features.forEach(f => outsideCluster.addLayer(makeMarker(f, false)));
    insideCluster.addTo(map);
    outsideCluster.addTo(map);
    L.control.layers(null, {{
      'Inside exemption area':  insideCluster,
      'Outside exemption area': outsideCluster,
    }}, {{ collapsed: false }}).addTo(map);
  }}).catch(() => console.warn('DHCD point GeoJSON files not found'));
}})();
</script>
</body>
</html>"""

out_path = os.path.join(OUTPUT, "index.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
size_kb = os.path.getsize(out_path) / 1024
print(f"\n✓ Written: output/index.html ({size_kb:.0f} KB)")
print("Done.")
