"""
generate_site.py — reads housing_dev.db and produces output/index.html

Usage:
    python3 generate_site.py               # writes output/index.html
    python3 generate_site.py path/out.html # writes to a custom path
"""

import os
import sys
import sqlite3
import json

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = os.path.join(HERE, 'housing_dev.db')
OUTPUT = os.path.join(HERE, 'output')
os.makedirs(OUTPUT, exist_ok=True)
OUT    = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUTPUT, 'index.html')

from config import START_YEAR, END_YEAR, PROJ_START_YEAR, PROJ_END_YEAR

STATE_TARGET_LOWER = 5573    # Act 47 (2023) minimum annual housing target
STATE_TARGET_UPPER = 8237    # Act 47 (2023) upper annual housing target
VAPDA_INSIDE_PCT   = 0.60    # VAPDA projection: share of future housing inside growth areas

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── 1. Annual production by tier (year-round only) ────────────────────────────
annual_rows = con.execute(f'''
    SELECT
        CAST(d.year_built AS INTEGER) AS yr,
        LOWER(COALESCE(t.urban_rural_tier,'rural')) AS tier,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY yr, tier
    ORDER BY yr, tier
''').fetchall()

years  = list(range(START_YEAR, END_YEAR + 1))
tiers  = ['rural','suburban','urban']
annual = {t: {y: 0 for y in years} for t in tiers}
for r in annual_rows:
    if r['tier'] in annual:
        annual[r['tier']][r['yr']] = int(r['units'] or 0)

annual_labels   = [str(y) for y in years]
annual_rural    = [annual['rural'][y]    for y in years]
annual_suburban = [annual['suburban'][y] for y in years]
annual_urban    = [annual['urban'][y]    for y in years]
annual_total    = [annual['rural'][y]+annual['suburban'][y]+annual['urban'][y] for y in years]


total_units = sum(annual_total)
avg_annual  = round(total_units / len(years))

# Rural share of year-round production
rural_total    = sum(annual_rural)
rural_pct      = round(rural_total / total_units * 100)
non_urban_pct  = round((rural_total + sum(annual_suburban)) / total_units * 100)

# ── 2. Project scale by tier (% of units) ────────────────────────────────────
scale_rows = con.execute(f'''
    SELECT
        LOWER(COALESCE(t.urban_rural_tier,'rural')) AS tier,
        CASE
            WHEN d.unit_count=1               THEN 'single'
            WHEN d.unit_count BETWEEN 2 AND 9  THEN 'small'
            WHEN d.unit_count BETWEEN 10 AND 49 THEN 'medium'
            ELSE 'large'
        END AS bucket,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY tier, bucket
''').fetchall()

buckets = ['single','small','medium','large']
scale   = {t: {b: 0 for b in buckets} for t in tiers}
for r in scale_rows:
    if r['tier'] in scale:
        scale[r['tier']][r['bucket']] = int(r['units'] or 0)

# Compute each tier's share of total year-round statewide production
def pct_of_statewide(d):
    return {b: round(d[b] / total_units * 100, 1) if total_units else 0 for b in buckets}

scale_pct = {t: pct_of_statewide(scale[t]) for t in tiers}

# Rural single-unit share as % of rural production
rural_tier_total = sum(scale['rural'].values())
rural_single_pct = round(scale['rural']['single'] / rural_tier_total * 100, 1) if rural_tier_total else 0

# ── 3. Rural construction types (year-round only — seasonals fully excluded) ───
type_rows = con.execute(f'''
    SELECT
        CASE
            WHEN d.unit_count=1
                 AND LOWER(COALESCE(d.site_type,'')) NOT LIKE '%condo%'
                 AND LOWER(COALESCE(d.site_type,'')) NOT LIKE '%apartment%'
                 AND LOWER(COALESCE(d.site_type,'')) NOT LIKE '%multi%'
                 AND LOWER(COALESCE(d.site_type,'')) NOT LIKE '%mobile%'
                THEN 'Single-Family Home'
            WHEN d.unit_count>=2
                THEN 'Multi-Family / Condo'
            ELSE 'Other'
        END AS label,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(t.urban_rural_tier,'rural'))='rural'
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY label
    ORDER BY units DESC
''').fetchall()

type_labels = [r['label'] for r in type_rows]
type_units  = [int(r['units']) for r in type_rows]
type_total  = sum(type_units)

# Single-family share of year-round rural permits
rural_sfh_pct = round(
    next((int(r['units']) for r in type_rows if r['label']=='Single-Family Home'), 0)
    / type_total * 100, 1
) if type_total else 0

# ── 4. Municipality classification table ──────────────────────────────────
muni_rows = con.execute('''
    SELECT
        townname_title                          AS town,
        population_2020,
        ROUND(pop_density_km2, 1)               AS density,
        COALESCE(urban_rural_tier, 'rural')     AS tier
    FROM town_lookup
    ORDER BY townname_title
''').fetchall()
muni_data = [
    {
        'town':    r['town'],
        'pop':     int(r['population_2020']) if r['population_2020'] is not None else None,
        'density': float(r['density'])       if r['density']         is not None else None,
        'tier':    r['tier'],
    }
    for r in muni_rows
]

# ── 6b. Exemption area analysis ───────────────────────────────────────────
EXEMPT_SEASONAL_FILTER = """
      AND LOWER(COALESCE(site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
"""

exempt_summary_rows = con.execute(f'''
    SELECT
        in_exemption_area,
        SUM(unit_count) AS units
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
      {EXEMPT_SEASONAL_FILTER}
    GROUP BY in_exemption_area
    ORDER BY in_exemption_area DESC
''').fetchall()

exempt_inside_units  = next((int(r['units'] or 0) for r in exempt_summary_rows if r['in_exemption_area'] == 1), 0)
exempt_outside_units = next((int(r['units'] or 0) for r in exempt_summary_rows if r['in_exemption_area'] == 0), 0)
exempt_total_units   = exempt_inside_units + exempt_outside_units
exempt_inside_pct    = round(exempt_inside_units  / exempt_total_units * 100) if exempt_total_units else 0
exempt_outside_pct   = 100 - exempt_inside_pct

exempt_type_rows = con.execute(f'''
    SELECT
        site_type_general,
        SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
        SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
      {EXEMPT_SEASONAL_FILTER}
    GROUP BY site_type_general
    ORDER BY (inside_units + outside_units) DESC
''').fetchall()

_TYPE_DISPLAY = {
    'MULTI-FAMILY DWELLING':  'Multi-Family',
    'SINGLE FAMILY DWELLING': 'Single-Family',
    'OTHER RESIDENTIAL':      'Other Residential',
}
exempt_type_labels  = [_TYPE_DISPLAY.get(r['site_type_general'], (r['site_type_general'] or 'Other').title()) for r in exempt_type_rows]
exempt_type_inside  = [int(r['inside_units']  or 0) for r in exempt_type_rows]
exempt_type_outside = [int(r['outside_units'] or 0) for r in exempt_type_rows]

