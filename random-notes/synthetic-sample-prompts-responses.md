Data Collection Queries for Synthetic Data Calibration

Run these in order. Each section targets a specific assumption in fixtures.py.

1. Overall Counts (validate ratios)

// Node counts by label
MATCH (n) WITH labels(n)[0] AS label, count(\*) AS cnt
RETURN label, cnt ORDER BY cnt DESC;

// Relationship counts by type
MATCH ()-[r]->() WITH type(r) AS relType, count(\*) AS cnt
RETURN relType, cnt ORDER BY cnt DESC;

// Overall ratio
MATCH (n) WITH count(n) AS nodes
MATCH ()-[r]->() WITH nodes, count(r) AS rels
RETURN nodes, rels, round(toFloat(rels)/nodes * 100) / 100 AS rels_per_node;

2. BY relationship fan-out (releases per artist)

// Distribution: how many releases does each artist have?
MATCH (a:Artist)\<-[:BY]-(r:Release)
WITH a, count(r) AS releases
RETURN
min(releases) AS min_releases,
max(releases) AS max_releases,
avg(releases) AS avg_releases,
percentileCont(releases, 0.5) AS p50,
percentileCont(releases, 0.9) AS p90,
percentileCont(releases, 0.95) AS p95,
percentileCont(releases, 0.99) AS p99;

// Bucket histogram (power-law check)
MATCH (a:Artist)\<-[:BY]-(r:Release)
WITH a, count(r) AS releases
RETURN
CASE
WHEN releases = 1 THEN '1'
WHEN releases \<= 5 THEN '2-5'
WHEN releases \<= 10 THEN '6-10'
WHEN releases \<= 50 THEN '11-50'
WHEN releases \<= 100 THEN '51-100'
WHEN releases \<= 500 THEN '101-500'
ELSE '500+'
END AS bucket,
count(\*) AS artist_count
ORDER BY artist_count DESC;

3. Artists per release (reverse fan-out)

MATCH (r:Release)-[:BY]->(a:Artist)
WITH r, count(a) AS artists
RETURN
min(artists) AS min_artists,
max(artists) AS max_artists,
avg(artists) AS avg_artists,
percentileCont(artists, 0.5) AS p50,
percentileCont(artists, 0.9) AS p90,
percentileCont(artists, 0.95) AS p95,
percentileCont(artists, 0.99) AS p99;

4. Labels per release (ON fan-out)

MATCH (r:Release)-[:ON]->(l:Label)
WITH r, count(l) AS labels
RETURN
min(labels) AS min_labels,
max(labels) AS max_labels,
avg(labels) AS avg_labels,
percentileCont(labels, 0.5) AS p50,
percentileCont(labels, 0.9) AS p90,
percentileCont(labels, 0.95) AS p95;

5. DERIVED_FROM coverage (what % of releases have a master?)

MATCH (r:Release)
OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)
WITH count(r) AS total, count(m) AS with_master
RETURN total, with_master,
round(toFloat(with_master) / total * 10000) / 100 AS pct_with_master;

6. Releases per master

MATCH (m:Master)\<-[:DERIVED_FROM]-(r:Release)
WITH m, count(r) AS releases
RETURN
min(releases) AS min_releases,
max(releases) AS max_releases,
avg(releases) AS avg_releases,
percentileCont(releases, 0.5) AS p50,
percentileCont(releases, 0.9) AS p90,
percentileCont(releases, 0.95) AS p95,
percentileCont(releases, 0.99) AS p99;

7. Genre and Style distributions

// How many genres per release?
MATCH (r:Release)-[:IS]->(g:Genre)
WITH r, count(g) AS genres
RETURN
min(genres) AS min_genres,
max(genres) AS max_genres,
avg(genres) AS avg_genres,
percentileCont(genres, 0.5) AS p50,
percentileCont(genres, 0.9) AS p90;

// How many styles per release?
MATCH (r:Release)-[:IS]->(s:Style)
WITH r, count(s) AS styles
RETURN
min(styles) AS min_styles,
max(styles) AS max_styles,
avg(styles) AS avg_styles,
percentileCont(styles, 0.5) AS p50,
percentileCont(styles, 0.9) AS p90;

// Total genre and style node counts
MATCH (g:Genre) WITH count(g) AS genres
MATCH (s:Style) WITH genres, count(s) AS styles
RETURN genres, styles;

// Top 20 genres by release count
MATCH (r:Release)-[:IS]->(g:Genre)
RETURN g.name AS genre, count(r) AS releases
ORDER BY releases DESC LIMIT 20;

