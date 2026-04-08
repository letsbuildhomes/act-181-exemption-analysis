"""
generate_blog.py — reads housing_dev.db and produces output/blog.html

Usage:
    python3 generate_blog.py               # writes output/blog.html
    python3 generate_blog.py path/out.html # writes to a custom path
"""

import os
import sys
import sqlite3
import json

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = os.path.join(HERE, 'housing_dev.db')
OUTPUT = os.path.join(HERE, 'output')
os.makedirs(OUTPUT, exist_ok=True)
OUT    = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUTPUT, 'blog.html')

from config import START_YEAR, END_YEAR, PROJ_START_YEAR, PROJ_END_YEAR

STATE_TARGET_LOWER = 5573    # Act 47 minimum annual housing target
STATE_TARGET_UPPER = 8237    # Act 47 upper annual housing target
VAPDA_INSIDE_PCT   = 0.60    # VAPDA: share of future housing inside growth areas

SF = """
  AND LOWER(COALESCE(site_type,'')) NOT IN (
      'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')"""

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── 1. Annual production by tier ──────────────────────────────────────────────
years = list(range(START_YEAR, END_YEAR + 1))
annual_rows = con.execute(f'''
    SELECT
        CAST(d.year_built AS INTEGER) AS yr,
        LOWER(COALESCE(t.urban_rural_tier,'rural')) AS tier,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR} {SF}
    GROUP BY yr, tier ORDER BY yr, tier
''').fetchall()

tiers = ['rural', 'suburban', 'urban']
annual = {t: {y: 0 for y in years} for t in tiers}
for r in annual_rows:
    if r['tier'] in annual:
        annual[r['tier']][r['yr']] = int(r['units'] or 0)

annual_rural    = [annual['rural'][y]    for y in years]
annual_suburban = [annual['suburban'][y] for y in years]
annual_urban    = [annual['urban'][y]    for y in years]
annual_total    = [r + s + u for r, s, u in zip(annual_rural, annual_suburban, annual_urban)]

total_units    = sum(annual_total)
avg_annual     = round(total_units / len(years))
rural_total    = sum(annual_rural)
suburban_total = sum(annual_suburban)
urban_total    = sum(annual_urban)

rural_pct    = f'{rural_total    / total_units * 100:.1f}'
suburban_pct = f'{suburban_total / total_units * 100:.1f}'
urban_pct    = f'{urban_total    / total_units * 100:.1f}'

# ── 2. Town counts per tier ────────────────────────────────────────────────────
town_counts = {r['tier']: int(r['cnt']) for r in con.execute('''
    SELECT LOWER(COALESCE(urban_rural_tier,'rural')) AS tier, COUNT(*) AS cnt
    FROM town_lookup GROUP BY tier
''').fetchall()}
urban_town_count    = town_counts.get('urban', 13)
suburban_town_count = town_counts.get('suburban', 62)
rural_town_count    = town_counts.get('rural', 181)

# ── 3. Typology × tier with MFH sub-categories (Viz 2) ────────────────────────
TYPOLOGIES = [
    'Single-Family',
    'Multi-Family 2\u20134',
    'Multi-Family 5\u201319',
    'Multi-Family 20+',
    'Other Residential',
]

typology_tier_rows = con.execute(f'''
    SELECT
        LOWER(COALESCE(t.urban_rural_tier,'rural')) AS tier,
        CASE
            WHEN d.site_type_general = 'SINGLE FAMILY DWELLING'                    THEN 'Single-Family'
            WHEN d.site_type_general = 'MULTI-FAMILY DWELLING' AND d.unit_count <= 4  THEN 'Multi-Family 2\u20134'
            WHEN d.site_type_general = 'MULTI-FAMILY DWELLING' AND d.unit_count <= 19 THEN 'Multi-Family 5\u201319'
            WHEN d.site_type_general = 'MULTI-FAMILY DWELLING'                     THEN 'Multi-Family 20+'
            ELSE 'Other Residential'
        END AS typology,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title)=UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR} {SF}
    GROUP BY tier, typology
''').fetchall()

typology_tier = {ti: {ty: 0 for ty in TYPOLOGIES} for ti in tiers}
for r in typology_tier_rows:
    if r['tier'] in typology_tier and r['typology'] in typology_tier[r['tier']]:
        typology_tier[r['tier']][r['typology']] = int(r['units'] or 0)

sfh_total = sum(typology_tier[ti]['Single-Family'] for ti in tiers)
sfh_rural_suburban = (typology_tier['rural']['Single-Family'] +
                      typology_tier['suburban']['Single-Family'])
sfh_rural_suburban_pct = round(sfh_rural_suburban / sfh_total * 100, 1) if sfh_total else 0

# ── 4. Inside/outside overall ─────────────────────────────────────────────────
exempt_sum = con.execute(f'''
    SELECT in_exemption_area, SUM(unit_count) AS units
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL AND year_built BETWEEN {START_YEAR} AND {END_YEAR} {SF}
    GROUP BY in_exemption_area ORDER BY in_exemption_area DESC
''').fetchall()
inside_units  = next((int(r['units'] or 0) for r in exempt_sum if r['in_exemption_area'] == 1), 0)
outside_units = next((int(r['units'] or 0) for r in exempt_sum if r['in_exemption_area'] == 0), 0)
exempt_total  = inside_units + outside_units
inside_pct    = f'{inside_units  / exempt_total * 100:.1f}' if exempt_total else '0.0'
outside_pct   = f'{outside_units / exempt_total * 100:.1f}' if exempt_total else '0.0'
avg_inside    = round(inside_units  / len(years))
avg_outside   = round(outside_units / len(years))

