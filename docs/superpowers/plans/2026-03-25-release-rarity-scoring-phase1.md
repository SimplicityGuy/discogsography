# Release Rarity Scoring Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute a rarity index (0-100) for every release in the knowledge graph using 5 graph-derived signals, surface hidden gems, and expose 5 read-only API endpoints.

**Architecture:** Batch Cypher queries compute per-release signal scores, which are combined into a composite rarity score and stored in PostgreSQL (`insights.release_rarity`). The insights service fetches scored data from an internal API endpoint and persists it. Five public API endpoints serve cached rarity data from PostgreSQL.

**Tech Stack:** Python 3.13+, FastAPI, Neo4j (Cypher), PostgreSQL (psycopg), Redis (caching), structlog, pytest, uv

**Spec:** `docs/superpowers/specs/2026-03-25-release-rarity-scoring-phase1-design.md`

______________________________________________________________________

## File Structure

| Action | File                                        | Responsibility                                                                                  |
| ------ | ------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Create | `api/queries/rarity_queries.py`             | Neo4j batch signal queries + PostgreSQL rarity lookups                                          |
| Create | `api/routers/rarity.py`                     | 5 public endpoints + 1 internal endpoint + `configure()`                                        |
| Create | `tests/api/test_rarity_queries.py`          | Unit tests for query functions                                                                  |
| Create | `tests/api/test_rarity.py`                  | Endpoint integration tests                                                                      |
| Create | `tests/insights/test_rarity_computation.py` | Insights pipeline tests                                                                         |
| Modify | `api/models.py`                             | Add `RaritySignal`, `RarityBreakdown`, `RarityResponse`, `RarityListItem`, `RarityListResponse` |
| Modify | `api/api.py`                                | Import + configure + include rarity router                                                      |
| Modify | `schema-init/postgres_schema.py`            | Add `insights.release_rarity` table + indexes                                                   |
| Modify | `insights/computations.py`                  | Add `compute_and_store_rarity()` + wire into `run_all_computations()`                           |
| Modify | `tests/api/conftest.py`                     | Configure rarity router in `test_client` fixture                                                |

______________________________________________________________________

## Task 1: PostgreSQL Schema — `insights.release_rarity` Table

**Files:**

- Modify: `schema-init/postgres_schema.py` (add table + indexes to `_INSIGHTS_TABLES`)

- Test: `tests/schema-init/test_postgres_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/schema-init/test_release_rarity_schema.py`:

```python
"""Tests for release_rarity schema definition."""

from schema_init.postgres_schema import _INSIGHTS_TABLES


class TestReleaseRaritySchema:
    def test_release_rarity_table_defined(self) -> None:
        """Verify release_rarity table exists in _INSIGHTS_TABLES."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "insights.release_rarity table" in names

    def test_release_rarity_score_index_defined(self) -> None:
        """Verify rarity_score descending index exists."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "idx_release_rarity_score" in names

    def test_release_rarity_tier_index_defined(self) -> None:
        """Verify tier index exists."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "idx_release_rarity_tier" in names

    def test_release_rarity_gem_index_defined(self) -> None:
        """Verify hidden_gem_score index exists."""
        names = [name for name, _ddl in _INSIGHTS_TABLES]
        assert "idx_release_rarity_gem" in names

    def test_release_rarity_ddl_has_required_columns(self) -> None:
        """Verify DDL includes all required columns."""
        ddl = ""
        for name, stmt in _INSIGHTS_TABLES:
            if name == "insights.release_rarity table":
                ddl = stmt
                break
        for col in [
            "release_id",
            "title",
            "artist_name",
            "year",
            "rarity_score",
            "tier",
            "hidden_gem_score",
            "pressing_scarcity",
            "label_catalog",
            "format_rarity",
            "temporal_scarcity",
            "graph_isolation",
            "computed_at",
        ]:
            assert col in ddl, f"Column {col} missing from DDL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/schema-init/test_release_rarity_schema.py -v`
Expected: FAIL — `insights.release_rarity table` not found in `_INSIGHTS_TABLES`

- [ ] **Step 3: Add release_rarity table to schema**

In `schema-init/postgres_schema.py`, add the following entries to `_INSIGHTS_TABLES` list, **before** the `insights.computation_log table` entry (keep computation_log and indexes last):

```python
    (
        "insights.release_rarity table",
        """
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
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_release_rarity_score",
        "CREATE INDEX IF NOT EXISTS idx_release_rarity_score ON insights.release_rarity (rarity_score DESC)",
    ),
    (
        "idx_release_rarity_tier",
        "CREATE INDEX IF NOT EXISTS idx_release_rarity_tier ON insights.release_rarity (tier)",
    ),
    (
        "idx_release_rarity_gem",
        "CREATE INDEX IF NOT EXISTS idx_release_rarity_gem ON insights.release_rarity (hidden_gem_score DESC NULLS LAST)",
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/schema-init/test_release_rarity_schema.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add schema-init/postgres_schema.py tests/schema-init/test_release_rarity_schema.py
git commit -m "feat(schema): add insights.release_rarity table and indexes (#205)"
```

______________________________________________________________________

## Task 2: Pydantic Response Models

**Files:**

- Modify: `api/models.py`

- Test: `tests/api/test_rarity_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_rarity_models.py`:

