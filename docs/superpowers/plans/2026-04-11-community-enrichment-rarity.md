# Community Have/Want Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 6th "collection prevalence" rarity signal by fetching Discogs community have/want counts for releases in user collections, storing in PostgreSQL + Neo4j, and integrating into the rarity scoring engine.

**Architecture:** New enrichment endpoint in the API service fetches community counts from the Discogs REST API (rate-limited, OAuth-authenticated), stores them in `insights.community_counts` (PostgreSQL) and as Release node properties (Neo4j). The existing rarity computation pipeline is extended with a 6th signal that reads these counts.

**Tech Stack:** Python 3.13+, FastAPI, httpx, psycopg, neo4j async driver, pytest

---

### Task 1: Add PostgreSQL schema for community_counts table

**Files:**
- Modify: `schema-init/postgres_schema.py:430-443` (insert new table + index after release_rarity indexes, before computation_log)
- Modify: `schema-init/postgres_schema.py:415-429` (add column to release_rarity table)

- [ ] **Step 1: Add `insights.community_counts` table to `_INSIGHTS_TABLES`**

In `schema-init/postgres_schema.py`, after the `idx_release_rarity_gem` entry (line ~443) and before the `insights.computation_log table` entry (line ~445), insert:

```python
    (
        "insights.community_counts table",
        """
        CREATE TABLE IF NOT EXISTS insights.community_counts (
            release_id      BIGINT PRIMARY KEY,
            have_count      INTEGER NOT NULL DEFAULT 0,
            want_count      INTEGER NOT NULL DEFAULT 0,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_community_counts_fetched",
        "CREATE INDEX IF NOT EXISTS idx_community_counts_fetched ON insights.community_counts (fetched_at)",
    ),
```

- [ ] **Step 2: Add `collection_prevalence` column to `insights.release_rarity` table definition**

In the `insights.release_rarity table` CREATE TABLE statement (line ~415-429), add `collection_prevalence REAL` after `graph_isolation REAL`:

```python
        CREATE TABLE IF NOT EXISTS insights.release_rarity (
            release_id      BIGINT PRIMARY KEY,
            title           TEXT,
            artist_name     TEXT,
            year            INTEGER,
            rarity_score    REAL NOT NULL,
            tier            TEXT NOT NULL,
            hidden_gem_score REAL,
            pressing_scarcity REAL,
            label_catalog   REAL,
            format_rarity   REAL,
            temporal_scarcity REAL,
            graph_isolation REAL,
            collection_prevalence REAL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
```

- [ ] **Step 3: Add migration for existing databases**

Since the schema uses `CREATE TABLE IF NOT EXISTS` and existing databases already have the `release_rarity` table without the new column, add an `ALTER TABLE` entry at the end of the insights section (after `idx_genre_trends_genre`, before `_MUSICBRAINZ_TABLES`):

```python
    (
        "insights.release_rarity add collection_prevalence",
        "ALTER TABLE insights.release_rarity ADD COLUMN IF NOT EXISTS collection_prevalence REAL",
    ),
```

- [ ] **Step 4: Run schema-init tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/schema-init/ -v`
Expected: All existing tests pass (schema entries are validated for syntax)

- [ ] **Step 5: Commit**

```bash
git add schema-init/postgres_schema.py
git commit -m "feat(schema): add community_counts table and collection_prevalence column (#206)"
```

---

### Task 2: Add collection prevalence scoring function and update weights

**Files:**
- Modify: `api/queries/rarity_queries.py:29-35` (update SIGNAL_WEIGHTS)
- Modify: `api/queries/rarity_queries.py:123-133` (add new scoring function after compute_graph_isolation_score)
- Test: `tests/api/test_rarity_queries.py`

- [ ] **Step 1: Write failing tests for the new scoring function**

In `tests/api/test_rarity_queries.py`, add after the `TestGraphIsolationScore` class (line ~133) and update the import:

```python
from api.queries.rarity_queries import (
    SIGNAL_WEIGHTS,
    compute_collection_prevalence_score,
    compute_format_rarity_score,
    compute_graph_isolation_score,
    compute_label_catalog_score,
    compute_pressing_scarcity_score,
    compute_rarity_tier,
    compute_temporal_scarcity_score,
    fetch_all_rarity_signals,
    get_rarity_by_artist,
    get_rarity_by_label,
    get_rarity_for_release,
    get_rarity_hidden_gems,
    get_rarity_leaderboard,
)