# ── 5. Annual inside/outside by year (Viz 3) ──────────────────────────────────
yr_rows = con.execute(f'''
    SELECT CAST(year_built AS INTEGER) AS yr,
        SUM(CASE WHEN in_exemption_area=1 THEN unit_count ELSE 0 END) AS ins,
        SUM(CASE WHEN in_exemption_area=0 THEN unit_count ELSE 0 END) AS out
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL AND year_built BETWEEN {START_YEAR} AND {END_YEAR} {SF}
    GROUP BY yr ORDER BY yr
''').fetchall()
yr_inside  = [int(r['ins'] or 0) for r in yr_rows]
yr_outside = [int(r['out'] or 0) for r in yr_rows]

# ── 6. Typology × inside/outside with MFH sub-categories (Viz 4) ─────────────
typ_ex_rows = con.execute(f'''
    SELECT
        CASE
            WHEN site_type_general = 'SINGLE FAMILY DWELLING'                    THEN 'Single-Family'
            WHEN site_type_general = 'MULTI-FAMILY DWELLING' AND unit_count <= 4  THEN 'Multi-Family 2\u20134'
            WHEN site_type_general = 'MULTI-FAMILY DWELLING' AND unit_count <= 19 THEN 'Multi-Family 5\u201319'
            WHEN site_type_general = 'MULTI-FAMILY DWELLING'                     THEN 'Multi-Family 20+'
            ELSE 'Other Residential'
        END AS typology,
        SUM(CASE WHEN in_exemption_area=1 THEN unit_count ELSE 0 END) AS ins,
        SUM(CASE WHEN in_exemption_area=0 THEN unit_count ELSE 0 END) AS out
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL AND year_built BETWEEN {START_YEAR} AND {END_YEAR} {SF}
    GROUP BY typology
''').fetchall()

typ_ex = {ty: {'inside': 0, 'outside': 0} for ty in TYPOLOGIES}
for r in typ_ex_rows:
    if r['typology'] in typ_ex:
        typ_ex[r['typology']]['inside']  = int(r['ins'] or 0)
        typ_ex[r['typology']]['outside'] = int(r['out'] or 0)

mf_keys        = [ty for ty in TYPOLOGIES if ty.startswith('Multi-Family')]
mf_inside_tot  = sum(typ_ex[ty]['inside'] for ty in mf_keys)
mf_inside_pct  = round(mf_inside_tot / inside_units * 100, 1) if inside_units else 0

sf_in          = typ_ex['Single-Family']['inside']
sf_out         = typ_ex['Single-Family']['outside']
sf_total_ex    = sf_in + sf_out
sf_outside_pct = round(sf_out / outside_units * 100, 1) if outside_units else 0
sf_inside_pct  = round(sf_in  / sf_total_ex  * 100, 1) if sf_total_ex   else 0
sf_out_of_sfh  = round(sf_out / sf_total_ex  * 100, 1) if sf_total_ex   else 0

# ── 7. VAPDA projections ──────────────────────────────────────────────────────
target_mid    = (STATE_TARGET_LOWER + STATE_TARGET_UPPER) / 2
proj_in_mid   = round(target_mid * VAPDA_INSIDE_PCT)
proj_out_mid  = round(target_mid * (1 - VAPDA_INSIDE_PCT))
proj_in_lo    = round(STATE_TARGET_LOWER * VAPDA_INSIDE_PCT)
proj_in_hi    = round(STATE_TARGET_UPPER * VAPDA_INSIDE_PCT)
proj_out_lo   = round(STATE_TARGET_LOWER * (1 - VAPDA_INSIDE_PCT))
proj_out_hi   = round(STATE_TARGET_UPPER * (1 - VAPDA_INSIDE_PCT))
fold_lo       = round(proj_in_lo / avg_inside) if avg_inside else 0
fold_hi       = round(proj_in_hi / avg_inside) if avg_inside else 0

PROJ_YEARS   = list(range(PROJ_START_YEAR, PROJ_END_YEAR + 1))
all_labels   = [str(y) for y in years] + [str(y) for y in PROJ_YEARS]
hist_in      = yr_inside  + [None] * len(PROJ_YEARS)
hist_out     = yr_outside + [None] * len(PROJ_YEARS)
proj_in_arr  = [None] * len(years) + [proj_in_mid]  * len(PROJ_YEARS)
proj_out_arr = [None] * len(years) + [proj_out_mid] * len(PROJ_YEARS)

con.close()

# ── Helpers ───────────────────────────────────────────────────────────────────
fmt = lambda n: f'{n:,}'
j   = json.dumps

# ── Chart JSON ────────────────────────────────────────────────────────────────
annual_lbl_j = j([str(y) for y in years])
annual_r_j   = j(annual_rural)
annual_s_j   = j(annual_suburban)
annual_u_j   = j(annual_urban)

