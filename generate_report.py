"""
generate_report.py — reads housing_dev.db and produces output/report.md

A data reference document for blog-post authors. Every statistic is paired
with the SQL query that produced it, so numbers can always be verified or
re-run against the database directly.

Usage:
    uv run python3 generate_report.py               # writes output/report.md
    uv run python3 generate_report.py path/out.md   # custom path
"""

import os
import sys
import sqlite3
from config import START_YEAR, END_YEAR, PROJ_START_YEAR, PROJ_END_YEAR

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = os.path.join(HERE, 'housing_dev.db')
OUTPUT = os.path.join(HERE, 'output')
os.makedirs(OUTPUT, exist_ok=True)
OUT    = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUTPUT, 'report.md')

# ── Constants (match generate_site.py) ────────────────────────────────────────
STATE_TARGET_LOWER = 5573    # Act 47 (2023) minimum annual housing target
STATE_TARGET_UPPER = 8237    # Act 47 (2023) upper annual housing target
VAPDA_INSIDE_PCT   = 0.60    # VAPDA projection: share of future housing inside growth areas

# Readable multi-line fragment for embedding in SQL code blocks
SEASONAL_FILTER = """\
  AND LOWER(COALESCE(site_type, '')) NOT IN (
      'camp', 'seasonal home', 'seasonal camp', 'camp/seasonal home', 'seasonal'
  )"""

# Inline fragment for actual query execution (single line)
_SEASONAL_INLINE = (
    "AND LOWER(COALESCE(site_type,'')) NOT IN "
    "('camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')"
)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


# ── Query 0: Seasonal units excluded ──────────────────────────────────────────
seasonal_excluded = int(con.execute(f'''
    SELECT SUM(unit_count) FROM dhcd_new_housing
    WHERE year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(site_type,'')) IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
''').fetchone()[0] or 0)


# ── Query 1: site_type_general vocabulary ─────────────────────────────────────
typology_vocab_rows = con.execute(f'''
    SELECT
        COALESCE(site_type_general, '(null)') AS raw_value,
        COUNT(*)          AS project_count,
        SUM(unit_count)   AS unit_count
    FROM dhcd_new_housing
    WHERE year_built BETWEEN {START_YEAR} AND {END_YEAR}
    GROUP BY site_type_general
    ORDER BY unit_count DESC
''').fetchall()


# ── Query 2: Town counts by tier ──────────────────────────────────────────────
tier_count_rows = con.execute(f'''
    SELECT
        COALESCE(urban_rural_tier, 'Rural') AS tier,
        COUNT(*) AS town_count
    FROM town_lookup
    GROUP BY urban_rural_tier
    ORDER BY
        CASE COALESCE(urban_rural_tier, 'Rural')
            WHEN 'Urban'    THEN 1
            WHEN 'Suburban' THEN 2
            ELSE 3
        END
''').fetchall()


# ── Query 3: Total units by tier ──────────────────────────────────────────────
TOTAL_BY_TIER_SQL = f"""\
SELECT
    tier,
    units,
    ROUND(100.0 * units / SUM(units) OVER (), 1) AS pct_of_total
FROM (
    SELECT
        LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
    GROUP BY tier
)
ORDER BY units DESC;"""

total_tier_rows = con.execute(f'''
    SELECT
        tier,
        units,
        ROUND(100.0 * units / SUM(units) OVER (), 1) AS pct_of_total
    FROM (
        SELECT
            LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
            SUM(d.unit_count) AS units
        FROM dhcd_new_housing d
        LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
        WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
          AND LOWER(COALESCE(d.site_type,'')) NOT IN (
              'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
        GROUP BY tier
    )
    ORDER BY units DESC
''').fetchall()

total_units = sum(int(r['units']) for r in total_tier_rows)


# ── Query 4: Annual units by tier ─────────────────────────────────────────────
ANNUAL_BY_TIER_SQL = f"""\
SELECT
    CAST(d.year_built AS INTEGER) AS yr,
    LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
    SUM(d.unit_count) AS units
FROM dhcd_new_housing d
LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY yr, tier
ORDER BY yr, tier;"""