_mf = next((r for r in exempt_type_rows if r['site_type_general'] and 'MULTI'   in r['site_type_general']), None)
_sf = next((r for r in exempt_type_rows if r['site_type_general'] and 'SINGLE'  in r['site_type_general']), None)
mf_inside_pct  = round(int(_mf['inside_units']  or 0) / max(int(_mf['inside_units'] or 0) + int(_mf['outside_units'] or 0), 1) * 100) if _mf else 0
sf_outside_pct = round(int(_sf['outside_units'] or 0) / max(int(_sf['inside_units'] or 0) + int(_sf['outside_units'] or 0), 1) * 100) if _sf else 0

exempt_year_rows = con.execute(f'''
    SELECT
        CAST(year_built AS INTEGER) AS yr,
        SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
        SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
      {EXEMPT_SEASONAL_FILTER}
    GROUP BY yr
    ORDER BY yr
''').fetchall()

exempt_year_inside  = [int(r['inside_units']  or 0) for r in exempt_year_rows]
exempt_year_outside = [int(r['outside_units'] or 0) for r in exempt_year_rows]

# ── Projected target chart data (VAPDA 60/40 inside/outside split) ────────
target_mid           = (STATE_TARGET_LOWER + STATE_TARGET_UPPER) / 2
proj_annual_inside   = round(target_mid * VAPDA_INSIDE_PCT)
proj_annual_outside  = round(target_mid * (1 - VAPDA_INSIDE_PCT))
avg_vs_lower_pct     = round(avg_annual / STATE_TARGET_LOWER * 100)
avg_vs_upper_pct     = round(avg_annual / STATE_TARGET_UPPER * 100)
target_multiple      = round(STATE_TARGET_LOWER / avg_annual, 1)

PROJ_YEARS           = list(range(PROJ_START_YEAR, PROJ_END_YEAR + 1))
chart_all_labels     = [str(y) for y in years] + [str(y) for y in PROJ_YEARS]
chart_hist_inside    = exempt_year_inside  + [None] * len(PROJ_YEARS)
chart_hist_outside   = exempt_year_outside + [None] * len(PROJ_YEARS)
chart_proj_inside    = [None] * len(years) + [proj_annual_inside]  * len(PROJ_YEARS)
chart_proj_outside   = [None] * len(years) + [proj_annual_outside] * len(PROJ_YEARS)

# ── Total seasonal permits excluded (for disclaimer) ──────────────────────
seasonal_excluded = int(con.execute(f'''
    SELECT SUM(unit_count) FROM dhcd_new_housing
    WHERE year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(site_type,'')) IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
''').fetchone()[0] or 0)

con.close()

# ── Build HTML rows ───────────────────────────────────────────────────────────
def tier_badge(tier):
    t = (tier or 'unknown').lower()
    cls = t if t in ('urban','suburban','rural') else 'unknown'
    return f'<span class="badge badge-{cls}">{t.title()}</span>'

# ── Municipality table rows ───────────────────────────────────────────────────
muni_rows_html = ''
for m in muni_data:
    pop_str     = f"{m['pop']:,}"     if m['pop']     is not None else '—'
    density_str = f"{m['density']}"   if m['density'] is not None else '—'
    muni_rows_html += f'''<tr>
      <td>{m["town"]}</td>
      <td class="num">{pop_str}</td>
      <td class="num">{density_str}</td>
      <td>{tier_badge(m["tier"])}</td>
    </tr>'''