// Top 30 styles by release count
MATCH (r:Release)-[:IS]->(s:Style)
RETURN s.name AS style, count(r) AS releases
ORDER BY releases DESC LIMIT 30;

// What % of releases have NO genre? No style?
MATCH (r:Release)
OPTIONAL MATCH (r)-[:IS]->(g:Genre)
OPTIONAL MATCH (r)-[:IS]->(s:Style)
WITH count(r) AS total,
sum(CASE WHEN g IS NULL THEN 1 ELSE 0 END) AS no_genre,
sum(CASE WHEN s IS NULL THEN 1 ELSE 0 END) AS no_style
RETURN total, no_genre, no_style,
round(toFloat(no_genre)/total * 10000)/100 AS pct_no_genre,
round(toFloat(no_style)/total * 10000)/100 AS pct_no_style;

8. MEMBER_OF (band memberships)

// How many artists participate in MEMBER_OF?
MATCH (a:Artist)-[:MEMBER_OF]->(b:Artist)
WITH count(DISTINCT a) AS members, count(DISTINCT b) AS bands
MATCH (all:Artist)
WITH members, bands, count(all) AS total_artists
RETURN members, bands, total_artists,
round(toFloat(members)/total_artists * 10000)/100 AS pct_members,
round(toFloat(bands)/total_artists * 10000)/100 AS pct_bands;

// Members per band distribution
MATCH (a:Artist)-[:MEMBER_OF]->(b:Artist)
WITH b, count(a) AS members
RETURN
min(members) AS min_members,
max(members) AS max_members,
avg(members) AS avg_members,
percentileCont(members, 0.5) AS p50,
percentileCont(members, 0.9) AS p90;

9. ALIAS_OF

MATCH (a:Artist)-[:ALIAS_OF]->(b:Artist)
WITH count(DISTINCT a) + count(DISTINCT b) AS artists_with_aliases
MATCH (all:Artist)
WITH artists_with_aliases, count(all) AS total
RETURN artists_with_aliases, total,
round(toFloat(artists_with_aliases)/total * 10000)/100 AS pct_with_aliases;

10. SUBLABEL_OF

MATCH (child:Label)-[:SUBLABEL_OF]->(parent:Label)
WITH count(DISTINCT child) AS sublabels
MATCH (all:Label)
WITH sublabels, count(all) AS total
RETURN sublabels, total,
round(toFloat(sublabels)/total * 10000)/100 AS pct_sublabels;

// Children per parent label
MATCH (child:Label)-[:SUBLABEL_OF]->(parent:Label)
WITH parent, count(child) AS children
RETURN
min(children) AS min_children,
max(children) AS max_children,
avg(children) AS avg_children,
percentileCont(children, 0.5) AS p50,
percentileCont(children, 0.9) AS p90;

11. Year distribution

// Release year distribution by decade
MATCH (r:Release) WHERE r.year > 0
WITH
CASE
WHEN r.year < 1960 THEN 'pre-1960'
WHEN r.year < 1970 THEN '1960s'
WHEN r.year < 1980 THEN '1970s'
WHEN r.year < 1990 THEN '1980s'
WHEN r.year < 2000 THEN '1990s'
WHEN r.year < 2010 THEN '2000s'
WHEN r.year < 2020 THEN '2010s'
ELSE '2020s'
END AS decade, count(\*) AS cnt
RETURN decade, cnt ORDER BY decade;

// What % of releases have year=0 or null?
MATCH (r:Release)
WITH count(r) AS total,
sum(CASE WHEN r.year IS NULL OR r.year = 0 THEN 1 ELSE 0 END) AS no_year
RETURN total, no_year,
round(toFloat(no_year)/total * 10000)/100 AS pct_no_year;

12. Property shape validation

// Name length distribution (artists)
MATCH (a:Artist) WHERE a.name IS NOT NULL
WITH size(a.name) AS len
RETURN min(len) AS min_len, max(len) AS max_len, avg(len) AS avg_len,
percentileCont(len, 0.5) AS p50, percentileCont(len, 0.99) AS p99;

// Title length distribution (releases)
MATCH (r:Release) WHERE r.title IS NOT NULL
WITH size(r.title) AS len
RETURN min(len) AS min_len, max(len) AS max_len, avg(len) AS avg_len,
percentileCont(len, 0.5) AS p50, percentileCont(len, 0.99) AS p99;