annual_tier_rows = con.execute(f'''
    SELECT
        CAST(d.year_built AS INTEGER) AS yr,
        LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
        SUM(d.unit_count) AS units
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY yr, tier
    ORDER BY yr, tier
''').fetchall()

years       = list(range(START_YEAR, END_YEAR + 1))
tiers_lower = ['rural', 'suburban', 'urban']
annual      = {t: {y: 0 for y in years} for t in tiers_lower}
for r in annual_tier_rows:
    if r['tier'] in annual:
        annual[r['tier']][r['yr']] = int(r['units'] or 0)
annual_totals = [sum(annual[t][y] for t in tiers_lower) for y in years]
avg_annual    = round(sum(annual_totals) / len(years))


# ── Query 5: Typology by tier ─────────────────────────────────────────────────
TYPOLOGY_BY_TIER_SQL = f"""\
SELECT
    LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
    COALESCE(d.site_type_general, 'OTHER RESIDENTIAL') AS typology,
    SUM(d.unit_count) AS units,
    ROUND(
        100.0 * SUM(d.unit_count)
        / SUM(SUM(d.unit_count)) OVER (
            PARTITION BY LOWER(COALESCE(t.urban_rural_tier, 'rural'))
        ),
        1
    ) AS pct_of_tier
FROM dhcd_new_housing d
LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY tier, typology
ORDER BY tier, units DESC;"""

typology_tier_rows = con.execute(f'''
    SELECT
        LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
        COALESCE(d.site_type_general, 'OTHER RESIDENTIAL') AS typology,
        SUM(d.unit_count) AS units,
        ROUND(
            100.0 * SUM(d.unit_count)
            / SUM(SUM(d.unit_count)) OVER (
                PARTITION BY LOWER(COALESCE(t.urban_rural_tier, 'rural'))
            ),
            1
        ) AS pct_of_tier
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY tier, typology
    ORDER BY tier, units DESC
''').fetchall()


# ── Query 6: Project scale by tier ────────────────────────────────────────────
SCALE_BY_TIER_SQL = f"""\
SELECT
    LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
    CASE
        WHEN d.unit_count = 1                THEN 'single (1 unit)'
        WHEN d.unit_count BETWEEN 2 AND 9    THEN 'small (2-9 units)'
        WHEN d.unit_count BETWEEN 10 AND 49  THEN 'medium (10-49 units)'
        ELSE                                      'large (50+ units)'
    END AS scale_bucket,
    SUM(d.unit_count) AS units,
    ROUND(
        100.0 * SUM(d.unit_count)
        / SUM(SUM(d.unit_count)) OVER (
            PARTITION BY LOWER(COALESCE(t.urban_rural_tier, 'rural'))
        ),
        1
    ) AS pct_of_tier
FROM dhcd_new_housing d
LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY tier, scale_bucket
ORDER BY tier,
    CASE scale_bucket
        WHEN 'single (1 unit)'     THEN 1
        WHEN 'small (2-9 units)'   THEN 2
        WHEN 'medium (10-49 units)'THEN 3
        ELSE 4
    END;"""

scale_rows = con.execute(f'''
    SELECT
        LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
        CASE
            WHEN d.unit_count = 1                THEN 'single (1 unit)'
            WHEN d.unit_count BETWEEN 2 AND 9    THEN 'small (2-9 units)'
            WHEN d.unit_count BETWEEN 10 AND 49  THEN 'medium (10-49 units)'
            ELSE                                      'large (50+ units)'
        END AS scale_bucket,
        SUM(d.unit_count) AS units,
        ROUND(
            100.0 * SUM(d.unit_count)
            / SUM(SUM(d.unit_count)) OVER (
                PARTITION BY LOWER(COALESCE(t.urban_rural_tier, 'rural'))
            ),
            1
        ) AS pct_of_tier
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
    WHERE d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY tier, scale_bucket
    ORDER BY tier,
        CASE scale_bucket
            WHEN 'single (1 unit)'      THEN 1
            WHEN 'small (2-9 units)'    THEN 2
            WHEN 'medium (10-49 units)' THEN 3
            ELSE 4
        END
''').fetchall()