```python
"""Tests for rarity response models."""

from api.models import RarityListItem, RarityListResponse, RarityResponse, RaritySignal


class TestRaritySignal:
    def test_valid_signal(self) -> None:
        signal = RaritySignal(score=85.0, weight=0.30)
        assert signal.score == 85.0
        assert signal.weight == 0.30


class TestRarityResponse:
    def test_full_response(self) -> None:
        resp = RarityResponse(
            release_id=456,
            title="Test Release",
            artist="Test Artist",
            year=1968,
            rarity_score=87.2,
            tier="ultra-rare",
            hidden_gem_score=72.1,
            breakdown={
                "pressing_scarcity": RaritySignal(score=95.0, weight=0.30),
                "label_catalog": RaritySignal(score=80.0, weight=0.15),
                "format_rarity": RaritySignal(score=70.0, weight=0.15),
                "temporal_scarcity": RaritySignal(score=92.0, weight=0.20),
                "graph_isolation": RaritySignal(score=65.0, weight=0.20),
            },
        )
        assert resp.rarity_score == 87.2
        assert resp.tier == "ultra-rare"
        assert resp.breakdown["pressing_scarcity"].score == 95.0


class TestRarityListItem:
    def test_list_item(self) -> None:
        item = RarityListItem(
            release_id=456,
            title="Test",
            artist="Artist",
            year=1968,
            rarity_score=87.2,
            tier="ultra-rare",
        )
        assert item.release_id == 456


class TestRarityListResponse:
    def test_list_response(self) -> None:
        resp = RarityListResponse(
            items=[
                RarityListItem(
                    release_id=1,
                    title="R1",
                    artist="A1",
                    year=2000,
                    rarity_score=50.0,
                    tier="scarce",
                )
            ],
            total=100,
            page=1,
            page_size=20,
        )
        assert len(resp.items) == 1
        assert resp.total == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_rarity_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'RaritySignal'`

- [ ] **Step 3: Add models to api/models.py**

Append to the end of `api/models.py`:

```python
class RaritySignal(BaseModel):
    """A single rarity signal score and its weight."""

    score: float
    weight: float


class RarityResponse(BaseModel):
    """Full rarity breakdown for a single release."""

    release_id: int
    title: str
    artist: str
    year: int | None
    rarity_score: float
    tier: str
    hidden_gem_score: float | None
    breakdown: dict[str, RaritySignal]


class RarityListItem(BaseModel):
    """A release in a rarity list (leaderboard, artist, label)."""

    release_id: int
    title: str
    artist: str
    year: int | None
    rarity_score: float
    tier: str
    hidden_gem_score: float | None = None


class RarityListResponse(BaseModel):
    """Paginated list of rarity-scored releases."""

    items: list[RarityListItem]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_rarity_models.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/models.py tests/api/test_rarity_models.py
git commit -m "feat(models): add rarity response models (#205)"
```

______________________________________________________________________

## Task 3: Rarity Scoring Engine — Query Functions

**Files:**

- Create: `api/queries/rarity_queries.py`
- Test: `tests/api/test_rarity_queries.py`