// Formats array size (releases)
MATCH (r:Release) WHERE r.formats IS NOT NULL
WITH size(r.formats) AS fmt_count
RETURN min(fmt_count) AS min_fmts, max(fmt_count) AS max_fmts, avg(fmt_count) AS avg_fmts,
percentileCont(fmt_count, 0.5) AS p50, percentileCont(fmt_count, 0.9) AS p90;

13. Isolated nodes (no relationships)

// Artists with no BY relationships (orphan artists)
MATCH (a:Artist) WHERE NOT exists((a)\<-[:BY]-()) AND NOT exists((a)-[:MEMBER_OF]->()) AND NOT exists(()-[:MEMBER_OF]->(a))
WITH count(a) AS orphans
MATCH (all:Artist) WITH orphans, count(all) AS total
RETURN orphans, total, round(toFloat(orphans)/total * 10000)/100 AS pct_orphan_artists;

// Labels with no ON relationships
MATCH (l:Label) WHERE NOT exists(()-[:ON]->(l)) AND NOT exists((l)-[:SUBLABEL_OF]->())
WITH count(l) AS orphans
MATCH (all:Label) WITH orphans, count(all) AS total
RETURN orphans, total, round(toFloat(orphans)/total * 10000)/100 AS pct_orphan_labels;

______________________________________________________________________

## OUTPUT

______________________________________________________________________

Complete Results

1. Overall Counts

┌─────────┬────────────┐
│ Label │ Count │
├─────────┼────────────┤
│ Release │ 18,954,226 │
├─────────┼────────────┤
│ Artist │ 9,974,217 │
├─────────┼────────────┤
│ Master │ 2,531,018 │
├─────────┼────────────┤
│ Label │ 2,363,420 │
├─────────┼────────────┤
│ Style │ 757 │
├─────────┼────────────┤
│ Genre │ 16 │
├─────────┼────────────┤
│ User │ 1 │
└─────────┴────────────┘

┌──────────────┬────────────┐
│ Relationship │ Count │
├──────────────┼────────────┤
│ IS │ 61,217,777 │
├──────────────┼────────────┤
│ BY │ 26,043,980 │
├──────────────┼────────────┤
│ ON │ 20,655,445 │
├──────────────┼────────────┤
│ DERIVED_FROM │ 18,970,893 │
├──────────────┼────────────┤
│ ALIAS_OF │ 4,872,723 │
├──────────────┼────────────┤
│ MEMBER_OF │ 2,313,450 │
├──────────────┼────────────┤
│ SUBLABEL_OF │ 277,678 │
├──────────────┼────────────┤
│ PART_OF │ 10,412 │
├──────────────┼────────────┤
│ COLLECTED │ 2,986 │
├──────────────┼────────────┤
│ WANTS │ 711 │
└──────────────┴────────────┘

Totals: 33,823,655 nodes, 134,366,055 relationships, 3.97 rels/node

2. BY Fan-Out (Releases per Artist)

┌──────┬───────────┐
│ Stat │ Value │
├──────┼───────────┤
│ min │ 1 │
├──────┼───────────┤
│ max │ 1,320,907 │
├──────┼───────────┤
│ avg │ 8.17 │
├──────┼───────────┤
│ p50 │ 2 │
├──────┼───────────┤
│ p90 │ 10 │
├──────┼───────────┤
│ p95 │ 20 │
├──────┼───────────┤
│ p99 │ 86 │
└──────┴───────────┘

Histogram (power-law confirmed):

┌─────────┬──────────────┐
│ Bucket │ Artist Count │
├─────────┼──────────────┤
│ 1 │ 1,349,818 │
├─────────┼──────────────┤
│ 2-5 │ 949,298 │
├─────────┼──────────────┤
│ 6-10 │ 233,040 │
├─────────┼──────────────┤
│ 11-50 │ 224,405 │
├─────────┼──────────────┤
│ 51-100 │ 28,000 │
├─────────┼──────────────┤
│ 101-500 │ 19,952 │
├─────────┼──────────────┤
│ 500+ │ 3,418 │
└─────────┴──────────────┘

3. Artists per Release (reverse BY)

┌──────┬───────┐
│ Stat │ Value │
├──────┼───────┤
│ min │ 1 │
├──────┼───────┤
│ max │ 49 │
├──────┼───────┤
│ avg │ 1.21 │
├──────┼───────┤
│ p50 │ 1 │
├──────┼───────┤
│ p90 │ 2 │
├──────┼───────┤
│ p95 │ 2 │
├──────┼───────┤
│ p99 │ 4 │
└──────┴───────┘