class TestCollectionPrevalenceScore:
    def test_zero_have(self) -> None:
        assert compute_collection_prevalence_score(0, 0) == 95.0

    def test_very_few_have(self) -> None:
        assert compute_collection_prevalence_score(5, 0) == 85.0

    def test_few_have(self) -> None:
        assert compute_collection_prevalence_score(50, 0) == 70.0

    def test_moderate_have(self) -> None:
        assert compute_collection_prevalence_score(500, 0) == 50.0

    def test_many_have(self) -> None:
        assert compute_collection_prevalence_score(5000, 0) == 25.0

    def test_mass_market(self) -> None:
        assert compute_collection_prevalence_score(50000, 0) == 10.0

    def test_boundary_1_inclusive(self) -> None:
        assert compute_collection_prevalence_score(1, 0) == 85.0

    def test_boundary_10_inclusive(self) -> None:
        assert compute_collection_prevalence_score(10, 0) == 85.0

    def test_boundary_11(self) -> None:
        assert compute_collection_prevalence_score(11, 0) == 70.0

    def test_boundary_100_inclusive(self) -> None:
        assert compute_collection_prevalence_score(100, 0) == 70.0

    def test_boundary_101(self) -> None:
        assert compute_collection_prevalence_score(101, 0) == 50.0

    def test_boundary_1000_inclusive(self) -> None:
        assert compute_collection_prevalence_score(1000, 0) == 50.0

    def test_boundary_1001(self) -> None:
        assert compute_collection_prevalence_score(1001, 0) == 25.0

    def test_boundary_10000_inclusive(self) -> None:
        assert compute_collection_prevalence_score(10000, 0) == 25.0

    def test_boundary_10001(self) -> None:
        assert compute_collection_prevalence_score(10001, 0) == 10.0

    def test_want_bonus_applied(self) -> None:
        # have=50, want=100 -> base 70.0 + 5.0 bonus = 75.0
        assert compute_collection_prevalence_score(50, 100) == 75.0

    def test_want_bonus_not_applied_when_want_lte_have(self) -> None:
        assert compute_collection_prevalence_score(50, 50) == 70.0
        assert compute_collection_prevalence_score(50, 30) == 70.0

    def test_want_bonus_capped_at_100(self) -> None:
        # have=0 -> base 95.0 + 5.0 = 100.0, not 105.0
        assert compute_collection_prevalence_score(0, 10) == 100.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_rarity_queries.py::TestCollectionPrevalenceScore -v`
Expected: FAIL with `ImportError: cannot import name 'compute_collection_prevalence_score'`

- [ ] **Step 3: Implement the scoring function**

In `api/queries/rarity_queries.py`, after `compute_graph_isolation_score` (line ~133), add:

```python
def compute_collection_prevalence_score(have_count: int, want_count: int) -> float:
    """Score based on community ownership rarity (inverse of prevalence).

    Uses log-scale thresholds since community counts follow power-law distribution.
    Want > have adds a +5 bonus (capped at 100) indicating scarcity pressure.
    """
    if have_count <= 0:
        base = 95.0
    elif have_count <= 10:
        base = 85.0
    elif have_count <= 100:
        base = 70.0
    elif have_count <= 1000:
        base = 50.0
    elif have_count <= 10000:
        base = 25.0
    else:
        base = 10.0

    if want_count > have_count:
        base = min(100.0, base + 5.0)

    return base