# ── Main HTML ─────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vermont Housing Production: What's Actually Being Built?</title>
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

  /* Nav */
  nav {{
    background: var(--green);
    padding: 0.65rem 2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
  }}
  .nav-logo   {{ color:#fff; font-weight:bold; font-family:system-ui,sans-serif; font-size:1rem; }}
  .nav-sub    {{ color:var(--blue); font-family:system-ui,sans-serif; font-size:0.82rem; }}

  /* Hero */
  .hero {{
    background: var(--green);
    color: #fff;
    padding: 3rem 2rem 2.5rem;
    text-align: center;
  }}
  .hero h1 {{
    font-size: clamp(1.7rem, 3.5vw, 2.6rem);
    line-height: 1.2;
    max-width: 740px;
    margin: 0 auto 0.9rem;
  }}
  .hero p {{
    font-size: 1.05rem;
    max-width: 600px;
    margin: 0 auto;
    opacity: 0.87;
  }}

  /* Layout */
  .container {{ max-width: 960px; margin: 0 auto; padding: 0 1.5rem; }}
  section {{ padding: 2.5rem 0; border-bottom: 1px solid var(--border); }}
  section:last-of-type {{ border-bottom: none; }}

  h2 {{ font-size: 1.55rem; color: var(--green); margin-bottom: 0.35rem; line-height:1.25; }}
  h3 {{ font-size: 1.1rem; color: var(--green); margin: 1.4rem 0 0.4rem; }}

  .intro {{
    font-size: 1rem;
    color: var(--muted);
    max-width: 700px;
    margin-bottom: 1.4rem;
    line-height: 1.65;
  }}
  .intro p {{ margin-bottom: 0.75rem; }}

  /* Callouts */
  .callouts {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 0.9rem;
    margin: 1.2rem 0 1.6rem;
  }}
  .callout {{
    background: #fff;
    border: 1px solid var(--border);
    border-top: 4px solid var(--green);
    border-radius: 3px;
    padding: 1rem 1.2rem 0.9rem;
    text-align: center;
  }}
  .callout .num   {{ font-size: 2rem; font-weight: bold; color: var(--red); font-family: system-ui,sans-serif; line-height: 1; }}
  .callout .lbl   {{ font-size: 0.82rem; color: var(--muted); margin-top: 0.3rem; font-family: system-ui,sans-serif; }}

  /* Charts */
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
    font-family: system-ui,sans-serif;
    margin-bottom: 0.6rem;
  }}
  .chart-source {{
    font-size: 0.75rem;
    color: #999;
    font-family: system-ui,sans-serif;
    margin-top: 0.5rem;
    font-style: italic;
  }}
  .chart-container {{
    position: relative;
  }}
  .chart-container.h300 {{ height: 300px; }}
  .chart-container.h240 {{ height: 240px; }}
  .chart-container.h160 {{ height: 160px; }}
  .chart-container.h200 {{ height: 200px; }}

  /* Tables */
  .table-wrap {{ overflow-x: auto; margin: 1rem 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; font-family: system-ui,sans-serif; }}
  thead th {{
    background: var(--green); color: #fff;
    padding: 0.55rem 0.8rem; text-align: left;
    font-weight: 600; white-space: nowrap;
  }}
  tbody tr:nth-child(even) {{ background: #f5f4ef; }}
  tbody td {{ padding: 0.45rem 0.8rem; border-bottom: 1px solid #e5e4df; vertical-align: middle; }}
  .num   {{ font-variant-numeric: tabular-nums; }}
  .mono  {{ font-family: monospace; font-size: 0.82em; }}
  .small {{ font-size: 0.82em; }}

  /* Badges */
  .badge {{
    display: inline-block; padding: 0.12em 0.5em;
    border-radius: 20px; font-size: 0.75rem;
    font-family: system-ui,sans-serif; font-weight: 600;
  }}
  .badge-urban    {{ background:#e3f2f9; color:#0a5a7c; }}
  .badge-suburban {{ background:#fff3e0; color:#7c4400; }}
  .badge-rural    {{ background:#e5f2ee; color:#074B41; }}
  .badge-unknown  {{ background:#eee; color:#555; }}

  .source-tag {{
    display: inline-block; padding: 0.1em 0.45em;
    border-radius: 3px; font-size: 0.72rem;
    font-family: system-ui,sans-serif; font-weight: 700;
    letter-spacing: 0.03em;
  }}
  .source-dhcd  {{ background:#e5f2ee; color:#074B41; }}

  /* Note / caveat boxes */
  .note {{
    background: #fff;
    border-left: 4px solid var(--blue);
    padding: 0.8rem 1.1rem;
    margin: 0.9rem 0;
    font-size: 0.875rem;
    color: var(--muted);
    font-family: system-ui,sans-serif;
    border-radius: 0 3px 3px 0;
  }}
  .note strong {{ color: var(--text); }}
  .caveat {{
    background: #fff8f1;
    border-left: 4px solid var(--orange);
    padding: 0.8rem 1.1rem;
    margin: 0.9rem 0;
    font-size: 0.875rem;
    color: var(--muted);
    font-family: system-ui,sans-serif;
    border-radius: 0 3px 3px 0;
  }}

  /* Act 181 highlight box */
  .thesis-box {{
    border-radius: 5px;
    overflow: hidden;
    margin: 1.5rem 0;
    border: 2px solid var(--green);
  }}
  .thesis-box-header {{
    background: var(--green);
    padding: 1rem 2rem;
  }}
  .thesis-box-header h3 {{
    color: var(--blue);
    margin: 0;
    font-size: 1.15rem;
  }}
  .thesis-box-body {{
    background: #fff;
    padding: 1.2rem 2rem 1.5rem;
  }}
  .thesis-box-body p {{
    font-size: 0.98rem;
    color: var(--text);
    margin-top: 0.75rem;
    line-height: 1.6;
  }}
  .thesis-box-body p:first-child {{ margin-top: 0; }}

  /* Footer */
  footer {{
    background: var(--green);
    color: rgba(255,255,255,0.7);
    text-align: center;
    padding: 1.8rem 1.5rem;
    font-size: 0.83rem;
    font-family: system-ui,sans-serif;
    margin-top: 1.5rem;
  }}
  footer a {{ color: var(--blue); }}
  a {{ color: var(--green); }}
  a:hover {{ color: var(--red); }}
  ul.sources {{ margin-top: 0.8rem; padding-left: 0; list-style: none; }}
  ul.sources li {{ margin: 0.3rem 0; font-size: 0.875rem; font-family: system-ui,sans-serif; }}
  ul.sources li::before {{ content: "→ "; color: var(--green); font-weight: bold; }}

  /* Details / disclosure blocks */
  details {{
    border: 1px solid var(--border);
    border-radius: 4px;
    margin: 1.2rem 0;
    background: #fff;
  }}
  details[open] summary {{ border-bottom: 1px solid var(--border); }}
  summary {{
    padding: 0.65rem 1rem;
    font-family: system-ui, sans-serif;
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--green);
    cursor: pointer;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }}
  summary::-webkit-details-marker {{ display: none; }}
  summary::before {{
    content: "▶";
    font-size: 0.65rem;
    transition: transform 0.15s;
    display: inline-block;
  }}
  details[open] summary::before {{ transform: rotate(90deg); }}
  .details-body {{
    padding: 1rem 1.2rem 1.2rem;
    overflow-x: auto;
  }}
  .details-body p {{
    font-size: 0.875rem;
    color: var(--muted);
    font-family: system-ui, sans-serif;
    margin-bottom: 0.7rem;
    line-height: 1.55;
  }}
  .details-body table {{
    font-size: 0.82rem;
  }}
  .details-body thead th {{
    font-size: 0.8rem;
    padding: 0.4rem 0.7rem;
  }}
  .details-body tbody td {{
    padding: 0.35rem 0.7rem;
  }}
  .excluded-row td {{ color: #888; text-decoration: line-through; background: #fafafa; }}
  .excluded-row td:last-child {{ text-decoration: none; color: var(--red); font-weight: 600; }}

  /* Disclaimer bar */
  .disclaimer-bar {{
    background: #fff8ec;
    border-bottom: 1px solid #e8d8b0;
    padding: 0.65rem 2rem;
    font-size: 0.82rem;
    color: #6b5a2e;
    font-family: system-ui, sans-serif;
    text-align: center;
  }}
  .disclaimer-bar strong {{ color: #4a3a10; }}

  /* Map section */
  #vt-map {{
    height: 580px;
    border-radius: 8px;
    border: 1px solid var(--border);
    margin: 1.5rem 0 1rem;
  }}
  .map-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem 1.4rem;
    font-family: system-ui, sans-serif;
    font-size: 0.82rem;
    color: var(--muted);
    margin-bottom: 0.5rem;
  }}
  .map-legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .map-legend-dot {{
    width: 12px; height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
  }}
  .map-note {{
    font-family: system-ui, sans-serif;
    font-size: 0.82rem;
    color: var(--muted);
    margin-top: 0.4rem;
  }}
</style>
</head>
<body>

<nav>
  <span class="nav-logo">Let's Build Homes</span>
  <span class="nav-sub">Vermont Housing Data</span>
</nav>

<div class="hero">
  <h1>Vermont Housing Production:<br>What's Actually Being Built?</h1>
  <p>A decade of state data reveals where Vermont's homes are coming from — and what's at stake for rural communities.</p>
</div>

<div class="disclaimer-bar">
  <strong>Note:</strong> This is a rapidly developed overview of broad statewide trends using publicly available data — a napkin sketch, not a rigorous research project. Numbers should be understood as directionally informative, not authoritative. Do not cite specific figures as canonical fact without independent verification against the underlying sources linked in the methodology section. <strong>Seasonal and camp structures ({seasonal_excluded:,} permits, {START_YEAR}–{END_YEAR}) are excluded from all data in this analysis.</strong>
</div>

<div class="container">

<!-- ── 1. The production gap ──────────────────────────────────────────────── -->
<section>
  <h2>Vermont is building far less than it needs.</h2>
  <div class="intro">
    <p>Vermont's Act 47 (2023) sets an annual housing production target of <strong>{STATE_TARGET_LOWER:,}–{STATE_TARGET_UPPER:,} units per year</strong>. The lower bound is the minimum needed to keep pace with demand; the upper bound would make meaningful progress on the existing shortage. Since {START_YEAR}, Vermont has averaged {avg_annual:,} units/year — about {avg_vs_lower_pct}% of the minimum target.</p>
    <p>There's also a geographic mismatch. Vermont's Act 181 growth area framework intends future development to concentrate inside designated centers — VAPDA projects 60% of future housing will be built inside those areas. Yet only <strong>{exempt_inside_pct}%</strong> of production since {START_YEAR} landed inside growth areas. The chart below shows both gaps at once: the production shortfall and the geographic split.</p>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Annual Housing Units — {START_YEAR}–{END_YEAR} Actual, {PROJ_START_YEAR}–{PROJ_END_YEAR} Illustrative Target</div>
    <div class="chart-container h300">
      <canvas id="annualChart"></canvas>
    </div>
    <div class="chart-source">Source: DHCD New Housing Database (Vermont ACCD) · Target range: Act 47 (2023) · Geographic projection: VAPDA</div>
  </div>
  <div class="note">
    <strong>Shaded band:</strong> Vermont's annual target range of {STATE_TARGET_LOWER:,}–{STATE_TARGET_UPPER:,} units/year.
    <strong>Lighter bars ({PROJ_START_YEAR}–{PROJ_END_YEAR}):</strong> Illustrative target-level production using the VAPDA-projected 60/40 inside/outside split — {proj_annual_inside:,} units inside and {proj_annual_outside:,} outside growth areas per year.
    Reaching the lower bound would require roughly {target_multiple}× current production.
  </div>
</section>

<!-- ── 2. Rural share ─────────────────────────────────────────────────────── -->
<section>
  <h2>Rural Vermont accounts for about {rural_pct}% of the state's housing production.</h2>
  <div class="intro">
    <p>Vermont's 180 rural towns — covering the vast majority of the state's land area — collectively produce more new housing than urban Vermont's 13 designated urban centers. Together, rural and suburban communities outside of urban centers are responsible for {non_urban_pct}% of all new homes built since {START_YEAR}.</p>
    <p>That production is spread thinly. Nearly every rural permit is a single home, built one at a time, by individual families, contractors, and small developers.</p>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Share of All Statewide Units by Project Size and Community Type ({START_YEAR}–{END_YEAR})</div>
    <div class="chart-container h160">
      <canvas id="scaleChart"></canvas>
    </div>
    <div class="chart-source">Source: DHCD New Housing Database (Vermont Agency of Commerce &amp; Community Development)</div>
  </div>
  <div class="note">
    Each bar shows that tier's share of <em>total year-round statewide production</em>, broken down by project size. Bar lengths are not normalized to 100% — a shorter bar means that tier produced fewer homes overall. <strong>{rural_single_pct}% of rural units</strong> come from single-unit projects. In urban areas, the majority of units come from projects of 10 or more.
  </div>
</section>

<!-- ── 3. What rural Vermont builds ─────────────────────────────────────────── -->
<section>
  <h2>Rural housing is overwhelmingly single-family.</h2>
  <div class="intro">
    <p>Of all year-round rural housing permits from {START_YEAR} to {END_YEAR}, <strong>{rural_sfh_pct}%</strong> are single-family homes — built one at a time, on individual lots, by families, small contractors, and local builders. Multi-family construction and other residential types together make up a small share of rural output.</p>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Rural Housing Permits by Type — {START_YEAR}–{END_YEAR} (year-round permits only)</div>
    <div class="chart-container h200">
      <canvas id="typeChart"></canvas>
    </div>
    <div class="chart-source">Source: DHCD New Housing Database (Vermont Agency of Commerce &amp; Community Development)</div>
  </div>
</section>

<!-- ── 4. Act 181 thesis ──────────────────────────────────────────────────── -->
<section>
  <div class="thesis-box">
    <div class="thesis-box-header">
      <h3>What Act 181 means for rural housing production</h3>
    </div>
    <div class="thesis-box-body">
      <p>Vermont's Act 181 (2024) restructures Act 250 development review into a tiered system. Tier 1 designates growth centers and downtowns — the urban cores — for streamlined development review. Tier 2 and Tier 3 cover the remaining 97–98% of Vermont's land area, including nearly all of the rural and suburban towns where single-family homebuilding occurs.</p>
      <p>The data above shows that rural Vermont's housing production depends almost entirely on single-unit, one-at-a-time construction — the exact type of development that Tier 2 and Tier 3 regulations govern. New or expanded permitting requirements in these tiers would apply to the category of construction responsible for roughly a third of Vermont's total housing output.</p>
      <p>Vermont needs to build <em>more</em> rural housing to meet its targets. Regulatory changes that increase friction on single-family construction in Tier 2/3 risk moving in the opposite direction.</p>
    </div>
  </div>
</section>

<!-- ── 5. Inside/outside growth areas ─────────────────────────────────────── -->
<section>
  <h2>About {exempt_outside_pct}% of new housing was built outside Vermont's designated growth areas.</h2>
  <div class="intro">
    <p>Vermont's Act 181 (2024) designates a set of "growth areas" — downtown districts, town centers, village centers, and transit corridors — where new development is meant to be concentrated and permitting streamlined. Using the state's temporary exemption maps (the operative growth-area boundaries now in effect), we can test how well the past decade of housing production actually aligns with those goals.</p>
    <p>The answer: most of it doesn't. Of {exempt_total_units:,} year-round units built from {START_YEAR} to {END_YEAR}, <strong>{exempt_inside_pct}% fall inside designated growth areas</strong> and {exempt_outside_pct}% fall outside them. The split is not random — it tracks almost perfectly with housing type.</p>
  </div>

  <div class="callouts">
    <div class="callout">
      <div class="num">{exempt_inside_pct}%</div>
      <div class="lbl">of units built <em>inside</em> growth areas ({exempt_inside_units:,} units)</div>
    </div>
    <div class="callout">
      <div class="num">{exempt_outside_pct}%</div>
      <div class="lbl">of units built <em>outside</em> growth areas ({exempt_outside_units:,} units)</div>
    </div>
    <div class="callout">
      <div class="num">{mf_inside_pct}%</div>
      <div class="lbl">of multi-family units are inside growth areas</div>
    </div>
    <div class="callout">
      <div class="num">{sf_outside_pct}%</div>
      <div class="lbl">of single-family units are outside growth areas</div>
    </div>
  </div>

  <h3>Housing type tells the story</h3>
  <div class="chart-wrap">
    <div class="chart-label">Units Inside vs. Outside Growth Areas by Housing Type — {START_YEAR}–{END_YEAR}</div>
    <div class="chart-container h240">
      <canvas id="exemptTypeChart"></canvas>
    </div>
    <div class="chart-source">Source: DHCD New Housing Database · Vermont Act 181 temporary exemption area maps (ACCD)</div>
  </div>
  <div class="note">
    Multi-family development is heavily concentrated inside designated growth areas — which is exactly what Act 181 intends. Single-family and other residential construction is overwhelmingly outside those areas. This reflects the fundamental mismatch between where Vermont's housing policy aims to direct growth and where most new homes are actually being built.
  </div>

  <h3>Year-by-year: inside vs. outside growth areas</h3>
  <div class="chart-wrap">
    <div class="chart-label">Annual Units by Growth Area Status — {START_YEAR}–{END_YEAR}</div>
    <div class="chart-container h240">
      <canvas id="exemptYearChart"></canvas>
    </div>
    <div class="chart-source">Source: DHCD New Housing Database · Vermont Act 181 temporary exemption area maps (ACCD)</div>
  </div>
  <div class="caveat">
    <strong>Important caveat:</strong> The growth area maps are not uniform across Vermont. Towns that have not yet adopted a designated center or growth area simply have no polygons — development in those towns falls "outside" by default, not necessarily because it conflicts with Act 181's intent. This analysis reflects the maps as currently in effect; the final Act 181 Tier 1 maps, once fully adopted statewide, may shift some of these totals.
  </div>
</section>

<!-- ── 8. Methodology ─────────────────────────────────────────────────────── -->
<section id="methodology">
  <h2>Data &amp; Methodology</h2>

  <h3>DHCD New Housing Database</h3>
  <p class="intro">The Vermont Department of Housing &amp; Community Development (DHCD), in partnership with the Vermont Center for Geographic Information (VCGI), tracks new residential housing completions statewide, derived primarily from E911 site records. Data is published as the <em>VT New Housing Units view</em> ArcGIS feature service (<code>VT_New_Housing_Units_view</code>, hosted by VCGI on ArcGIS Online) and is accessible via the DHCD Housing Development Dashboard at HousingData.org. Coverage begins in {START_YEAR}. Each record is a single E911 site address with a unit count, coordinates, and a <code>YEARBUILT</code> field.</p>

  <h3>Seasonal and camp structures</h3>
  <p class="intro">Permits classified as seasonal or camp structures are <strong>excluded entirely from all data and charts in this analysis.</strong> This affects {seasonal_excluded:,} permits in the {START_YEAR}–{END_YEAR} study period. These structures do not contribute to Vermont's year-round housing supply. Identifying these permits by their DHCD <code>site_type</code> field: the three values filtered out are <em>CAMP</em>, <em>SEASONAL HOME</em>, and <em>SEASONAL CAMP</em>.</p>

  <h3>How community types are assigned</h3>
  <p class="intro">Every permitted structure is classified by the community type of the municipality in which it was permitted, using 2020 Census population and population density (residents per km², computed using Vermont State Plane EPSG:32145 projection). The three tiers and their thresholds are:</p>
  <p class="intro">
    <strong>Urban</strong> — population ≥ 5,000 <em>and</em> density ≥ 100/km². Thirteen towns qualify, including Burlington, Montpelier, Barre City, Rutland City, and St. Albans City. These correspond broadly to Vermont's Act 181 Tier 1 growth centers.<br>
    <strong>Suburban</strong> — population ≥ 2,500 <em>or</em> density ≥ 40/km² (but not meeting both urban thresholds). Sixty-two towns qualify, including South Burlington, Williston, and Barre Town. These correspond broadly to Act 181 Tier 2 designated growth areas.<br>
    <strong>Rural</strong> — all remaining towns (181), plus any gores, grants, or unorganized territories with no Census population data. These correspond broadly to Act 181 Tier 3.
  </p>
  <p class="intro"><strong>Important limitation:</strong> This classification is <em>town-level, not parcel-level.</em> A new home built on a large rural lot within a "suburban" town is counted as suburban. The tier reflects the character of the municipality as a whole, not the specific location, density, or context of the individual construction project.</p>

  <details>
    <summary>Full municipality classification table ({len(muni_data)} towns)</summary>
    <div class="details-body">
      <p>Each Vermont municipality's assigned tier, based on 2020 Census population and computed population density. Towns with no Census population data (gores, grants, unorganized territories) default to Rural.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Municipality</th>
              <th class="num">Population (2020)</th>
              <th class="num">Density (per km²)</th>
              <th>Community Type</th>
            </tr>
          </thead>
          <tbody>{muni_rows_html}</tbody>
        </table>
      </div>
      <p style="margin-top:0.8rem;font-size:0.8rem;color:#888;font-family:system-ui,sans-serif;"><em>Note on Essex Town and Essex Junction:</em> These two municipalities were a single town (Essex) at the time of the 2020 Census. Population and housing unit figures for each are estimated as half of the combined 2020 total (22,094 residents, 9,588 units). DHCD permits filed under the pre-split name "Essex" are distributed evenly between the two towns by record order. Both municipalities meet the Urban threshold under this split.</p>
    </div>
  </details>

  <h3>Act 181 growth area analysis</h3>
  <p class="intro">To determine whether each DHCD permit falls inside or outside Vermont's designated growth areas, we performed a point-in-polygon spatial join using the state's <strong>Act 181 temporary exemption maps</strong> — the operative growth-area boundaries currently in effect under Vermont law. These maps are maintained by the Agency of Commerce and Community Development (ACCD) and are published as GeoJSON layers on the Vermont Open Geodata Portal.</p>
  <p class="intro">Five exemption overlay layers were used: (I) Downtown District Areas, (II) Town and Growth Centers &amp; Development Areas, (III) Village Center &amp; Buffer, (IV) Priority Housing Projects within Buffer, and (V) Urbanized Area within Transit Route Buffer. All five layers were unioned into a single geometry. Each DHCD record's latitude/longitude coordinates were then tested against that union using a point-in-polygon operation (GeoPandas <code>within</code>). Records that fall within any of the five overlay types are classified as <em>inside a growth area</em>; all others are classified as <em>outside</em>.</p>
  <p class="intro"><strong>Key limitation:</strong> These are temporary exemption maps, not the final Act 181 Tier 1 designations. Coverage is uneven — some municipalities have detailed polygons while others have none at all. A permit falling "outside" any growth area may simply reflect that its municipality has not yet adopted a designated center, rather than indicating the project is truly outside the intended growth area framework. The final Tier 1 maps, once fully adopted statewide, may shift some totals. Results should be understood as directionally informative.</p>

  <h3>How permit types are classified</h3>
  <p class="intro">For the rural construction type chart, DHCD permits are assigned to one of three categories based on the raw <code>site_type</code> field and the permit's unit count. The table below shows how each distinct <code>site_type</code> value in our dataset maps to an analysis category.</p>

  <details>
    <summary>DHCD site_type mapping table</summary>
    <div class="details-body">
      <p>The construction type chart uses this classification for all rural year-round permits. The unit count rule applies on top of the type name: any permit with 2 or more units is always counted as Multi-Family / Condo regardless of its <code>site_type</code> label. Single-unit permits are classified by type name pattern. Note: the permit and unit counts below cover all Vermont municipalities across {START_YEAR}–{END_YEAR}, not only rural towns.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Raw site_type value</th>
              <th class="num">Permits</th>
              <th class="num">Units</th>
              <th>Analysis category</th>
            </tr>
          </thead>
          <tbody>
            <tr class="excluded-row"><td>CAMP</td><td class="num">2,426</td><td class="num">2,414</td><td>Excluded — Seasonal/Camp</td></tr>
            <tr class="excluded-row"><td>SEASONAL HOME</td><td class="num">124</td><td class="num">124</td><td>Excluded — Seasonal/Camp</td></tr>
            <tr class="excluded-row"><td>SEASONAL CAMP</td><td class="num">7</td><td class="num">7</td><td>Excluded — Seasonal/Camp</td></tr>
            <tr><td>SINGLE FAMILY DWELLING</td><td class="num">9,681</td><td class="num">9,697</td><td>Single-Family Home (1-unit) · Multi-Family/Condo (2+ units)</td></tr>
            <tr><td>ACCESSORY DWELLING UNIT</td><td class="num">153</td><td class="num">154</td><td>Single-Family Home</td></tr>
            <tr><td>OTHER RESIDENTIAL</td><td class="num">1,135</td><td class="num">1,126</td><td>Single-Family Home (1-unit) · Multi-Family/Condo (2+ units)</td></tr>
            <tr><td>RESIDENTIAL FARM</td><td class="num">18</td><td class="num">10</td><td>Single-Family Home</td></tr>
            <tr><td>COMMERCIAL W/RESIDENCE</td><td class="num">45</td><td class="num">151</td><td>Single-Family Home (1-unit) · Multi-Family/Condo (2+ units)</td></tr>
            <tr><td>INSTITUTIONAL RESIDENCE / DORM / BARRACKS</td><td class="num">35</td><td class="num">77</td><td>Single-Family Home (1-unit) · Multi-Family/Condo (2+ units)</td></tr>
            <tr><td>(unclassified / null)</td><td class="num">6</td><td class="num">1</td><td>Single-Family Home (1-unit)</td></tr>
            <tr><td>MULTI-FAMILY DWELLING</td><td class="num">1,100</td><td class="num">5,447</td><td>Multi-Family/Condo (2+ units) · Other (1-unit records)</td></tr>
            <tr><td>CONDOMINIUM</td><td class="num">464</td><td class="num">560</td><td>Multi-Family/Condo (2+ units) · Other (1-unit records)</td></tr>
            <tr><td>GROUP QUARTERS</td><td class="num">1</td><td class="num">71</td><td>Multi-Family/Condo</td></tr>
            <tr><td>MOBILE HOME</td><td class="num">812</td><td class="num">809</td><td>Other (type name contains "mobile")</td></tr>
          </tbody>
        </table>
      </div>
      <p style="margin-top:0.8rem;"><em>Note on "Other":</em> Single-unit permits whose type name contains "condo", "apartment", "multi", or "mobile" fall into "Other" because they are ambiguously classified in the source data. These are a small fraction of total permits.</p>
    </div>
  </details>

  <ul class="sources">
    <li><a href="https://housingdata.org/profile/home-building/dhcd-dashboard" target="_blank">DHCD Housing Development Dashboard — HousingData.org (Vermont Housing Finance Agency / VCGI)</a></li>
    <li><a href="https://www.arcgis.com/home/item.html?id=c3d713d4bdca45499e1b322c6be6f666" target="_blank">VT New Housing Units view — ArcGIS Online (VCGI) — underlying feature service for DHCD data</a></li>
    <li><a href="https://geodata.vermont.gov/datasets/VCGI::vt-data-2020-census-county-subdivision/about" target="_blank">VT Data – 2020 Census County Subdivision — Vermont Open Geodata Portal (VCGI)</a></li>
    <li><a href="https://legislature.vermont.gov/bill/status/2024/S.100" target="_blank">Act 47 (2023) — Vermont HOME Act / Housing Production Goal (8,237 units/year)</a></li>
    <li><a href="https://legislature.vermont.gov/bill/status/2024/H.687" target="_blank">Act 181 (2024) — Act 250 Modernization / Development Tier System</a></li>
    <li><a href="https://geodata.vermont.gov/" target="_blank">Vermont Open Geodata Portal — Act 181 Temporary Exemption Area Maps (ACCD)</a></li>
  </ul>
</section>

</div>

<section id="map-section">
<div class="container">
  <h2>Where Projects Are Being Built</h2>
  <p>Each dot represents a DHCD-recorded housing project ({START_YEAR}&ndash;{END_YEAR}). Projects are split into two independent cluster groups&mdash;inside and outside Act&nbsp;181 exemption areas&mdash;so clusters never mix the two. Zoom in to explore individual projects; click any dot for details.</p>

  <div id="vt-map"></div>

  <div class="map-legend">
    <span style="font-weight:600; color:var(--text); font-family:system-ui,sans-serif;">Housing type:</span>
    <span class="map-legend-item"><span class="map-legend-dot" style="background:#8ED4DA;"></span> Multi-Family</span>
    <span class="map-legend-item"><span class="map-legend-dot" style="background:#F89C45;"></span> Single-Family</span>
    <span class="map-legend-item"><span class="map-legend-dot" style="background:#F2644A;"></span> Other Residential</span>
    <span class="map-legend-item"><span class="map-legend-dot" style="background:#aaa;"></span> Other / Unknown</span>
  </div>
  <p class="map-note">Green shading = Act&nbsp;181 exemption area boundary. Cluster color: <strong style="color:#F2644A">red = inside</strong>, <strong style="color:#2a8a6e">green = outside</strong>. Use the layer control (top-right) to toggle each group independently.</p>
</div>
</section>

<footer>
  <p>Analysis by <strong style="color:#fff;">Let's Build Homes</strong> · Data current through {END_YEAR}</p>
  <p style="margin-top:0.3rem;"><a href="#methodology">Methodology &amp; Sources</a></p>
</footer>

<script>
// Data embedded from housing_dev.db at generation time
const YEARS               = {json.dumps(annual_labels)};   // {START_YEAR}–{END_YEAR}, used by exemptYearChart
const SCALE_PCT           = {json.dumps(scale_pct)};
const TYPE_LABELS         = {json.dumps(type_labels)};
const TYPE_UNITS          = {json.dumps(type_units)};

// Section 1 chart: historical + projected target bars
const CHART_ALL_LABELS    = {json.dumps(chart_all_labels)};
const CHART_HIST_INSIDE   = {json.dumps(chart_hist_inside)};
const CHART_HIST_OUTSIDE  = {json.dumps(chart_hist_outside)};
const CHART_PROJ_INSIDE   = {json.dumps(chart_proj_inside)};
const CHART_PROJ_OUTSIDE  = {json.dumps(chart_proj_outside)};
const STATE_TARGET_LOWER  = {STATE_TARGET_LOWER};
const STATE_TARGET_UPPER  = {STATE_TARGET_UPPER};

// Exemption area data
const EXEMPT_TYPE_LABELS  = {json.dumps(exempt_type_labels)};
const EXEMPT_TYPE_INSIDE  = {json.dumps(exempt_type_inside)};
const EXEMPT_TYPE_OUTSIDE = {json.dumps(exempt_type_outside)};
const EXEMPT_YEAR_INSIDE  = {json.dumps(exempt_year_inside)};
const EXEMPT_YEAR_OUTSIDE = {json.dumps(exempt_year_outside)};

// ── Annual chart: inside/outside growth areas, historical + projected ────────
const targetBandPlugin = {{
  id: 'targetBand',
  beforeDraw(chart) {{
    const {{ctx, chartArea, scales: {{y}}}} = chart;
    if (!y || !chartArea) return;
    const yTop  = y.getPixelForValue(STATE_TARGET_UPPER);
    const yBot  = y.getPixelForValue(STATE_TARGET_LOWER);
    const {{left, right}} = chartArea;
    ctx.save();
    // Shaded band
    ctx.fillStyle = 'rgba(242,100,74,0.09)';
    ctx.fillRect(left, yTop, right - left, yBot - yTop);
    // Dashed boundary lines
    ctx.strokeStyle = 'rgba(242,100,74,0.55)';
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 1.5;
    [yTop, yBot].forEach(px => {{
      ctx.beginPath(); ctx.moveTo(left, px); ctx.lineTo(right, px); ctx.stroke();
    }});
    ctx.setLineDash([]);
    // Bound labels at right edge
    ctx.fillStyle = 'rgba(200,75,50,0.85)';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText('{STATE_TARGET_UPPER:,}', right - 4, yTop - 4);
    ctx.fillText('{STATE_TARGET_LOWER:,}', right - 4, yBot - 4);
    // "Target range" label
    const midY = (yTop + yBot) / 2;
    ctx.fillStyle = 'rgba(200,75,50,0.6)';
    ctx.textAlign = 'left';
    ctx.fillText('Target range', left + 4, midY + 4);
    ctx.restore();
  }}
}};

new Chart(document.getElementById('annualChart'), {{
  type: 'bar',
  plugins: [targetBandPlugin],
  data: {{
    labels: CHART_ALL_LABELS,
    datasets: [
      {{ label: 'Outside growth areas',         data: CHART_HIST_OUTSIDE, backgroundColor: '#F89C45',               stack: 's' }},
      {{ label: 'Inside growth areas',          data: CHART_HIST_INSIDE,  backgroundColor: '#074B41',               stack: 's' }},
      {{ label: 'Outside growth areas (proj.)', data: CHART_PROJ_OUTSIDE, backgroundColor: 'rgba(248,156,69,0.38)', stack: 's', borderColor: '#F89C45', borderWidth: 1 }},
      {{ label: 'Inside growth areas (proj.)',  data: CHART_PROJ_INSIDE,  backgroundColor: 'rgba(7,75,65,0.38)',    stack: 's', borderColor: '#074B41', borderWidth: 1 }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{
        position: 'bottom',
        labels: {{
          font: {{ size: 12 }}, padding: 16,
          filter: item => !item.text.includes('(proj.)'),
        }},
      }},
      tooltip: {{
        filter: item => item.raw !== null,
        callbacks: {{
          footer: items => {{
            const active = items.filter(i => i.raw !== null);
            const tot = active.reduce((s, i) => s + i.raw, 0);
            const isProjYear = active.some(i => i.datasetIndex >= 2);
            return tot ? (isProjYear ? 'Projected total: ' : 'Total: ') + tot.toLocaleString() + ' units' : '';
          }},
        }},
      }},
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{
        stacked: true,
        beginAtZero: true,
        suggestedMax: {STATE_TARGET_UPPER + 900},
        ticks: {{ callback: v => v.toLocaleString() }},
      }},
    }},
  }},
}});

// ── Scale 100% horizontal bars ─────────────────────────────────────────────
new Chart(document.getElementById('scaleChart'), {{
  type: 'bar',
  data: {{
    labels: ['Rural', 'Suburban', 'Urban'],
    datasets: [
      {{ label: 'Single Unit', data: ['rural','suburban','urban'].map(t=>SCALE_PCT[t].single), backgroundColor: '#074B41', stack: 's' }},
      {{ label: '2–9 Units',   data: ['rural','suburban','urban'].map(t=>SCALE_PCT[t].small),  backgroundColor: '#8ED4DA', stack: 's' }},
      {{ label: '10–49 Units', data: ['rural','suburban','urban'].map(t=>SCALE_PCT[t].medium), backgroundColor: '#F89C45', stack: 's' }},
      {{ label: '50+ Units',   data: ['rural','suburban','urban'].map(t=>SCALE_PCT[t].large),  backgroundColor: '#F2644A', stack: 's' }},
    ],
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 12 }}, padding: 14 }} }},
      tooltip: {{ callbacks: {{ label: i => ` ${{i.dataset.label}}: ${{i.raw.toFixed(1)}}%` }} }}
    }},
    scales: {{
      x: {{ stacked: true, ticks: {{ callback: v => v+'%' }}, grid: {{ display: false }},
           title: {{ display: true, text: '% of all year-round statewide permits', font: {{ size: 11 }} }} }},
      y: {{ stacked: true }},
    }},
  }},
}});

// ── Rural types horizontal bar ─────────────────────────────────────────────
const typeTotal = TYPE_UNITS.reduce((a,b)=>a+b,0);
const typeColors = ['#074B41','#F2644A','#8ED4DA','#F89C45'];
new Chart(document.getElementById('typeChart'), {{
  type: 'bar',
  data: {{
    labels: TYPE_LABELS,
    datasets: [{{
      data: TYPE_UNITS,
      backgroundColor: typeColors.slice(0, TYPE_LABELS.length),
      borderWidth: 0,
    }}],
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: i => ` ${{i.raw.toLocaleString()}} units (${{(i.raw/typeTotal*100).toFixed(1)}}%)`
        }}
      }}
    }},
    scales: {{
      x: {{ ticks: {{ callback: v => v.toLocaleString() }}, grid: {{ display: false }} }},
      y: {{ grid: {{ display: false }} }},
    }},
  }},
}});

