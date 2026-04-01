"""
generate_site.py — reads housing_dev.db and produces index.html

Usage:
    python3 generate_site.py            # writes index.html next to this script
    python3 generate_site.py out.html   # writes to a custom path
"""

import os
import sys
import sqlite3
import json

HERE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(HERE, 'housing_dev.db')
OUT  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'index.html')

STATE_TARGET = 8237

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── 1. Annual production by tier (year-round only) ────────────────────────────
annual_rows = con.execute('''
    SELECT
        CAST(d.year_built AS INTEGER) AS yr,
        LOWER(COALESCE(t.urban_rural_tier,'rural')) AS tier,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN 2016 AND 2025
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY yr, tier
    ORDER BY yr, tier
''').fetchall()

years  = list(range(2016, 2026))
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
scale_rows = con.execute('''
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
    WHERE d.year_built BETWEEN 2016 AND 2025
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
type_rows = con.execute('''
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
    WHERE d.year_built BETWEEN 2016 AND 2025
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

# ── 4. Combined large-project table (DHCD top + ESITE subdivisions) ────────────
dhcd_top = con.execute('''
    SELECT
        'DHCD'                             AS source,
        d.address,
        d.town_name_title                  AS town,
        COALESCE(t.urban_rural_tier,'—')   AS tier,
        d.site_type                        AS category,
        d.unit_count                       AS units,
        CAST(d.year_built AS INTEGER)      AS year_label
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN 2016 AND 2025
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
      AND d.unit_count >= 20
    ORDER BY d.unit_count DESC
    LIMIT 12
''').fetchall()

esite_top = con.execute('''
    SELECT
        'ESITE (parcel)'  AS source,
        COALESCE(e.town_name, '—') AS town_raw,
        COALESCE(t.urban_rural_tier,'—') AS tier,
        CASE e.parcel_category
            WHEN 'C'  THEN 'Condo'
            WHEN 'M'  THEN 'Multi-unit'
            WHEN 'R1' THEN 'Single-family'
            WHEN 'R2' THEN 'Single-family'
            WHEN 'F'  THEN 'Residential / Farm'
            WHEN ''   THEN 'Residential'
            ELSE 'Residential'
        END               AS category,
        e.site_count      AS units,
        CASE WHEN CAST(e.year_min AS INTEGER)=CAST(e.year_max AS INTEGER)
             THEN CAST(CAST(e.year_min AS INTEGER) AS TEXT)
             ELSE CAST(CAST(e.year_min AS INTEGER) AS TEXT)||'–'||CAST(CAST(e.year_max AS INTEGER) AS TEXT)
        END               AS year_label,
        e.parcelnum
    FROM esite_parcel_groups e
    LEFT JOIN town_lookup t ON UPPER(e.town_name)=UPPER(t.townname_title)
    WHERE e.site_count >= 20
      AND LOWER(COALESCE(e.parcel_category,'')) NOT IN ('ca','s1','s2')
    ORDER BY e.site_count DESC
    LIMIT 12
''').fetchall()

# ── 5. RPC table ──────────────────────────────────────────────────────────────
rpc_rows = con.execute('''
    SELECT
        t.rpc_name,
        SUM(d.unit_count)                    AS total_units,
        ROUND(AVG(d.unit_count),2)           AS avg_per_project
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN 2016 AND 2025
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
      AND t.rpc_name IS NOT NULL
    GROUP BY t.rpc_name
    ORDER BY total_units DESC
''').fetchall()

# ── 6. Municipality classification table ──────────────────────────────────
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
      AND year_built BETWEEN 2016 AND 2025
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
      AND year_built BETWEEN 2016 AND 2025
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
      AND year_built BETWEEN 2016 AND 2025
      {EXEMPT_SEASONAL_FILTER}
    GROUP BY yr
    ORDER BY yr
''').fetchall()

exempt_year_inside  = [int(r['inside_units']  or 0) for r in exempt_year_rows]
exempt_year_outside = [int(r['outside_units'] or 0) for r in exempt_year_rows]

# ── Total seasonal permits excluded (for disclaimer) ──────────────────────
seasonal_excluded = int(con.execute('''
    SELECT SUM(unit_count) FROM dhcd_new_housing
    WHERE year_built BETWEEN 2016 AND 2025
      AND LOWER(COALESCE(site_type,'')) IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
''').fetchone()[0] or 0)

con.close()

# ── Build HTML rows ───────────────────────────────────────────────────────────
def tier_badge(tier):
    t = (tier or 'unknown').lower()
    cls = t if t in ('urban','suburban','rural') else 'unknown'
    return f'<span class="badge badge-{cls}">{t.title()}</span>'

# Merge DHCD + ESITE into one list, sort by units desc
combined_list = []
for p in dhcd_top:
    combined_list.append({
        'source': 'DHCD',
        'address_parcel': p['address'] or '—',
        'town': p['town'] or '—',
        'tier': p['tier'],
        'units': int(p['units']),
        'year_label': str(p['year_label']),
        'category': (p['category'] or '—').title(),
        'is_esite': False,
    })
for e in esite_top:
    combined_list.append({
        'source': 'ESITE',
        'address_parcel': e['parcelnum'],
        'town': (e['town_raw'] or '—').title(),
        'tier': e['tier'],
        'units': int(e['units']),
        'year_label': e['year_label'],
        'category': e['category'] or '—',
        'is_esite': True,
    })
combined_list.sort(key=lambda r: r['units'], reverse=True)

combined_rows_html = ''
for row in combined_list:
    src_tag = (f'<span class="source-tag source-esite">ESITE</span>'
               if row['is_esite'] else
               f'<span class="source-tag source-dhcd">DHCD</span>')
    addr_cls = 'mono small' if row['is_esite'] else ''
    combined_rows_html += f'''<tr>
      <td>{src_tag}</td>
      <td class="{addr_cls}">{row["address_parcel"]}</td>
      <td>{row["town"]}</td>
      <td>{tier_badge(row["tier"])}</td>
      <td class="num">{row["units"]:,}</td>
      <td class="num">{row["year_label"]}</td>
      <td>{row["category"]}</td>
    </tr>'''

# RPC rows
rpc_rows_html = ''
for r in rpc_rows:
    rpc_rows_html += f'''<tr>
      <td>{r["rpc_name"] or "—"}</td>
      <td class="num">{int(r["total_units"] or 0):,}</td>
      <td class="num">{r["avg_per_project"]}</td>
    </tr>'''

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
  .source-esite {{ background:#e8eef8; color:#1a4080; }}

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
  <strong>Note:</strong> This is a rapidly developed overview of broad statewide trends using publicly available data — a napkin sketch, not a rigorous research project. Numbers should be understood as directionally informative, not authoritative. Do not cite specific figures as canonical fact without independent verification against the underlying sources linked in the methodology section. <strong>Seasonal and camp structures ({seasonal_excluded:,} permits, 2016–2025) are excluded from all data in this analysis.</strong>
</div>

<div class="container">

<!-- ── 1. The production gap ──────────────────────────────────────────────── -->
<section>
  <h2>Vermont is building about one-fifth of what it needs.</h2>
  <div class="intro">
    <p>Vermont's official housing target is <strong>{STATE_TARGET:,} units per year</strong> — the number the state needs to build annually to address its housing shortage. Since 2016, the state has averaged just {avg_annual:,} units per year, roughly 22% of that goal.</p>
  </div>

  <div class="callouts">
    <div class="callout"><div class="num">{avg_annual:,}</div><div class="lbl">Avg. units/year built (2016–2025)</div></div>
    <div class="callout"><div class="num">{STATE_TARGET:,}</div><div class="lbl">State's annual target</div></div>
    <div class="callout"><div class="num">{STATE_TARGET-avg_annual:,}</div><div class="lbl">Annual shortfall</div></div>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Annual Housing Units Completed by Community Type — 2016–2025</div>
    <div class="chart-container h240">
      <canvas id="annualChart"></canvas>
    </div>
    <div class="chart-source">Source: DHCD New Housing Database (Vermont Agency of Commerce &amp; Community Development)</div>
  </div>
  <div class="note">
    <strong>State target:</strong> Vermont's annual goal of {STATE_TARGET:,} units/year is not shown on the chart because it is nearly four times the highest year recorded — including it would make year-to-year differences unreadable. Community types (rural, suburban, urban) are based on 2020 Census population and density; see the methodology section for thresholds and definitions. These counts do <em>not</em> imply primary residence — many permitted units may be second homes or part-time residences.
  </div>
</section>

<!-- ── 2. Rural share ─────────────────────────────────────────────────────── -->
<section>
  <h2>Rural Vermont accounts for about {rural_pct}% of the state's housing production.</h2>
  <div class="intro">
    <p>Vermont's 180 rural towns — covering the vast majority of the state's land area — collectively produce more new housing than urban Vermont's 13 designated urban centers. Together, rural and suburban communities outside of urban centers are responsible for {non_urban_pct}% of all new homes built since 2016.</p>
    <p>That production is spread thinly. Nearly every rural permit is a single home, built one at a time, by individual families, contractors, and small developers.</p>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Share of All Statewide Units by Project Size and Community Type (2016–2025)</div>
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
    <p>Of all year-round rural housing permits from 2016 to 2025, <strong>{rural_sfh_pct}%</strong> are single-family homes — built one at a time, on individual lots, by families, small contractors, and local builders. Multi-family construction and other residential types together make up a small share of rural output.</p>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Rural Housing Permits by Type — 2016–2025 (year-round permits only)</div>
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

<!-- ── 5. Large-scale development ────────────────────────────────────────── -->
<section>
  <h2>Large-scale development is concentrated in Tier 1 communities.</h2>
  <div class="intro">
    <p>The table below combines the largest projects from two sources: DHCD (which captures large multi-family buildings as single permit records) and ESITE (Vermont's statewide parcel database, which reveals single-family subdivisions that appear in DHCD as many individual 1-unit permits). Together they show that large-scale residential development — whether apartment buildings or developer subdivisions — is overwhelmingly concentrated in urban and suburban Chittenden County.</p>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Source</th>
          <th>Address / Parcel</th>
          <th>Town</th>
          <th>Community Type</th>
          <th class="num">Units</th>
          <th class="num">Year(s)</th>
          <th>Category</th>
        </tr>
      </thead>
      <tbody>
        {combined_rows_html}
      </tbody>
    </table>
    <div class="chart-source">Sources: DHCD New Housing Database (Vermont ACCD) · VCGI ESITE Development Sites Parcel Layer</div>
  </div>
  <div class="caveat">
    <strong>Two data sources:</strong> <em>DHCD</em> records are individual building permits; large multi-family projects appear as a single entry.
    <em>ESITE</em> records group all homes sharing a parcel number within a town — a reliable signal for developer subdivisions that would otherwise be invisible in DHCD as dozens of single-unit permits.
    The two datasets cannot be directly joined; they are shown here as complementary evidence.
  </div>
</section>

<!-- ── 6. Regional breakdown ──────────────────────────────────────────────── -->
<section>
  <h2>Regional production by planning district</h2>
  <div class="intro">
    <p>Chittenden County Regional Planning Commission (CCRPC) leads both in total volume and in average project size — a direct result of its urban character and concentrated demand. Most other regions average close to one unit per permit, reflecting the single-family rural pattern.</p>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Regional Planning Commission</th>
          <th class="num">Total Units (2016–2025)</th>
          <th class="num">Avg Units / Project</th>
        </tr>
      </thead>
      <tbody>{rpc_rows_html}</tbody>
    </table>
    <div class="chart-source">Source: DHCD New Housing Database (Vermont Agency of Commerce &amp; Community Development) · Year-round units only</div>
  </div>
</section>

<!-- ── 7. Inside/outside growth areas ─────────────────────────────────────── -->
<section>
  <h2>About {exempt_outside_pct}% of new housing was built outside Vermont's designated growth areas.</h2>
  <div class="intro">
    <p>Vermont's Act 181 (2024) designates a set of "growth areas" — downtown districts, town centers, village centers, and transit corridors — where new development is meant to be concentrated and permitting streamlined. Using the state's temporary exemption maps (the operative growth-area boundaries now in effect), we can test how well the past decade of housing production actually aligns with those goals.</p>
    <p>The answer: most of it doesn't. Of {exempt_total_units:,} year-round units built from 2016 to 2025, <strong>{exempt_inside_pct}% fall inside designated growth areas</strong> and {exempt_outside_pct}% fall outside them. The split is not random — it tracks almost perfectly with housing type.</p>
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
    <div class="chart-label">Units Inside vs. Outside Growth Areas by Housing Type — 2016–2025</div>
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
    <div class="chart-label">Annual Units by Growth Area Status — 2016–2025</div>
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
  <p class="intro">The Vermont Department of Housing &amp; Community Development (DHCD), in partnership with the Vermont Center for Geographic Information (VCGI), tracks new residential housing completions statewide, derived primarily from E911 site records. Data is published as the <em>VT New Housing Units view</em> ArcGIS feature service (<code>VT_New_Housing_Units_view</code>, hosted by VCGI on ArcGIS Online) and is accessible via the DHCD Housing Development Dashboard at HousingData.org. Coverage begins in 2016. Each record is a single E911 site address with a unit count, coordinates, and a <code>YEARBUILT</code> field. Large single-family subdivisions often appear as many individual 1-unit records rather than one aggregated project; ESITE parcel analysis (below) is used to identify these.</p>

  <h3>VCGI ESITE / E911 Site Locations Layer</h3>
  <p class="intro">Vermont Center for Geographic Information (VCGI) maintains the E911 Site Locations (ESITE) database — the same underlying source as the DHCD housing records above. For the large-project table, we used this layer independently to identify developer subdivisions by grouping all residential sites sharing the same parcel number within a town. ESITE records aggregated this way cannot be reliably joined to individual DHCD permit records by address or ID, so the two are shown as complementary rather than merged evidence.</p>

  <h3>Seasonal and camp structures</h3>
  <p class="intro">Permits classified as seasonal or camp structures are <strong>excluded entirely from all data and charts in this analysis.</strong> This affects {seasonal_excluded:,} permits in the 2016–2025 study period. These structures do not contribute to Vermont's year-round housing supply. Identifying these permits by their DHCD <code>site_type</code> field: the three values filtered out are <em>CAMP</em>, <em>SEASONAL HOME</em>, and <em>SEASONAL CAMP</em>. In the ESITE parcel layer, parcels with category codes <em>CA</em> (camp), <em>S1</em>, and <em>S2</em> (seasonal) are likewise excluded.</p>

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
      <p>The construction type chart uses this classification for all rural year-round permits. The unit count rule applies on top of the type name: any permit with 2 or more units is always counted as Multi-Family / Condo regardless of its <code>site_type</code> label. Single-unit permits are classified by type name pattern. Note: the permit and unit counts below cover all Vermont municipalities across 2016–2025, not only rural towns.</p>
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

  <details>
    <summary>ESITE parcel_category mapping table</summary>
    <div class="details-body">
      <p>ESITE is used only in the large-project table, where parcel groups with 20 or more sites are shown. The <code>parcel_category</code> field is mapped to a display label for that table. Seasonal and camp categories are excluded from the table entirely.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>parcel_category code</th>
              <th>Description</th>
              <th>Display label in large-project table</th>
            </tr>
          </thead>
          <tbody>
            <tr class="excluded-row"><td>CA</td><td>Camp</td><td>Excluded — Seasonal/Camp</td></tr>
            <tr class="excluded-row"><td>S1</td><td>Seasonal (type 1)</td><td>Excluded — Seasonal/Camp</td></tr>
            <tr class="excluded-row"><td>S2</td><td>Seasonal (type 2)</td><td>Excluded — Seasonal/Camp</td></tr>
            <tr><td>R1</td><td>Residential, 1 unit</td><td>Single-family</td></tr>
            <tr><td>R2</td><td>Residential, 2 units</td><td>Single-family</td></tr>
            <tr><td>M</td><td>Multi-unit / Condo complex</td><td>Multi-unit</td></tr>
            <tr><td>C</td><td>Condominium</td><td>Condo</td></tr>
            <tr><td>F</td><td>Farm with residence</td><td>Residential / Farm</td></tr>
            <tr><td>MHU / MHL</td><td>Mobile home (upper / lower)</td><td>Residential</td></tr>
            <tr><td>W</td><td>Woodland / waterfront</td><td>Residential</td></tr>
            <tr><td>O</td><td>Other</td><td>Residential</td></tr>
            <tr><td>I</td><td>Institutional</td><td>Residential</td></tr>
            <tr><td>UO / UE</td><td>Urban open / urban exempt</td><td>Residential</td></tr>
            <tr><td>(null / blank)</td><td>Unclassified</td><td>Residential</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </details>

  <ul class="sources">
    <li><a href="https://housingdata.org/profile/home-building/dhcd-dashboard" target="_blank">DHCD Housing Development Dashboard — HousingData.org (Vermont Housing Finance Agency / VCGI)</a></li>
    <li><a href="https://www.arcgis.com/home/item.html?id=c3d713d4bdca45499e1b322c6be6f666" target="_blank">VT New Housing Units view — ArcGIS Online (VCGI) — underlying feature service for DHCD data</a></li>
    <li><a href="https://geodata.vermont.gov/datasets/VCGI::vt-data-2020-census-county-subdivision/about" target="_blank">VT Data – 2020 Census County Subdivision — Vermont Open Geodata Portal (VCGI)</a></li>
    <li><a href="https://geodata.vermont.gov/datasets/VCGI::vt-data-e911-site-locations-address-points-1/about" target="_blank">VT Data – E911 Site Locations (ESITE) — Vermont Open Geodata Portal (VCGI)</a></li>
    <li><a href="https://legislature.vermont.gov/bill/status/2024/S.100" target="_blank">Act 47 (2023) — Vermont HOME Act / Housing Production Goal (8,237 units/year)</a></li>
    <li><a href="https://legislature.vermont.gov/bill/status/2024/H.687" target="_blank">Act 181 (2024) — Act 250 Modernization / Development Tier System</a></li>
    <li><a href="https://geodata.vermont.gov/" target="_blank">Vermont Open Geodata Portal — Act 181 Temporary Exemption Area Maps (ACCD)</a></li>
  </ul>
</section>

</div>

<footer>
  <p>Analysis by <strong style="color:#fff;">Let's Build Homes</strong> · Data current through 2025</p>
  <p style="margin-top:0.3rem;"><a href="#methodology">Methodology &amp; Sources</a></p>
</footer>

<script>
// Data embedded from housing_dev.db at generation time
const YEARS           = {json.dumps(annual_labels)};
const ANNUAL_RURAL    = {json.dumps(annual_rural)};
const ANNUAL_SUBURBAN = {json.dumps(annual_suburban)};
const ANNUAL_URBAN    = {json.dumps(annual_urban)};
const SCALE_PCT       = {json.dumps(scale_pct)};
const TYPE_LABELS     = {json.dumps(type_labels)};
const TYPE_UNITS      = {json.dumps(type_units)};

// Exemption area data
const EXEMPT_TYPE_LABELS  = {json.dumps(exempt_type_labels)};
const EXEMPT_TYPE_INSIDE  = {json.dumps(exempt_type_inside)};
const EXEMPT_TYPE_OUTSIDE = {json.dumps(exempt_type_outside)};
const EXEMPT_YEAR_INSIDE  = {json.dumps(exempt_year_inside)};
const EXEMPT_YEAR_OUTSIDE = {json.dumps(exempt_year_outside)};

// ── Annual stacked bar ─────────────────────────────────────────────────────
new Chart(document.getElementById('annualChart'), {{
  type: 'bar',
  data: {{
    labels: YEARS,
    datasets: [
      {{ label: 'Rural',    data: ANNUAL_RURAL,    backgroundColor: '#074B41', stack: 's' }},
      {{ label: 'Suburban', data: ANNUAL_SUBURBAN, backgroundColor: '#8ED4DA', stack: 's' }},
      {{ label: 'Urban',    data: ANNUAL_URBAN,    backgroundColor: '#F89C45', stack: 's' }},
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
          footer: items => 'Total: ' + items.reduce((s,i)=>s+i.raw,0).toLocaleString() + ' units'
        }}
      }}
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{
        stacked: true,
        beginAtZero: true,
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
</script>
</body>
</html>
"""

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Done. {len(html):,} chars → {OUT}")