typologies_j = j(TYPOLOGIES)
viz2_r_j     = j([typology_tier['rural'][ty]    for ty in TYPOLOGIES])
viz2_s_j     = j([typology_tier['suburban'][ty] for ty in TYPOLOGIES])
viz2_u_j     = j([typology_tier['urban'][ty]    for ty in TYPOLOGIES])

all_labels_j = j(all_labels)
hist_in_j    = j(hist_in)
hist_out_j   = j(hist_out)
proj_in_j    = j(proj_in_arr)
proj_out_j   = j(proj_out_arr)

viz4_ins_j   = j([typ_ex[ty]['inside']  for ty in TYPOLOGIES])
viz4_out_j   = j([typ_ex[ty]['outside'] for ty in TYPOLOGIES])

tgt_hi_js    = fmt(STATE_TARGET_UPPER)   # pre-formatted for JS string literals
tgt_lo_js    = fmt(STATE_TARGET_LOWER)
viz3_ymax    = STATE_TARGET_UPPER + 1200

# ── HTML ──────────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Where Vermont Builds &mdash; And What That Means for Act 181</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link  rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link  rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link  rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<link  rel="stylesheet" href="https://unpkg.com/leaflet.fullscreen/dist/Control.FullScreen.css"/>
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
    line-height: 1.75;
    font-size: 18px;
  }}
  a {{ color: var(--green); }}
  a:hover {{ color: var(--red); }}

  nav {{
    background: var(--green);
    padding: 0.6rem 2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
  }}
  .nav-logo {{ color: #fff; font-weight: bold; font-family: system-ui,sans-serif; font-size: 0.95rem; }}
  .nav-sub  {{ color: var(--blue); font-family: system-ui,sans-serif; font-size: 0.8rem; }}

  .blog-header {{
    background: var(--green);
    color: #fff;
    padding: 3.5rem 2rem 3rem;
    text-align: center;
  }}
  .blog-header h1 {{
    font-size: clamp(1.7rem, 3.5vw, 2.5rem);
    line-height: 1.2;
    max-width: 780px;
    margin: 0 auto 1rem;
  }}
  .byline {{
    font-family: system-ui,sans-serif;
    font-size: 0.9rem;
    opacity: 0.75;
    letter-spacing: 0.03em;
  }}

  .blog-container {{
    max-width: 740px;
    margin: 0 auto;
    padding: 3rem 1.5rem 5rem;
  }}

  p {{ margin-bottom: 1.4rem; }}
  p:last-child {{ margin-bottom: 0; }}
  em {{ font-style: italic; }}

  h2 {{
    font-size: 1.5rem;
    color: var(--green);
    margin: 3rem 0 1rem;
    line-height: 1.2;
  }}
  h3 {{
    font-size: 1.05rem;
    color: var(--green);
    margin: 2.2rem 0 0.7rem;
  }}

  hr {{
    border: none;
    border-top: 1px dashed #ccc;
    margin: 3rem 0;
  }}

  .method-note {{
    background: #fff;
    border-left: 4px solid var(--blue);
    border-radius: 0 4px 4px 0;
    padding: 1.1rem 1.4rem;
    margin: 2.2rem 0;
    font-size: 0.88rem;
    color: var(--muted);
    line-height: 1.6;
    font-family: system-ui, sans-serif;
  }}
  .method-note h3 {{
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--green);
    margin: 0 0 0.7rem;
  }}
  .method-note p {{ margin-bottom: 0.75rem; font-size: 0.88rem; font-family: system-ui,sans-serif; }}
  .method-note p:last-child {{ margin-bottom: 0; }}

  .chart-wrap {{
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1.2rem 1.3rem 1rem;
    margin: 2rem 0;
  }}
  .chart-label {{
    font-family: system-ui,sans-serif;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 0.75rem;
  }}
  .chart-source {{
    font-family: system-ui,sans-serif;
    font-size: 0.7rem;
    color: #999;
    font-style: italic;
    margin-top: 0.6rem;
  }}
  .chart-container {{ position: relative; }}
  .h280 {{ height: 280px; }}
  .h320 {{ height: 320px; }}

  #vt-map {{
    height: 520px;
    border-radius: 4px;
    margin: 0.5rem 0;
  }}
  .map-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.2rem;
    font-family: system-ui,sans-serif;
    font-size: 0.77rem;
    color: var(--muted);
    margin-top: 0.7rem;
  }}
  .map-legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .map-legend-dot {{ width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }}

  footer {{
    background: var(--green);
    color: rgba(255,255,255,0.7);
    text-align: center;
    padding: 2rem 1.5rem;
    font-size: 0.82rem;
    font-family: system-ui,sans-serif;
  }}
  footer a {{ color: var(--blue); }}
</style>
</head>
<body>

<nav>
  <span class="nav-logo">Let&#8217;s Build Homes</span>
  <span class="nav-sub">Vermont Housing Data</span>
</nav>

<header class="blog-header">
  <h1>Where Vermont Builds&#8202;&mdash;&#8202;And What That Means for Act&nbsp;181</h1>
  <p class="byline">Jak Tiano &middot; April 2, 2026</p>
</header>

<div class="blog-container">