4. Labels per Release (ON)

┌──────┬───────┐
│ Stat │ Value │
├──────┼───────┤
│ min │ 1 │
├──────┼───────┤
│ max │ 100 │
├──────┼───────┤
│ avg │ 1.09 │
├──────┼───────┤
│ p50 │ 1 │
├──────┼───────┤
│ p90 │ 1 │
├──────┼───────┤
│ p95 │ 2 │
└──────┴───────┘

5. DERIVED_FROM Coverage

- Total releases with DERIVED_FROM: 18,970,893 (but total releases = 18,954,226)
- 100% of DERIVED_FROM targets exist as Masters
- Note: The count difference suggests some releases have multiple DERIVED_FROM edges

6. Releases per Master

┌──────┬───────────┐
│ Stat │ Value │
├──────┼───────────┤
│ min │ 1 │
├──────┼───────────┤
│ max │ 7,897,514 │
├──────┼───────────┤
│ avg │ 7.50 │
├──────┼───────────┤
│ p50 │ 2 │
├──────┼───────────┤
│ p90 │ 7 │
├──────┼───────────┤
│ p95 │ 12 │
├──────┼───────────┤
│ p99 │ 32 │
└──────┴───────────┘

7. Genre & Style Distributions

Genres per release: min=1, max=15, avg=1.33, p50=1, p90=2
Styles per release: min=1, max=90, avg=1.79, p50=1, p90=3

Totals: 16 genres, 757 styles

Top 10 Genres:

┌────────────────────────┬───────────┐
│ Genre │ Releases │
├────────────────────────┼───────────┤
│ Rock │ 6,176,795 │
├────────────────────────┼───────────┤
│ Electronic │ 4,871,317 │
├────────────────────────┼───────────┤
│ Pop │ 3,845,954 │
├────────────────────────┼───────────┤
│ Folk, World, & Country │ 2,481,469 │
├────────────────────────┼───────────┤
│ Jazz │ 1,514,081 │
├────────────────────────┼───────────┤
│ Funk / Soul │ 1,293,154 │
├────────────────────────┼───────────┤
│ Classical │ 1,197,373 │
├────────────────────────┼───────────┤
│ Hip Hop │ 963,663 │
├────────────────────────┼───────────┤
│ Latin │ 845,839 │
├────────────────────────┼───────────┤
│ Stage & Screen │ 580,707 │
└────────────────────────┴───────────┘

Top 10 Styles:

┌──────────────────┬──────────┐
│ Style │ Releases │
├──────────────────┼──────────┤
│ Pop Rock │ 928,289 │
├──────────────────┼──────────┤
│ House │ 704,929 │
├──────────────────┼──────────┤
│ Vocal │ 638,048 │
├──────────────────┼──────────┤
│ Experimental │ 624,930 │
├──────────────────┼──────────┤
│ Punk │ 574,730 │
├──────────────────┼──────────┤
│ Alternative Rock │ 540,982 │
├──────────────────┼──────────┤
│ Synth-pop │ 526,145 │
├──────────────────┼──────────┤
│ Techno │ 488,428 │
├──────────────────┼──────────┤
│ Indie Rock │ 448,987 │
├──────────────────┼──────────┤
│ Ambient │ 442,348 │
└──────────────────┴──────────┘

Missing coverage: ~0% no genre, 8.15% no style

8. MEMBER_OF

┌─────────┬───────────┬──────────────┐
│ Metric │ Count │ % of Artists │
├─────────┼───────────┼──────────────┤
│ Members │ 1,334,519 │ 13.38% │
├─────────┼───────────┼──────────────┤
│ Bands │ 653,565 │ 6.55% │
└─────────┴───────────┴──────────────┘

Members per band: min=1, max=804, avg=3.54, p50=3, p90=6

9. ALIAS_OF

- Alias sources: 640,211
- Alias targets: 638,386
- Combined unique: ~1,278,597 artists with aliases (~12.82% of all artists)

10. SUBLABEL_OF

- Sublabels: 277,502 out of 2,363,420 total (11.74%)
- Children per parent: min=1, max=140,330, avg=4.47, p50=1, p90=4

11. Year Distribution

Note: year property exists on Master nodes only, not Release nodes.