```

- [ ] **Step 4: Update SIGNAL_WEIGHTS**

In `api/queries/rarity_queries.py`, replace the `SIGNAL_WEIGHTS` dict (lines 29-35):

```python
SIGNAL_WEIGHTS: dict[str, float] = {
    "pressing_scarcity": 0.25,
    "label_catalog": 0.10,
    "format_rarity": 0.10,
    "temporal_scarcity": 0.20,
    "graph_isolation": 0.15,
    "collection_prevalence": 0.20,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_rarity_queries.py::TestCollectionPrevalenceScore tests/api/test_rarity_queries.py::TestSignalWeights -v`
Expected: All PASS (weights still sum to 1.0)

- [ ] **Step 6: Commit**

```bash
git add api/queries/rarity_queries.py tests/api/test_rarity_queries.py
git commit -m "feat(rarity): add collection_prevalence scoring function and update weights (#206)"
```

---

### Task 3: Integrate collection prevalence into fetch_all_rarity_signals

**Files:**
- Modify: `api/queries/rarity_queries.py:147-331` (update fetch_all_rarity_signals to accept pool, query community_counts, compute 6th signal)
- Test: `tests/api/test_rarity_queries.py`

- [ ] **Step 1: Update the test for fetch_all_rarity_signals to include community data**

In `tests/api/test_rarity_queries.py`, update `TestFetchAllRaritySignals.test_computes_scores_for_releases` — add a mock for the PostgreSQL community counts query. The function will now take both `driver` and `pool`:

```python
class TestFetchAllRaritySignals:
    @pytest.mark.asyncio
    async def test_computes_scores_for_releases(self) -> None:
        """Test end-to-end signal fetch and scoring."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP", "Flexi-disc"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

        # Mock PostgreSQL pool for community counts
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[
            {"release_id": 1, "have_count": 50, "want_count": 10},
        ])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.rarity_queries.run_query") as mock_run:
            mock_run.side_effect = [
                pressing_data,
                label_data,
                format_data,
                temporal_data,
                degree_data,
                artist_degree_data,
                label_size_data,
                genre_count_data,
            ]

            results = await fetch_all_rarity_signals(mock_driver, mock_pool)

        assert len(results) == 1
        r = results[0]
        assert r["release_id"] == "1"
        assert 0 <= r["rarity_score"] <= 100
        assert r["tier"] in ("common", "uncommon", "scarce", "rare", "ultra-rare")
        assert r["pressing_scarcity"] == 100.0  # 1 pressing
        assert r["format_rarity"] == 95.0  # Flexi-disc max
        assert r["collection_prevalence"] == 70.0  # have=50, want<have -> no bonus
        assert "hidden_gem_score" in r

    @pytest.mark.asyncio
    async def test_handles_zero_quality_signals(self) -> None:
        """Test that releases with zero quality signals get hidden_gem_score of 0."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 5}]
        format_data = [{"release_id": "1", "formats": ["LP"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 2}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 0}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 0}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 0}]

        # Mock pool with no community data
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[])
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch("api.queries.rarity_queries.run_query") as mock_run:
            mock_run.side_effect = [
                pressing_data,
                label_data,
                format_data,
                temporal_data,
                degree_data,
                artist_degree_data,
                label_size_data,
                genre_count_data,
            ]
            results = await fetch_all_rarity_signals(mock_driver, mock_pool)

        assert len(results) == 1
        assert results[0]["hidden_gem_score"] == 0.0
        assert results[0]["collection_prevalence"] == 50.0  # neutral fallback

    @pytest.mark.asyncio
    async def test_fallback_when_no_pool(self) -> None:
        """Test that passing pool=None uses neutral fallback for all releases."""
        mock_driver = MagicMock()

        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

        with patch("api.queries.rarity_queries.run_query") as mock_run:
            mock_run.side_effect = [
                pressing_data, label_data, format_data, temporal_data,
                degree_data, artist_degree_data, label_size_data, genre_count_data,
            ]
            results = await fetch_all_rarity_signals(mock_driver, None)

        assert len(results) == 1
        assert results[0]["collection_prevalence"] == 50.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_rarity_queries.py::TestFetchAllRaritySignals -v`
Expected: FAIL (function signature mismatch or missing `collection_prevalence` key)

- [ ] **Step 3: Update `fetch_all_rarity_signals` to accept pool and integrate community counts**

In `api/queries/rarity_queries.py`, update the function signature and body:

```python
async def fetch_all_rarity_signals(driver: Any, pool: Any = None) -> list[dict[str, Any]]:
    """Fetch all rarity signals from Neo4j and compute scores.

    Executes 8 batch Cypher queries (5 signal queries + 3 quality queries),
    optionally fetches community counts from PostgreSQL,
    joins by release_id, and computes composite rarity + hidden gem scores.

    Returns a list of dicts ready for PostgreSQL insertion.
    """
```

After the 8 Neo4j queries and their `asyncio.gather` (line ~243), add the PostgreSQL community counts fetch:

```python
    # 9. Community counts from PostgreSQL (if pool available)
    community_map: dict[str, tuple[int, int]] = {}
    if pool is not None:
        try:
            async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT release_id, have_count, want_count FROM insights.community_counts"
                )
                community_rows = await cur.fetchall()
            community_map = {
                str(r["release_id"]): (r["have_count"], r["want_count"])
                for r in community_rows
            }
            logger.info("📊 Community counts loaded", count=len(community_map))
        except Exception:
            logger.warning("⚠️ Failed to load community counts, using neutral fallback")
