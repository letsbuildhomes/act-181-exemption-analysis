# Research question

How has the scale of residential development projects in Vermont varied over roughly the last 20–25 years, and how do those project-size “buckets” compare across different parts of the state? The goal is not just a statewide distribution, but a dataset or assembled evidence base with at least some geospatial component so the size mix can be compared by place, region, or other geographic layers.

Most explicitly, I'm trying to get a sense of how many projects in "rural" Vermont are small "family plot" homes versus larger developer subdivisions. Since both of these questions are somewhat dependent on defintions, our goal is to try to build a dataset that can help us explore this question interactively, instead of just trying to answer the question directly. An absolute best case scenario would be a database that has coordinates of every project permitted in the state in the last 25 years, along with the unit count (and date, and any other useful metadata). Knowing that this will be probably impossible to fully achieve, we should do our best to get as close to that as is reasonable with the data we can find.

# Background

There does not appear to be a single, ready-made Vermont dataset that directly answers this question at the statewide level as a clean project-level file over the last 20–25 years. The available evidence is split across sources that measure different things: some track permitted units or structures, while others track projects or permit records.  ￼

The best statewide historical backbone is the U.S. Census Building Permits Survey, because it provides long-run data and breaks residential permitting out by structure type: 1 unit, 2 units, 3–4 units, and 5+ units. That is very close to the “scale spectrum” you want, but it is not the same as a true project-size distribution. It is best understood as a statewide historical proxy for development scale.  ￼

For true project-level information, Vermont’s Act 250 and related permit systems are more promising, especially because the state maintains a geospatial Act 250 permits layer linked to a searchable project database. Act 250 is especially relevant for larger residential projects, since Vermont law uses a 10-or-more-units threshold in a key residential trigger.  ￼

For smaller projects, statewide permit systems tied to wastewater/water supply may be important because they often capture development activity that will not show up as clearly in Act 250. Vermont provides a searchable Wastewater Regional Office project database for permit documents and plans.  ￼

There are also more recent statewide efforts to map and summarize actual housing development. Vermont’s DHCD Housing Development Dashboard is explicitly built from sources including E911 and Regional Planning Commissions, and it is meant to support place-based housing tracking. It is recent and methodologically evolving, so it is better viewed as a recent-period validation or supplemental geospatial source than as the full historical backbone.  ￼

# Potential sources and what they are good for

1) U.S. Census Building Permits Survey / HousingData building permits

This is the strongest source for a statewide historical baseline. It should be the starting point for understanding the long-run mix of 1-unit, 2-unit, 3–4-unit, and 5+ residential permitting in Vermont. HousingData provides a Vermont-facing interface and explicitly allows download of the underlying data from Tableau.  ￼

Best use: statewide trendline and broad scale buckets.
Main limitation: not a true project-level file, and the upper end is collapsed into 5+.  ￼

2) Act 250 geodata + Act 250 database

This is the strongest statewide lead for project-level, geospatially anchored information on larger developments. The geodata layer includes permit locations since 1970 and links to the Act 250 database and associated documents.  ￼

Best use: identifying and mapping larger residential projects; recovering actual unit counts from project records; comparing the upper tail of development scale across regions.
Main limitation: it is biased toward larger projects and will not fully represent the small-project universe. Vermont’s residential trigger is tied to 10 or more units in an important part of the law.  ￼

3) Wastewater Regional Office Permit Search

This appears to be one of the better statewide sources for smaller and more dispersed residential development activity. It is a searchable database of documents and plans associated with permits issued by Vermont’s regional offices.  ￼

Best use: supplementing the lower end of the scale spectrum, especially where Act 250 undercaptures activity.
Main limitation: it is a records system, not an immediately analysis-ready statewide table.  ￼

4) DHCD Housing Development Dashboard

This is a useful recent-period geospatial cross-check. HousingData states that it draws on E911, Regional Planning Commissions, and other sources, and that the methodology is still evolving.  ￼

Best use: recent housing production patterns by place; sanity-checking where development is happening; supporting a spatial comparison across regions or localities.
Main limitation: recent and evolving, not a 20–25 year historical project archive.  ￼

5) Stormwater permits

Vermont’s stormwater permits layer is downloadable in CSV and geospatial formats and includes issued permits from the Stormwater Management Program.  ￼

Best use: a supplementary spatial layer for larger site development and subdivision-type activity.
Main limitation: not a housing-specific source and likely incomplete as a standalone residential development dataset.  ￼

6) Affordable housing / development pipeline sources

HousingData’s affordable construction pipeline includes projects funded through VHFA, VHCB, or DHCD and gives a cleaner project-level subset for recent multifamily and subsidized development.  ￼

Best use: a cleaner recent subset of larger residential projects; cross-checking project counts and locations.
Main limitation: only a subset of the market, not statewide all-tenure development.  ￼

7) Regional and municipal housing / permit dashboards

Some regional planning bodies and municipalities maintain more detailed housing or permit tracking. For example, the Northwest Regional Planning Commission has a housing dashboard showing the location of units built since 2020 based on municipal building permits.  ￼

Best use: local or regional depth in the areas where development is concentrated; improving the spatial picture.
Main limitation: fragmented coverage and inconsistent methods across places.  ￼

# Brief research plan

Start with the Building Permits Survey / HousingData as the statewide historical frame. That gives a clean baseline for how Vermont’s residential permitting has been distributed across small versus larger structure types over time.  ￼

Then use Act 250 as the main source for project-level and geospatial information on larger developments, since it is both statewide and spatially anchored. That should make it possible to compare where the larger-project tail is concentrated.  ￼

Use wastewater permits to fill in some of the smaller-project landscape, especially in places where local development may not surface clearly through Act 250.  ￼

Use the DHCD dashboard, stormwater permits, and selected regional/municipal permit datasets as validation and enrichment layers, especially for the spatial dimension. These sources are most useful for comparing project-size patterns across towns, regions, or other geographic slices of the state.  ￼

The likely end product is not one perfect master file, but a layered evidence base: a statewide historical trend source, a project-level large-development source, and a set of supplemental geospatial sources that help compare how the size mix differs across Vermont’s geographies.  ￼

If useful, I can condense this one more step into a one-page memo format.