# ── Query 7: Overall inside/outside split ─────────────────────────────────────
EXEMPT_SPLIT_SQL = f"""\
SELECT
    CASE in_exemption_area WHEN 1 THEN 'inside' ELSE 'outside' END AS area,
    SUM(unit_count) AS units,
    ROUND(100.0 * SUM(unit_count) / SUM(SUM(unit_count)) OVER (), 1) AS pct_of_total
FROM dhcd_new_housing
WHERE in_exemption_area IS NOT NULL
  AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY in_exemption_area
ORDER BY in_exemption_area DESC;"""

exempt_split_rows = con.execute(f'''
    SELECT
        CASE in_exemption_area WHEN 1 THEN 'inside' ELSE 'outside' END AS area,
        SUM(unit_count) AS units,
        ROUND(100.0 * SUM(unit_count) / SUM(SUM(unit_count)) OVER (), 1) AS pct_of_total
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY in_exemption_area
    ORDER BY in_exemption_area DESC
''').fetchall()

exempt_inside     = next((int(r['units']) for r in exempt_split_rows if r['area'] == 'inside'),  0)
exempt_outside    = next((int(r['units']) for r in exempt_split_rows if r['area'] == 'outside'), 0)
exempt_total      = exempt_inside + exempt_outside
exempt_inside_pct = round(exempt_inside  / exempt_total * 100, 1) if exempt_total else 0
exempt_outside_pct= round(exempt_outside / exempt_total * 100, 1) if exempt_total else 0

no_join_count = int(con.execute(f'''
    SELECT COUNT(*) FROM dhcd_new_housing
    WHERE in_exemption_area IS NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
''').fetchone()[0] or 0)
total_records = int(con.execute(f'''
    SELECT COUNT(*) FROM dhcd_new_housing
    WHERE year_built BETWEEN {START_YEAR} AND {END_YEAR}
''').fetchone()[0] or 0)


# ── Query 8: Annual inside/outside ────────────────────────────────────────────
EXEMPT_ANNUAL_SQL = f"""\
SELECT
    CAST(year_built AS INTEGER) AS yr,
    SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
    SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units,
    SUM(unit_count) AS total_units
FROM dhcd_new_housing
WHERE in_exemption_area IS NOT NULL
  AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY yr
ORDER BY yr;"""

exempt_year_rows = con.execute(f'''
    SELECT
        CAST(year_built AS INTEGER) AS yr,
        SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
        SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units,
        SUM(unit_count) AS total_units
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY yr
    ORDER BY yr
''').fetchall()


# ── Query 9: Typology inside/outside ─────────────────────────────────────────
EXEMPT_TYPOLOGY_SQL = f"""\
SELECT
    COALESCE(site_type_general, 'OTHER RESIDENTIAL') AS typology,
    SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
    SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units,
    SUM(unit_count) AS total_units,
    ROUND(
        100.0 * SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END)
        / NULLIF(SUM(unit_count), 0),
        1
    ) AS pct_inside
FROM dhcd_new_housing
WHERE in_exemption_area IS NOT NULL
  AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY site_type_general
ORDER BY total_units DESC;"""

exempt_typology_rows = con.execute(f'''
    SELECT
        COALESCE(site_type_general, 'OTHER RESIDENTIAL') AS typology,
        SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END) AS inside_units,
        SUM(CASE WHEN in_exemption_area = 0 THEN unit_count ELSE 0 END) AS outside_units,
        SUM(unit_count) AS total_units,
        ROUND(
            100.0 * SUM(CASE WHEN in_exemption_area = 1 THEN unit_count ELSE 0 END)
            / NULLIF(SUM(unit_count), 0),
            1
        ) AS pct_inside
    FROM dhcd_new_housing
    WHERE in_exemption_area IS NOT NULL
      AND year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY site_type_general
    ORDER BY total_units DESC
''').fetchall()