```

In the scoring loop, after `isolation_score` (line ~288), add:

```python
        have, want = community_map.get(rid, (None, None))
        if have is not None:
            prevalence_score = compute_collection_prevalence_score(have, want or 0)
        else:
            prevalence_score = 50.0  # neutral fallback
```

Update the weighted sum (lines ~290-296):

```python
        rarity_score = (
            SIGNAL_WEIGHTS["pressing_scarcity"] * pressing_score
            + SIGNAL_WEIGHTS["label_catalog"] * label_score
            + SIGNAL_WEIGHTS["format_rarity"] * fmt_score
            + SIGNAL_WEIGHTS["temporal_scarcity"] * temporal_score
            + SIGNAL_WEIGHTS["graph_isolation"] * isolation_score
            + SIGNAL_WEIGHTS["collection_prevalence"] * prevalence_score
        )
```

Add `collection_prevalence` to the result dict (after `"graph_isolation": isolation_score,`):

```python
                "collection_prevalence": prevalence_score,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_rarity_queries.py::TestFetchAllRaritySignals -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/queries/rarity_queries.py tests/api/test_rarity_queries.py
git commit -m "feat(rarity): integrate collection_prevalence into signal computation (#206)"
```

---

### Task 4: Update call sites for fetch_all_rarity_signals

**Files:**
- Modify: `api/routers/insights_compute.py:126-133` (pass pool to fetch_all_rarity_signals)
- Modify: `api/queries/rarity_queries.py:337-351` (update get_rarity_for_release SELECT)

- [ ] **Step 1: Update the internal rarity-scores endpoint to pass pool**

In `api/routers/insights_compute.py`, update the `rarity_scores` endpoint (line ~132):

```python
@router.get("/rarity-scores")
@limiter.limit("5/minute")
async def rarity_scores(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return computed rarity scores for all releases from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await fetch_all_rarity_signals(_neo4j, _pool)
    return JSONResponse(content={"items": results})
```

- [ ] **Step 2: Update `get_rarity_for_release` SELECT to include collection_prevalence**

In `api/queries/rarity_queries.py`, update the SQL in `get_rarity_for_release` (line ~342-346):

```python
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier,
                   hidden_gem_score, pressing_scarcity, label_catalog,
                   format_rarity, temporal_scarcity, graph_isolation,
                   collection_prevalence
            FROM insights.release_rarity
            WHERE release_id = %s
            """,
            (release_id,),
        )
```

- [ ] **Step 3: Run the full rarity test suite**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_rarity_queries.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add api/routers/insights_compute.py api/queries/rarity_queries.py
git commit -m "feat(rarity): update call sites to pass pool and select collection_prevalence (#206)"
```

---

### Task 5: Update insights computation pipeline to store collection_prevalence

**Files:**
- Modify: `insights/computations.py:305-353` (update INSERT in compute_and_store_rarity)
- Modify: `insights/insights.py:296-339` (update SELECT in release_rarity endpoint)
- Modify: `insights/insights.py:424-454` (add community_enrichment to status endpoint)
- Test: `tests/insights/test_rarity_computation.py`

- [ ] **Step 1: Update mock data in test_rarity_computation.py**

In `tests/insights/test_rarity_computation.py`, update `_MOCK_RARITY_ITEMS` (line ~31) to include the new column:

```python
_MOCK_RARITY_ITEMS = [
    {
        "release_id": "1",
        "title": "Test Release",
        "artist_name": "Test Artist",
        "year": 1970,
        "rarity_score": 85.0,
        "tier": "ultra-rare",
        "hidden_gem_score": 60.0,
        "pressing_scarcity": 100.0,
        "label_catalog": 75.0,
        "format_rarity": 95.0,
        "temporal_scarcity": 80.0,
        "graph_isolation": 70.0,
        "collection_prevalence": 85.0,
    }
]
```

- [ ] **Step 2: Update `compute_and_store_rarity` INSERT statement**

In `insights/computations.py`, update the INSERT in `compute_and_store_rarity` (lines ~322-343):

```python
                for row in results:
                    await cursor.execute(
                        """
                            INSERT INTO insights.release_rarity
                                (release_id, title, artist_name, year, rarity_score, tier,
                                 hidden_gem_score, pressing_scarcity, label_catalog,
                                 format_rarity, temporal_scarcity, graph_isolation,
                                 collection_prevalence)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                        (
                            row["release_id"],
                            row.get("title", ""),
                            row.get("artist_name", ""),
                            row.get("year"),
                            row["rarity_score"],
                            row["tier"],
                            row.get("hidden_gem_score"),
                            row.get("pressing_scarcity"),
                            row.get("label_catalog"),
                            row.get("format_rarity"),
                            row.get("temporal_scarcity"),
                            row.get("graph_isolation"),
                            row.get("collection_prevalence"),
                        ),
                    )