┌──────────┬─────────┐
│ Decade │ Count │
├──────────┼─────────┤
│ pre-1960 │ 119,744 │
├──────────┼─────────┤
│ 1960s │ 175,497 │
├──────────┼─────────┤
│ 1970s │ 233,656 │
├──────────┼─────────┤
│ 1980s │ 279,104 │
├──────────┼─────────┤
│ 1990s │ 422,213 │
├──────────┼─────────┤
│ 2000s │ 423,540 │
├──────────┼─────────┤
│ 2010s │ 477,583 │
├──────────┼─────────┤
│ 2020s │ 229,390 │
└──────────┴─────────┘

Masters with no year: 170,291 (6.73%)

12. Property Shape

Release properties: id, sha256, title (no year, no formats)
Master properties: id, sha256, title, year
Artist properties: id, name, releases_url, resource_url, sha256
Label properties: id, name, sha256

Artist name length: min=1, max=255, avg=13.77, p50=13, p99=34
Release title length: min=1, max=255, avg=20.96, p50=17, p99=73
Formats: Not present on Release nodes (NULL)

13. Isolated Nodes

┌───────────────────────────────────┬───────────┬───────────┬────────┐
│ Node Type │ Orphaned │ Total │ % │
├───────────────────────────────────┼───────────┼───────────┼────────┤
│ Artists (no relationships at all) │ 5,766,339 │ 9,974,217 │ 57.81% │
├───────────────────────────────────┼───────────┼───────────┼────────┤
│ Artists with BY edges │ 2,807,934 │ 9,974,217 │ 28.15% │
├───────────────────────────────────┼───────────┼───────────┼────────┤
│ Labels (no relationships at all) │ 929,522 │ 2,363,420 │ 39.33% │
└───────────────────────────────────┴───────────┴───────────┴────────┘

______________________________________________________________________

Key takeaways for fixtures.py calibration:

- Very high orphan rate: ~58% of artists and ~39% of labels have zero relationships
- Power-law confirmed on BY fan-out (heavy tail, median=2)
- Year lives on Master, not Release — and 6.73% of masters lack it
- No formats property exists on Release nodes
- ~8% of releases have no style; genre coverage is near-complete
- rels_per_node = 3.97 overall
- DERIVED_FROM is nearly 1:1 with releases (100% coverage)

Good catch. Here's the corrected query for section 12 — the original likely failed on r.formats (doesn't exist) and may have had issues with properties that aren't on the expected node types:

12. Property Shape Validation (corrected)

// Artist name length distribution
MATCH (a:Artist) WHERE a.name IS NOT NULL
WITH size(a.name) AS len
RETURN 'artist_name' AS property,
min(len) AS min_len, max(len) AS max_len, avg(len) AS avg_len,
percentileCont(len, 0.5) AS p50, percentileCont(len, 0.99) AS p99;

// Release title length distribution
MATCH (r:Release) WHERE r.title IS NOT NULL
WITH size(r.title) AS len
RETURN 'release_title' AS property,
min(len) AS min_len, max(len) AS max_len, avg(len) AS avg_len,
percentileCont(len, 0.5) AS p50, percentileCont(len, 0.99) AS p99;

// Master title length distribution
MATCH (m:Master) WHERE m.title IS NOT NULL
WITH size(m.title) AS len
RETURN 'master_title' AS property,
min(len) AS min_len, max(len) AS max_len, avg(len) AS avg_len,
percentileCont(len, 0.5) AS p50, percentileCont(len, 0.99) AS p99;

// Label name length distribution
MATCH (l:Label) WHERE l.name IS NOT NULL
WITH size(l.name) AS len
RETURN 'label_name' AS property,
min(len) AS min_len, max(len) AS max_len, avg(len) AS avg_len,
percentileCont(len, 0.5) AS p50, percentileCont(len, 0.99) AS p99;

// List all property keys per label (verify actual schema)
CALL db.schema.nodeTypeProperties()
YIELD nodeLabels, propertyName, propertyTypes
RETURN nodeLabels, propertyName, propertyTypes
ORDER BY nodeLabels, propertyName;

// Release year distribution (if year now exists on Release)
MATCH (r:Release) WHERE r.year IS NOT NULL AND r.year > 0
WITH count(r) AS has_year
MATCH (r2:Release)
WITH has_year, count(r2) AS total
RETURN has_year, total,
round(toFloat(has_year)/total * 10000)/100 AS pct_with_year;

The db.schema.nodeTypeProperties() call will give you the definitive schema — paste that back and I'll reconcile the fixtures with the actual property set on each node type.