# ── Query 10: Community type × exemption area cross-tab ──────────────────────
TIER_EXEMPT_SQL = f"""\
SELECT
    LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
    CASE d.in_exemption_area WHEN 1 THEN 'inside' ELSE 'outside' END AS area,
    SUM(d.unit_count) AS units,
    ROUND(
        100.0 * SUM(d.unit_count)
        / SUM(SUM(d.unit_count)) OVER (
            PARTITION BY LOWER(COALESCE(t.urban_rural_tier, 'rural'))
        ),
        1
    ) AS pct_of_tier
FROM dhcd_new_housing d
LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
WHERE d.in_exemption_area IS NOT NULL
  AND d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
{{seasonal_filter}}
GROUP BY tier, d.in_exemption_area
ORDER BY tier, d.in_exemption_area DESC;"""

tier_exempt_rows = con.execute(f'''
    SELECT
        LOWER(COALESCE(t.urban_rural_tier, 'rural')) AS tier,
        CASE d.in_exemption_area WHEN 1 THEN 'inside' ELSE 'outside' END AS area,
        SUM(d.unit_count) AS units,
        ROUND(
            100.0 * SUM(d.unit_count)
            / SUM(SUM(d.unit_count)) OVER (
                PARTITION BY LOWER(COALESCE(t.urban_rural_tier, 'rural'))
            ),
            1
        ) AS pct_of_tier
    FROM dhcd_new_housing d
    LEFT JOIN town_lookup t ON UPPER(d.town_name_title) = UPPER(t.townname_title)
    WHERE d.in_exemption_area IS NOT NULL
      AND d.year_built BETWEEN {START_YEAR} AND {END_YEAR}
      AND LOWER(COALESCE(d.site_type,'')) NOT IN (
          'camp','seasonal home','seasonal camp','camp/seasonal home','seasonal')
    GROUP BY tier, d.in_exemption_area
    ORDER BY tier, d.in_exemption_area DESC
''').fetchall()


# ── Query 11: Town classification appendix ────────────────────────────────────
TOWN_CLASS_SQL = """\
SELECT
    townname_title                      AS town,
    COALESCE(urban_rural_tier, 'Rural') AS tier,
    population_2020,
    ROUND(pop_density_km2, 1)           AS density_per_km2
FROM town_lookup
ORDER BY
    CASE COALESCE(urban_rural_tier, 'Rural')
        WHEN 'Urban'    THEN 1
        WHEN 'Suburban' THEN 2
        ELSE 3
    END,
    townname_title;"""

town_class_rows = con.execute(f'''
    SELECT
        townname_title                      AS town,
        COALESCE(urban_rural_tier, 'Rural') AS tier,
        population_2020,
        ROUND(pop_density_km2, 1)           AS density_per_km2
    FROM town_lookup
    ORDER BY
        CASE COALESCE(urban_rural_tier, 'Rural')
            WHEN 'Urban'    THEN 1
            WHEN 'Suburban' THEN 2
            ELSE 3
        END,
        townname_title
''').fetchall()

con.close()


# ── Derived projections ────────────────────────────────────────────────────────
target_mid          = (STATE_TARGET_LOWER + STATE_TARGET_UPPER) / 2
proj_annual_inside  = round(target_mid * VAPDA_INSIDE_PCT)
proj_annual_outside = round(target_mid * (1 - VAPDA_INSIDE_PCT))
proj_lower_inside   = round(STATE_TARGET_LOWER * VAPDA_INSIDE_PCT)
proj_upper_inside   = round(STATE_TARGET_UPPER * VAPDA_INSIDE_PCT)
proj_lower_outside  = round(STATE_TARGET_LOWER * (1 - VAPDA_INSIDE_PCT))
proj_upper_outside  = round(STATE_TARGET_UPPER * (1 - VAPDA_INSIDE_PCT))


# ── Helpers ────────────────────────────────────────────────────────────────────
def n(val):
    """Format integer with comma thousands separator."""
    return f"{int(val):,}"


def sql_block(query_str):
    """Wrap a SQL string in a fenced code block, substituting the seasonal filter."""
    return "```sql\n" + query_str.format(seasonal_filter=SEASONAL_FILTER) + "\n```"


# ── Build document ─────────────────────────────────────────────────────────────
lines = []
A = lines.append


def hr():
    lines.extend(['', '---', ''])