This task implements the core scoring logic and all database query functions.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_rarity_queries.py`:

```python
"""Tests for rarity scoring query functions."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.queries.rarity_queries import (
    FORMAT_RARITY_SCORES,
    RARITY_TIERS,
    SIGNAL_WEIGHTS,
    compute_format_rarity_score,
    compute_graph_isolation_score,
    compute_label_catalog_score,
    compute_pressing_scarcity_score,
    compute_rarity_tier,
    compute_temporal_scarcity_score,
    fetch_all_rarity_signals,
    get_rarity_for_release,
    get_rarity_leaderboard,
    get_rarity_by_artist,
    get_rarity_by_label,
    get_rarity_hidden_gems,
)


# ── Pure scoring function tests ──────────────────────────────────────


class TestPressingScarcityScore:
    def test_single_pressing(self) -> None:
        assert compute_pressing_scarcity_score(1) == 100.0

    def test_two_pressings(self) -> None:
        assert compute_pressing_scarcity_score(2) == 85.0

    def test_three_to_five(self) -> None:
        assert compute_pressing_scarcity_score(3) == 60.0
        assert compute_pressing_scarcity_score(5) == 60.0

    def test_six_to_ten(self) -> None:
        assert compute_pressing_scarcity_score(6) == 35.0
        assert compute_pressing_scarcity_score(10) == 35.0

    def test_eleven_plus(self) -> None:
        assert compute_pressing_scarcity_score(11) == 10.0
        assert compute_pressing_scarcity_score(100) == 10.0

    def test_zero_standalone(self) -> None:
        assert compute_pressing_scarcity_score(0) == 90.0


class TestLabelCatalogScore:
    def test_tiny_label(self) -> None:
        assert compute_label_catalog_score(5) == 100.0

    def test_small_label(self) -> None:
        assert compute_label_catalog_score(25) == 75.0

    def test_medium_label(self) -> None:
        assert compute_label_catalog_score(100) == 50.0

    def test_large_label(self) -> None:
        assert compute_label_catalog_score(500) == 25.0

    def test_major_label(self) -> None:
        assert compute_label_catalog_score(5000) == 10.0

    def test_zero_catalog(self) -> None:
        assert compute_label_catalog_score(0) == 100.0


class TestFormatRarityScore:
    def test_test_pressing(self) -> None:
        assert compute_format_rarity_score(["Test Pressing"]) == 100.0

    def test_cd_only(self) -> None:
        assert compute_format_rarity_score(["CD"]) == 10.0

    def test_multiple_formats_takes_max(self) -> None:
        assert compute_format_rarity_score(["CD", "Flexi-disc"]) == 95.0

    def test_unknown_format(self) -> None:
        assert compute_format_rarity_score(["UnknownFormat"]) == 50.0

    def test_empty_formats(self) -> None:
        assert compute_format_rarity_score([]) == 50.0

    def test_none_in_list(self) -> None:
        assert compute_format_rarity_score([None, "LP"]) == 30.0


class TestTemporalScarcityScore:
    def test_old_no_reissue(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(1960, None, current_year)
        assert score == 99.0  # min(100, (2026-1960)*1.5) = 99.0

    def test_old_with_recent_reissue(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(1960, current_year - 5, current_year)
        assert score == 59.0  # 99.0 - 40 = 59.0

    def test_recent_release(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(current_year - 2, None, current_year)
        assert score == 3.0  # 2 * 1.5 = 3.0

    def test_no_year(self) -> None:
        current_year = datetime.now(UTC).year
        score = compute_temporal_scarcity_score(None, None, current_year)
        assert score == 50.0


class TestGraphIsolationScore:
    def test_very_isolated(self) -> None:
        assert compute_graph_isolation_score(1) == 90.0

    def test_somewhat_isolated(self) -> None:
        assert compute_graph_isolation_score(4) == 70.0

    def test_moderate(self) -> None:
        assert compute_graph_isolation_score(6) == 50.0

    def test_connected(self) -> None:
        assert compute_graph_isolation_score(10) == 30.0

    def test_highly_connected(self) -> None:
        assert compute_graph_isolation_score(20) == 10.0

    def test_zero_rels(self) -> None:
        assert compute_graph_isolation_score(0) == 90.0


class TestRarityTier:
    def test_common(self) -> None:
        assert compute_rarity_tier(15.0) == "common"

    def test_uncommon(self) -> None:
        assert compute_rarity_tier(35.0) == "uncommon"

    def test_scarce(self) -> None:
        assert compute_rarity_tier(55.0) == "scarce"

    def test_rare(self) -> None:
        assert compute_rarity_tier(75.0) == "rare"

    def test_ultra_rare(self) -> None:
        assert compute_rarity_tier(90.0) == "ultra-rare"

    def test_boundary_20(self) -> None:
        assert compute_rarity_tier(20.0) == "common"

    def test_boundary_21(self) -> None:
        assert compute_rarity_tier(21.0) == "uncommon"


class TestSignalWeights:
    def test_weights_sum_to_one(self) -> None:
        total = sum(SIGNAL_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001


# ── PostgreSQL query function tests ──────────────────────────────────


class TestGetRarityForRelease:
    @pytest.mark.asyncio
    async def test_returns_row(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(
            return_value={
                "release_id": 456,
                "title": "Test",
                "artist_name": "Artist",
                "year": 1968,
                "rarity_score": 87.2,
                "tier": "ultra-rare",
                "hidden_gem_score": 72.1,
                "pressing_scarcity": 95.0,
                "label_catalog": 80.0,
                "format_rarity": 70.0,
                "temporal_scarcity": 92.0,
                "graph_isolation": 65.0,
            }
        )
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await get_rarity_for_release(mock_pool, 456)
        assert result is not None
        assert result["rarity_score"] == 87.2

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        result = await get_rarity_for_release(mock_pool, 999)
        assert result is None


class TestGetRarityLeaderboard:
    @pytest.mark.asyncio
    async def test_returns_items_and_total(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {"release_id": 1, "title": "R1", "artist_name": "A1", "year": 1970, "rarity_score": 95.0, "tier": "ultra-rare", "hidden_gem_score": 80.0}
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 100})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        items, total = await get_rarity_leaderboard(mock_pool, page=1, page_size=20)
        assert len(items) == 1
        assert total == 100


class TestGetRarityHiddenGems:
    @pytest.mark.asyncio
    async def test_returns_items_with_min_rarity(self) -> None:
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall = AsyncMock(
            return_value=[
                {"release_id": 1, "title": "R1", "artist_name": "A1", "year": 1970, "rarity_score": 65.0, "tier": "rare", "hidden_gem_score": 55.0}
            ]
        )
        mock_cur.fetchone = AsyncMock(return_value={"total": 50})
        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)
        mock_cur.__aenter__ = AsyncMock(return_value=mock_cur)
        mock_cur.__aexit__ = AsyncMock(return_value=False)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=mock_conn)

        items, total = await get_rarity_hidden_gems(mock_pool, page=1, page_size=20, min_rarity=41.0)
        assert len(items) == 1
        assert total == 50


# ── Neo4j batch query tests ──────────────────────────────────────────


class TestFetchAllRaritySignals:
    @pytest.mark.asyncio
    async def test_computes_scores_for_releases(self) -> None:
        """Test end-to-end signal fetch and scoring."""
        mock_driver = MagicMock()

        # Mock the 5 batch queries via run_query
        pressing_data = [{"release_id": "1", "pressing_count": 1, "title": "R1", "artist_name": "A1", "year": 1970}]
        label_data = [{"release_id": "1", "label_catalog_size": 20}]
        format_data = [{"release_id": "1", "formats": ["LP", "Flexi-disc"]}]
        temporal_data = [{"release_id": "1", "year": 1970, "latest_sibling_year": None}]
        degree_data = [{"release_id": "1", "degree": 3}]
        # Quality signals for hidden gem
        artist_degree_data = [{"release_id": "1", "artist_max_degree": 500}]
        label_size_data = [{"release_id": "1", "label_max_catalog": 2000}]
        genre_count_data = [{"release_id": "1", "genre_max_release_count": 50000}]

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

            results = await fetch_all_rarity_signals(mock_driver)

        assert len(results) == 1
        r = results[0]
        assert r["release_id"] == "1"
        assert 0 <= r["rarity_score"] <= 100
        assert r["tier"] in ("common", "uncommon", "scarce", "rare", "ultra-rare")
        assert r["pressing_scarcity"] == 100.0  # 1 pressing
        assert r["format_rarity"] == 95.0  # Flexi-disc max
        assert "hidden_gem_score" in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_rarity_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.queries.rarity_queries'`

- [ ] **Step 3: Implement rarity_queries.py**

Create `api/queries/rarity_queries.py`:

```python
"""Rarity scoring queries and computation logic.

Computes a 5-signal rarity index (0-100) for releases using Neo4j graph data,
and provides PostgreSQL lookup functions for precomputed scores.

Graph model:
  (Release)-[:BY]->(Artist)
  (Release)-[:ON]->(Label)
  (Release)-[:IS]->(Genre)
  (Release)-[:IS]->(Style)
  (Release)-[:DERIVED_FROM]->(Master)
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from api.queries.helpers import run_query
from psycopg.rows import dict_row


logger = structlog.get_logger(__name__)

# ── Signal weights (must sum to 1.0) ────────────────────────────────

SIGNAL_WEIGHTS: dict[str, float] = {
    "pressing_scarcity": 0.30,
    "label_catalog": 0.15,
    "format_rarity": 0.15,
    "temporal_scarcity": 0.20,
    "graph_isolation": 0.20,
}

