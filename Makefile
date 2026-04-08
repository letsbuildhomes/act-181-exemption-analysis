# Vermont Housing Development — Tier 1 Exemption Area Analysis
#
# Pipeline:
#   make          — build housing.db and output/index.html (default)
#   make extract  — re-download data/dhcd_housing.csv from source API
#   make clean    — remove housing.db and output/
#   make rebuild  — clean + all
#
# To serve locally:
#   cd output && python3 -m http.server
#   Then open http://localhost:8000

.PHONY: all extract clean rebuild

UV = /opt/homebrew/bin/uv run python3
OUTPUT = output

all: output/index.html

# ── Fresh data download (overwrites data/dhcd_housing.csv) ───────────────────

extract: extract.py
	$(UV) extract.py

# ── Transform: CSV → housing.db ──────────────────────────────────────────────

housing.db: transform.py data/dhcd_housing.csv \
    data/exemption-areas/downtown_district.geojson \
    data/exemption-areas/town_growth_centers.geojson \
    data/exemption-areas/village_center_buffer.geojson \
    data/exemption-areas/priority_housing_projects.geojson \
    data/exemption-areas/urbanized_transit_buffer.geojson
	$(UV) transform.py

# ── Analyze: housing.db → output/index.html + GeoJSONs ───────────────────────

output/index.html: analyze.py housing.db | $(OUTPUT)
	$(UV) analyze.py

$(OUTPUT):
	mkdir -p $(OUTPUT)

# ── Utilities ─────────────────────────────────────────────────────────────────

serve: output/index.html
	python3 -m http.server --directory output

clean:
	rm -rf $(OUTPUT) housing.db

rebuild: clean all