<p>In our <a href="#">last post</a>, we argued that Act 181&#8217;s &#8220;road rule&#8221; and Tier 3 designation place new regulatory burdens on the rural Vermonters least equipped to bear them, while doing little to address the large-scale development patterns they were designed to manage. The response to that piece confirmed what we&#8217;d been hearing from coalition members and the Rural Caucus for months: these rules are landing hard in communities that feel shut out of the conversation.</p>

<p>But as we dug into those equity arguments, we kept running into a more basic question we couldn&#8217;t find a good answer to: where is Vermont actually building housing, how much, and what kind? Without that baseline, it&#8217;s hard to evaluate whether Act 181&#8217;s geographic framework&#8212;its tiers, its boundaries, its implied targets&#8212;lines up with what&#8217;s happening on the ground. The data to answer these questions has been sitting in state databases for years. As far as we can tell, no one has used it to stress-test the assumptions behind Act 181&#8217;s implementation.</p>

<p>So we did it ourselves. This post walks through what we found.</p>

<div class="method-note">
  <h3>A note on methodology</h3>
  <p>All figures in this analysis use the DHCD New Housing Database, the same data source behind Vermont&#8217;s official <a href="https://housingdata.org/profile/home-building/dhcd-dashboard" target="_blank">housing dashboard</a>. The dashboard was created by the Vermont Center for Geographic Information in partnership with DHCD to track progress toward the statewide and regional housing targets required under the HOME Act (2023) and Act 181 (2024). It draws on E911 data, regional planning commission records, and other sources. The methodology for counting units and determining year built is still evolving, but it represents the best statewide picture we have. We use records from {START_YEAR} through {END_YEAR}, excluding seasonal and camp structures throughout&#8212;we&#8217;re focused on year-round homes.</p>
  <p>We approach the data through two different lenses. The first classifies Vermont&#8217;s 256 municipalities into community types&#8212;urban, suburban, and rural&#8212;based on 2020 Census population and density. This captures how towns function in practice: a rural town is rural whether or not its center has a designated growth area. The second uses the Act 181 temporary exemption maps as a proxy for future Tier 1 boundaries, tagging every housing project as inside or outside those areas. This captures the regulatory geography that Act 181 is creating.</p>
  <p>These two lenses don&#8217;t perfectly overlap, and that&#8217;s the point. A suburban town might have most of its housing built outside the exemption boundary. A rural town&#8217;s village center might fall inside it. By looking at both, we can see not just the legal map, but the community-level reality underneath it.</p>
</div>

<hr>

<h2>Vermont&#8217;s housing production by community type</h2>

<p>We classified every municipality into one of three categories: <strong>urban</strong> (population &ge;&nbsp;5,000 and density &ge;&nbsp;100/km&sup2;), <strong>suburban</strong> (population &ge;&nbsp;2,500 or density &ge;&nbsp;40/km&sup2;), and <strong>rural</strong> (everything else). That gives us {urban_town_count} urban towns, {suburban_town_count} suburban towns, and {rural_town_count} rural towns.</p>

<div class="chart-wrap">
  <div class="chart-label">Annual Housing Production by Community Type, {START_YEAR}&#8211;{END_YEAR}</div>
  <div class="chart-container h320"><canvas id="tierChart"></canvas></div>
  <div class="chart-source">Source: DHCD New Housing Database (Vermont ACCD) &middot; Seasonal and camp structures excluded</div>
</div>

<p>The statewide picture is more balanced than most people expect. Over the past decade, rural towns produced {rural_pct}% of Vermont&#8217;s year-round housing, suburban towns {suburban_pct}%, and urban towns {urban_pct}%. Rural Vermont isn&#8217;t a marginal player in the state&#8217;s housing output&#8212;it&#8217;s the single largest contributor.</p>

<p>None of this is an argument against concentrating future growth in Vermont&#8217;s population centers. That remains good policy. But directing new growth is different from constraining existing growth, and effective housing policy needs to do the former without inadvertently doing the latter. The data here establishes that rural housing production is a significant share of the state&#8217;s total output&#8212;and that constraints on it carry statewide consequences.</p>

<div class="chart-wrap">
  <div class="chart-label">Housing Typology by Community Type, {START_YEAR}&#8211;{END_YEAR} (units)</div>
  <div class="chart-container h320"><canvas id="typologyTierChart"></canvas></div>
  <div class="chart-source">Source: DHCD New Housing Database (Vermont ACCD) &middot; Multi-family split by unit count per project</div>
</div>

<p>The <em>type</em> of housing each community builds tells an important part of the story. Vermont&#8217;s single-family homes are built overwhelmingly in rural and suburban towns&#8212;together they account for over {sfh_rural_suburban_pct}% of single-family production. Multifamily housing concentrates in urban communities, with suburban towns contributing most of the remainder. Rural towns produce very little multifamily housing.</p>

<p>Different community types have different infrastructure, different zoning, different land economics, and different development industries serving them. Any policy that shifts <em>where</em> housing gets built will also shift <em>what kind</em> of housing gets built&#8212;a theme we&#8217;ll return to.</p>

<hr>

<h2>Inside vs. outside the Tier 1 proxy area</h2>