# ── Format rarity lookup ────────────────────────────────────────────

FORMAT_RARITY_SCORES: dict[str, float] = {
    "Test Pressing": 100.0,
    "Lathe Cut": 98.0,
    "Flexi-disc": 95.0,
    "Shellac": 90.0,
    "Blu-spec CD": 80.0,
    "Box Set": 70.0,
    '10"': 65.0,
    "8-Track Cartridge": 60.0,
    "CDr": 50.0,
    "Vinyl": 40.0,
    "Cassette": 35.0,
    "LP": 30.0,
    "CD": 10.0,
    "File": 5.0,
}

_DEFAULT_FORMAT_SCORE = 50.0

# ── Rarity tiers ────────────────────────────────────────────────────

RARITY_TIERS: list[tuple[float, str]] = [
    (80.0, "ultra-rare"),
    (60.0, "rare"),
    (40.0, "scarce"),
    (20.0, "uncommon"),
    (0.0, "common"),
]


# ── Pure scoring functions ──────────────────────────────────────────


def compute_pressing_scarcity_score(pressing_count: int) -> float:
    """Score based on number of pressings of the same master."""
    if pressing_count <= 0:
        return 90.0  # Standalone release (no master link)
    if pressing_count == 1:
        return 100.0
    if pressing_count == 2:
        return 85.0
    if pressing_count <= 5:
        return 60.0
    if pressing_count <= 10:
        return 35.0
    return 10.0


def compute_label_catalog_score(catalog_size: int) -> float:
    """Score based on label catalog size (smaller = rarer)."""
    if catalog_size < 10:
        return 100.0
    if catalog_size <= 50:
        return 75.0
    if catalog_size <= 200:
        return 50.0
    if catalog_size <= 1000:
        return 25.0
    return 10.0


def compute_format_rarity_score(formats: list[Any]) -> float:
    """Score based on rarest format. Takes max across all formats."""
    if not formats:
        return _DEFAULT_FORMAT_SCORE
    scores = [
        FORMAT_RARITY_SCORES.get(str(f), _DEFAULT_FORMAT_SCORE)
        for f in formats
        if f is not None
    ]
    return max(scores) if scores else _DEFAULT_FORMAT_SCORE


def compute_temporal_scarcity_score(
    release_year: int | None,
    latest_sibling_year: int | None,
    current_year: int,
) -> float:
    """Score based on age and reissue status."""
    if release_year is None:
        return 50.0
    age = current_year - release_year
    base = min(100.0, age * 1.5)
    if latest_sibling_year is not None and latest_sibling_year >= current_year - 10:
        base = max(0.0, base - 40.0)
    return base


def compute_graph_isolation_score(degree: int) -> float:
    """Score based on graph node degree (fewer connections = rarer)."""
    if degree <= 2:
        return 90.0
    if degree <= 4:
        return 70.0
    if degree <= 7:
        return 50.0
    if degree <= 12:
        return 30.0
    return 10.0


def compute_rarity_tier(score: float) -> str:
    """Map composite score to rarity tier label."""
    for threshold, tier in RARITY_TIERS:
        if score > threshold:
            return tier
    return "common"


# ── Neo4j batch signal queries ──────────────────────────────────────


