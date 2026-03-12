# Future Project Ideas

Brainstormed 2026-03-11. Synthesizes open GitHub issues, CSV feature ideas, and new concepts.

## Open GitHub Issues (as of 2026-03-11)

| # | Title | Type |
|---|-------|------|
| 104 | Admin Dashboard — operational visibility and historical metrics | enhancement |
| 103 | Full-Text Search — unified cross-entity search with facets | enhancement |
| 102 | Webhook / Event Stream — real-time notifications for integrations | enhancement |
| 101 | Label DNA — fingerprint and compare record labels | enhancement |
| 100 | Collection Timeline — visualize music taste evolution | enhancement |
| 99 | Collaboration Network — artist connection graph and centrality | enhancement |
| 98 | Export & Backup — collection data portability | enhancement |
| 97 | refactor(extractor): introduce traits for dependency injection to improve test coverage | enhancement |
| 86 | Notifier Service — watchlists and alerts for new music data | enhancement |
| 85 | Insights Service — precomputed analytics and music trends | enhancement |
| 84 | Expand Explore frontend — path visualisation, timeline, and collaboration heatmap | enhancement |
| 83 | MCP Server — expose the knowledge graph to AI assistants | enhancement |
| 82 | Recommender Service — graph-powered music discovery | enhancement |
| 74 | security(M3): enable Neo4j TLS for non-local deployments | security |
| 50 | feat(explore): release-centric exploration | enhancement |
| 49 | feat(explore): path finder — shortest path between two entities | enhancement |

## CSV Feature Ideas

