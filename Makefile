# Vermont Housing Data Site
#
# Full pipeline (builds everything from raw data sources):
#
#   make all      — full pipeline: process → enrich → patch → build
#   make enrich   — re-run exemption area spatial join
#   make patch    — re-apply Essex split patch
#   make build    — regenerate index.html from housing_dev.db
#
# Other targets:
#   make clean    — remove generated outputs (index.html, .stamps/)
#   make rebuild  — clean + all

.PHONY: all build enrich patch clean rebuild

STAMPS = .stamps

RAW_DATA = data/act250_permits.csv data/dhcd_housing.csv \
           data/rpc_housing_targets.csv data/stormwater_permits.csv \
           data/vt_towns.geojson data/vt_counties.geojson

all: enrich patch build

build: index.html

# ── Step 1: Build the initial database from raw sources ──────────────────────

housing_dev.db: process_all.py $(RAW_DATA)
	uv run python3 process_all.py

# ── Step 2: Add rural/urban population tiers ─────────────────────────────────

$(STAMPS)/rural_urban: add_rural_urban.py housing_dev.db data/town_population_2020.csv | $(STAMPS)
	uv run python3 add_rural_urban.py
	touch $@

# ── Step 3: Build project clusters from ESITE parcels ────────────────────────

$(STAMPS)/clusters: build_clusters.py $(STAMPS)/rural_urban data/esite_parcels.csv
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

# ── Step 6: Generate site ─────────────────────────────────────────────────────

index.html: generate_site.py housing_dev.db
	uv run python3 generate_site.py

# ── Utilities ─────────────────────────────────────────────────────────────────

$(STAMPS):
	mkdir -p $(STAMPS)

clean:
	rm -f index.html
	rm -rf $(STAMPS)

rebuild: clean all