async def fetch_all_rarity_signals(driver: Any) -> list[dict[str, Any]]:
    """Fetch all rarity signals from Neo4j and compute scores.

    Executes 8 batch Cypher queries (5 signal queries + 3 quality queries),
    joins by release_id, and computes composite rarity + hidden gem scores.

    Returns a list of dicts ready for PostgreSQL insertion.
    """
    current_year = datetime.now(UTC).year

    # 1. Pressing scarcity: count siblings per master
    pressing_query = """
    MATCH (r:Release)
    OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)<-[:DERIVED_FROM]-(sibling:Release)
    WITH r, count(DISTINCT sibling) + 1 AS pressing_count
    OPTIONAL MATCH (r)-[:BY]->(a:Artist)
    WITH r, pressing_count, collect(DISTINCT a.name)[0] AS artist_name
    RETURN r.id AS release_id, pressing_count,
           r.title AS title, artist_name, r.year AS year
    """

    # 2. Label catalog size per release
    label_query = """
    MATCH (r:Release)-[:ON]->(l:Label)
    WITH r.id AS release_id, min(COALESCE(l.release_count, 0)) AS label_catalog_size
    RETURN release_id, label_catalog_size
    """

    # 3. Formats per release
    format_query = """
    MATCH (r:Release)
    WHERE r.formats IS NOT NULL
    RETURN r.id AS release_id, r.formats AS formats
    """

    # 4. Temporal: release year + latest sibling year
    temporal_query = """
    MATCH (r:Release)
    OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)<-[:DERIVED_FROM]-(sibling:Release)
    WHERE sibling.year IS NOT NULL AND sibling <> r
    WITH r.id AS release_id, r.year AS year,
         max(sibling.year) AS latest_sibling_year
    RETURN release_id, year, latest_sibling_year
    """

    # 5. Graph degree per release
    degree_query = """
    MATCH (r:Release)
    WITH r, size([(r)-[]-() | 1]) AS degree
    RETURN r.id AS release_id, degree
    """

    # Quality signals for hidden gem scoring
    # 6. Max artist degree per release
    artist_degree_query = """
    MATCH (r:Release)-[:BY]->(a:Artist)
    WITH r.id AS release_id, max(size([(a)-[]-() | 1])) AS artist_max_degree
    RETURN release_id, artist_max_degree
    """

    # 7. Max label catalog size per release
    label_size_query = """
    MATCH (r:Release)-[:ON]->(l:Label)
    WITH r.id AS release_id, max(COALESCE(l.release_count, 0)) AS label_max_catalog
    RETURN release_id, label_max_catalog
    """

    # 8. Max genre release count per release
    genre_count_query = """
    MATCH (r:Release)-[:IS]->(g:Genre)
    WITH r.id AS release_id, max(COALESCE(g.release_count, 0)) AS genre_max_release_count
    RETURN release_id, genre_max_release_count
    """

    logger.info("🔍 Fetching rarity signals from Neo4j...")

    pressing_rows = await run_query(driver, pressing_query, database="neo4j")
    label_rows = await run_query(driver, label_query, database="neo4j")
    format_rows = await run_query(driver, format_query, database="neo4j")
    temporal_rows = await run_query(driver, temporal_query, database="neo4j")
    degree_rows = await run_query(driver, degree_query, database="neo4j")
    artist_degree_rows = await run_query(driver, artist_degree_query, database="neo4j")
    label_size_rows = await run_query(driver, label_size_query, database="neo4j")
    genre_count_rows = await run_query(driver, genre_count_query, database="neo4j")

    logger.info(
        "📊 Rarity signal data fetched",
        releases=len(pressing_rows),
        labels=len(label_rows),
        formats=len(format_rows),
    )

    # Build lookup dicts keyed by release_id
    label_map = {r["release_id"]: r["label_catalog_size"] for r in label_rows}
    format_map = {r["release_id"]: r["formats"] for r in format_rows}
    temporal_map = {r["release_id"]: r for r in temporal_rows}
    degree_map = {r["release_id"]: r["degree"] for r in degree_rows}
    artist_deg_map = {r["release_id"]: r["artist_max_degree"] for r in artist_degree_rows}
    label_size_map = {r["release_id"]: r["label_max_catalog"] for r in label_size_rows}
    genre_count_map = {r["release_id"]: r["genre_max_release_count"] for r in genre_count_rows}

    # Compute percentile normalization for quality signals
    all_artist_degrees = sorted(r["artist_max_degree"] for r in artist_degree_rows if r["artist_max_degree"])
    all_label_sizes = sorted(r["label_max_catalog"] for r in label_size_rows if r["label_max_catalog"])
    all_genre_counts = sorted(r["genre_max_release_count"] for r in genre_count_rows if r["genre_max_release_count"])

    def _percentile_rank(value: float, sorted_values: list[float]) -> float:
        """Return percentile rank (0.0 to 1.0) of value in sorted list."""
        if not sorted_values or value <= 0:
            return 0.0
        count_below = sum(1 for v in sorted_values if v < value)
        return count_below / len(sorted_values)

    # Score each release
    results: list[dict[str, Any]] = []
    for row in pressing_rows:
        rid = row["release_id"]

        pressing_score = compute_pressing_scarcity_score(row["pressing_count"])
        label_score = compute_label_catalog_score(label_map.get(rid, 0))
        fmt_score = compute_format_rarity_score(format_map.get(rid, []))

        temporal_info = temporal_map.get(rid, {})
        temporal_score = compute_temporal_scarcity_score(
            temporal_info.get("year"),
            temporal_info.get("latest_sibling_year"),
            current_year,
        )

        isolation_score = compute_graph_isolation_score(degree_map.get(rid, 0))

        rarity_score = (
            SIGNAL_WEIGHTS["pressing_scarcity"] * pressing_score
            + SIGNAL_WEIGHTS["label_catalog"] * label_score
            + SIGNAL_WEIGHTS["format_rarity"] * fmt_score
            + SIGNAL_WEIGHTS["temporal_scarcity"] * temporal_score
            + SIGNAL_WEIGHTS["graph_isolation"] * isolation_score
        )

        tier = compute_rarity_tier(rarity_score)

        # Hidden gem: quality multiplier from artist/label/genre prominence
        artist_deg = artist_deg_map.get(rid, 0) or 0
        label_sz = label_size_map.get(rid, 0) or 0
        genre_ct = genre_count_map.get(rid, 0) or 0

        quality_multiplier = (
            0.4 * _percentile_rank(artist_deg, all_artist_degrees)
            + 0.3 * _percentile_rank(label_sz, all_label_sizes)
            + 0.3 * _percentile_rank(genre_ct, all_genre_counts)
        )

        hidden_gem_score = round(rarity_score * quality_multiplier, 1)

        results.append(
            {
                "release_id": rid,
                "title": row.get("title") or "",
                "artist_name": row.get("artist_name") or "",
                "year": row.get("year"),
                "rarity_score": round(rarity_score, 1),
                "tier": tier,
                "hidden_gem_score": hidden_gem_score,
                "pressing_scarcity": pressing_score,
                "label_catalog": label_score,
                "format_rarity": fmt_score,
                "temporal_scarcity": temporal_score,
                "graph_isolation": isolation_score,
            }
        )

    logger.info("✅ Rarity scores computed", total=len(results))
    return results


# ── PostgreSQL lookup functions ─────────────────────────────────────


async def get_rarity_for_release(pool: Any, release_id: int) -> dict[str, Any] | None:
    """Get precomputed rarity breakdown for a single release."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier,
                   hidden_gem_score, pressing_scarcity, label_catalog,
                   format_rarity, temporal_scarcity, graph_isolation
            FROM insights.release_rarity
            WHERE release_id = %s
            """,
            (release_id,),
        )
        return await cur.fetchone()