# ── Title and preamble ─────────────────────────────────────────────────────────
A(f'# Vermont Housing Production: Data Reference ({START_YEAR}–{END_YEAR})')
A('')
A('> **How to use this document.**')
A('> Every statistic is paired with the SQL query that produced it.')
A('> To verify or re-run any figure, copy the query into a SQLite client:')
A('>')
A('> ```sh')
A('> sqlite3 housing_dev.db')
A('> ```')
A('>')
A('> Rows are returned in the same order as the bullet points above each query.')
A('> Do not quote figures from memory — re-run the query.')

hr()

# ── Methodology ───────────────────────────────────────────────────────────────
A('## Data Sources and Methodology')
A('')
A('### Source dataset')
A('')
A('All housing figures use the **DHCD New Housing Database** — the dataset that drives the')
A('Vermont Housing Dashboard. Records represent new housing units as recorded in the')
A(f'state E911 address system from {START_YEAR} through {END_YEAR}.')
A('The database file is `housing_dev.db` (SQLite); the primary table is `dhcd_new_housing`.')
A('')
A('### Seasonal exclusion')
A('')
A(f'**{n(seasonal_excluded)} units** in the DHCD data ({START_YEAR}–{END_YEAR}) are classified as seasonal')
A('or camp structures and are excluded from every analysis in this document.')
A('The filter below is applied in every query — it is shown explicitly in each SQL block:')
A('')
A('```sql')
A("-- Seasonal exclusion filter (paste into any query against dhcd_new_housing)")
A("AND LOWER(COALESCE(site_type, '')) NOT IN (")
A("    'camp', 'seasonal home', 'seasonal camp', 'camp/seasonal home', 'seasonal'")
A(')')
A('```')
A('')
A('### Housing typology mapping (`site_type_general`)')
A('')
A('The `site_type_general` column is passed through from the DHCD source field `sitetype_general`.')
A('Three values appear in the data and are used throughout this document:')
A('')
A('| Raw value in `site_type_general`  | Display label     |')
A('|-----------------------------------|-------------------|')
A('| `MULTI-FAMILY DWELLING`           | Multi-Family      |')
A('| `SINGLE FAMILY DWELLING`          | Single-Family     |')
A('| `OTHER RESIDENTIAL`               | Other Residential |')
A('')
A(f'Full vocabulary with unit counts ({START_YEAR}–{END_YEAR}, **before** the seasonal filter):')
A('')
for r in typology_vocab_rows:
    A(f'- `{r["raw_value"]}`: {n(r["unit_count"])} units across {n(r["project_count"])} projects')
A('')
A('```sql')
A("SELECT")
A("    COALESCE(site_type_general, '(null)') AS raw_value,")
A("    COUNT(*)        AS project_count,")
A("    SUM(unit_count) AS unit_count")
A("FROM dhcd_new_housing")
A(f"WHERE year_built BETWEEN {START_YEAR} AND {END_YEAR}")
A("GROUP BY site_type_general")
A("ORDER BY unit_count DESC;")
A('```')

hr()

# ── Part 1 ────────────────────────────────────────────────────────────────────
A('## Part 1: Community Archetypes — Urban, Suburban, and Rural')
A('')
A('This section classifies Vermont\'s 256 municipalities into three tiers using 2020 Census')
A('population data, then measures how much housing each type of community has produced.')

A('')
A('### 1.1 Town classification methodology')
A('')
A('Towns are classified using the `urban_rural_tier` column in `town_lookup`,')
A('derived from 2020 Census `population_2020` and `pop_density_km2`. The thresholds are:')
A('')
A('| Tier         | Criteria                                                  |')
A('|--------------|-----------------------------------------------------------|')
A('| **Urban**    | Population ≥ 5,000 **AND** density ≥ 100 people/km²      |')
A('| **Suburban** | Population ≥ 2,500 **OR** density ≥ 40 people/km²        |')
A('| **Rural**    | All other towns; also default when Census data is absent  |')
A('')
A('> **Note on Essex/Essex Junction:** Following the 2020 Census, Essex Town and Essex')
A('> Junction became separate municipalities. DHCD records before 2022 predate the split.')
A('> `patch_essex_split.py` applies a spatial heuristic to assign pre-split records to the')
A('> correct jurisdiction.')
A('')
A('Town counts per tier (rows are returned in Urban → Suburban → Rural order):')
A('')
for r in tier_count_rows:
    A(f'- **{r["tier"]}:** {r["town_count"]} towns')