```

- [ ] **Step 3: Update the insights release-rarity read endpoint**

In `insights/insights.py`, update the SELECT in the `release_rarity` endpoint (lines ~310-313) to include `collection_prevalence`:

```python
        await cursor.execute(
            "SELECT release_id, title, artist_name, year, rarity_score, tier, "
            "hidden_gem_score, pressing_scarcity, label_catalog, "
            "format_rarity, temporal_scarcity, graph_isolation, "
            "collection_prevalence "
            "FROM insights.release_rarity ORDER BY rarity_score DESC LIMIT %s",
            (limit,),
        )
```

And update the item dict (lines ~319-333) to include `collection_prevalence`:

```python
    items = [
        {
            "release_id": r[0],
            "title": r[1],
            "artist_name": r[2],
            "year": r[3],
            "rarity_score": r[4],
            "tier": r[5],
            "hidden_gem_score": r[6],
            "pressing_scarcity": r[7],
            "label_catalog": r[8],
            "format_rarity": r[9],
            "temporal_scarcity": r[10],
            "graph_isolation": r[11],
            "collection_prevalence": r[12],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Add `community_enrichment` to the status endpoint insight_types list**

In `insights/insights.py`, update the `insight_types` list in `computation_status` (line ~429):

```python
    insight_types = [
        "artist_centrality", "genre_trends", "label_longevity",
        "anniversaries", "data_completeness", "community_enrichment",
        "release_rarity",
    ]
```

- [ ] **Step 5: Run insights tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/insights/test_rarity_computation.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add insights/computations.py insights/insights.py tests/insights/test_rarity_computation.py
git commit -m "feat(insights): update pipeline to store and serve collection_prevalence (#206)"
```

---

### Task 6: Add community enrichment endpoint

**Files:**
- Modify: `api/routers/insights_compute.py` (add community-enrichment endpoint)
- Create: `tests/api/test_community_enrichment.py`

- [ ] **Step 1: Write tests for the enrichment endpoint**

Create `tests/api/test_community_enrichment.py`:

```python
"""Tests for community have/want enrichment endpoint."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.routers import insights_compute


def _make_mock_pool(community_rows=None, oauth_row=None, app_config_rows=None,
                     collection_release_ids=None):
    """Create mock pool with configurable query responses."""
    mock_cur = AsyncMock()

    # Track which query is being executed to return the right response
    call_count = 0
    execute_calls = []

    async def mock_execute(sql, params=None):
        nonlocal call_count
        execute_calls.append((sql, params))
        call_count += 1

    mock_cur.execute = mock_execute
    mock_cur.executemany = AsyncMock()

    responses = []
    if collection_release_ids is not None:
        responses.append(collection_release_ids)
    if oauth_row is not None:
        responses.append(oauth_row)
    if app_config_rows is not None:
        responses.append(app_config_rows)

    fetchall_idx = 0
    async def mock_fetchall():
        nonlocal fetchall_idx
        if fetchall_idx < len(responses):
            result = responses[fetchall_idx]
            fetchall_idx += 1
            return result
        return []

    fetchone_idx = 0
    async def mock_fetchone():
        nonlocal fetchone_idx
        if oauth_row and fetchone_idx == 0:
            fetchone_idx += 1
            return oauth_row
        return None

    mock_cur.fetchall = mock_fetchall
    mock_cur.fetchone = mock_fetchone
    mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
    mock_cur.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cur)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


class TestEnrichReleasesFromDiscogs:
    @pytest.mark.asyncio
    async def test_no_releases_to_enrich(self) -> None:
        """When no releases need enrichment, return 0."""
        from api.routers.insights_compute import _enrich_community_counts

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(return_value=[])  # no releases
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await _enrich_community_counts(mock_pool, None, None)
        assert result["enriched"] == 0

    @pytest.mark.asyncio
    async def test_no_oauth_credentials(self) -> None:
        """When no OAuth credentials found, skip enrichment."""
        from api.routers.insights_compute import _enrich_community_counts

        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        # First call: releases needing enrichment
        # Second call: no OAuth token
        call_count = 0
        async def mock_fetchall():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"release_id": 123}]
            return []  # no app config

        mock_cur.fetchall = mock_fetchall
        mock_cur.fetchone = AsyncMock(return_value=None)  # no OAuth token
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await _enrich_community_counts(mock_pool, None, None)
        assert result["enriched"] == 0
        assert result["error"] == "no_credentials"

    @pytest.mark.asyncio
    async def test_successful_enrichment(self) -> None:
        """Successful fetch stores counts in PG and Neo4j."""
        from api.routers.insights_compute import _enrich_community_counts

        mock_pool = MagicMock()
        mock_cur = AsyncMock()

        call_count = 0
        async def mock_fetchall():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"release_id": 123}]  # releases to enrich
            if call_count == 2:
                return [  # app config
                    {"key": "discogs_consumer_key", "value": "ck"},
                    {"key": "discogs_consumer_secret", "value": "cs"},
                ]
            return []

        mock_cur.fetchall = mock_fetchall
        mock_cur.fetchone = AsyncMock(return_value={
            "access_token": "at", "access_secret": "as",
            "provider_username": "testuser",
        })
        mock_cur.execute = AsyncMock()
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        # Mock Neo4j
        mock_neo4j_result = AsyncMock()
        mock_neo4j_result.consume = AsyncMock()
        mock_neo4j_session = AsyncMock()
        mock_neo4j_session.run = AsyncMock(return_value=mock_neo4j_result)
        mock_neo4j_session.__aenter__ = AsyncMock(return_value=mock_neo4j_session)
        mock_neo4j_session.__aexit__ = AsyncMock(return_value=False)
        mock_neo4j = MagicMock()
        mock_neo4j.session = MagicMock(return_value=mock_neo4j_session)

        # Mock Discogs API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "community": {"have": 42, "want": 7},
        }

        with (
            patch("api.routers.insights_compute.decrypt_oauth_token", side_effect=lambda v, _k: v),
            patch("api.routers.insights_compute._auth_header", return_value="OAuth ..."),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _enrich_community_counts(
                mock_pool, mock_neo4j, None,
            )

        assert result["enriched"] == 1
        assert result["errors"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_community_enrichment.py -v`
Expected: FAIL with `ImportError: cannot import name '_enrich_community_counts'`

- [ ] **Step 3: Implement the enrichment function**

In `api/routers/insights_compute.py`, add the necessary imports at the top:

```python
import asyncio
from typing import Any

import httpx

from api.auth import decrypt_oauth_token, get_oauth_encryption_key
from api.syncer import _auth_header, DISCOGS_API_BASE, MAX_RATE_LIMIT_RETRIES
from common.query_debug import execute_sql
```

Add the `_enrich_community_counts` function and the endpoint after the existing endpoints:

```python
_ENRICHMENT_DELAY_SECONDS = 1.0  # 1 req/sec to stay under 60 req/min
_STALENESS_DAYS = 7


async def _enrich_community_counts(
    pool: Any,
    neo4j: Any,
    encryption_key: str | None,
) -> dict[str, Any]:
    """Fetch community have/want counts from Discogs API for releases in user collections.

    Returns a dict with enriched/skipped/errors counts.
    """
    from psycopg.rows import dict_row

    # 1. Find releases needing enrichment (new or stale)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT DISTINCT release_id FROM (
                SELECT release_id FROM user_collections
                UNION
                SELECT release_id FROM user_wantlists
            ) AS combined
            WHERE release_id NOT IN (
                SELECT release_id FROM insights.community_counts
                WHERE fetched_at > NOW() - INTERVAL '%s days'
            )
            """,
            (_STALENESS_DAYS,),
        )
        rows = await cur.fetchall()
        release_ids = [r["release_id"] for r in rows]

    if not release_ids:
        logger.info("📊 No releases need community enrichment")
        return {"enriched": 0, "skipped": 0, "errors": 0}

    logger.info("📊 Releases needing community enrichment", count=len(release_ids))

    # 2. Get OAuth credentials (any user with valid Discogs OAuth)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT ot.access_token, ot.access_secret, ot.provider_username
            FROM oauth_tokens ot
            WHERE ot.provider = 'discogs'
            LIMIT 1
            """
        )
        token = await cur.fetchone()

        if not token:
            logger.warning("⚠️ No Discogs OAuth credentials for community enrichment")
            return {"enriched": 0, "skipped": len(release_ids), "errors": 0, "error": "no_credentials"}

        access_token = decrypt_oauth_token(token["access_token"], encryption_key)
        access_secret = decrypt_oauth_token(token["access_secret"], encryption_key)

        await cur.execute(
            "SELECT key, value FROM app_config WHERE key IN ('discogs_consumer_key', 'discogs_consumer_secret')"
        )
        config_rows = await cur.fetchall()
        app_config = {r["key"]: r["value"] for r in config_rows}
        if "discogs_consumer_key" not in app_config or "discogs_consumer_secret" not in app_config:
            logger.warning("⚠️ Discogs app credentials not configured")
            return {"enriched": 0, "skipped": len(release_ids), "errors": 0, "error": "no_credentials"}
        consumer_key = decrypt_oauth_token(app_config["discogs_consumer_key"], encryption_key)
        consumer_secret = decrypt_oauth_token(app_config["discogs_consumer_secret"], encryption_key)

    # 3. Fetch community counts from Discogs API
    enriched = 0
    errors = 0
    batch: list[dict[str, Any]] = []
    rate_limit_retries = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for release_id in release_ids:
            url = f"{DISCOGS_API_BASE}/releases/{release_id}"
            auth = _auth_header(
                "GET", url, consumer_key, consumer_secret,
                access_token, access_secret,
            )
            headers = {
                "Authorization": auth,
                "User-Agent": "discogsography/1.0 +https://github.com/SimplicityGuy/discogsography",
                "Accept": "application/json",
            }

            response = await client.get(url, headers=headers)

            if response.status_code == 429:
                rate_limit_retries += 1
                if rate_limit_retries > MAX_RATE_LIMIT_RETRIES:
                    logger.error("❌ Rate limit retries exhausted during enrichment")
                    break
                logger.warning("⚠️ Rate limited, waiting 60s...", retry=rate_limit_retries)
                await asyncio.sleep(60)
                continue

            rate_limit_retries = 0

            if response.status_code != 200:
                logger.warning("⚠️ Discogs API error for release", release_id=release_id, status=response.status_code)
                errors += 1
                await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)
                continue

            data = response.json()
            community = data.get("community", {})
            have = community.get("have", 0)
            want = community.get("want", 0)

            # Upsert to PostgreSQL
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO insights.community_counts (release_id, have_count, want_count, fetched_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (release_id) DO UPDATE SET
                        have_count = EXCLUDED.have_count,
                        want_count = EXCLUDED.want_count,
                        fetched_at = NOW()
                    """,
                    (release_id, have, want),
                )

            batch.append({"release_id": release_id, "have": have, "want": want})
            enriched += 1
            await asyncio.sleep(_ENRICHMENT_DELAY_SECONDS)

    # 4. Batch update Neo4j Release nodes
    if batch and neo4j is not None:
        cypher = """
        UNWIND $batch AS item
        MATCH (r:Release {id: toString(item.release_id)})
        SET r.community_have = item.have,
            r.community_want = item.want
        """
        try:
            async with neo4j.session() as session:
                result = await session.run(cypher, {"batch": batch})
                await result.consume()
            logger.info("✅ Neo4j Release nodes updated with community counts", count=len(batch))
        except Exception as e:
            logger.error("❌ Failed to update Neo4j community counts", error=str(e))

    logger.info("✅ Community enrichment complete", enriched=enriched, errors=errors)
    return {"enriched": enriched, "skipped": len(release_ids) - enriched - errors, "errors": errors}