async def get_rarity_leaderboard(
    pool: Any,
    page: int = 1,
    page_size: int = 20,
    tier: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Get paginated global rarity leaderboard."""
    offset = (page - 1) * page_size
    where_clause = "WHERE tier = %s" if tier else ""
    params_list: list[Any] = [tier] if tier else []

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            {where_clause}
            ORDER BY rarity_score DESC
            LIMIT %s OFFSET %s
            """,
            (*params_list, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            f"SELECT count(*) AS total FROM insights.release_rarity {where_clause}",
            tuple(params_list),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total


async def get_rarity_hidden_gems(
    pool: Any,
    page: int = 1,
    page_size: int = 20,
    min_rarity: float = 41.0,
) -> tuple[list[dict[str, Any]], int]:
    """Get paginated hidden gems sorted by hidden_gem_score."""
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            WHERE rarity_score >= %s AND hidden_gem_score IS NOT NULL
            ORDER BY hidden_gem_score DESC
            LIMIT %s OFFSET %s
            """,
            (min_rarity, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            "SELECT count(*) AS total FROM insights.release_rarity WHERE rarity_score >= %s AND hidden_gem_score IS NOT NULL",
            (min_rarity,),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total


async def get_rarity_by_artist(
    driver: Any,
    pool: Any,
    artist_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int] | None:
    """Get rarest releases by a specific artist.

    First queries Neo4j for release_ids, then fetches from PostgreSQL.
    Returns None if artist not found.
    """
    # Check artist exists
    artist_rows = await run_query(
        driver,
        "MATCH (a:Artist {id: $artist_id}) RETURN a.id AS id, a.name AS name LIMIT 1",
        database="neo4j",
        artist_id=artist_id,
    )
    if not artist_rows:
        return None

    # Get release IDs for this artist
    release_rows = await run_query(
        driver,
        "MATCH (a:Artist {id: $artist_id})<-[:BY]-(r:Release) RETURN r.id AS release_id",
        database="neo4j",
        artist_id=artist_id,
    )
    if not release_rows:
        return [], 0

    release_ids = [int(r["release_id"]) for r in release_rows]
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            WHERE release_id = ANY(%s)
            ORDER BY rarity_score DESC
            LIMIT %s OFFSET %s
            """,
            (release_ids, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            "SELECT count(*) AS total FROM insights.release_rarity WHERE release_id = ANY(%s)",
            (release_ids,),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total


async def get_rarity_by_label(
    driver: Any,
    pool: Any,
    label_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int] | None:
    """Get rarest releases on a specific label.

    First queries Neo4j for release_ids, then fetches from PostgreSQL.
    Returns None if label not found.
    """
    # Check label exists
    label_rows = await run_query(
        driver,
        "MATCH (l:Label {id: $label_id}) RETURN l.id AS id, l.name AS name LIMIT 1",
        database="neo4j",
        label_id=label_id,
    )
    if not label_rows:
        return None

    # Get release IDs for this label
    release_rows = await run_query(
        driver,
        "MATCH (l:Label {id: $label_id})<-[:ON]-(r:Release) RETURN r.id AS release_id",
        database="neo4j",
        label_id=label_id,
    )
    if not release_rows:
        return [], 0

    release_ids = [int(r["release_id"]) for r in release_rows]
    offset = (page - 1) * page_size

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT release_id, title, artist_name, year, rarity_score, tier, hidden_gem_score
            FROM insights.release_rarity
            WHERE release_id = ANY(%s)
            ORDER BY rarity_score DESC
            LIMIT %s OFFSET %s
            """,
            (release_ids, page_size, offset),
        )
        items = await cur.fetchall()

        await cur.execute(
            "SELECT count(*) AS total FROM insights.release_rarity WHERE release_id = ANY(%s)",
            (release_ids,),
        )
        count_row = await cur.fetchone()
        total = count_row["total"] if count_row else 0

    return items, total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_rarity_queries.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run linting**

Run: `uv run ruff check api/queries/rarity_queries.py && uv run ruff format api/queries/rarity_queries.py`

- [ ] **Step 6: Commit**

```bash
git add api/queries/rarity_queries.py tests/api/test_rarity_queries.py
git commit -m "feat(queries): add rarity scoring engine with 5-signal model (#205)"
```

______________________________________________________________________

## Task 4: API Router — Rarity Endpoints

**Files:**

- Create: `api/routers/rarity.py`

- Create: `tests/api/test_rarity.py`

- Modify: `api/api.py` (import + configure + include)

- Modify: `tests/api/conftest.py` (configure rarity router)

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_rarity.py`:

```python
"""Tests for rarity API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_MOCK_RARITY_ROW = {
    "release_id": 456,
    "title": "Test Release",
    "artist_name": "Test Artist",
    "year": 1968,
    "rarity_score": 87.2,
    "tier": "ultra-rare",
    "hidden_gem_score": 72.1,
    "pressing_scarcity": 95.0,
    "label_catalog": 80.0,
    "format_rarity": 70.0,
    "temporal_scarcity": 92.0,
    "graph_isolation": 65.0,
}

_MOCK_LIST_ITEM = {
    "release_id": 456,
    "title": "Test Release",
    "artist_name": "Test Artist",
    "year": 1968,
    "rarity_score": 87.2,
    "tier": "ultra-rare",
    "hidden_gem_score": 72.1,
}


class TestGetReleaseRarity:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_for_release",
            new=AsyncMock(return_value=_MOCK_RARITY_ROW),
        ):
            response = test_client.get("/api/rarity/456")
        assert response.status_code == 200
        data = response.json()
        assert data["release_id"] == 456
        assert data["tier"] == "ultra-rare"
        assert "breakdown" in data
        assert data["breakdown"]["pressing_scarcity"]["score"] == 95.0

    def test_not_found(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_for_release",
            new=AsyncMock(return_value=None),
        ):
            response = test_client.get("/api/rarity/999")
        assert response.status_code == 404

    def test_503_when_not_ready(self, test_client: TestClient) -> None:
        import api.routers.rarity as rarity_router

        original = rarity_router._pg_pool
        rarity_router._pg_pool = None
        try:
            response = test_client.get("/api/rarity/456")
            assert response.status_code == 503
        finally:
            rarity_router._pg_pool = original


class TestRarityLeaderboard:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_leaderboard",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 100)),
        ):
            response = test_client.get("/api/rarity/leaderboard")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100
        assert len(data["items"]) == 1

    def test_pagination(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_leaderboard",
            new=AsyncMock(return_value=([], 0)),
        ):
            response = test_client.get("/api/rarity/leaderboard?page=2&page_size=10")
        assert response.status_code == 200

    def test_tier_filter(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_leaderboard",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 1)),
        ):
            response = test_client.get("/api/rarity/leaderboard?tier=ultra-rare")
        assert response.status_code == 200


class TestHiddenGems:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_hidden_gems",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 50)),
        ):
            response = test_client.get("/api/rarity/hidden-gems")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 50

    def test_min_rarity_param(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_hidden_gems",
            new=AsyncMock(return_value=([], 0)),
        ):
            response = test_client.get("/api/rarity/hidden-gems?min_rarity=61")
        assert response.status_code == 200