<p>Act 181 designates growth areas&#8212;what will become Tier 1&#8212;where development review is streamlined and housing production is meant to concentrate. The final Tier 1 boundaries aren&#8217;t drawn yet, so we used the temporary exemption maps (downtown districts, village centers, growth centers, transit corridors) as a proxy. These aren&#8217;t a perfect stand-in for the final maps, but they&#8217;re the best statewide approximation available, and they let us ask: how does the housing Vermont has actually been building line up with the areas where Act 181 expects future growth to concentrate?</p>

<div class="chart-wrap">
  <div class="chart-label">Annual Production Inside vs. Outside Exemption Areas, {START_YEAR}&#8211;{END_YEAR} actual &amp; {PROJ_START_YEAR}&#8211;{PROJ_END_YEAR} projected</div>
  <div class="chart-container h320"><canvas id="insideOutsideChart"></canvas></div>
  <div class="chart-source">Source: DHCD New Housing Database &middot; Act 181 temporary exemption area maps (ACCD) &middot; Projections: VAPDA 60/40 split applied to Act 47 target midpoint ({fmt(proj_in_mid)} inside + {fmt(proj_out_mid)} outside/yr)</div>
</div>

<p>The gap between where we&#8217;ve been and where we need to go is significant.</p>

<p>Over the past decade, just {inside_pct}% of Vermont&#8217;s year-round housing was built inside these proxy Tier 1 areas. In testimony earlier this session, VAPDA stated that they expect roughly 60% of future housing growth to occur inside Tier 1 areas, with 40% still occurring outside. That would be close to a full inversion of the historical pattern&#8212;and it needs to happen while the state simultaneously triples or quadruples total annual output, from roughly {fmt(avg_annual)} units per year to somewhere between {fmt(STATE_TARGET_LOWER)} and {fmt(STATE_TARGET_UPPER)}.</p>

<p>It&#8217;s worth noting that the statewide housing targets themselves don&#8217;t prescribe where housing should go relative to Tier 1. They break down regionally, and it falls to regional and municipal planning to decide how that growth is distributed. The 60/40 split is VAPDA&#8217;s projection of how that distribution will play out, not a binding target&#8212;but it&#8217;s the closest thing we have to a statewide expectation of how Act 181&#8217;s geography will shape development.</p>

<p>Under that projection, roughly {fmt(proj_out_lo)} to {fmt(proj_out_hi)} units per year would still need to be built <em>outside</em> of Tier 1. That&#8217;s significantly more than the roughly {fmt(avg_outside)} per year those areas have historically produced. The state&#8217;s own expectations call for housing growth outside of Tier 1&#8212;not contraction.</p>

<div class="chart-wrap">
  <div class="chart-label">Housing Typology Inside vs. Outside Exemption Areas, {START_YEAR}&#8211;{END_YEAR} (units)</div>
  <div class="chart-container h320"><canvas id="typologyExemptChart"></canvas></div>
  <div class="chart-source">Source: DHCD New Housing Database &middot; Act 181 temporary exemption area maps (ACCD) &middot; Multi-family split by unit count per project</div>
</div>

<p>The typology split across the Tier 1 boundary mirrors the community-type analysis. Inside the proxy Tier 1 areas, {mf_inside_pct}% of housing built over the past decade was multifamily. Outside, {sf_outside_pct}% was single-family.</p>

<p>Only about {sf_inside_pct}% of Vermont&#8217;s single-family production over this period fell inside the exemption areas. That&#8217;s a remarkably small share, and it points to something that deserves more attention in the Tier 1 planning conversation: if almost all single-family and lower-density housing is being built outside of designated growth areas, that means it is, by default, being built in locations that are more dispersed, more car-dependent, and less connected to community infrastructure. That isn&#8217;t a good outcome for anyone&#8212;not for the families living in those homes, not for the municipalities serving them, and not for the state&#8217;s climate and land conservation goals.</p>

<p>A more productive approach would be to plan for the long tail of lower-density housing types&#8212;single-family homes, duplexes, accessory dwellings&#8212;to happen <em>inside</em> Tier 1 rather than outside it. Even in designated growth areas where multifamily development should be the primary focus, there is a role for well-integrated single-family and missing-middle housing that contributes to a connected community fabric rather than defaulting to disconnected, car-dependent patterns elsewhere. That requires Tier 1 areas with enough geographic scope to accommodate a range of housing types&#8212;which circles back to the question of whether the current footprint is large enough.</p>

<div class="chart-wrap">
  <div class="chart-label">All Housing Projects {START_YEAR}&#8211;{END_YEAR} &mdash; Inside vs. Outside Act 181 Exemption Areas</div>
  <div id="vt-map"></div>
  <div class="map-legend">
    <span style="font-weight:600;font-family:system-ui,sans-serif;color:var(--text)">Dot color:</span>
    <span class="map-legend-item"><span class="map-legend-dot" style="background:#c26a60"></span> Inside exemption area</span>
    <span class="map-legend-item"><span class="map-legend-dot" style="background:#3a8a6e"></span> Outside exemption area</span>
    <span style="font-family:system-ui,sans-serif;font-size:0.77rem;color:var(--muted)">Dot size and saturation scale with unit count. Click any dot for project details.</span>
  </div>
  <div class="chart-source">Source: DHCD New Housing Database &middot; Act 181 temporary exemption area maps (ACCD) &middot; Green shading = exemption area boundary &middot; Use layer control (top-right) to toggle groups</div>
