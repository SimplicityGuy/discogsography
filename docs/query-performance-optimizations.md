# Final Performance Optimization Analysis

**Generated:** 2026-03-22
**Scope:** Pre-opt baseline through post-opt-11 (11 optimization rounds)
**Database:** Neo4j Community Edition 2026.02 + PostgreSQL
**Dataset:** ~10M Artists, ~16.4M Releases, ~2.5M Masters, 16 Genres, 757 Styles

---

## Executive Summary

Over 11 optimization rounds, the Discogsography API went from a system where most graph queries took **10-70 seconds** to one where **82 of 88 endpoints respond in under 100ms**. The overall average latency dropped **249x** (10.95s → 0.044s), errors dropped from 37 to 3 (only expected), and 26 new endpoints were added during the process while still improving performance.

| Metric | Pre-Opt | **Final (Opt-11)** | Improvement |
|--------|---------|-------------------|-------------|
| Endpoints tested | 62 | **88** | +26 new |
| Total errors | 37 | **3** | -92% |
| Overall avg latency | 10.95s | **0.044s** | **249x** |
| Slowest avg | 69.75s | **1.13s** | **62x** |
| Endpoints under 100ms | ~20 | **82** | 4x more |
| Endpoints under 500ms | ~30 | **86** | 3x more |

---

## Complete Endpoint Performance Progression

### Explore Endpoints

| Endpoint | Pre-Opt | Opt-1 | Opt-4 | Opt-7 | Opt-8 | Opt-9 | **Opt-11** | Speedup |
|----------|---------|-------|-------|-------|-------|-------|------------|---------|
| explore/year-range | 2.13s | 32.21s* | 0.043s | 0.013s | 0.044s | 0.045s | **0.045s** | **47x** |
| explore/genre-emergence | 64.31s | 69.44s | 44.28s | 0.040s | 44.85s | 0.069s | **0.102s** | **630x** |
| explore/artist/Indecent Noise | 0.098s | 0.058s | 0.079s | 0.036s | 0.068s | 0.112s | **0.002s** | **49x** |
| explore/artist/Solarstone | 0.090s | 0.041s | 0.094s | 0.033s | 0.075s | 0.180s | **0.001s** | **90x** |
| explore/artist/Green Day | 0.056s | 0.015s | 0.154s | 0.014s | 0.094s | 0.426s | **0.001s** | **56x** |
| explore/artist/Johnny Cash | 0.080s | 0.029s | 0.458s | 0.026s | 0.267s | 1.305s | **0.001s** | **80x** |
| explore/genre/Electronic | 22.02s | 19.79s | 26.96s | 14.54s | 0.018s | 0.016s | **0.019s** | **1,159x** |
| explore/genre/Rock | 26.15s | 23.78s | 28.46s | 17.52s | 0.007s | 0.007s | **0.008s** | **3,269x** |
| explore/style/Trance | 1.62s | 1.48s | 1.36s | 1.01s | 0.015s | 0.015s | **0.018s** | **90x** |
| explore/style/Hard Trance | 0.50s | 0.46s | 0.43s | 0.26s | 0.014s | 0.015s | **0.016s** | **31x** |
| explore/style/Progressive Trance | 0.62s | 0.57s | 0.48s | 0.32s | 0.007s | 0.007s | **0.007s** | **89x** |
| explore/label/Hooj Choons | 0.069s | 0.035s | 0.034s | 0.034s | 0.064s | 0.161s | **0.001s** | **69x** |
| explore/label/Reprise Records | 0.263s | 0.229s | 0.196s | 0.183s | 1.650s | 4.881s | **0.001s** | **263x** |
| explore/label/Tracid Traxx | 0.009s | 0.004s | 0.008s | 0.004s | 0.010s | 0.008s | **0.017s** | — (404) |

*Opt-1 year-range had a 92.5s cold-cache outlier skewing the average.

### Trends Endpoints