class TestArtistRarity:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_artist",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 5)),
        ):
            response = test_client.get("/api/rarity/artist/123")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5

    def test_not_found(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_artist",
            new=AsyncMock(return_value=None),
        ):
            response = test_client.get("/api/rarity/artist/nonexistent")
        assert response.status_code == 404


class TestLabelRarity:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_label",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 10)),
        ):
            response = test_client.get("/api/rarity/label/456")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10

    def test_not_found(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_label",
            new=AsyncMock(return_value=None),
        ):
            response = test_client.get("/api/rarity/label/nonexistent")
        assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_rarity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routers.rarity'`

- [ ] **Step 3: Implement the rarity router**

Create `api/routers/rarity.py`:

```python
"""Rarity scoring API endpoints.

Serves precomputed rarity scores from PostgreSQL, with Redis caching.
Artist and label endpoints also query Neo4j for release ID lookups.
"""

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
import structlog

from api.limiter import limiter
from api.queries.rarity_queries import (
    SIGNAL_WEIGHTS,
    get_rarity_by_artist,
    get_rarity_by_label,
    get_rarity_for_release,
    get_rarity_hidden_gems,
    get_rarity_leaderboard,
)


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/rarity", tags=["rarity"])

_neo4j_driver: Any = None
_pg_pool: Any = None
_redis: Any = None

_CACHE_TTL = 3600  # 1 hour


def configure(neo4j: Any, pg_pool: Any, redis: Any = None) -> None:
    """Configure the rarity router with database connections."""
    global _neo4j_driver, _pg_pool, _redis
    _neo4j_driver = neo4j
    _pg_pool = pg_pool
    _redis = redis


def _format_breakdown(row: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Build the breakdown dict from a flat database row."""
    return {
        signal: {"score": row.get(signal, 0.0) or 0.0, "weight": weight}
        for signal, weight in SIGNAL_WEIGHTS.items()
    }


def _format_list_item(row: dict[str, Any]) -> dict[str, Any]:
    """Format a database row as a list item."""
    return {
        "release_id": row["release_id"],
        "title": row.get("title") or "",
        "artist": row.get("artist_name") or "",
        "year": row.get("year"),
        "rarity_score": row["rarity_score"],
        "tier": row["tier"],
        "hidden_gem_score": row.get("hidden_gem_score"),
    }


@router.get("/{release_id}")
@limiter.limit("30/minute")
async def get_release_rarity(release_id: int) -> JSONResponse:
    """Get full rarity breakdown for a single release."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    row = await get_rarity_for_release(_pg_pool, release_id)
    if row is None:
        return JSONResponse(content={"error": "Release rarity not found"}, status_code=404)

    return JSONResponse(
        content={
            "release_id": row["release_id"],
            "title": row.get("title") or "",
            "artist": row.get("artist_name") or "",
            "year": row.get("year"),
            "rarity_score": row["rarity_score"],
            "tier": row["tier"],
            "hidden_gem_score": row.get("hidden_gem_score"),
            "breakdown": _format_breakdown(row),
        }
    )


@router.get("/leaderboard")
@limiter.limit("30/minute")
async def rarity_leaderboard(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tier: str | None = Query(None),
) -> JSONResponse:
    """Get global rarity leaderboard, paginated."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    items, total = await get_rarity_leaderboard(_pg_pool, page, page_size, tier)
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/hidden-gems")
@limiter.limit("30/minute")
async def hidden_gems(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    min_rarity: float = Query(41.0, ge=0, le=100),
) -> JSONResponse:
    """Get top hidden gems sorted by hidden gem score."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    items, total = await get_rarity_hidden_gems(_pg_pool, page, page_size, min_rarity)
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/artist/{artist_id}")
@limiter.limit("30/minute")
async def artist_rarity(
    artist_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Get rarest releases by a specific artist."""
    if not _pg_pool or not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    result = await get_rarity_by_artist(_neo4j_driver, _pg_pool, artist_id, page, page_size)
    if result is None:
        return JSONResponse(content={"error": "Artist not found"}, status_code=404)

    items, total = result
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/label/{label_id}")
@limiter.limit("30/minute")
async def label_rarity(
    label_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Get rarest releases on a specific label."""
    if not _pg_pool or not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    result = await get_rarity_by_label(_neo4j_driver, _pg_pool, label_id, page, page_size)
    if result is None:
        return JSONResponse(content={"error": "Label not found"}, status_code=404)

    items, total = result
    return JSONResponse(
        content={
            "items": [_format_list_item(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
```

- [ ] **Step 4: Register the router in api/api.py**

Add import near line 50 (with other router imports):

```python
import api.routers.rarity as _rarity_router
```

Add configure call near line 237 (with other configure calls):

```python
_rarity_router.configure(_neo4j, _pool, _redis)
```

Add include_router near line 316 (with other include_router calls):

```python
app.include_router(_rarity_router.router)
```

- [ ] **Step 5: Configure rarity router in test conftest**

In `tests/api/conftest.py`, inside the `test_client` fixture, add after the other router imports (around line 183):

```python
import api.routers.rarity as _rarity_router
```

And add the configure call (around line 198):

```python
_rarity_router.configure(mock_neo4j, mock_pool, mock_redis)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_rarity.py -v`
Expected: All tests PASS

- [ ] **Step 7: Run linting**

Run: `uv run ruff check api/routers/rarity.py && uv run ruff format api/routers/rarity.py`

- [ ] **Step 8: Commit**

```bash
git add api/routers/rarity.py api/api.py tests/api/test_rarity.py tests/api/conftest.py
git commit -m "feat(api): add rarity scoring endpoints (#205)"
```

______________________________________________________________________

## Task 5: Internal Compute Endpoint + Insights Pipeline

**Files:**