A('')
A('```sql')
A('SELECT')
A("    COALESCE(urban_rural_tier, 'Rural') AS tier,")
A('    COUNT(*) AS town_count')
A('FROM town_lookup')
A('GROUP BY urban_rural_tier')
A('ORDER BY')
A("    CASE COALESCE(urban_rural_tier, 'Rural')")
A("        WHEN 'Urban'    THEN 1")
A("        WHEN 'Suburban' THEN 2")
A('        ELSE 3')
A('    END;')
A('```')

A('')
A(f'### 1.2 Total housing production by community type ({START_YEAR}–{END_YEAR})')
A('')
A(f'Total year-round units produced {START_YEAR}–{END_YEAR}: **{n(total_units)}**')
A(f'Average annual year-round production: **{n(avg_annual)} units/year**')
A('')
A('Breakdown by community type (rows are ordered by `units DESC`, matching the query output):')
A('')
for r in total_tier_rows:
    A(f'- **{r["tier"]}:** {n(r["units"])} units ({r["pct_of_total"]}%)')
A('')
A('_Run the query below to reproduce these figures._')
A('')
A(sql_block(TOTAL_BY_TIER_SQL))

A('')
A('### 1.3 Annual production by community type')
A('')
A('Year-by-year totals (all tiers combined, for reference):')
A('')
for y in years:
    total_y = sum(annual[t][y] for t in tiers_lower)
    A(f'- **{y}:** {n(total_y)} units')
A('')
A('_The query below returns the per-tier breakdown (30 rows: 10 years × 3 tiers).')
A('Use this as the data source for stacked bar charts by tier._')
A('')
A(sql_block(ANNUAL_BY_TIER_SQL))

A('')
A('### 1.4 Housing typology by community type')
A('')
A('Units broken down by `site_type_general` within each tier.')
A('`pct_of_tier` is each typology\'s share of that tier\'s total year-round production.')
A('')

typology_by_tier: dict = {}
for r in typology_tier_rows:
    typology_by_tier.setdefault(r['tier'], []).append(r)

for tier in ['rural', 'suburban', 'urban']:
    rows = typology_by_tier.get(tier, [])
    if not rows:
        continue
    A(f'**{tier.title()}:**')
    for r in rows:
        A(f'- `{r["typology"]}`: {n(r["units"])} units ({r["pct_of_tier"]}% of tier)')
    A('')

A('_Run the query below to reproduce these figures. Rows are ordered tier ASC, units DESC._')
A('')
A(sql_block(TYPOLOGY_BY_TIER_SQL))

A('')
A('### 1.5 Project scale distribution by community type')
A('')
A('Unit counts by project size bucket within each tier.')
A('`pct_of_tier` is each bucket\'s share of that tier\'s total year-round production.')
A('')

scale_by_tier: dict = {}
for r in scale_rows:
    scale_by_tier.setdefault(r['tier'], []).append(r)

for tier in ['rural', 'suburban', 'urban']:
    rows = scale_by_tier.get(tier, [])
    if not rows:
        continue
    A(f'**{tier.title()}:**')
    for r in rows:
        A(f'- {r["scale_bucket"]}: {n(r["units"])} units ({r["pct_of_tier"]}% of tier)')
    A('')

A('_Run the query below to reproduce these figures._')
A('')
A(sql_block(SCALE_BY_TIER_SQL))

hr()

# ── Part 2 ────────────────────────────────────────────────────────────────────
A('## Part 2: Inside vs. Outside the Tier 1 Proxy Area')
A('')
A('This section examines where housing has been built relative to Vermont\'s designated')
A('growth areas, using the Act 181 (2024) temporary exemption maps as a Tier 1 proxy.')