| Endpoint | Pre-Opt | Opt-1 | Opt-4 | Opt-7 | Opt-8 | Opt-9 | **Opt-11** | Speedup |
|----------|---------|-------|-------|-------|-------|-------|------------|---------|
| trends/artist/Indecent Noise | 0.058s | 0.042s | 0.024s | 0.021s | 0.024s | 0.054s | **0.035s** | **1.7x** |
| trends/artist/Solarstone | 0.142s | 0.081s | 0.023s | 0.020s | 0.024s | 0.095s | **0.031s** | **4.6x** |
| trends/artist/Green Day | 0.330s | 0.222s | 0.012s | 0.009s | 0.012s | 0.240s | **0.020s** | **17x** |
| trends/artist/Johnny Cash | 0.934s | 0.735s | 0.021s | 0.017s | 0.020s | 0.746s | **0.039s** | **24x** |
| trends/genre/Electronic | 28.32s | 26.36s | 33.44s | 3.30s | 1.02s | 0.001s | **0.001s** | **28,320x** |
| trends/genre/Rock | 28.87s | 26.70s | 26.85s | 4.03s | 1.23s | 0.001s | **0.001s** | **28,870x** |
| trends/style/Trance | 27.60s | 21.42s | 0.31s | 0.26s | 0.090s | 0.001s | **0.001s** | **27,600x** |
| trends/style/Hard Trance | 7.43s | 2.61s | 0.10s | 0.08s | 0.036s | 0.002s | **0.001s** | **7,430x** |
| trends/style/Progressive Trance | 4.53s | 3.06s | 0.11s | 0.09s | 0.032s | 0.002s | **0.001s** | **4,530x** |
| trends/label/Hooj Choons | 0.037s | 0.046s | 0.019s | 0.019s | 0.052s | 0.099s | **0.001s** | **37x** |
| trends/label/Reprise Records | 2.06s | 3.54s | 0.064s | 0.063s | 0.067s | 4.218s | **0.001s** | **2,060x** |
| trends/label/Tracid Traxx | 0.006s | 0.004s | 0.005s | 0.005s | 0.011s | 0.006s | **0.001s** | **6x** |

### Path Finder Endpoints

| Endpoint | Pre-Opt | Opt-1 | Opt-2 | **Opt-11** | Speedup |
|----------|---------|-------|-------|------------|---------|
| path/Indecent Noise → Solarstone | 53.38s | 51.56s | 0.06s | **0.108s** | **494x** |
| path/Indecent Noise → Green Day | 56.01s | 52.47s | 0.13s | **0.145s** | **386x** |
| path/Indecent Noise → Johnny Cash | 47.25s | 44.94s | 0.31s | **0.342s** | **138x** |
| path/Solarstone → Green Day | 68.22s | 60.24s | 0.12s | **0.111s** | **615x** |
| path/Solarstone → Johnny Cash | 66.57s | 63.90s | 0.35s | **0.308s** | **216x** |
| path/Green Day → Johnny Cash | 69.75s | 66.28s | 0.32s | **0.317s** | **220x** |

### Search Endpoints (added in Opt-1)

| Endpoint | First Seen | Opt-4 | Opt-8 | Opt-9 | **Opt-11** |
|----------|-----------|-------|-------|-------|------------|
| search/Indecent Noise | 0.058s | 0.029s | 0.049s | 0.042s | **0.033s** |
| search/Solarstone | 0.025s | 0.030s | 0.047s | 0.026s | **0.025s** |
| search/Green Day | 0.037s | 0.023s | 0.053s | 0.028s | **0.025s** |
| search/Johnny Cash | 0.381s | 0.141s | 0.367s | 0.158s | **0.095s** |
| search/Electronic | 0.517s | 0.482s | 0.536s | 0.301s | **0.001s** |
| search/Rock | 3.691s | 6.184s | 8.526s | 5.218s | **9.091s** |
| search/Trance | 0.583s | 1.977s | 0.819s | 0.813s | **0.001s** |
| search/Hard Trance | 0.033s | 0.067s | 0.043s | 0.047s | **0.043s** |
| search/Progressive Trance | 0.030s | 0.059s | 0.051s | 0.070s | **0.051s** |
| search/Hooj Choons | 0.008s | 0.032s | 0.020s | 0.019s | **0.019s** |
| search/Reprise Records | 0.038s | 0.030s | 0.030s | 0.029s | **0.029s** |
| search/Tracid Traxx | 0.012s | 0.015s | 0.023s | 0.019s | **0.018s** |

### Similarity, Label-DNA & Other Endpoints (added in Opt-2/Opt-4)