```

- [ ] **Step 4: Add the HTTP endpoint**

In `api/routers/insights_compute.py`, add after the existing endpoints:

```python
# Module-level config reference (set by configure())
_config: Any = None


@router.get("/community-enrichment")
@limiter.limit("1/minute")
async def community_enrichment(request: Request) -> JSONResponse:  # noqa: ARG001
    """Enrich releases in user collections with Discogs community have/want counts."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    encryption_key = get_oauth_encryption_key(_config.encryption_master_key) if _config else None
    result = await _enrich_community_counts(_pool, _neo4j, encryption_key)
    return JSONResponse(content=result)
```

- [ ] **Step 5: Update `configure()` to accept and store config**

In `api/routers/insights_compute.py`, update the `configure` function:

```python
def configure(neo4j: Any, pool: Any, redis: Any = None, config: Any = None) -> None:
    """Configure the insights compute router with database connections."""
    global _neo4j, _pool, _redis, _config
    _neo4j = neo4j
    _pool = pool
    _redis = redis
    _config = config
```

- [ ] **Step 6: Update the configure call site in api.py**

In `api/api.py`, update line ~258:

```python
    _insights_compute_router.configure(_neo4j, _pool, _redis, _config)
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_community_enrichment.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add api/routers/insights_compute.py api/api.py tests/api/test_community_enrichment.py
git commit -m "feat(enrichment): add community have/want enrichment endpoint (#206)"
```

---

### Task 7: Add enrichment to insights computation pipeline

**Files:**
- Modify: `insights/computations.py:356-388` (add community_enrichment to run_all_computations, before release_rarity)

- [ ] **Step 1: Add `compute_and_store_community_enrichment` function**

In `insights/computations.py`, add before `compute_and_store_rarity` (line ~305):

```python
async def compute_and_store_community_enrichment(client: httpx.AsyncClient, pool: Any) -> int:
    """Trigger community enrichment via the API internal endpoint."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, "/api/internal/insights/community-enrichment", timeout=3600.0)
        enriched = results.get("enriched", 0) if isinstance(results, dict) else 0
        logger.info("📊 Community enrichment complete", enriched=enriched)
        await _log_computation(pool, "community_enrichment", "completed", started_at, enriched)
        return enriched
    except Exception as e:
        logger.error("❌ Community enrichment failed", error=str(e))
        try:
            await _log_computation(pool, "community_enrichment", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
        raise
```

Note: The `_fetch_from_api` function returns `data.get("items", [])` by default, but the community-enrichment endpoint returns a flat dict, not `{"items": [...]}`. We need to handle this — update the function to handle the response format:

Actually, looking at this more carefully, `_fetch_from_api` always returns `data.get("items", [])` which would return `[]` for the community enrichment response. Instead, make a direct call:

```python
async def compute_and_store_community_enrichment(client: httpx.AsyncClient, pool: Any) -> int:
    """Trigger community enrichment via the API internal endpoint."""
    started_at = datetime.now(UTC)
    try:
        response = await client.get("/api/internal/insights/community-enrichment", timeout=3600.0)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        enriched = data.get("enriched", 0)
        logger.info("📊 Community enrichment complete", enriched=enriched)
        await _log_computation(pool, "community_enrichment", "completed", started_at, enriched)
        return enriched
    except Exception as e:
        logger.error("❌ Community enrichment failed", error=str(e))
        try:
            await _log_computation(pool, "community_enrichment", "failed", started_at, error_message=str(e))
        except Exception as log_err:
            logger.warning("⚠️ Failed to log computation error", error=str(log_err))
        raise
```

- [ ] **Step 2: Add to `run_all_computations` — before release_rarity**

In `insights/computations.py`, update the `computations` list in `run_all_computations` (lines ~367-377). Insert community_enrichment before release_rarity:

```python
    computations: list[tuple[str, Callable[[], Coroutine[Any, Any, int]]]] = [
        ("artist_centrality", lambda: compute_and_store_artist_centrality(client, pool)),
        ("genre_trends", lambda: compute_and_store_genre_trends(client, pool)),
        ("label_longevity", lambda: compute_and_store_label_longevity(client, pool)),
        (
            "anniversaries",
            lambda: compute_and_store_anniversaries(client, pool, milestone_years=milestone_years),
        ),
        ("data_completeness", lambda: compute_and_store_data_completeness(client, pool)),
        ("community_enrichment", lambda: compute_and_store_community_enrichment(client, pool)),
        ("release_rarity", lambda: compute_and_store_rarity(client, pool)),
    ]
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/insights/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add insights/computations.py
git commit -m "feat(insights): add community enrichment to computation pipeline (#206)"
```

---

### Task 8: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run full Python test suite**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run pytest tests/api/test_rarity_queries.py tests/api/test_community_enrichment.py tests/insights/test_rarity_computation.py -v`
Expected: All PASS

- [ ] **Step 2: Run type checking**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run mypy api/queries/rarity_queries.py api/routers/insights_compute.py insights/computations.py insights/insights.py schema-init/postgres_schema.py`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Run linter**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run ruff check api/queries/rarity_queries.py api/routers/insights_compute.py insights/computations.py insights/insights.py schema-init/postgres_schema.py`
Expected: No errors

- [ ] **Step 4: Run formatter**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && uv run ruff format api/queries/rarity_queries.py api/routers/insights_compute.py insights/computations.py insights/insights.py schema-init/postgres_schema.py`

- [ ] **Step 5: Run the broader test suite to check for regressions**

Run: `cd /Users/Robert/Code/public/discogsography/.claude/worktrees/206-customer-rarity && just test`
Expected: All tests pass

- [ ] **Step 6: Commit any formatting changes**

```bash
git add -A
git commit -m "chore: format and lint fixes (#206)"
```