A('')
A('### 2.1 Methodology')
A('')
A('Vermont\'s Act 181 (2024) designates "growth areas" — downtown districts, town centers,')
A('village centers, and transit corridors — where development should be concentrated and')
A('permitting streamlined. Because the final Tier 1 boundary is not yet established, this')
A('analysis uses the **temporary exemption maps** as a proxy. The five layers are:')
A('')
A('- `downtown_district.geojson`')
A('- `town_growth_centers.geojson`')
A('- `village_center_buffer.geojson`')
A('- `priority_housing_projects.geojson`')
A('- `urbanized_transit_buffer.geojson`')
A('')
A('These are spatially unioned in `add_exemption_areas.py`. Each DHCD project point is')
A('tagged `in_exemption_area = 1` (inside) or `0` (outside) via a point-in-polygon join.')
A('')
A(f'**Spatial join coverage ({START_YEAR}–{END_YEAR}):** {n(total_records - no_join_count)} of')
A(f'{n(total_records)} records have a join result. {n(no_join_count)} records have')
A('`in_exemption_area IS NULL` (typically missing coordinates) and are excluded from')
A('all inside/outside analysis.')

A('')
A(f'### 2.2 Overall inside/outside split ({START_YEAR}–{END_YEAR})')
A('')
A(f'Year-round units with a spatial join result: **{n(exempt_total)}**')
A('')
A('Split (rows are ordered inside first, matching the query output):')
A('')
for r in exempt_split_rows:
    A(f'- **{r["area"].title()}:** {n(r["units"])} units ({r["pct_of_total"]}%)')
A('')
A(f'**VAPDA target split:** 60% inside / 40% outside')
A(f'**Actual historical split:** {exempt_inside_pct}% inside / {exempt_outside_pct}% outside')
A('')
A('_Run the query below to reproduce these figures._')
A('')
A(sql_block(EXEMPT_SPLIT_SQL))

A('')
A('### 2.3 Annual inside/outside production (year-by-year)')
A('')
A('Per-year units inside and outside the exemption areas. This is the basis for')
A('the yearly bar chart showing the inside/outside split over time.')
A('')
for r in exempt_year_rows:
    A(f'- **{r["yr"]}:** {n(r["inside_units"])} inside / {n(r["outside_units"])} outside'
      f' ({n(r["total_units"])} total)')
A('')
A('_Run the query below to reproduce these figures._')
A('')
A(sql_block(EXEMPT_ANNUAL_SQL))

A('')
A(f'### 2.4 VAPDA target projections ({PROJ_START_YEAR}–{PROJ_END_YEAR})')
A('')
A('The VAPDA study projects that 60% of future housing should occur inside designated')
A('growth areas. Applied to the Act 47 (2023) annual targets:')
A('')
A(f'- **State target range:** {n(STATE_TARGET_LOWER)}–{n(STATE_TARGET_UPPER)} units/year')
A(f'- **Inside — lower bound:** {n(proj_lower_inside)} units/year'
  f' → {n(proj_lower_inside * 5)} over {PROJ_START_YEAR}–{PROJ_END_YEAR}')
A(f'- **Inside — upper bound:** {n(proj_upper_inside)} units/year'
  f' → {n(proj_upper_inside * 5)} over {PROJ_START_YEAR}–{PROJ_END_YEAR}')
A(f'- **Outside — lower bound:** {n(proj_lower_outside)} units/year'
  f' → {n(proj_lower_outside * 5)} over {PROJ_START_YEAR}–{PROJ_END_YEAR}')
A(f'- **Outside — upper bound:** {n(proj_upper_outside)} units/year'
  f' → {n(proj_upper_outside * 5)} over {PROJ_START_YEAR}–{PROJ_END_YEAR}')