| # | Feature | Value Proposition | Sketch of Implementation |
|---|---------|-------------------|--------------------------|
| 1 | Temporal "career timeline" visualisation | Shows an artist's activity over decades, highlighting gaps and peaks. | Add a new endpoint /api/timeline/{artist_id} that aggregates releases per year (PostgreSQL), then render a D3.js stacked area chart in the Explore UI. |
| 2 | Label-level market share dashboard | Gives insights into how dominant a label is in a genre or era. | Compute label-genre counts nightly (SQL aggregation) and store results in a materialised view; expose via /api/label-stats and display with Plotly.js bar charts. |
| 3 | "What-If" graph simulation sandbox | Lets users experiment by adding hypothetical releases or collaborations and instantly seeing graph impact. | Provide a sandbox API that writes temporary nodes/edges to an in-memory Neo4j instance (or uses Neo4j's apoc.create.node with a short TTL). UI shows a live force-directed graph. |
| 4 | Audio-preview integration (YouTube / SoundCloud embeds) | Enriches release pages with short listening clips. | Store a preview_url (YouTube ID or SoundCloud link) in the Release node; UI renders an iframe when a user clicks a "Play preview" button. |
| 5 | Entity-level change-log audit trail | Enables tracking of edits, imports, and deletions for compliance and debugging. | Write every mutation (INSERT/UPDATE/DELETE) to a change_log table in PostgreSQL (JSONB payload, timestamp, user). Provide /api/audit/{entity_type}/{id} endpoint. |
| 6 | Multi-language metadata support | Serves non-English users with translated titles, genres, and descriptions. | Extend JSONB schema with a translations object ({en: {...}, es: {...}}). Add a language selector in the UI that swaps displayed fields via Alpine.js. |
| 7 | Community-voted "canonical" artist/label aliases | Improves data quality by surfacing the most accepted name for ambiguous entities. | Create a Vote node type; users can up-vote an alias. Periodically compute the highest-voted alias and set it as the primary name property. |
| 8 | Graph-based "influence chain" explorer | Shows how a genre or style propagated through artists and releases over time. | Use Neo4j's apoc.path.expandConfig to traverse INFLUENCED_BY relationships (to be added) with a time filter, then visualise the chain as a timeline graph. |
| 9 | Export-as-CSV/JSON bulk download | Allows researchers to pull subsets of data for offline analysis. | Add a streaming endpoint /api/export?type=release&genre=Jazz&year_start=1970&year_end=1980 that streams rows as CSV using PostgreSQL's COPY TO STDOUT. |
| 10 | Dynamic "heat-map" of release density by country | Gives a geographic view of where most releases originate. | Pre-aggregate counts per country nightly, store in Redis, and render a Leaflet.js choropleth map in the UI. |
| 11 | Custom user-defined "smart playlists" | Users can define rule-based playlists (e.g., "All 1970s progressive rock releases on vinyl"). | Store playlist rules as JSON; a background worker evaluates rules against PostgreSQL data and updates a Playlist node with CONTAINS edges. UI shows playlist contents and allows export to CSV. |
| 12 | Integration with MusicBrainz "artist-relations" | Adds richer relationship types (e.g., "producer", "engineer"). | Periodically ingest MusicBrainz XML, match on Discogs IDs, and create new relationship types (PRODUCED_BY, ENGINEERED_BY). |
| 13 | Rate-limited public GraphQL gateway | Gives developers a flexible query interface while protecting backend resources. | Deploy a GraphQL server (e.g., Ariadne) that resolves to Neo4j/PostgreSQL, enforce per-API-key quotas stored in Redis. |
| 14 | "Lost-and-found" orphan record detector | Finds records that exist in one store but not the other (e.g., a Release in Neo4j but missing in PostgreSQL). | Run a nightly job that compares IDs between the two databases, writes discrepancies to an orphan table, and surfaces them via /api/orphans. |
| 15 | Dark-mode UI toggle with Tailwind | Improves accessibility and modern look for the Explore frontend. | **DONE** — Implemented 2026-03-11 for Dashboard. |

## Overlaps Between CSV and Open Issues

| CSV | Overlapping Issue(s) | Notes |
|-----|---------------------|-------|
| #1 Career timeline | #84 (Explore frontend), #100 (Collection Timeline) | Both cover temporal visualization |
| #2 Label market share | #101 (Label DNA), #85 (Insights Service) | Label DNA is a superset |
| #5 Change-log audit | #104 (Admin Dashboard) | Admin dashboard scope includes this |
| #9 Export CSV/JSON | #98 (Export & Backup) | Near-identical |
| #15 Dark mode | -- | Already implemented |

## Brainstormed Ideas (New)

### 1. "Six Degrees of Vinyl" — Make the Graph the Star

The Neo4j knowledge graph is the most unique asset, but the Explore UI currently only shows one-hop neighbors. The biggest unlock is making multi-hop traversal intuitive.

- **Path finder** (#49) — shortest path between any two entities. "How is Miles Davis connected to Kraftwerk?" This is the feature people would share.
- **Influence chain explorer** (CSV #8) — would require adding INFLUENCED_BY edges (possibly via MusicBrainz #12), but the payoff is enormous. Visualize how punk evolved from proto-punk across labels and cities.
- **Collaboration network** (#99) — compute centrality scores to find the "Kevin Bacons" of music. Who's the most-connected session musician? Which label is the hub of a genre?

This cluster turns the graph from "look up an artist" into "discover hidden connections."

### 2. "Label DNA" — Analytical Fingerprinting

Combines CSV #2 (label market share) and issue #101 (Label DNA):

- Compute a label's "fingerprint" — genre/style distribution, active decades, artist roster diversity, release cadence
- **Label similarity search** — "labels that feel like ECM Records"
- **Era analysis** — how a label's sound shifted decade-to-decade
- Visualization as a radar chart or stacked timeline

Answers questions like: "What label should I explore if I like the Blue Note catalog from the 60s?"

### 3. MCP Server — Let AI Assistants Query the Graph

Issue #83. An MCP server would let Claude (and other AI assistants) query the knowledge graph directly:

- "Find me jazz labels active in the 1960s that released fewer than 50 records"
- "What's the shortest path between Brian Eno and J Dilla?"
- "Show me the genre distribution of my collection"

Turns Discogsography into an AI-queryable music encyclopedia. Relatively contained implementation (MCP tools wrapping existing API endpoints), massive reach.

### 4. Full-Text Search (#103) — Table Stakes

Cross-entity search with faceted filtering:

- Search "Blue" -> Blue Note label, Blueprint artist, Blue Monday release
- Faceted filtering by type, genre, decade, label
- Relevance ranking via PostgreSQL full-text search

Less glamorous but the feature users will try first and judge the platform by.

### 5. "What-If" Sandbox (CSV #3) — Creative Wildcard

A sandbox where you can:

- Add a hypothetical release ("What if Radiohead released on Warp Records?")
- See how it changes graph metrics (centrality, shortest paths, genre overlaps)
- Explore alternate music history

Implementation via an ephemeral Neo4j session or in-memory overlay. The kind of feature that gets write-ups — playful, educational, shows off the graph uniquely.

### 6. "Vinyl Archaeology" — Time-Travel Through the Graph (NEW)

Not in CSV or issues. The graph already has year on releases. What if you could:

- Set a "time slider" to 1975 and see the graph as it existed then — only releases, artists, and labels active by that year
- Watch genres emerge and evolve as you scrub forward through decades
- See which labels pioneered a genre vs. which followed

Uses existing data (no new ingestion), produces a visceral "wow" moment. Implementation: a year filter parameter on explore/expand endpoints + a timeline scrubber in the UI.

### 7. "Taste Fingerprint" — Personal Analytics (NEW)

Collection sync already exists. The data is there. Missing the "Spotify Wrapped for vinyl collectors" moment:

- Genre/decade heat map of your collection
- Your "most obscure" and "most mainstream" records (based on how many other users have them)
- "Taste drift" over time — how your collecting has evolved
- "Blind spots" — genres or eras you've never explored
- Shareable taste card (SVG/image export)

Turns the personal collection from a list into a story.

## Suggested Priority Order

1. **Full-text search** (#103) — table stakes, unblocks everything else
2. **Path finder** (#49) — high-impact, contained scope, showcases the graph
3. **MCP server** (#83) — high leverage, moderate effort, unique positioning
4. **Taste fingerprint** (new) — uses existing data, creates shareable moments

## Deprioritized Ideas

| CSV # | Feature | Reason |
|-------|---------|--------|
| 4 | Audio previews | Legal complexity, external dependency for marginal value |
| 6 | Multi-language | Discogs data is predominantly English; premature |
| 7 | Community voting | Requires critical mass of users that doesn't exist yet |
| 10 | Country heat map | Discogs release data doesn't reliably have country of origin (often pressing country, not origin) |
| 11 | Smart playlists | Without audio integration, playlists are just filtered lists |
| 13 | GraphQL gateway | High engineering cost, REST API + MCP server covers the same ground |
| 14 | Orphan detector | Useful for ops but not user-facing; simple cron job rather than a feature |