</div>

<hr>

<h2>What this means for policy</h2>

<h3>The rules affecting development outside Tier 1 need to be revisited</h3>

<p>This analysis began because we couldn&#8217;t find evidence that anyone had rigorously examined what the road rule and Tier 3 designation would mean for housing production. The data makes a clear case: the areas where these rules apply are where the vast majority of Vermont&#8217;s single-family homes are built&#8212;over {fmt(sf_out)} units in the past decade, {sf_out_of_sfh}% of all single-family production statewide. And even under VAPDA&#8217;s projection, these areas are expected to produce <em>more</em> housing in the future, not less.</p>

<p>The high-level goals behind these rules are sound: protecting critical natural resources and managing the footprint of new road infrastructure are legitimate priorities. But the specific instruments chosen to pursue them appear not to have been informed by the kind of housing production analysis we&#8217;ve presented here. New rules that add cost and complexity to development in areas responsible for the bulk of Vermont&#8217;s single-family output&#8212;at a moment when the state needs to dramatically increase that output&#8212;should have a strong empirical basis. Right now, they don&#8217;t.</p>

<p>We continue to believe the road rule should be repealed and the Tier 3 framework substantially narrowed, as we argued in our <a href="#">previous post</a>. Analysis like what we&#8217;ve presented here should be directly informing those decisions. The question isn&#8217;t just whether these rules are equitable&#8212;it&#8217;s whether they&#8217;re compatible with Vermont&#8217;s housing goals.</p>

<h3>We also have real questions about whether Tier 1 is set up to succeed</h3>

<p>In doing this analysis for the areas outside Tier 1, we ended up with a detailed picture of what&#8217;s happening inside it&#8212;and it raises its own set of questions.</p>

<p>The proxy Tier 1 areas we analyzed have historically produced about {fmt(avg_inside)} units per year. Under the VAPDA projection, they&#8217;d need to produce between {fmt(proj_in_lo)} and {fmt(proj_in_hi)}&#8212;a {fold_lo}- to {fold_hi}-fold increase, concentrated in areas that currently cover roughly two percent of the state&#8217;s land.</p>

<p>Whether that&#8217;s achievable depends on questions we don&#8217;t yet have full answers to. Is there enough developable land within or adjacent to these boundaries to absorb that volume&#8212;including the greenfield land needed to attract subdivision-scale projects we&#8217;re trying to redirect from rural areas? Are the boundaries drawn broadly enough to offer real development options?</p>

<p>This connects directly to the concerns outside Tier 1. If the growth areas are so narrowly defined that they can&#8217;t absorb the housing the state needs, the overflow doesn&#8217;t disappear&#8212;it pushes into Tier 2, where the road rule and Tier 3 create new barriers to the very development being displaced. The benefits of designated growth areas&#8212;concentrated infrastructure investment, walkable development patterns, efficient land use&#8212;only materialize if those areas are large enough to actually attract and hold the growth they&#8217;re designed for. When they&#8217;re too small, the clustering benefit is lost, and greenfield subdivisions end up scattered across the landscape, guided by whatever signals the market finds rather than by deliberate planning.</p>

<p>Some towns are already choosing to opt out of Tier 1 designation entirely, which narrows the footprint further. We don&#8217;t want to prematurely conclude that the Tier 1 areas can&#8217;t absorb the development planned for them&#8212;the final maps aren&#8217;t drawn, and regional planning commissions may have capacity analyses we haven&#8217;t seen. But the gap between historical production inside these areas and the targets they&#8217;re being asked to meet is very large, and we intend to do further analysis as the final maps take shape.</p>

<h3>Connecting the tools</h3>

<p>Throughout this analysis, a consistent pattern emerges: Act 181&#8217;s framework concentrates opportunity in a small geographic footprint, while the communities outside that footprint&#8212;communities producing a third or more of the state&#8217;s housing&#8212;face new constraints without new tools.</p>

<p>This is part of why Let&#8217;s Build Homes has been developing and championing <a href="#">ROOT Zones</a> this session. ROOT Zones would give any Vermont municipality&#8212;especially the smaller and rural towns the current Tier 1 process struggles to reach&#8212;a straightforward, opt-in mechanism to designate new growth areas and adopt development-ready zoning. Critically, we&#8217;re pushing for ROOT Zones to qualify as a pathway to Tier 1 designation, so that communities making a commitment to responsible growth can access the streamlined permitting and state support that comes with it. If Tier 1 areas need to be bigger and more capable of shouldering the housing growth Vermont needs, ROOT Zones are one tool that can help make that happen&#8212;from the community level up.</p>

<hr>

<p>Vermont&#8217;s housing challenge is statewide, and so is its housing production. The data shows a state where every type of community contributes, where the housing market has structural patterns that don&#8217;t shift easily, and where the assumptions behind our most ambitious land use reform have yet to be tested against what&#8217;s actually happening on the ground. We hope this analysis is a useful step toward that kind of grounding.</p>

<p>Let&#8217;s Build Homes remains committed to the success of Act 181. We look forward to continuing this research as the Tier 1 maps are finalized, and to working with legislators, planners, and communities across the state to make sure the framework delivers the homes Vermonters need.</p>

</div><!-- .blog-container -->

