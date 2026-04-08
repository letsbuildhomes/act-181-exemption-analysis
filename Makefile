# Vermont Housing Data Site
#
# Full pipeline (builds everything from raw data sources):
#
#   make all      — full pipeline: process → enrich → patch → build → site → report
#   make build    — generate the data essay blog post (output/blog.html)  [default]
#   make site     — generate the interactive dashboard (output/index.html)
#   make enrich   — re-run exemption area spatial join
#   make patch    — re-apply Essex split patch
#
# Other targets:
#   make clean    — remove generated outputs (output/, .stamps/)
#   make rebuild  — clean + all
#
# To serve locally:
#   cd output && python3 -m http.server
#   Then open http://localhost:8000/blog.html

.PHONY: all build blog site report enrich patch map_data clean rebuild

STAMPS = .stamps
OUTPUT = output

RAW_DATA = data/act250_permits.csv data/dhcd_housing.csv \
           data/rpc_housing_targets.csv data/stormwater_permits.csv \
           data/vt_towns.geojson data/vt_counties.geojson

all: enrich patch map_data build site report

# ── Default build: data essay blog post ──────────────────────────────────────

build: $(OUTPUT)/blog.html

blog: build

$(OUTPUT)/blog.html: generate_blog.py housing_dev.db blog-draft.md | $(OUTPUT)
	/opt/homebrew/bin/uv run python3 generate_blog.py
	@echo "Note: map requires output/*.geojson — run 'make map_data' if needed"

# ── Step 1: Build the initial database from raw sources ──────────────────────

housing_dev.db: process_all.py $(RAW_DATA)
	uv run python3 process_all.py

# ── Step 2: Add rural/urban population tiers ─────────────────────────────────

$(STAMPS)/rural_urban: add_rural_urban.py housing_dev.db data/town_population_2020.csv | $(STAMPS)
	uv run python3 add_rural_urban.py
	touch $@

# ── Step 3: Build project clusters (DBSCAN spatial clustering) ───────────────

$(STAMPS)/clusters: build_clusters.py $(STAMPS)/rural_urban
	uv run python3 build_clusters.py
	touch $@

# ── Step 4: Enrich with Act 181 exemption areas ───────────────────────────────

enrich: add_exemption_areas.py $(STAMPS)/clusters \
        data/exemption-areas/downtown_district.geojson \
        data/exemption-areas/priority_housing_projects.geojson \
        data/exemption-areas/town_growth_centers.geojson \
        data/exemption-areas/urbanized_transit_buffer.geojson \
        data/exemption-areas/village_center_buffer.geojson
	uv run python3 add_exemption_areas.py

# ── Step 5: Patch Essex / Essex Junction split ────────────────────────────────

patch: patch_essex_split.py $(STAMPS)/clusters
	uv run python3 patch_essex_split.py

# ── Step 5b: Build GeoJSON map data files ────────────────────────────────────

map_data: $(STAMPS)/map_data
$(STAMPS)/map_data: build_map_data.py housing_dev.db \
        data/exemption-areas/downtown_district.geojson \
        data/exemption-areas/priority_housing_projects.geojson \
        data/exemption-areas/town_growth_centers.geojson \
        data/exemption-areas/urbanized_transit_buffer.geojson \
        data/exemption-areas/village_center_buffer.geojson | $(STAMPS) $(OUTPUT)
	uv run python3 build_map_data.py
	touch $@

# ── Step 6: Generate interactive dashboard ───────────────────────────────────

site: $(OUTPUT)/index.html

$(OUTPUT)/index.html: generate_site.py housing_dev.db | $(OUTPUT)
	uv run python3 generate_site.py

# ── Step 7: Generate SQL reference document ───────────────────────────────────

report: $(OUTPUT)/report.md

$(OUTPUT)/report.md: generate_report.py housing_dev.db | $(OUTPUT)
	/opt/homebrew/bin/uv run python3 generate_report.py

# ── Utilities ─────────────────────────────────────────────────────────────────

$(STAMPS):
	mkdir -p $(STAMPS)

$(OUTPUT):
	mkdir -p $(OUTPUT)

clean:
	rm -rf $(OUTPUT) $(STAMPS)

rebuild: clean all