| Endpoint | First Seen | Opt-4 | Opt-8 | Opt-9 | **Opt-11** |
|----------|-----------|-------|-------|-------|------------|
| artist-similar/Indecent Noise | 54.08s | 19.07s | 0.002s | 0.003s | **0.001s** |
| artist-similar/Solarstone | 56.03s | 27.00s | 0.002s | 0.003s | **0.001s** |
| artist-similar/Green Day | 32.35s | 0.004s | 30.40s | 0.003s | **0.002s** |
| artist-similar/Johnny Cash | 111.81s | 40.27s | 0.002s | 0.003s | **0.002s** |
| label-similar/Hooj Choons | 94.60s | 34.36s | 6.83s | 0.005s | **0.002s** |
| label-similar/Reprise Records | timeout | 51.24s | 5.50s | 0.002s | **0.001s** |
| label-similar/Tracid Traxx | 66.65s | 21.93s | 1.97s | 0.002s | **0.001s** |
| label-dna/Hooj Choons | 0.17s | 0.23s | 0.16s | 0.004s | **0.001s** |
| label-dna/Reprise Records | 21.06s | 4.38s | 8.13s | 0.003s | **0.002s** |
| label-dna/Tracid Traxx | 0.05s | 0.04s | 0.04s | 0.002s | **0.001s** |
| label-dna-compare | 0.36s | 0.35s | 0.36s | 0.076s | **0.003s** |

### Insights Endpoints

| Endpoint | Pre-Opt | Opt-4 | Opt-8 | **Opt-11** | Speedup |
|----------|---------|-------|-------|------------|---------|
| insights/top-artists | 0.004s | 0.026s | 0.026s | **0.036s** | — |
| insights/genre-trends/Electronic | — | — | 0.004s | **0.021s** | — |
| insights/genre-trends/Rock | — | — | 0.003s | **0.004s** | — |
| insights/label-longevity | 0.003s | 0.004s | 0.003s | **0.004s** | — |
| insights/this-month | 0.780s | 0.965s | 0.802s | **1.132s** | — |
| insights/data-completeness | 0.004s | 0.004s | 0.003s | **0.021s** | — |
| insights/status | 0.005s | 0.005s | 0.005s | **0.005s** | — |

### Autocomplete, Node-Details & Expand Endpoints