<footer>
  <p>Analysis by <strong style="color:#fff">Let&#8217;s Build Homes</strong> &middot; Data current through {END_YEAR}</p>
  <p style="margin-top:0.3rem;opacity:0.6;font-size:0.78rem">DHCD New Housing Database &middot; Act 181 temporary exemption area maps (ACCD) &middot; 2020 U.S. Census</p>
</footer>

<script>
// ── Embedded chart data ───────────────────────────────────────────────────────
const ANNUAL_LABELS = {annual_lbl_j};
const ANNUAL_RURAL  = {annual_r_j};
const ANNUAL_SUB    = {annual_s_j};
const ANNUAL_URBAN  = {annual_u_j};

const TYPOLOGIES    = {typologies_j};
const VIZ2_RURAL    = {viz2_r_j};
const VIZ2_SUB      = {viz2_s_j};
const VIZ2_URBAN    = {viz2_u_j};

const ALL_LABELS    = {all_labels_j};
const HIST_IN       = {hist_in_j};
const HIST_OUT      = {hist_out_j};
const PROJ_IN       = {proj_in_j};
const PROJ_OUT      = {proj_out_j};

const VIZ4_INSIDE   = {viz4_ins_j};
const VIZ4_OUTSIDE  = {viz4_out_j};

const TARGET_LOWER  = {STATE_TARGET_LOWER};
const TARGET_UPPER  = {STATE_TARGET_UPPER};

// ── Viz 1: Stacked bar — annual production by tier ────────────────────────────
new Chart(document.getElementById('tierChart'), {{
  type: 'bar',
  data: {{
    labels: ANNUAL_LABELS,
    datasets: [
      {{ label: 'Rural',    data: ANNUAL_RURAL, backgroundColor: '#074B41', stack: 's' }},
      {{ label: 'Suburban', data: ANNUAL_SUB,   backgroundColor: '#F89C45', stack: 's' }},
      {{ label: 'Urban',    data: ANNUAL_URBAN, backgroundColor: '#8ED4DA', stack: 's' }},
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
            const tot = items.reduce((s, i) => s + (i.raw || 0), 0);
            return tot ? `Total: ${{tot.toLocaleString()}} units` : '';
          }},
        }},
      }},
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{
        stacked: true, beginAtZero: true,
        ticks: {{ callback: v => v.toLocaleString() }},
        title: {{ display: true, text: 'Units', font: {{ size: 11 }} }},
      }},
    }},
  }},
}});

// ── Viz 2: Stacked horizontal bar — typology × community type ────────────────
new Chart(document.getElementById('typologyTierChart'), {{
  type: 'bar',
  data: {{
    labels: TYPOLOGIES,
    datasets: [
      {{ label: 'Rural',    data: VIZ2_RURAL, backgroundColor: '#074B41', stack: 's' }},
      {{ label: 'Suburban', data: VIZ2_SUB,   backgroundColor: '#F89C45', stack: 's' }},
      {{ label: 'Urban',    data: VIZ2_URBAN, backgroundColor: '#8ED4DA', stack: 's' }},
    ],
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 12 }}, padding: 16 }} }},
      tooltip: {{
        callbacks: {{
          footer: items => {{
            const tot = items.reduce((s, i) => s + (i.raw || 0), 0);
            return tot ? `Total: ${{tot.toLocaleString()}} units` : '';
          }},
        }},
      }},
    }},
    scales: {{
      x: {{
        stacked: true, beginAtZero: true,
        ticks: {{ callback: v => v.toLocaleString() }},
        title: {{ display: true, text: 'Units', font: {{ size: 11 }} }},
      }},
      y: {{ stacked: true, grid: {{ display: false }} }},
    }},
  }},
}});

// ── Viz 3: Stacked bar + projection — inside/outside by year ─────────────────
const targetBandPlugin = {{
  id: 'targetBand',
  beforeDraw(chart) {{
    const {{ctx, chartArea, scales: {{y}}}} = chart;
    if (!y || !chartArea) return;
    const yTop = y.getPixelForValue(TARGET_UPPER);
    const yBot = y.getPixelForValue(TARGET_LOWER);
    const {{left, right}} = chartArea;
    ctx.save();
    ctx.fillStyle = 'rgba(242,100,74,0.09)';
    ctx.fillRect(left, yTop, right - left, yBot - yTop);
    ctx.strokeStyle = 'rgba(242,100,74,0.5)';
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.2;
    [yTop, yBot].forEach(px => {{
      ctx.beginPath(); ctx.moveTo(left, px); ctx.lineTo(right, px); ctx.stroke();
    }});
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(200,75,50,0.8)';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText('{tgt_hi_js}', right - 4, yTop - 4);
    ctx.fillText('{tgt_lo_js}', right - 4, yBot - 4);
    ctx.fillStyle = 'rgba(200,75,50,0.55)';
    ctx.textAlign = 'left';
    ctx.fillText('Act\u202447 target range', left + 4, (yTop + yBot) / 2 + 4);
    ctx.restore();
  }},
}};