A(f'- **Midpoint inside projection:** {n(proj_annual_inside)} units/year (used in chart)')
A(f'- **Midpoint outside projection:** {n(proj_annual_outside)} units/year (used in chart)')
A('')
A('These are arithmetic — not database queries. The computation:')
A('')
A('```python')
A('STATE_TARGET_LOWER = 5573   # Act 47 minimum annual housing target')
A('STATE_TARGET_UPPER = 8237   # Act 47 upper annual housing target')
A('VAPDA_INSIDE_PCT   = 0.60   # VAPDA: projected share inside growth areas')
A('')
A('target_mid          = (STATE_TARGET_LOWER + STATE_TARGET_UPPER) / 2')
A(f'# target_mid = {target_mid}')
A('')
A(f'proj_annual_inside  = round(target_mid * VAPDA_INSIDE_PCT)             # {proj_annual_inside}')
A(f'proj_annual_outside = round(target_mid * (1 - VAPDA_INSIDE_PCT))       # {proj_annual_outside}')
A(f'proj_lower_inside   = round(STATE_TARGET_LOWER * VAPDA_INSIDE_PCT)     # {proj_lower_inside}')
A(f'proj_upper_inside   = round(STATE_TARGET_UPPER * VAPDA_INSIDE_PCT)     # {proj_upper_inside}')
A(f'proj_lower_outside  = round(STATE_TARGET_LOWER * (1 - VAPDA_INSIDE_PCT))  # {proj_lower_outside}')
A(f'proj_upper_outside  = round(STATE_TARGET_UPPER * (1 - VAPDA_INSIDE_PCT))  # {proj_upper_outside}')
A('```')

A('')
A('### 2.5 Housing typology inside vs. outside')
A('')
A('Breakdown by `site_type_general` showing how each housing type distributes')
A('across the inside/outside boundary. `pct_inside` is the share of that typology')
A('falling inside the exemption areas. Rows are ordered by `total_units DESC`.')
A('')
for r in exempt_typology_rows:
    A(f'- **`{r["typology"]}`:** {n(r["inside_units"])} inside / {n(r["outside_units"])} outside'
      f' — {r["pct_inside"]}% of this typology falls inside')
A('')
A('_Run the query below to reproduce these figures._')
A('')
A(sql_block(EXEMPT_TYPOLOGY_SQL))

A('')
A('### 2.6 Community type × exemption area')
A('')
A('Cross-tabulation of urban/suburban/rural × inside/outside. Shows how the geographic')
A('split varies across community types. `pct_of_tier` is each area\'s share of that tier\'s')
A('total units within the spatially-joined subset.')
A('')

tier_exempt_by_tier: dict = {}
for r in tier_exempt_rows:
    tier_exempt_by_tier.setdefault(r['tier'], []).append(r)

for tier in ['rural', 'suburban', 'urban']:
    rows = tier_exempt_by_tier.get(tier, [])
    if not rows:
        continue
    A(f'**{tier.title()}:**')
    for r in rows:
        A(f'- {r["area"]}: {n(r["units"])} units ({r["pct_of_tier"]}% of tier)')
    A('')

A('_Run the query below to reproduce these figures._')
A('')
A(sql_block(TIER_EXEMPT_SQL))

hr()

# ── Appendix ──────────────────────────────────────────────────────────────────
A('## Appendix: Town Classification Reference')
A('')
tier_counts = {r['tier']: r['town_count'] for r in tier_count_rows}
A(f'Vermont has {sum(tier_counts.values())} municipalities classified as follows:')
A('')
for r in tier_count_rows:
    A(f'- **{r["tier"]}:** {r["town_count"]} towns')

A('')
A('**Urban towns** (population ≥ 5,000 AND density ≥ 100/km²):')
A('')
urban_towns = [r['town'] for r in town_class_rows if r['tier'] == 'Urban']
A(', '.join(urban_towns))

A('')
A('**Suburban towns** (population ≥ 2,500 OR density ≥ 40/km²; not Urban):')
A('')
suburban_towns = [r['town'] for r in town_class_rows if r['tier'] == 'Suburban']
A(', '.join(suburban_towns))

A('')
A('All remaining towns are classified **Rural**.')
A('')
A('_The full classification table (all towns, with population and density) can be')
A('retrieved with the query below._')
A('')
A('```sql')
A(TOWN_CLASS_SQL)
A('```')

# ── Write output ───────────────────────────────────────────────────────────────
doc = '\n'.join(lines) + '\n'
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(doc)

print(f'Wrote {len(doc):,} bytes → {OUT}')