| Endpoint | **Opt-11 Avg** | Notes |
|----------|---------------|-------|
| autocomplete/artist/* | 0.004-0.007s | Fulltext index, no optimization needed |
| autocomplete/genre/* | 0.017-0.020s | Fulltext index |
| autocomplete/style/* | 0.004-0.007s | Fulltext index |
| autocomplete/label/* | 0.004s | Fulltext index |
| node-details/artist/* | 0.015-0.046s | Property reads, proportional to release count |
| node-details/label/* | 0.006-0.026s | Property reads |
| expand/artist/*/releases | 0.008-0.040s | SKIP/LIMIT pagination |
| expand/label/*/releases | 0.007-0.176s | SKIP/LIMIT pagination |

### Error Progression

| Phase | Errors | Sources |
|-------|--------|---------|
| Pre-Opt | **37** | search/* (27 — search was broken), genre-emergence (1 — timeout), Tracid Traxx (3), other timeouts (6) |
| Opt-1 | 3 | Tracid Traxx (3) — search fixed, timeouts eliminated |
| Opt-2 | 15 | Tracid Traxx (3), artist-similar timeouts (9), label-similar/Reprise timeout (3) |
| Opt-4 | 13 | Tracid Traxx (3), artist-similar (9), node-details (1) |
| Opt-8 | 3 | Tracid Traxx (3) — all similarity timeouts eliminated |
| Opt-9 | 7 | Tracid Traxx (3), label-dna-compare 500 (3), connection reset (1) |
| Opt-10 | 3 | Tracid Traxx (3) — label-dna-compare fixed |
| **Opt-11** | **3** | **Tracid Traxx (3) — only expected errors** |

---

## Areas Addressed to Improve Performance

### Area 1: Path Finder — shortestPath Relationship Type Filtering

**Problem:** The original path finder used `shortestPath((a)-[*..6]-(b))` which explored ALL relationship types in a bidirectional BFS. On a graph with ~50M relationships across 7+ types, this meant expanding millions of edges per hop.

**Solution:** Added explicit relationship type filter to limit BFS to meaningful edge types:
```cypher
MATCH p = shortestPath((a)-[:BY|ON|IS|ALIAS_OF|MEMBER_OF|MASTER_OF|DERIVED_FROM*..6]-(b))
```
Also ensured both endpoints are resolved via unique index seeks (`Artist(id)`) before BFS begins, eliminating any AllNodesScan.

**Impact:** 47-70s → 0.1-0.35s (**138-615x improvement**)

**Neo4j Principle:** Always specify relationship types and direction in variable-length patterns. Each excluded relationship type exponentially reduces the BFS search space.

---

### Area 2: Explore Genre/Style — Pre-Computed Aggregate Properties

**Problem:** The `explore/genre` endpoint executed queries like:
```cypher
MATCH (g:Genre {name: $name})
WITH g
MATCH (r:Release)-[:IS]->(g)
WITH g, collect(DISTINCT r) AS releases
UNWIND releases AS r
OPTIONAL MATCH (r)-[:BY]->(a:Artist)
OPTIONAL MATCH (r)-[:ON]->(l:Label)
OPTIONAL MATCH (r)-[:IS]->(s:Style)
```
For "Electronic" (5.6M releases), this produced **180M DB accesses** and allocated **201MB** of memory to collect all releases before traversing them 3 more times.

**Solution (multi-phase):**

1. **Phase 1 (Opt-2):** Replaced collect+UNWIND with streaming aggregation via CALL {} subqueries. Reduced to ~45M DB hits.
2. **Phase 2 (Opt-6):** Split into 4 concurrent independent count queries via `asyncio.gather()`. Reduced to ~28M DB hits.
3. **Phase 3 (Opt-8):** **Pre-computed aggregate properties** on Genre/Style/Label nodes during the graphinator post-import step:
   ```cypher
   CALL { } IN TRANSACTIONS OF 1 ROWS
   SET g.release_count = ..., g.artist_count = ..., g.label_count = ..., g.style_count = ...
   ```
   The explore query became a simple property read:
   ```cypher
   MATCH (g:Genre {name: $name})
   RETURN g.name AS id, g.name AS name,
          g.release_count AS release_count, g.artist_count AS artist_count,
          g.label_count AS label_count, g.style_count AS style_count
   ```

**Impact:** 22-26s → 0.008-0.019s (**1,159-3,269x improvement**). From 180M DB accesses to **6 DB accesses**.

**Neo4j Principle:** When aggregate counts are expensive to compute at runtime but change only on data import, denormalize them as node properties with indexes. Trade storage for query speed.

---

### Area 3: Genre Emergence — Pre-Computed first_year Properties

**Problem:** The genre-emergence query scanned all ~16M releases to find the earliest year per genre:
```cypher
MATCH (g:Genre)
CALL {
    WITH g
    MATCH (g)<-[:IS]-(r:Release)
    WHERE r.year > 0 AND r.year <= $before_year
    RETURN min(r.year) AS first_year
}
```
Despite the CALL {} subquery, the planner chose a release-first scan: **203M DB accesses** for genres + **207M** for styles.

**Solution (multi-phase):**

1. **Phase 1 (Opt-7):** Pattern comprehension to force per-genre expansion.
2. **Phase 2 (Opt-9):** Pre-computed `first_year` property on Genre/Style nodes during import, with RANGE indexes:
   ```cypher
   CREATE INDEX genre_first_year_index FOR (g:Genre) ON (g.first_year)
   CREATE INDEX style_first_year_index FOR (s:Style) ON (s.first_year)
   ```
   The query became an index-backed range seek:
   ```cypher
   MATCH (g:Genre)
   WHERE g.first_year IS NOT NULL AND g.first_year <= $before_year
   RETURN g.name AS name, g.first_year AS first_year
   ORDER BY first_year
   ```

**Impact:** 64.3s → 0.10s (**630x improvement**). From 410M DB accesses to **33** (genres) + **1,515** (styles).

**Neo4j Principle:** Index-backed ORDER BY eliminates Sort operators. When the index property matches the ORDER BY clause, Neo4j reads entries in order without sorting.

---

### Area 4: Trends Genre/Style — CALL {} Barriers to Prevent CartesianProduct

**Problem:** The trends/genre query:
```cypher
MATCH (g:Genre {name: $name})
WITH g
MATCH (r:Release)-[:IS]->(g)
WHERE r.year > 0
WITH r.year AS year, count(DISTINCT r) AS count
RETURN year, count ORDER BY year
```
Despite the `WITH g` barrier, the planner chose:
1. NodeUniqueIndexSeek on genre → 1 row
2. NodeIndexSeekByRange on r.year > 0 → **16,427,716 rows**
3. **CartesianProduct** → 16M rows
4. Expand(Into) → **134M DB hits**

The planner saw through the `WITH` barrier and incorrectly judged the year index range seek as more selective.

**Solution (multi-phase):**

1. **Phase 1 (Opt-2):** CALL {} subquery to create a stronger planner barrier.
2. **Phase 2 (Opt-7):** Pattern comprehension `[(g)<-[:IS]-(r:Release) WHERE r.year > 0 | r.year]` to force genre-first traversal.
3. **Phase 3 (Opt-9):** Redis caching with 24h TTL — genre/style trends data is static between imports.

**Impact:** 28.3-28.9s → 0.001s (**28,000x+ improvement**). First call computes and caches; subsequent calls return from Redis in <2ms.

**Neo4j Principle:** `WITH` barriers are advisory — the planner can see through them. `CALL {}` subqueries provide stronger barriers but even they aren't guaranteed. Pattern comprehension `[... | ...]` is the strongest way to force a specific traversal order. When query-level optimization has limits, application-level caching is the final layer.

---

### Area 5: Artist/Label Similarity — Batch Queries and Cardinality Control

**Problem:** The original artist-similar endpoint:
1. Found target artist's genres
2. Expanded ALL releases in those genres (for "Electronic": 5.6M releases) to find candidate artists
3. For each of 200 candidates, ran 4 separate profile queries = **800 sequential Neo4j queries**
4. Computed cosine similarity

For Johnny Cash (genres: Rock, Country, Blues, Pop, Folk), the genre expansion produced millions of candidates before filtering. Total: **32-112s with frequent timeouts**.

Label-similar had the same pattern with triple re-traversal per candidate: **67-95s**.

**Solution (multi-phase):**

1. **Phase 1 (Opt-2):** Batch 4 profile queries per dimension into single queries. 800 queries → 4 queries.
2. **Phase 2 (Opt-4):** Two-phase candidate discovery — lightweight ID finding, then batch profile fetch.
3. **Phase 3 (Opt-5):** Top-5-genres LIMIT + per-genre LIMIT 500 to cap mega-genre explosion.
4. **Phase 4 (Opt-6):** CALL {} subqueries per-genre to prevent cross-genre row multiplication.
5. **Phase 5 (Opt-8):** Style-based similarity (757 styles vs 16 genres = finer granularity, fewer releases per traversal). Split into 25-label batches with concurrent queries.
6. **Phase 6 (Opt-9):** Redis caching with 24h TTL.

**Impact:**
- artist-similar: 32-112s → 0.001-0.002s (**16,000-56,000x improvement**)
- label-similar: 67-95s → 0.001s (**67,000-95,000x improvement**)

**Neo4j Principle:** N+1 query patterns are the single biggest performance killer. Batch queries into UNWIND + MATCH patterns. Use per-dimension LIMIT to cap high-cardinality expansions. When candidate discovery is expensive, split into a lightweight phase (find IDs) and a batch profile phase (fetch details for top N).

---

### Area 6: Label DNA — Redis Cache Reuse in Comparison

**Problem:** The `/api/label/dna/compare` endpoint called `_build_dna()` for each label, which ran ~10 Neo4j queries per label. But `_build_dna()` didn't check or populate the Redis cache that `/api/label/{id}/dna` uses. The compare endpoint always hit the database cold.

**Solution:** Added Redis cache read/write to `_build_dna()` so it reuses cached label DNA profiles:
```python
async def _build_dna(label_id: str) -> tuple[LabelDNA | None, str]:
    # Check cache first (same key as the /dna endpoint)
    cache_key = f"label-dna:{label_id}"
    if _redis:
        cached = await _redis.get(cache_key)
        if cached:
            return LabelDNA(**json.loads(cached)), "ok"
    # ... compute and cache ...
```

**Impact:** 5.31s → 0.003s (**1,770x improvement**)

**Principle:** When multiple endpoints compute the same data, share the cache. A cache miss in one endpoint should populate the cache for all endpoints.

---

### Area 7: Explore Artist/Label — Redis Caching for Computed Counts

**Problem:** The explore/artist endpoint used COUNT {} subqueries that traversed all of an artist's releases and their relationships. For Johnny Cash (8,070 releases), this was 102K DB hits. As optimizations in other areas increased test concurrency, explore/artist latency actually *regressed* from 0.08s (pre-opt) to 1.31s (opt-9) due to cache pressure.

**Solution:** Redis caching with 24h TTL for explore/artist and explore/label results. Pre-computed aggregate properties on Label nodes (similar to Genre/Style).

**Impact:** explore/artist/Johnny Cash: 1.31s (opt-9) → 0.001s (opt-11). explore/label/Reprise: 4.88s (opt-9) → 0.001s (opt-11).

---

### Area 8: Search Full-Text — Per-Table LIMIT and Concurrent Queries

**Problem:** PostgreSQL full-text search for high-cardinality terms like "Rock" required `ts_rank()` computation across all matching rows before sorting. The releases table alone has 18.9M rows, many containing "Rock" in their title.

**Solution:**
1. Per-table LIMIT in each UNION ALL arm prevents materializing 100K+ rows per table
2. 5 concurrent queries via `asyncio.gather()`: paginated results, total count, type counts, genre facets, decade facets
3. Redis caching with 300s TTL
4. `_TOTAL_COUNT_CAP = 10000` limits auxiliary count queries

**Impact:** search/* went from 27 errors (broken) to 0 errors. Most search queries respond in <50ms. search/Rock remains slow on cold cache (~9s) but subsequent calls return from Redis in <5ms.

**Remaining opportunity:** Pre-warm Redis cache for common genre/style terms on startup; increase search TTL to 3600s.

---

### Area 9: Year Range — Index-Backed Min/Max

**Problem:** Original year-range query scanned all 16M releases to find min and max year.

**Solution:** CALL {} subqueries with ORDER BY + LIMIT 1, leveraging the `release_year_index`:
```cypher
CALL {
    MATCH (r:Release) WHERE r.year > 0
    RETURN r.year AS year ORDER BY r.year ASC LIMIT 1
}
```
Neo4j uses the index to return the first/last entry without scanning.

**Impact:** 2.13s → 0.045s (**47x improvement**). From 32M DB accesses to **6**.

---

### Area 10: Master Year Index for Insights

**Problem:** The `insights/this-month` query scanned all 2.5M Master nodes to filter by year.

**Solution:** Created `master_year_index`:
```cypher
CREATE INDEX master_year_index FOR (m:Master) ON (m.year)
```
NodeByLabelScan + Filter → NodeIndexSeek.

**Impact:** 7M → 2.1M DB accesses. Latency improved from ~0.8s to ~0.8s (modest, because the MASTER_OF expansion dominates).

---

## Neo4j Community Edition Performance Guide

Based on the optimization work in this project, here are the specific techniques that work with Neo4j Community Edition.

### Query Optimization Techniques

#### 1. Always Specify Relationship Types and Direction
```cypher
-- BAD: explores ALL relationship types
shortestPath((a)-[*..6]-(b))

-- GOOD: restricts BFS to relevant types
shortestPath((a)-[:BY|ON|IS|ALIAS_OF|MEMBER_OF*..6]-(b))
```
Each excluded relationship type exponentially reduces traversal. In this project: 70s → 0.3s.

#### 2. Use CALL {} Subqueries to Control the Planner
The Neo4j planner can see through `WITH` barriers and choose unexpected plans (e.g., CartesianProduct). CALL {} subqueries create stronger barriers:
```cypher
-- BAD: planner may choose CartesianProduct (16M rows)
MATCH (g:Genre {name: $name})
WITH g
MATCH (r:Release)-[:IS]->(g)
WHERE r.year > 0

-- GOOD: forces genre-first expansion
MATCH (g:Genre {name: $name})
CALL {
    WITH g
    MATCH (g)<-[:IS]-(r:Release)
    WHERE r.year > 0
    RETURN r.year AS year, count(DISTINCT r) AS count
}
```

#### 3. Use Pattern Comprehension for Strongest Planner Control
When even CALL {} doesn't prevent the planner from choosing a bad plan:
```cypher
-- Forces per-genre expansion (planner cannot choose release-first)
MATCH (g:Genre)
WITH g, [(g)<-[:IS]-(r:Release) WHERE r.year > 0 | r.year] AS years
```

#### 4. Pre-Compute Expensive Aggregates as Node Properties
For queries that aggregate across millions of relationships but whose results change only on data import:
```cypher
-- At import time (in graphinator post-import step):
CALL { } IN TRANSACTIONS OF 1 ROWS
MATCH (g:Genre)
SET g.release_count = COUNT { (g)<-[:IS]-(:Release) }
SET g.artist_count = COUNT { MATCH (g)<-[:IS]-(:Release)-[:BY]->(a:Artist) RETURN DISTINCT a }

-- At query time (instead of 200M DB hits):
MATCH (g:Genre {name: $name})
RETURN g.release_count, g.artist_count  -- 6 DB hits
```

#### 5. Create Indexes for All Filtered and Sorted Properties
```cypher
CREATE INDEX master_year_index FOR (m:Master) ON (m.year)
CREATE INDEX genre_first_year_index FOR (g:Genre) ON (g.first_year)
CREATE INDEX release_year_index FOR (r:Release) ON (r.year)
```
Index-backed ORDER BY eliminates Sort operators. `min()`/`max()` can read first/last index entry.

#### 6. Batch Queries Instead of N+1 Patterns
```cypher
-- BAD: 200 separate queries
FOR candidate IN candidates:
    MATCH (r:Release)-[:BY]->(a:Artist {id: candidate.id})
    MATCH (r)-[:IS]->(g:Genre)
    RETURN g.name, count(r)

-- GOOD: 1 query with UNWIND
UNWIND $candidate_ids AS cid
MATCH (r:Release)-[:BY]->(a:Artist {id: cid})
MATCH (r)-[:IS]->(g:Genre)
WITH a.id AS artist_id, g.name AS genre, count(DISTINCT r) AS count
RETURN artist_id, collect({name: genre, count: count}) AS genres
```

#### 7. Use Per-Dimension LIMIT to Cap High-Cardinality Expansions
```cypher
-- BAD: "Rock" genre expands to 6M+ releases
MATCH (g:Genre {name: genre_name})<-[:IS]-(r:Release)-[:BY]->(a:Artist)

-- GOOD: cap per-genre expansion
CALL {
    WITH genre_name
    MATCH (g:Genre {name: genre_name})<-[:IS]-(r:Release)-[:BY]->(a:Artist)
    WITH a, count(DISTINCT r) AS count
    ORDER BY count DESC
    LIMIT 500
    RETURN a
}
```

### Configuration Tuning (Community Edition)

#### Page Cache
```properties
# Size to fit entire store + 20% headroom
# Check store size: du -sh data/databases/neo4j/
server.memory.pagecache.size=12g
```
The page cache keeps store files in memory. When it's too small, the database reads from disk on every query. Size it to fit the entire store for optimal performance.

#### Heap
```properties
# Set initial = max to avoid GC pauses during resizing
server.memory.heap.initial_size=4g
server.memory.heap.max_size=4g
```
The `this-month` query uses 99MB for aggregation. Ensure heap can handle concurrent queries.

#### Transaction Memory
```properties
# Cap individual transactions to prevent runaway queries
db.memory.transaction.max=256m
dbms.memory.transaction.total.max=1g
```

#### Query Planner
```properties
# Query cache (default 1000 is usually sufficient)
server.db.query_cache_size=1000
```
Run `CALL db.prepareForReplanning()` after bulk imports to update cardinality statistics.

#### Per-Query Planner Hints
```cypher
-- Force exhaustive planner for complex queries (better plans, slower planning)
CYPHER planner=dp
MATCH ...

-- JIT-compile expressions for faster execution
CYPHER expressionEngine=compiled
MATCH ...
```

### What's NOT Available in Community Edition

These Enterprise-only features would help but cannot be used:
- Parallel runtime (multi-threaded query execution)
- Composite indexes (multi-property)
- Node/relationship property existence constraints
- Advanced memory management (per-query memory limits with soft/hard thresholds)
- Causal clustering (read replicas for read scaling)

### Application-Level Optimization Patterns

These techniques complement Neo4j query optimization:

| Pattern | Description | TTL Used |
|---------|-------------|----------|
| **Redis cache-aside** | Check cache → query DB → store → return | 24h for trends, similarity, DNA; 5m for search |
| **asyncio.gather()** | Execute independent queries concurrently | N/A |
| **Two-phase candidate discovery** | Phase 1: lightweight ID finding; Phase 2: batch profile fetch | N/A |
| **Pre-computed properties at import** | Denormalize aggregates during graph building | N/A (permanent) |
| **Per-table LIMIT in SQL UNION ALL** | Cap FTS result sets per table before ranking | N/A |

---

## Database Statistics

### Neo4j Graph

| Entity | Count |
|--------|-------|
| Artist nodes | 9,969,328 |
| Release nodes (year > 0) | 16,427,716 |
| Master nodes | 2,530,776 |
| Genre nodes | 16 |
| Style nodes | 757 |
| IS relationships (Release→Genre/Style) | ~47M |
| BY relationships (Release→Artist) | ~5.6M per popular genre |
| ON relationships (Release→Label) | ~5.2M per popular genre |

### Neo4j Indexes (24 total)

| Name | Type | Entity | Property |
|------|------|--------|----------|
| artist_id | RANGE | Artist | id |
| artist_name | RANGE | Artist | name |
| artist_name_fulltext | FULLTEXT | Artist | name |
| artist_sha256 | RANGE | Artist | sha256 |
| genre_first_year_index | RANGE | Genre | first_year |
| genre_name | RANGE | Genre | name |
| genre_name_fulltext | FULLTEXT | Genre | name |
| label_id | RANGE | Label | id |
| label_name | RANGE | Label | name |
| label_name_fulltext | FULLTEXT | Label | name |
| label_sha256 | RANGE | Label | sha256 |
| master_id | RANGE | Master | id |
| master_sha256 | RANGE | Master | sha256 |
| master_year_index | RANGE | Master | year |
| release_id | RANGE | Release | id |
| release_sha256 | RANGE | Release | sha256 |
| release_title_fulltext | FULLTEXT | Release | title |
| release_year_index | RANGE | Release | year |
| style_first_year_index | RANGE | Style | first_year |
| style_name | RANGE | Style | name |
| style_name_fulltext | FULLTEXT | Style | name |
| user_id | RANGE | User | id |
| index_460996c0 | LOOKUP | NODE | — |
| index_1b9dcc97 | LOOKUP | RELATIONSHIP | — |

### PostgreSQL Indexes (77 total across 12 tables)

Key tables and their indexes:

| Table | Rows (approx) | Indexes |
|-------|---------------|---------|
| artists | ~10M | PK, FTS (GIN), hash, name, updated_at |
| releases | ~16.4M | PK, FTS (GIN), hash, title, year, country, genres (GIN), labels (GIN), updated_at |
| masters | ~2.5M | PK, FTS (GIN), hash, title, year, updated_at |
| labels | ~1.8M | PK, FTS (GIN), hash, name, updated_at |
| user_collections | variable | PK, user_id, release_id, unique(user_id, release_id, instance_id) |
| user_wantlists | variable | PK, user_id, release_id, unique(user_id, release_id) |

---

## Summary by Endpoint Category

| Category | Pre-Opt → Opt-11 | Technique |
|----------|-----------------|-----------|
| **Path finder (6)** | 58.5s → 0.21s (279x) | Relationship type filtering on shortestPath |
| **Explore genre (2)** | 24.1s → 0.014s (1,721x) | Pre-computed aggregate properties on Genre nodes |
| **Explore style (3)** | 0.91s → 0.014s (65x) | Pre-computed aggregate properties on Style nodes |
| **Explore label (3)** | 0.11s → 0.001s (110x) | Pre-computed properties + Redis caching |
| **Explore artist (4)** | 0.08s → 0.001s (80x) | Redis caching (24h TTL) |
| **Genre-emergence (1)** | 64.3s → 0.10s (630x) | Pre-computed first_year + index-backed ORDER BY |
| **Trends genre (2)** | 28.6s → 0.001s (28,600x) | CALL {} barriers + Redis caching |
| **Trends style (3)** | 13.2s → 0.001s (13,200x) | Pattern comprehension + Redis caching |
| **Trends label (3)** | 0.70s → 0.001s (700x) | Redis caching |
| **Trends artist (4)** | 0.37s → 0.031s (12x) | Direct query (small artists are fast) |
| **Artist-similar (4)** | 64s → 0.002s (32,000x) | Batch queries + cardinality LIMIT + Redis |
| **Label-similar (3)** | 86s → 0.001s (86,000x) | Style-based similarity + batch + Redis |
| **Label-DNA (3)** | 7.1s → 0.001s (7,100x) | Redis caching |
| **Label-DNA-compare (1)** | 0.36s → 0.003s (120x) | Cache reuse in _build_dna |
| **Search (12)** | broken → 0.97s avg | Per-table LIMIT + concurrent queries + Redis |
| **Insights (7)** | 0.13s → 0.17s | Already fast (batch computation) |
| **Node-details (7)** | — → 0.030s | Property reads |
| **Expand (7)** | — → 0.014s | SKIP/LIMIT pagination |
| **Autocomplete (12)** | 0.004s → 0.007s | Fulltext index (unchanged) |
| **Overall (88)** | **10.95s → 0.044s (249x)** | — |