new Chart(document.getElementById('insideOutsideChart'), {{
  type: 'bar',
  plugins: [targetBandPlugin],
  data: {{
    labels: ALL_LABELS,
    datasets: [
      {{ label: 'Outside growth areas',         data: HIST_OUT,  backgroundColor: '#F89C45',               stack: 's' }},
      {{ label: 'Inside growth areas',          data: HIST_IN,   backgroundColor: '#074B41',               stack: 's' }},
      {{ label: 'Outside growth areas (proj.)', data: PROJ_OUT,  backgroundColor: 'rgba(248,156,69,0.38)', stack: 's', borderColor: '#F89C45', borderWidth: 1 }},
      {{ label: 'Inside growth areas (proj.)',  data: PROJ_IN,   backgroundColor: 'rgba(7,75,65,0.38)',    stack: 's', borderColor: '#074B41', borderWidth: 1 }},
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
            const tot  = active.reduce((s, i) => s + i.raw, 0);
            const isProj = active.some(i => i.datasetIndex >= 2);
            return tot ? (isProj ? 'Projected total: ' : 'Total: ') + tot.toLocaleString() + ' units' : '';
          }},
        }},
      }},
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{
        stacked: true, beginAtZero: true,
        suggestedMax: {viz3_ymax},
        ticks: {{ callback: v => v.toLocaleString() }},
        title: {{ display: true, text: 'Units', font: {{ size: 11 }} }},
      }},
    }},
  }},
}});

// ── Viz 4: Stacked horizontal bar — typology × inside/outside ────────────────
new Chart(document.getElementById('typologyExemptChart'), {{
  type: 'bar',
  data: {{
    labels: TYPOLOGIES,
    datasets: [
      {{ label: 'Inside growth areas',  data: VIZ4_INSIDE,  backgroundColor: '#074B41', stack: 's' }},
      {{ label: 'Outside growth areas', data: VIZ4_OUTSIDE, backgroundColor: '#F89C45', stack: 's' }},
    ],
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 12 }}, padding: 16 }} }},
      tooltip: {{
        callbacks: {{
          footer: items => {{
            const tot = items.reduce((s, i) => s + (i.raw || 0), 0);
            const ins = items.find(i => i.datasetIndex === 0)?.raw || 0;
            return tot ? `Inside share: ${{(ins / tot * 100).toFixed(0)}}%` : '';
          }},
        }},
      }},
    }},
    scales: {{
      x: {{
        stacked: true, beginAtZero: true,
        ticks: {{ callback: v => v.toLocaleString() }},
        title: {{ display: true, text: 'Units', font: {{ size: 11 }} }},
      }},
      y: {{ stacked: true, grid: {{ display: false }} }},
    }},
  }},
}});

// ── Viz 5: Leaflet map ────────────────────────────────────────────────────────
(function () {{
  const map = L.map('vt-map', {{ zoomSnap: 0.5 }}).setView([44.0, -72.7], 8);

  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }}).addTo(map);

  new L.Control.FullScreen().addTo(map);

  // Shared icon renderer — used for both clusters and individual markers
  function makeIcon(units, isInside) {{
    const label = units >= 1000 ? (units / 1000).toFixed(1) + 'k' : String(units);
    const size  = units >= 500 ? 44 : units >= 100 ? 36 : units >= 50 ? 30 : units >= 20 ? 26 : units >= 5 ? 24 : units >= 2 ? 22 : 20;
    const t     = Math.min(Math.log10(Math.max(units, 1)) / Math.log10(500), 1.0);
    const bg    = isInside
      ? `hsl(10,${{Math.round(22 + t * 64)}}%,60%)`
      : `hsl(158,${{Math.round(15 + t * 50)}}%,42%)`;
    return L.divIcon({{
      html: `<div style="width:${{size}}px;height:${{size}}px;background:${{bg}};color:#fff;border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;font-size:${{size >= 40 ? 11 : 10}}px;font-weight:700;line-height:1;box-shadow:0 1px 4px rgba(0,0,0,0.35)">${{label}}</div>`,
      className: '',
      iconSize:   L.point(size, size),
      iconAnchor: L.point(size / 2, size / 2),
    }});
  }}

  function makeClusterIcon(cluster, isInside) {{
    const total = cluster.getAllChildMarkers().reduce((s, m) => s + (m._units || 1), 0);
    return makeIcon(total, isInside);
  }}

  const insideCluster  = L.markerClusterGroup({{ chunkedLoading: true, maxClusterRadius: 40, iconCreateFunction: c => makeClusterIcon(c, true)  }});
  const outsideCluster = L.markerClusterGroup({{ chunkedLoading: true, maxClusterRadius: 40, iconCreateFunction: c => makeClusterIcon(c, false) }});

  function makeMarker(feature, isInside) {{
    const p      = feature.properties;
    const latlng = [feature.geometry.coordinates[1], feature.geometry.coordinates[0]];
    const marker = L.marker(latlng, {{ icon: makeIcon(p.units, isInside) }});
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

  fetch('exemption_union.geojson')
    .then(r => r.json())
    .then(data => {{
      L.geoJSON(data, {{
        style: {{ color: '#074B41', weight: 1.5, fillColor: '#074B41', fillOpacity: 0.12 }}
      }}).addTo(map);
    }})
    .catch(() => console.warn('exemption_union.geojson not found — run make map_data'));

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
  }}).catch(() => console.warn('DHCD GeoJSON files not found — run make map_data'));
}})();
</script>
</body>
</html>
"""

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'Written: {OUT}')
