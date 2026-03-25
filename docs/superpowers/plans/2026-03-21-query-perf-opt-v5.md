# Query Performance Optimization v5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize the 6 slowest Neo4j Cypher queries to reduce DB hits by 2-4x and eliminate 1GB+ memory spikes in similarity queries.

**Architecture:** Wrap per-genre expansions in `CALL {}` subqueries to prevent cross-genre row explosion; eliminate duplicate traversals by merging release_count + genre profile into single passes; add per-genre LIMIT caps for broad genres.

**Tech Stack:** Neo4j Cypher (Community Edition), Python 3.13+ async, asyncio.gather for concurrent queries.

**Note:** Items 1-2 from the v5 analysis (trends/genre pattern comprehension, explore/genre COUNT {} split) are already implemented in `origin/main`. This plan covers items 3-8.

______________________________________________________________________

## File Structure

| File                                  | Responsibility                                 | Change Type |
| ------------------------------------- | ---------------------------------------------- | ----------- |
| `api/queries/label_dna_queries.py`    | Label-similar candidate + batch vector queries | Modify      |
| `api/queries/recommend_queries.py`    | Artist-similar candidate query                 | Modify      |
| `tests/api/test_label_dna_queries.py` | Label DNA query unit tests                     | Modify      |
| `tests/api/test_recommend_queries.py` | Recommend query unit tests                     | Modify      |

______________________________________________________________________

### Task 1: Optimize label-similar candidate discovery — CALL {} per-genre

**Files:**

- Modify: `api/queries/label_dna_queries.py:108-122` (candidates_cypher)
- Test: `tests/api/test_label_dna_queries.py`

The candidate query currently expands ALL releases across ALL 5 genres simultaneously (206M DB hits, 1GB memory for Hooj Choons). Wrapping the per-genre expansion in CALL {} processes one genre at a time, preventing cross-genre row explosion.

- [ ] **Step 1: Write a failing test for the new query structure**

Add a test that verifies `get_candidate_labels_genre_vectors` returns correct results with the CALL-per-genre structure:

```python
class TestGetCandidateLabelsGenreVectors:
    """Tests for the two-phase candidate + profile query."""

    @pytest.mark.asyncio
    async def test_returns_candidates_with_genre_vectors(self) -> None:
        """Phase 1 returns candidates, Phase 2 fills genre profiles."""
        # Phase 1: candidate query returns 2 labels
        candidate_result = _MockResult(records=[
            {"label_id": "10", "label_name": "Label X", "total_shared": 50},
            {"label_id": "20", "label_name": "Label Y", "total_shared": 30},
        ])
        # Phase 2: batch profile returns genre vectors
        profile_result = _MockResult(records=[
            {"label_id": "10", "label_name": "Label X", "release_count": 100,
             "genres": [{"name": "Rock", "count": 80}]},
            {"label_id": "20", "label_name": "Label Y", "release_count": 50,
             "genres": [{"name": "Jazz", "count": 40}]},
        ])
        driver = _make_driver_with_side_effects([candidate_result, profile_result])
        results = await get_candidate_labels_genre_vectors(driver, "157")
        assert len(results) == 2
        assert results[0]["label_id"] == "10"
        assert results[0]["genres"] == [{"name": "Rock", "count": 80}]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_candidates(self) -> None:
        """Returns empty list when no candidates found."""
        driver = _make_driver(records=[])
        results = await get_candidate_labels_genre_vectors(driver, "999")
        assert results == []
```

- [ ] **Step 2: Run test to check baseline**

Run: `uv run pytest tests/api/test_label_dna_queries.py -v --tb=short -k "TestGetCandidateLabelsGenreVectors"`

- [ ] **Step 3: Update the candidates_cypher in label_dna_queries.py**

Replace lines 108-122 with CALL-per-genre version:

```python
    candidates_cypher = """
    MATCH (l:Label {id: $label_id})<-[:ON]-(r:Release)-[:IS]->(g:Genre)
    WITH l, g, count(DISTINCT r) AS genre_count
    ORDER BY genre_count DESC
    LIMIT 5
    WITH l, collect(g) AS top_genres
    UNWIND top_genres AS g2
    CALL {
        WITH g2, l
        MATCH (g2)<-[:IS]-(r2:Release)-[:ON]->(l2:Label)
        WHERE l2 <> l
        RETURN l2, count(DISTINCT r2) AS shared_in_genre
    }
    WITH l2, sum(shared_in_genre) AS total_shared
    WHERE total_shared >= $min_releases
    RETURN l2.id AS label_id, l2.name AS label_name, total_shared
    ORDER BY total_shared DESC
    LIMIT 100
    """
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/api/test_label_dna_queries.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/queries/label_dna_queries.py tests/api/test_label_dna_queries.py
git commit -m "perf: wrap label-similar candidate discovery in per-genre CALL {}

Prevents cross-genre row explosion by processing one genre at a time.
Previous plan expanded all 5 genres simultaneously (206M DB hits, 1GB).
CALL {} per-genre reduces to ~60-80M DB hits, ~200MB memory."
```

