# ArangoDB — Multi-Model Database

## Overview

[ArangoDB](https://github.com/arangodb/arangodb) is a native multi-model database combining document (JSON), graph, and key-value models in a single engine. It uses its own query language, AQL (ArangoDB Query Language), instead of Cypher.

- **Repository:** [arangodb/arangodb](https://github.com/arangodb/arangodb) (14.1k stars)
- **License:** Apache 2.0 (Community Edition)
- **Latest activity:** Active development (52k+ commits)
- **Python driver:** `python-arango` v8.3.0 (MIT license), async via `python-arango-async`
- **Query language:** AQL (not Cypher)

## Why This Is Interesting for Discogsography

- **Multi-model consolidation** — could replace both Neo4j (graph) and PostgreSQL (documents/analytics) with a single database
- **AQL is powerful** — supports graph traversals, document queries, full-text search, joins, and aggregation in one language
- **Strong community** — 14.1k stars, 131 contributors, very active development
- **Apache 2.0 license** — permissive, no restrictions
- **Horizontal scaling** — Community Edition includes clustering and replication

## Critical Caveat: Full Query Rewrite Required

ArangoDB does **not** use Cypher. Every query in the codebase must be rewritten in AQL. This is the highest migration cost of all candidates.

### AQL vs Cypher — Side-by-Side

#### Basic Node Lookup

```cypher
-- Cypher (current)
MATCH (a:Artist {id: $id})
RETURN a.id, a.name
```

```aql
-- AQL equivalent
FOR a IN artists
    FILTER a.id == @id
    RETURN { id: a.id, name: a.name }
```

#### Multi-Hop Traversal

```cypher
-- Cypher
MATCH (r:Release)-[:BY]->(a:Artist {name: $name}), (r)-[:ON]->(l:Label)
RETURN l.id AS id, l.name AS name, count(DISTINCT r) AS release_count
ORDER BY release_count DESC
SKIP $offset LIMIT $limit
```

```aql
-- AQL
FOR a IN artists
    FILTER a.name == @name
    FOR r IN INBOUND a release_by_artist
        FOR l IN OUTBOUND r release_on_label
            COLLECT label_id = l.id, label_name = l.name
            WITH COUNT INTO release_count
            SORT release_count DESC
            LIMIT @offset, @limit
            RETURN { id: label_id, name: label_name, release_count }
```

#### Batch MERGE (Upsert)

```cypher
-- Cypher
UNWIND $artists AS artist
MERGE (a:Artist {id: artist.id})
SET a.name = artist.name, a.sha256 = artist.sha256
```

```aql
-- AQL
FOR artist IN @artists
    UPSERT { id: artist.id }
    INSERT { id: artist.id, name: artist.name, sha256: artist.sha256 }
    UPDATE { name: artist.name, sha256: artist.sha256 }
    IN artists
```

#### User Collection with Relationships

```cypher
-- Cypher
MATCH (u:User {id: $user_id})-[c:COLLECTED]->(r:Release)
OPTIONAL MATCH (r)-[:BY]->(a:Artist)
OPTIONAL MATCH (r)-[:ON]->(l:Label)
WITH r, c, collect(DISTINCT a.name)[0] AS artist_name,
     collect(DISTINCT l.name)[0] AS label_name
RETURN r.id AS id, r.title AS title, r.year AS year,
       artist_name AS artist, label_name AS label,
       c.rating AS rating
ORDER BY c.date_added DESC
SKIP $offset LIMIT $limit
```

```aql
-- AQL
FOR u IN users
    FILTER u.id == @user_id
    FOR r, c IN OUTBOUND u user_collected
        LET artists = (
            FOR a IN OUTBOUND r release_by_artist
                RETURN a.name
        )
        LET labels = (
            FOR l IN OUTBOUND r release_on_label
                RETURN l.name
        )
        SORT c.date_added DESC
        LIMIT @offset, @limit
        RETURN {
            id: r.id, title: r.title, year: r.year,
            artist: FIRST(artists), label: FIRST(labels),
            rating: c.rating
        }
```

#### Fulltext Search

```cypher
-- Cypher
CALL db.index.fulltext.queryNodes('artist_name_fulltext', $query)
YIELD node, score
RETURN node.id AS id, node.name AS name, score
ORDER BY score DESC
LIMIT $limit
```

```aql
-- AQL (using ArangoSearch / SEARCH)
FOR a IN artist_search_view
    SEARCH ANALYZER(a.name IN TOKENS(@query, "text_en"), "text_en")
    SORT BM25(a) DESC
    LIMIT @limit
    RETURN { id: a.id, name: a.name, score: BM25(a) }
```

#### Trends Aggregation

```cypher
-- Cypher
MATCH (r:Release)-[:BY]->(a:Artist {name: $name})
WHERE r.year > 0
WITH r.year AS year, count(DISTINCT r) AS count
RETURN year, count
ORDER BY year
```

```aql
-- AQL
FOR a IN artists
    FILTER a.name == @name
    FOR r IN INBOUND a release_by_artist
        FILTER r.year > 0
        COLLECT year = r.year WITH COUNT INTO count
        SORT year
        RETURN { year, count }
```

## Data Model Differences

### Neo4j Property Graph → ArangoDB Document Collections + Edge Collections

```
Neo4j Nodes        → ArangoDB Document Collections
  :Artist          → artists (document collection)
  :Label           → labels (document collection)
  :Master          → masters (document collection)
  :Release         → releases (document collection)
  :Genre           → genres (document collection)
  :Style           → styles (document collection)
  :User            → users (document collection)

Neo4j Relationships → ArangoDB Edge Collections
  [:BY]            → release_by_artist (edge collection)
  [:ON]            → release_on_label (edge collection)
  [:DERIVED_FROM]  → release_derived_from_master (edge collection)
  [:IS] (genre)    → release_is_genre (edge collection)
  [:IS] (style)    → release_is_style (edge collection)
  [:MEMBER_OF]     → artist_member_of (edge collection)
  [:ALIAS_OF]      → artist_alias_of (edge collection)
  [:SUBLABEL_OF]   → label_sublabel_of (edge collection)
  [:PART_OF]       → style_part_of_genre (edge collection)
  [:COLLECTED]     → user_collected (edge collection)
  [:WANTS]         → user_wants (edge collection)
```

ArangoDB edges are full documents with `_from` and `_to` fields referencing document IDs, plus optional properties (rating, date_added, etc.).

### Graph Definition

```python
# Create the named graph
graph = db.create_graph("discogsography")
graph.create_edge_definition(
    edge_collection="release_by_artist",
    from_vertex_collections=["releases"],
    to_vertex_collections=["artists"],
)
# ... repeat for each relationship type
```

## Compatibility Analysis

### What Translates Cleanly

| Concept | Cypher | AQL | Effort |
|---------|--------|-----|--------|
| Node lookup by property | `MATCH (a:Artist {id: $id})` | `FOR a IN artists FILTER a.id == @id` | Low |
| Traversal | `(r)-[:BY]->(a)` | `FOR a IN OUTBOUND r release_by_artist` | Medium |
| Aggregation | `count(DISTINCT r)` | `COLLECT ... WITH COUNT INTO` | Medium |
| Pagination | `SKIP $offset LIMIT $limit` | `LIMIT @offset, @limit` | Low |
| Upsert | `MERGE ... SET` | `UPSERT ... INSERT ... UPDATE` | Low |
| Batch | `UNWIND $items AS item` | `FOR item IN @items` | Low |
| Conditional | `CASE WHEN ... END` | Ternary: `x > 0 ? x : null` | Low |
| Subqueries | `OPTIONAL MATCH` chain | `LET x = (FOR ...)` subquery | Medium |

### What Requires Significant Rework

| Area | Why | Effort |
|------|-----|--------|
| All ~50 Cypher queries | AQL is a completely different language | High |
| Fulltext search | ArangoSearch views replace fulltext indexes | Medium |
| Schema init | Document/edge collections + graph definition | Medium |
| Driver layer | `python-arango` replaces `neo4j` driver | Medium |
| Edge collections | One edge collection per relationship type (11 total) | Medium |
| Batch processor | `UPSERT` replaces `MERGE`; edge inserts change | Medium |

### Driver API

```python
from arango import ArangoClient

# Sync connection
client = ArangoClient(hosts="http://localhost:8529")
db = client.db("discogsography", username="root", password="discogsography")

# AQL query execution
cursor = db.aql.execute(
    "FOR a IN artists FILTER a.name == @name RETURN a",
    bind_vars={"name": "Radiohead"},
)
results = [doc for doc in cursor]

# Graph traversal
graph = db.graph("discogsography")
traversal = graph.traverse(
    start_vertex="artists/123",
    direction="outbound",
    edge_collections=["release_by_artist"],
    max_depth=2,
)

# Async (separate package)
# pip install python-arango-async
from arango_async import ArangoClient as AsyncArangoClient
```

## Performance Considerations

### Advantages

- **Multi-model queries** — traverse the graph AND query document fields AND do full-text search in a single AQL statement
- **ArangoSearch** — built-in full-text search powered by IResearch (Lucene-compatible). Creates "views" that combine multiple collections with BM25/TF-IDF ranking.
- **Smart indexing** — persistent indexes, hash indexes, fulltext indexes, geo indexes, TTL indexes all native
- **No JVM** — C++ implementation, lower memory overhead than Neo4j
- **Horizontal scaling** — Community Edition supports sharding and replication

### Concerns

- **Complete query rewrite** — highest migration cost of all candidates
- **Two Python packages** — sync (`python-arango`) and async (`python-arango-async`) are separate libraries
- **Graph traversal overhead** — multi-model databases historically trade some graph traversal speed for multi-model flexibility
- **Operational complexity** — learning curve for AQL, ArangoSearch views, edge collection design
- **Testing burden** — all existing Cypher-based tests must be rewritten

### What to Benchmark Specifically

In addition to the [shared workloads](shared-pre-work.md#workload-definitions) (adapted to AQL):

| Benchmark | Why It Matters for ArangoDB |
|-----------|---------------------------|
| UPSERT batch throughput | AQL UPSERT vs Neo4j MERGE — core write pattern |
| Edge creation throughput | Separate edge collection inserts vs Neo4j MERGE relationship |
| ArangoSearch latency | BM25-ranked full-text search vs Neo4j fulltext index |
| Multi-model query | Graph traversal + document filter + text search in one AQL query |
| Cross-collection traversal | 3+ hop traversal across multiple edge collections |
| Memory efficiency | C++ implementation may use less memory than Neo4j JVM |

### Multi-Model Query Example (Unique to ArangoDB)

This query type combines graph traversal, document filtering, and full-text search — only possible because ArangoDB is multi-model:

```aql
-- Find releases by artists matching a search term,
-- filtered by genre, enriched with label data
FOR artist IN artist_search_view
    SEARCH ANALYZER(artist.name IN TOKENS("radio", "text_en"), "text_en")
    SORT BM25(artist) DESC
    LIMIT 10
    FOR release IN INBOUND artist release_by_artist
        FILTER release.year >= 2000
        FOR genre_edge IN OUTBOUND release release_is_genre
            FILTER genre_edge.name == "Electronic"
            FOR label IN OUTBOUND release release_on_label
                RETURN DISTINCT {
                    artist: artist.name,
                    release: release.title,
                    year: release.year,
                    label: label.name,
                    score: BM25(artist)
                }
```

## Native Query Alternative: Full AQL + Driver API (No Cypher at All)

ArangoDB is the one candidate where the "native" approach is the **only** approach — there is no Cypher compatibility layer. Every query is written in AQL, and schema/index management uses the driver API. This means there are zero Cypher incompatibilities to work around, but the trade-off is a complete query rewrite.

### AQL Native Capabilities That Have No Cypher Equivalent

AQL has several features that are strictly more powerful than what Cypher offers:

#### 1. Subqueries (LET)

AQL subqueries are first-class and replace both COUNT {} subqueries and OPTIONAL MATCH chains:

```aql
-- Clean subquery syntax — no COUNT {} or OPTIONAL MATCH gymnastics
FOR a IN artists
    FILTER a.name == @name
    LET release_count = LENGTH(
        FOR r IN INBOUND a release_by_artist RETURN 1
    )
    LET label_count = LENGTH(
        FOR r IN INBOUND a release_by_artist
            FOR l IN OUTBOUND r release_on_label
                RETURN DISTINCT l._key
    )
    LET alias_count = LENGTH(
        FOR x IN OUTBOUND a artist_alias_of RETURN 1
    ) + LENGTH(
        FOR x IN OUTBOUND a artist_member_of RETURN 1
    ) + LENGTH(
        FOR x IN INBOUND a artist_member_of RETURN 1
    )
    RETURN { id: a.id, name: a.name, release_count, label_count, alias_count }
```

This is cleaner than Neo4j's COUNT {} and avoids the Memgraph/AGE/FalkorDB compatibility issues entirely.

#### 2. ArangoSearch (Built-in Full-Text + Semantic Search)

ArangoSearch uses "views" backed by the IResearch engine (Lucene-compatible):

```aql
-- Create an ArangoSearch view (via driver API)
db.create_arangosearch_view("artist_search", {
    "links": {
        "artists": {
            "analyzers": ["text_en"],
            "fields": {
                "name": {"analyzers": ["text_en"]}
            }
        }
    }
})

-- Full-text search with BM25 ranking
FOR a IN artist_search
    SEARCH ANALYZER(a.name IN TOKENS(@query, "text_en"), "text_en")
    SORT BM25(a) DESC
    LIMIT @limit
    RETURN { id: a.id, name: a.name, score: BM25(a) }

-- Phrase search
FOR a IN artist_search
    SEARCH PHRASE(a.name, @query, "text_en")
    SORT BM25(a) DESC
    LIMIT 10
    RETURN a

-- Fuzzy/prefix search (useful for autocomplete)
FOR a IN artist_search
    SEARCH STARTS_WITH(a.name, @prefix)
    LIMIT 10
    RETURN { id: a.id, name: a.name }
```

ArangoSearch supports analyzers (language-specific stemming, stop words, ngrams), BM25/TF-IDF scoring, phrase search, prefix/wildcard, and geospatial search — all in a single view.

#### 3. Multi-Collection Transactions

AQL supports explicit multi-collection transactions via the driver API:

```python
# Multi-collection transaction (equivalent to Neo4j execute_write with 6 queries)
tx = db.begin_transaction(
    read=[],
    write=["releases", "artists", "labels", "masters",
           "release_by_artist", "release_on_label",
           "release_derived_from_master", "release_is_genre", "release_is_style"],
)

try:
    # Upsert releases
    tx.aql.execute("""
        FOR release IN @releases
            UPSERT { id: release.id } INSERT release UPDATE release IN releases
    """, bind_vars={"releases": batch})

    # Create edges
    tx.aql.execute("""
        FOR rel IN @artist_rels
            UPSERT { _from: rel._from, _to: rel._to }
            INSERT { _from: rel._from, _to: rel._to }
            UPDATE {} IN release_by_artist
    """, bind_vars={"artist_rels": edges})

    tx.commit_transaction()
except Exception:
    tx.abort_transaction()
    raise
```

#### 4. Schema Management via Driver API

No DDL queries needed — collections, indexes, graphs, and views are managed programmatically:

```python
# Create collections
if not db.has_collection("artists"):
    db.create_collection("artists")
if not db.has_collection("release_by_artist"):
    db.create_collection("release_by_artist", edge=True)

# Create indexes (idempotent)
coll = db.collection("artists")
coll.add_persistent_index(fields=["id"], unique=True)
coll.add_persistent_index(fields=["sha256"])
coll.add_persistent_index(fields=["name"])

# Create named graph
if not db.has_graph("discogsography"):
    graph = db.create_graph("discogsography")
    graph.create_edge_definition(
        edge_collection="release_by_artist",
        from_vertex_collections=["releases"],
        to_vertex_collections=["artists"],
    )
    # ... repeat for all 11 edge types

# Create ArangoSearch views
db.create_arangosearch_view("artist_search", {
    "links": {"artists": {"analyzers": ["text_en"], "fields": {"name": {}}}}
})
```

No `IF NOT EXISTS` issues — `has_collection()`, `has_graph()` checks are built into the driver.

#### 5. Database Stats via HTTP API

```python
# Collection counts
for name in ["artists", "labels", "masters", "releases"]:
    count = db.collection(name).count()

# Server version
version = db.version()

# Database stats
properties = db.properties()

# Engine stats
engine = db.engine()
```

### What This Approach Means

| Concern | AQL Native Impact |
|---------|------------------|
| COUNT {} subqueries | Non-issue — AQL `LET x = LENGTH(...)` is the native way |
| Fulltext search | Non-issue — ArangoSearch views with BM25 scoring |
| Schema idempotency | Non-issue — driver API with `has_collection()` checks |
| Multi-statement transactions | Non-issue — driver API `begin_transaction()` |
| Stats/monitoring | Non-issue — driver API methods |
| Async support | Requires `python-arango-async` (separate package) |

**The only real cost is the query rewrite** — all ~50 Cypher queries must be rewritten in AQL. But there are no compatibility shims, no workarounds, no partial support. Every AQL feature is native and fully supported.

### Query Rewrite Strategy

The rewrite can be done systematically because AQL and Cypher map 1:1 at the concept level:

| Cypher Concept | AQL Equivalent | Mechanical? |
|---------------|---------------|-------------|
| `MATCH (n:Label {prop: val})` | `FOR n IN collection FILTER n.prop == val` | Yes |
| `(a)-[:REL]->(b)` | `FOR b IN OUTBOUND a edge_collection` | Yes |
| `OPTIONAL MATCH` | `LET x = (FOR ... RETURN ...)` | Yes |
| `UNWIND $list AS item` | `FOR item IN @list` | Yes |
| `MERGE (n {id: x}) SET n.y = z` | `UPSERT {id: x} INSERT {...} UPDATE {y: z} IN coll` | Yes |
| `collect(DISTINCT x)` | `RETURN DISTINCT x` or `COLLECT` | Yes |
| `count(DISTINCT x)` | `COLLECT ... WITH COUNT INTO` | Yes |
| `SKIP $n LIMIT $m` | `LIMIT @n, @m` | Yes |
| `CASE WHEN ... END` | `condition ? true_val : false_val` | Yes |

The rewrite is mechanical — each pattern has a direct AQL equivalent. A systematic approach would:

1. Create a query mapping spreadsheet (Cypher → AQL) for all ~50 queries
2. Rewrite in batches by query type (autocomplete, explore, expand, count, trends, user, gaps, batch)
3. Test each batch against Neo4j results for correctness
4. Benchmark each batch for performance

### Additional Work Items (Native AQL Approach)

- [ ] Create AQL query mapping for all ~50 Cypher queries (spreadsheet or markdown table)
- [ ] Implement schema init using `python-arango` driver API (collections, indexes, graph, views)
- [ ] Implement ArangoSearch views for 5 fulltext search targets
- [ ] Rewrite queries in batches, testing each batch for correctness:
  - [ ] Batch 1: autocomplete (4 queries) — ArangoSearch
  - [ ] Batch 2: explore center-node (4 queries) — LET subqueries
  - [ ] Batch 3: expand + count (30 queries) — traversal + COLLECT
  - [ ] Batch 4: node detail (5 queries) — traversal + COLLECT
  - [ ] Batch 5: trends (4 queries) — traversal + COLLECT by year
  - [ ] Batch 6: user collection/wantlist (8 queries) — traversal
  - [ ] Batch 7: gap analysis (3 queries) — traversal + exclusion
  - [ ] Batch 8: batch writes (18 queries) — UPSERT
- [ ] Implement stats/version via `python-arango` driver API methods
- [ ] Test multi-collection transactions for batch processor
- [ ] Compare `python-arango-async` stability with `python-arango` sync + executor

## Docker Setup

```yaml
# docker-compose.yml addition
arangodb:
  image: arangodb/arangodb:latest
  profiles: ["arangodb"]
  environment:
    ARANGO_ROOT_PASSWORD: discogsography
  ports:
    - "8529:8529"      # HTTP API + Web UI
  volumes:
    - arangodb_data:/var/lib/arangodb3
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8529/_api/version"]
    interval: 10s
    timeout: 5s
    retries: 5
```

ArangoDB includes a built-in web UI at `http://localhost:8529` for query execution, graph visualization, and administration.

## ArangoDB Backend Implementation

```python
# common/arangodb_backend.py
from arango import ArangoClient
from common.graph_backend import GraphBackend

class ArangoDBBackend(GraphBackend):
    EDGE_COLLECTIONS = {
        "BY": "release_by_artist",
        "ON": "release_on_label",
        "DERIVED_FROM": "release_derived_from_master",
        "IS_GENRE": "release_is_genre",
        "IS_STYLE": "release_is_style",
        "MEMBER_OF": "artist_member_of",
        "ALIAS_OF": "artist_alias_of",
        "SUBLABEL_OF": "label_sublabel_of",
        "PART_OF": "style_part_of_genre",
        "COLLECTED": "user_collected",
        "WANTS": "user_wants",
    }

    async def connect(self, uri, auth, **kwargs):
        # python-arango-async for async support
        self._client = ArangoClient(hosts=f"http://{uri}")
        self._db = self._client.db(
            "discogsography",
            username=auth[0], password=auth[1],
        )

    async def execute_read(self, query, params=None):
        cursor = self._db.aql.execute(query, bind_vars=params or {})
        return [doc for doc in cursor]

    async def execute_write(self, query, params=None):
        self._db.aql.execute(query, bind_vars=params or {})

    async def execute_write_batch(self, queries):
        # ArangoDB supports multi-statement transactions
        tx_db = self._db.begin_transaction(
            read=[],
            write=["artists", "labels", "masters", "releases", "genres", "styles",
                   *self.EDGE_COLLECTIONS.values()],
        )
        try:
            for query, params in queries:
                tx_db.aql.execute(query, bind_vars=params)
            tx_db.commit_transaction()
        except Exception:
            tx_db.abort_transaction()
            raise

    def fulltext_search_query(self, index_name, query_param):
        # ArangoSearch view-based full-text search
        view_name = f"{index_name}_view"
        return (
            f"FOR doc IN {view_name} "
            f"SEARCH ANALYZER(doc.name IN TOKENS(@{query_param}, 'text_en'), 'text_en') "
            f"SORT BM25(doc) DESC"
        )

    def stats_query(self):
        # ArangoDB HTTP API: GET /_api/collection/{name}/count
        return "RETURN { node_count: LENGTH(artists) + LENGTH(labels) + LENGTH(releases) }"

    def version_query(self):
        # Use HTTP API: GET /_api/version
        return "RETURN 'arangodb'"  # Version via HTTP API, not AQL

    def get_schema_statements(self):
        # Schema is created via driver API, not AQL statements
        # This returns AQL for index creation
        return [
            # Persistent indexes (equivalent to Neo4j range indexes)
            "db.artists.ensureIndex({ type: 'persistent', fields: ['id'], unique: true })",
            # ... etc
            # ArangoSearch views for fulltext
            # Created via driver API, not AQL
        ]
```

Note: ArangoDB schema setup is primarily done through the driver API (collection creation, index creation, graph definition, ArangoSearch view creation) rather than through query statements. The `get_schema_statements()` method would need to be split or the interface adapted.

## Work Items (ArangoDB-Specific)

Prerequisites: Complete [shared pre-work](shared-pre-work.md) first.

- [ ] Install `python-arango` and `python-arango-async` packages
- [ ] Design document collection schema (7 document collections)
- [ ] Design edge collection schema (11 edge collections)
- [ ] Create named graph definition with all edge definitions
- [ ] Create ArangoSearch views for fulltext search (5 views)
- [ ] Implement `common/arangodb_backend.py` with async support
- [ ] Rewrite all ~50 Cypher queries as AQL:
  - [ ] 4 autocomplete queries (ArangoSearch)
  - [ ] 4 explore center-node queries (traversal + aggregation)
  - [ ] ~15 expand queries (traversal + pagination)
  - [ ] ~15 count queries (traversal + count)
  - [ ] 5 node detail queries (traversal + collect)
  - [ ] 4 trends queries (traversal + collect by year)
  - [ ] ~8 user collection/wantlist queries (traversal)
  - [ ] 3 gap analysis queries (traversal + exclusion)
  - [ ] Batch write queries (UPSERT for all 4 entity types + relationships)
- [ ] Implement schema init using ArangoDB driver API
- [ ] Implement stats/version via ArangoDB HTTP API
- [ ] Adapt graphinator batch processor for AQL UPSERT pattern
- [ ] Test multi-statement transactions (`begin_transaction` / `commit_transaction`)
- [ ] Test ArangoSearch full-text search quality and latency
- [ ] Measure memory usage vs Neo4j for the same dataset
- [ ] Run full benchmark suite (adapted to AQL) and compare with Neo4j baseline
- [ ] Evaluate whether multi-model consolidation (replacing both Neo4j AND PostgreSQL) is viable

## Decision Criteria

Proceed with ArangoDB if:

- [ ] Combined graph + document performance matches or exceeds Neo4j + PostgreSQL separately
- [ ] AQL query rewrite is manageable (most patterns translate 1:1)
- [ ] ArangoSearch provides comparable fulltext search quality to Neo4j fulltext indexes
- [ ] Multi-model consolidation eliminates enough infrastructure complexity to justify the migration
- [ ] The `python-arango-async` library is stable enough for production use
- [ ] Multi-statement transactions work reliably for the batch processor pattern
- [ ] Total operational savings (one fewer database to manage) outweigh the rewrite cost

## When NOT to Choose ArangoDB

- If only marginal performance improvement is needed — the full query rewrite cost is too high
- If the team is invested in Cypher and doesn't want to learn AQL
- If PostgreSQL must remain for other reasons (existing analytics, compliance, team expertise)
- If the evaluation budget only allows testing one or two candidates — Memgraph and Apache AGE have lower migration costs