// ── Exemption area: grouped bar by housing type ────────────────────────────
new Chart(document.getElementById('exemptTypeChart'), {{
  type: 'bar',
  data: {{
    labels: EXEMPT_TYPE_LABELS,
    datasets: [
      {{ label: 'Inside growth area',  data: EXEMPT_TYPE_INSIDE,  backgroundColor: '#074B41' }},
      {{ label: 'Outside growth area', data: EXEMPT_TYPE_OUTSIDE, backgroundColor: '#F2644A' }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 12 }}, padding: 16 }} }},
      tooltip: {{
        callbacks: {{
          footer: items => {{
            const total = items.reduce((s,i)=>s+i.raw,0);
            const inside = items.find(i=>i.datasetIndex===0)?.raw || 0;
            return `Inside share: ${{(inside/total*100).toFixed(0)}}%`;
          }}
        }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{
        beginAtZero: true,
        ticks: {{ callback: v => v.toLocaleString() }},
        title: {{ display: true, text: 'Units', font: {{ size: 11 }} }},
      }},
    }},
  }},
}});

// ── Exemption area: stacked bar by year ────────────────────────────────────
new Chart(document.getElementById('exemptYearChart'), {{
  type: 'bar',
  data: {{
    labels: YEARS,
    datasets: [
      {{ label: 'Inside growth area',  data: EXEMPT_YEAR_INSIDE,  backgroundColor: '#074B41', stack: 's' }},
      {{ label: 'Outside growth area', data: EXEMPT_YEAR_OUTSIDE, backgroundColor: '#F2644A', stack: 's' }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 12 }}, padding: 16 }} }},
      tooltip: {{
        callbacks: {{
          footer: items => {{
            const total = items.reduce((s,i)=>s+i.raw,0);
            const inside = items.find(i=>i.datasetIndex===0)?.raw || 0;
            return `Total: ${{total.toLocaleString()}} · Inside: ${{(inside/total*100).toFixed(0)}}%`;
          }}
        }}
      }}
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{
        stacked: true,
        beginAtZero: true,
        ticks: {{ callback: v => v.toLocaleString() }},
        title: {{ display: true, text: 'Units', font: {{ size: 11 }} }},
      }},
    }},
  }},
}});

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
    'MULTI-FAMILY DWELLING':  '#8ED4DA',
    'SINGLE FAMILY DWELLING': '#F89C45',
    'OTHER RESIDENTIAL':      '#F2644A',
  }};

  function dotColor(type) {{
    return TYPE_COLORS[type] || '#aaaaaa';
  }}

  // Custom cluster icon: shows sum of unit_count across all child markers,
  // not a raw point count. Saturation scales logarithmically with unit total
  // (anchored: ~10 units = muted, ~10,000+ units = full color), keeping the
  // two-tone green/red scheme while adding a magnitude signal.
  function makeClusterIcon(cluster, isInside) {{
    const total = cluster.getAllChildMarkers()
      .reduce((sum, m) => sum + (m._units || 1), 0);
    const label = total >= 1000 ? (total / 1000).toFixed(1) + 'k' : String(total);
    const size  = total >= 500 ? 44 : total >= 100 ? 36 : 30;

    // t in [0,1]: log10 scale anchored at 1 unit (min) → 500 units (max sat)
    const t = Math.min(Math.log10(Math.max(total, 1)) / Math.log10(500), 1.0);
    // inside: red hsl(10, 22%→86%, 60%)  |  outside: green hsl(158, 15%→65%, 42%)
    const bg = isInside
      ? `hsl(10,${{Math.round(22 + t * 64)}}%,60%)`
      : `hsl(158,${{Math.round(15 + t * 50)}}%,42%)`;

    return L.divIcon({{
      html: `<div style="
        width:${{size}}px; height:${{size}}px;
        background:${{bg}}; color:#fff;
        border-radius:50%; border:2px solid #fff;
        display:flex; align-items:center; justify-content:center;
        font-family:system-ui,sans-serif; font-size:${{size >= 40 ? 11 : 10}}px;
        font-weight:700; line-height:1; box-shadow:0 1px 4px rgba(0,0,0,0.35);
      ">${{label}}</div>`,
      className: '',
      iconSize: L.point(size, size),
      iconAnchor: L.point(size / 2, size / 2),
    }});
  }}

  // Two separate cluster groups: inside and outside exemption area.
  // Keeping them separate guarantees MarkerCluster never merges a point from
  // inside the boundary with one from outside.
  const insideCluster = L.markerClusterGroup({{
    chunkedLoading: true,
    maxClusterRadius: 40,
    iconCreateFunction: c => makeClusterIcon(c, true),
  }});
  const outsideCluster = L.markerClusterGroup({{
    chunkedLoading: true,
    maxClusterRadius: 40,
    iconCreateFunction: c => makeClusterIcon(c, false),
  }});

  function makeMarker(feature, isInside) {{
    const p     = feature.properties;
    const color = dotColor(p.type);
    const latlng = [
      feature.geometry.coordinates[1],
      feature.geometry.coordinates[0],
    ];
    const marker = L.circleMarker(latlng, {{
      radius:      5,
      fillColor:   color,
      color:       isInside ? '#ffffff' : '#333333',
      weight:      1.5,
      fillOpacity: 0.88,
    }});
    const typeLabel = {{
      'MULTI-FAMILY DWELLING':  'Multi-Family',
      'SINGLE FAMILY DWELLING': 'Single-Family',
      'OTHER RESIDENTIAL':      'Other Residential',
    }}[p.type] || (p.type || 'Other');
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

  // Load exemption area polygon overlay
  fetch('exemption_union.geojson')
    .then(r => r.json())
    .then(data => {{
      L.geoJSON(data, {{
        style: {{
          color:       '#074B41',
          weight:      1.5,
          fillColor:   '#074B41',
          fillOpacity: 0.12,
        }}
      }}).addTo(map);
    }})
    .catch(() => console.warn('exemption_union.geojson not found — run make map_data'));

  // Load point layers and add to cluster groups
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
  }}).catch(() => console.warn('DHCD point GeoJSON files not found — run make map_data'));
}})();
</script>
</body>
</html>
"""

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Done. {len(html):,} chars → {OUT}")
