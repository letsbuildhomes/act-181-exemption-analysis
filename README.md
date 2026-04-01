# Vermont Housing Production — Data Site

A single-page data visualization site for Vermont legislators and the general public, produced by **Let's Build Homes**. It pulls directly from a local SQLite database at build time — no external API, no manual copy-paste.

## Quick start

```bash
# Rebuild the site
make

# Open it
open index.html
```

Requires Python 3 with the `sqlite3` standard library (no additional packages needed for `generate_site.py`).

---

## Files

| File | Purpose |
|---|---|
| `generate_site.py` | **Main generator.** Queries `housing_dev.db` and writes `index.html`. All chart data is embedded as JS constants at build time. |
| `housing_dev.db` | SQLite database. Single source of truth for all charts and tables. |
| `index.html` | Generated output. Open in any browser. Do not edit by hand — it will be overwritten on the next build. |
| `Makefile` | Convenience wrapper. `make` rebuilds the site; `make clean` removes the output. |
| `process_all.py` | **DB pipeline step 1.** Loads raw CSV/GeoJSON sources into `housing_dev.db`. Requires `pandas`, `geopandas`, `shapely`. |
| `add_rural_urban.py` | **DB pipeline step 2.** Adds 2020 Census population, area, density, and Urban/Suburban/Rural tier classification to `town_lookup`. |
| `build_project_clusters.py` | **DB pipeline step 3.** Groups DHCD single-family permits into likely developer subdivisions using ESITE parcel matches and DBSCAN spatial clustering. |
| `vt_towns.geojson` | Vermont town boundaries (VCGI). Used by the DB pipeline for spatial joins. |
| `vt_counties.geojson` | Vermont county boundaries (VCGI). Used by the DB pipeline. |

---

## Data sources

- **DHCD New Housing Database** — Vermont Agency of Commerce & Community Development. Residential building permits statewide, 2016–present. Each record is one address with a unit count.
  https://accd.vermont.gov/housing/plans-data-rules/dhcd-housing-data

- **VCGI ESITE Layer** — Vermont Center for Geographic Information. Residential development sites with parcel category. Used to identify large single-family subdivisions that appear in DHCD as many individual 1-unit permits.
  https://geodata.vermont.gov/datasets/VCGI::esite-development-sites-with-parcel-category/about

- **2020 U.S. Census** (via VCGI) — Town-level population counts from county subdivision geography.
  https://geodata.vermont.gov/datasets/VCGI::vt-census-2020-county-subdivisions-population-and-housing-units/about

- **State housing target: 8,237 units/year** — Set by Act 47 (2023).
  https://legislature.vermont.gov/bill/status/2024/H.687

- **Act 181 (2024)** — Act 250 modernization / development tier system.
  https://legislature.vermont.gov/bill/status/2024/S.100

---

## Community tier classification

Towns are classified using 2020 Census population density (EPSG:32145 / Vermont State Plane):

| Tier | Criteria | Count |
|---|---|---|
| **Urban** | Population ≥ 5,000 AND density ≥ 100/km² | 13 towns |
| **Suburban** | Population ≥ 2,500 OR density ≥ 40/km² | 62 towns |
| **Rural** | All others | 180 towns |

These tiers correspond to Act 181's Tier 1 (urban growth centers), Tier 2 (suburban/designated areas), and Tier 3 (rural) development review categories.

---

## What "year-round" means

Charts that show year-round production exclude permits classified as seasonal structures — camps, seasonal homes, vacation cabins. This does **not** mean the counted units are primary Vermont residences; many may be second homes or part-time residences. "Year-round" simply means the permit was not classified as a seasonal structure.

---

## Rebuilding the database from raw data

If you need to update `housing_dev.db` with new source data:

1. Place updated CSVs and GeoJSONs in a `raw_data/` directory (see `process_all.py` for expected filenames).
2. Run the pipeline in order:
   ```bash
   python3 process_all.py        # load raw sources
   python3 add_rural_urban.py    # add Census density tiers
   python3 build_project_clusters.py  # identify subdivisions
   ```
3. Rebuild the site: `make`

Pipeline scripts require: `pandas`, `geopandas`, `shapely`, `numpy`, `scikit-learn`.

---

## Notes

- The site uses [Chart.js 4.4.1](https://www.chartjs.org/) loaded from cdnjs. It requires an internet connection to render charts.
- `index.html` is self-contained aside from that CDN dependency — no server needed, just open it in a browser.
- All numbers should be understood as directionally informative. The DHCD database has known coverage gaps; ESITE parcel analysis is an approximation. Do not cite specific figures as authoritative without independent verification.
