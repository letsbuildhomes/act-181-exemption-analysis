# Vermont Housing Data Site
#
# Full pipeline (after housing_dev.db is built by process_all.py):
#
#   make enrich   — add in_exemption_area column via spatial join (run after DB rebuild)
#   make build    — regenerate index.html from housing_dev.db
#   make all      — enrich + build in one step
#
# Other targets:
#   make patch    — apply Essex split patch to housing_dev.db
#   make clean    — remove generated index.html
#   make rebuild  — clean + enrich + build

.PHONY: all build enrich patch clean rebuild

all: enrich patch build

build: index.html

index.html: generate_site.py housing_dev.db
	uv run python3 generate_site.py

enrich: add_exemption_areas.py housing_dev.db
	uv run python3 add_exemption_areas.py

patch:
	uv run python3 patch_essex_split.py

clean:
	rm -f index.html

rebuild: clean enrich build