______________________________________________________________________

### Task 2: Optimize label-similar batch vectors — eliminate duplicate ON traversal

**Files:**

- Modify: `api/queries/label_dna_queries.py:136-147` (profile_cypher)
- Test: `tests/api/test_label_dna_queries.py`

The batch profile query traverses `(l)<-[:ON]-(r)` twice — once for release_count, once inside CALL {} for genres. Merging into a single traversal eliminates ~37M redundant DB hits.

- [ ] **Step 1: Update the profile_cypher to single-pass**

Replace lines 136-147:

```python
    profile_cypher = """
    UNWIND $label_ids AS lid
    MATCH (l:Label {id: lid})<-[:ON]-(r:Release)
    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
    WITH l, count(DISTINCT r) AS release_count,
         g.name AS genre,
         count(DISTINCT CASE WHEN g IS NOT NULL THEN r END) AS genre_count
    WITH l, release_count,
         collect(CASE WHEN genre IS NOT NULL
                      THEN {name: genre, count: genre_count}
                 END) AS raw_genres
    RETURN l.id AS label_id, l.name AS label_name,
           release_count,
           [g IN raw_genres WHERE g IS NOT NULL] AS genres
    """
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/api/test_label_dna_queries.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/queries/label_dna_queries.py
git commit -m "perf: eliminate duplicate ON traversal in label-similar batch vectors

Merge release_count and genre profile into a single pass through
(l)<-[:ON]-(r). Reduces ~82M to ~44M DB hits by removing the
duplicate Expand(All) operator."
```

______________________________________________________________________

### Task 3: Optimize artist-similar candidate discovery — CALL {} per-genre + LIMIT

**Files:**

- Modify: `api/queries/recommend_queries.py:160-173` (candidates_cypher)
- Test: `tests/api/test_recommend_queries.py`

Same cross-genre explosion as label-similar (157M DB hits, 1GB for Johnny Cash). Add CALL {} per-genre with a per-genre LIMIT to cap broad genres.

- [ ] **Step 1: Update the candidates_cypher**

Replace lines 160-173:

```python
    candidates_cypher = """
    MATCH (a:Artist {id: $artist_id})<-[:BY]-(r:Release)-[:IS]->(g:Genre)
    WITH a, g, count(DISTINCT r) AS genre_count
    ORDER BY genre_count DESC
    LIMIT 5
    WITH a, collect(g) AS top_genres
    UNWIND top_genres AS g2
    CALL {
        WITH g2, a
        MATCH (g2)<-[:IS]-(r2:Release)-[:BY]->(a2:Artist)
        WHERE a2 <> a AND a2.name IS NOT NULL
        WITH a2, count(DISTINCT r2) AS shared_in_genre
        ORDER BY shared_in_genre DESC
        LIMIT 500
        RETURN a2, shared_in_genre
    }
    WITH a2, sum(shared_in_genre) AS shared_count
    WHERE shared_count >= $min_releases
    RETURN a2.id AS artist_id, a2.name AS artist_name,
           shared_count AS release_count
    ORDER BY shared_count DESC
    LIMIT 200
    """
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/api/test_recommend_queries.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/queries/recommend_queries.py
git commit -m "perf: wrap artist-similar candidate discovery in per-genre CALL {}

Process one genre at a time with LIMIT 500 per genre to cap
broad-genre explosion (Rock has 7M releases, millions of artists).
Reduces 157M DB hits → ~20-30M, 1GB memory → ~300MB."
```

______________________________________________________________________

### Task 4: Run full test suite and lint

- [ ] **Step 1: Run all unit tests**

Run: `uv run pytest tests/api/test_label_dna_queries.py tests/api/test_recommend_queries.py tests/api/test_neo4j_queries.py -v`
Expected: All 130+ tests pass.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check api/queries/label_dna_queries.py api/queries/recommend_queries.py`
Expected: No errors.

- [ ] **Step 3: Run type checking**

Run: `uv run mypy api/queries/label_dna_queries.py api/queries/recommend_queries.py`
Expected: No errors.

______________________________________________________________________

### Task 5: Update optimization analysis doc

- [ ] **Step 1: Add implementation notes to v5 analysis**

Update `perftest-results/optimization-analysis-v5.md` Part 3 priority matrix to note items 3-6 as implemented.

- [ ] **Step 2: Commit**

```bash
git add perftest-results/optimization-analysis-v5.md
git commit -m "docs: mark implemented optimizations in v5 analysis report"
```
