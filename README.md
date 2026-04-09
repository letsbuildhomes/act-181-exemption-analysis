# Vermont Housing Development Analysis

Analyzes new housing construction in Vermont, focusing on how many units—and of what type—are being built inside vs. outside the state's Act 181 temporary exemption areas.

## Data sources

- **DHCD Vermont New Housing database** — build records of new residential construction, fetched from the Vermont ArcGIS REST API. The copy in `data/dhcd_housing.csv` can be refreshed with `make extract`.
- **Act 181 temporary exemption-area GeoJSON files** (`data/exemption-areas/`) — five layers that together define Vermont's temporary exemption areas. These are static files checked into the repository.

## Pipeline

```
extract.py      downloads data/dhcd_housing.csv from ArcGIS API
transform.py    cleans CSV, runs point-in-polygon join → housing.db
analyze.py      queries housing.db, writes output/index.html + GeoJSONs
```

Analysis covers years 2021–2025 (set in `config.py`).

## Usage

```bash
# Build the report from existing data
make

# Refresh the source data from the API, then rebuild
make extract && make

# Serve the report locally
make serve
# → open http://localhost:8000
```

`make clean` removes `output/` and `housing.db`. `make rebuild` does a clean build from scratch.

## Output

- `output/index.html` — HTML report with:
  - Stacked bar chart of annual unit counts (inside/outside exemption areas), with Act 47 target bars for 2026–2030
  - Horizontal bar chart breaking down units by housing type (Single Family / Multi Family / Other Residential)
  - Interactive Leaflet map of sites in the analysis window, colored by type and clustered by inside/outside status
  - Data notes explaining sources, exclusions, and methodology, including the exclusion of records with missing or non-positive unit counts
- `output/exemption_union.geojson` — union of all five exemption-area layers (used by the map)
- `output/dhcd_inside_exemption.geojson` / `dhcd_outside_exemption.geojson` — point data for the map

## Dependencies

```bash
uv sync   # or: pip install -r requirements.txt
```

Requires Python 3.10+, `pandas`, `geopandas`, `shapely`.