- Modify: `api/routers/insights_compute.py` (add `/rarity-scores` endpoint)

- Modify: `insights/computations.py` (add `compute_and_store_rarity`)

- Create: `tests/insights/test_rarity_computation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/insights/test_rarity_computation.py`:

```python
"""Tests for rarity score computation pipeline."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from insights.computations import compute_and_store_rarity


def _make_mock_pool() -> MagicMock:
    """Create mock pool with cursor for storing results."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


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
    }
]


class TestComputeAndStoreRarity:
    @pytest.mark.asyncio
    async def test_fetches_and_stores(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = _MOCK_RARITY_ITEMS
            rows = await compute_and_store_rarity(mock_client, mock_pool)

        assert rows == 1
        mock_fetch.assert_called_once_with(
            mock_client,
            "/api/internal/insights/rarity-scores",
            timeout=600.0,
        )

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations._fetch_from_api") as mock_fetch:
            mock_fetch.return_value = []
            rows = await compute_and_store_rarity(mock_client, mock_pool)

        assert rows == 0

    @pytest.mark.asyncio
    async def test_logs_computation(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations._fetch_from_api") as mock_fetch,
            patch("insights.computations._log_computation") as mock_log,
        ):
            mock_fetch.return_value = _MOCK_RARITY_ITEMS
            await compute_and_store_rarity(mock_client, mock_pool)

        mock_log.assert_called_once()
        args = mock_log.call_args
        assert args[0][1] == "release_rarity"
        assert args[0][2] == "completed"

    @pytest.mark.asyncio
    async def test_logs_failure(self) -> None:
        mock_client = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations._fetch_from_api", side_effect=RuntimeError("fail")),
            patch("insights.computations._log_computation") as mock_log,
            pytest.raises(RuntimeError),
        ):
            await compute_and_store_rarity(mock_client, mock_pool)

        mock_log.assert_called_once()
        args = mock_log.call_args
        assert args[0][2] == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/insights/test_rarity_computation.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_and_store_rarity'`

- [ ] **Step 3: Add internal compute endpoint**

In `api/routers/insights_compute.py`, add import at top (after existing query imports):

```python
from api.queries.rarity_queries import fetch_all_rarity_signals
```

Add endpoint at end of file:

```python
@router.get("/rarity-scores")
async def rarity_scores() -> JSONResponse:
    """Return computed rarity scores for all releases from Neo4j."""
    if not _neo4j:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    results = await fetch_all_rarity_signals(_neo4j)
    return JSONResponse(content={"items": results})
```

- [ ] **Step 4: Add compute_and_store_rarity to insights/computations.py**

Add before `run_all_computations`:

```python
async def compute_and_store_rarity(client: httpx.AsyncClient, pool: Any) -> int:
    """Compute release rarity scores and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await _fetch_from_api(client, "/api/internal/insights/rarity-scores", timeout=600.0)
        if not results:
            logger.info("📊 No rarity score results to store")
            await _log_computation(pool, "release_rarity", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn, conn.cursor() as cursor:
            cursor = cast("Any", cursor)
            await cursor.execute("DELETE FROM insights.release_rarity")
            for row in results:
                await cursor.execute(
                    """
                    INSERT INTO insights.release_rarity
                        (release_id, title, artist_name, year, rarity_score, tier,
                         hidden_gem_score, pressing_scarcity, label_catalog,
                         format_rarity, temporal_scarcity, graph_isolation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    ),
                )
        logger.info("💾 Release rarity scores stored", count=len(results))
        await _log_computation(pool, "release_rarity", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Release rarity computation failed", error=str(e))
        await _log_computation(pool, "release_rarity", "failed", started_at, error_message=str(e))
        raise
```

- [ ] **Step 5: Wire into run_all_computations**

In `insights/computations.py`, add this line inside `run_all_computations` after the `data_completeness` line (around line 288):

```python
    results["release_rarity"] = await compute_and_store_rarity(client, pool)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/insights/test_rarity_computation.py -v`
Expected: All 4 tests PASS

- [ ] **Step 7: Run linting**

Run: `uv run ruff check insights/computations.py api/routers/insights_compute.py && uv run ruff format insights/computations.py api/routers/insights_compute.py`

- [ ] **Step 8: Commit**

```bash
git add api/routers/insights_compute.py insights/computations.py tests/insights/test_rarity_computation.py
git commit -m "feat(insights): add rarity score computation pipeline (#205)"
```

______________________________________________________________________

## Task 6: Full Test Suite Verification + Coverage

**Files:** All files from Tasks 1-5

- [ ] **Step 1: Run all rarity-related tests**

Run: `uv run pytest tests/schema-init/test_release_rarity_schema.py tests/api/test_rarity_models.py tests/api/test_rarity_queries.py tests/api/test_rarity.py tests/insights/test_rarity_computation.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run full test suite to check for regressions**

Run: `just test`
Expected: All existing tests still pass

- [ ] **Step 3: Run type checking**

Run: `uv run mypy api/queries/rarity_queries.py api/routers/rarity.py api/models.py insights/computations.py`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 4: Run linting on all changed files**

Run: `uv run ruff check api/queries/rarity_queries.py api/routers/rarity.py api/models.py insights/computations.py api/routers/insights_compute.py schema-init/postgres_schema.py`
Expected: No errors

- [ ] **Step 5: Check coverage for new files**

Run: `uv run pytest tests/api/test_rarity_queries.py tests/api/test_rarity.py tests/api/test_rarity_models.py tests/insights/test_rarity_computation.py --cov=api.queries.rarity_queries --cov=api.routers.rarity --cov=api.models --cov-report=term-missing`
Expected: >=80% coverage on new code

- [ ] **Step 6: Fix any coverage gaps**

If coverage is below 80%, add additional tests targeting uncovered lines. Common gaps to check:

- Error paths (database connection failures)

- Edge cases in scoring functions (boundary values)

- Empty result handling in query functions

- [ ] **Step 7: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "test: improve rarity scoring test coverage (#205)"
```
