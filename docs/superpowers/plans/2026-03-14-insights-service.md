# Insights Service Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Insights microservice that runs scheduled batch analytics against Neo4j and PostgreSQL, stores precomputed results in dedicated PostgreSQL tables, and exposes them via read-only API endpoints — delivering music analytics (graph centrality, genre trends, label longevity, anniversary releases, data completeness) that are too expensive to compute on demand.

**Architecture:** A new `insights/` service following the established FastAPI + HealthServer pattern. The service runs an async scheduler loop that periodically executes Cypher and SQL queries against Neo4j and PostgreSQL, writing aggregated results to an `insights` schema in PostgreSQL. Five read-only FastAPI endpoints serve these precomputed results with sub-100ms response times. The API service proxies these endpoints under `/api/insights/` so they're accessible from the consolidated API surface. No RabbitMQ integration needed — this service reads from existing data stores, not from message queues.

**Tech Stack:** Python 3.13+, FastAPI, Neo4j (Cypher), PostgreSQL (psycopg), asyncio scheduler, structlog, Pydantic v2

**GitHub Issue:** #85

---

## Architecture Decision Records

### ADR-1: Standalone Service vs. API Router

**Decision:** Standalone `insights/` service with its own process, not an API router.

**Why:** The insight computations are long-running batch jobs (minutes to hours for full-graph traversals). Running them inside the API process would compete for event loop time with user-facing request handling. A separate service isolates batch work, can be independently scaled, and can be restarted without affecting the API.

### ADR-2: No RabbitMQ Integration

**Decision:** The Insights service reads directly from Neo4j and PostgreSQL. It does not consume messages from RabbitMQ.

**Why:** Insights are derived from the **completed** state of the graph and tables — they need the full dataset, not individual record events. The existing graphinator and tableinator already populate the databases; insights runs after that data is available.

### ADR-3: API Proxy Pattern for Endpoints

**Decision:** Insights exposes its own FastAPI on port 8008. The main API service proxies `/api/insights/*` requests to the insights service via `httpx`, following the same pattern used for explore endpoints.

**Why:** This maintains the architectural principle that all user-facing HTTP traffic goes through the API service (port 8004), while keeping the insights computation and serving in its own process. The API service is the single entry point; insights is an internal service.

### ADR-4: PostgreSQL `insights` Schema (Not Separate Tables in Public)

**Decision:** All insight result tables live in a dedicated `insights` PostgreSQL schema, created by schema-init.

**Why:** Clean namespace separation from entity tables (`artists`, `labels`, `masters`, `releases`) and user tables. The schema-init service already handles all DDL, so adding `CREATE SCHEMA IF NOT EXISTS insights` and the new tables there keeps the single-source-of-truth pattern intact.

### ADR-5: Simple asyncio Scheduler (Not APScheduler)

**Decision:** Use a simple `asyncio.create_task` + `asyncio.sleep` loop for scheduling, not APScheduler.

**Why:** The project has no existing APScheduler dependency. Adding it for 5 periodic tasks is unnecessary complexity. An async loop with configurable intervals is simpler, has zero new dependencies, and is trivially testable. If cron-style scheduling becomes necessary later, APScheduler can be added then.

### ADR-6: Port Assignment

**Decision:** Port 8008 (service) and 8009 (health).

**Why:** Following the existing port allocation pattern. Ports 8000–8007 are taken. 8008/8009 are the next available pair.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `insights/__init__.py` | Package init |
| **Create** | `insights/insights.py` | FastAPI app, lifespan, scheduler loop, health |
| **Create** | `insights/queries/neo4j_queries.py` | Cypher queries for centrality, genre trends, label longevity, anniversaries |
| **Create** | `insights/queries/pg_queries.py` | PostgreSQL queries for data completeness |
| **Create** | `insights/queries/__init__.py` | Package init |
| **Create** | `insights/computations.py` | Orchestrates query execution and result storage |
| **Create** | `insights/models.py` | Pydantic response models for all 5 insight endpoints |
| **Create** | `insights/pyproject.toml` | Service package metadata |
| **Create** | `insights/Dockerfile` | Container build for insights service |
| **Create** | `tests/insights/__init__.py` | Test package init |
| **Create** | `tests/insights/conftest.py` | Test fixtures for insights service |
| **Create** | `tests/insights/test_models.py` | Tests for Pydantic models |
| **Create** | `tests/insights/test_neo4j_queries.py` | Tests for Neo4j query functions |
| **Create** | `tests/insights/test_pg_queries.py` | Tests for PostgreSQL query functions |
| **Create** | `tests/insights/test_computations.py` | Tests for computation orchestration |
| **Create** | `tests/insights/test_insights.py` | Tests for FastAPI endpoints |
| **Create** | `tests/insights/test_scheduler.py` | Tests for scheduler loop |
| **Create** | `.coveragerc.insights` | Coverage config for insights service |
| **Modify** | `common/config.py` | Add `InsightsConfig` dataclass |
| **Modify** | `common/__init__.py` | Export `InsightsConfig` |
| **Modify** | `schema-init/postgres_schema.py` | Add `insights` schema and 5 result tables |
| **Modify** | `tests/schema-init/test_postgres_schema.py` | Tests for new schema objects |
| **Modify** | `docker-compose.yml` | Add insights service definition |
| **Modify** | `pyproject.toml` | Add insights to workspace members, optional deps |
| **Modify** | `justfile` | Add `test-insights` and `insights` tasks |
| **Modify** | `.github/workflows/test.yml` | Add `test-insights` CI job |
| **Modify** | `codecov.yml` | Add `insights` flag and component |
| **Modify** | `api/routers/insights.py` | *(Create)* Proxy router forwarding to insights service |
| **Modify** | `api/api.py` | Register insights proxy router |
| **Modify** | `CLAUDE.md` | Update port table and service list |

---

## Chunk 1: Configuration, Schema, and Models

This chunk establishes the data layer — config, PostgreSQL schema for storing results, and Pydantic models for API responses. No service code yet.

### Task 1: InsightsConfig in common/config.py

**Files:**
- Modify: `common/config.py`
- Modify: `common/__init__.py`
- Test: `tests/common/test_config.py`

- [ ] **Step 1: Write failing test for InsightsConfig**

Add to `tests/common/test_config.py`:

```python
class TestInsightsConfig:
    """Tests for InsightsConfig."""

    def test_from_env_with_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEO4J_HOST", "neo4j")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "password")
        monkeypatch.setenv("POSTGRES_HOST", "postgres")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "db")
        monkeypatch.setenv("INSIGHTS_SCHEDULE_HOURS", "12")

        from common.config import InsightsConfig

        config = InsightsConfig.from_env()
        assert config.neo4j_host == "bolt://neo4j:7687"
        assert config.postgres_database == "db"
        assert config.schedule_hours == 12

    def test_from_env_default_schedule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEO4J_HOST", "neo4j")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "password")
        monkeypatch.setenv("POSTGRES_HOST", "postgres")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "db")

        from common.config import InsightsConfig

        config = InsightsConfig.from_env()
        assert config.schedule_hours == 24  # default: once per day

    def test_from_env_missing_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEO4J_HOST", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("POSTGRES_HOST", raising=False)

        from common.config import InsightsConfig

        with pytest.raises(ValueError, match="Missing required environment variables"):
            InsightsConfig.from_env()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/common/test_config.py::TestInsightsConfig -v`
Expected: FAIL — `ImportError: cannot import name 'InsightsConfig'`

- [ ] **Step 3: Implement InsightsConfig**

Add to `common/config.py` (after `ExploreConfig`):

```python
@dataclass(frozen=True)
class InsightsConfig:
    """Configuration for the insights service."""

    neo4j_host: str
    neo4j_username: str
    neo4j_password: str
    postgres_host: str
    postgres_username: str
    postgres_password: str
    postgres_database: str
    schedule_hours: int = 24  # How often to recompute insights (hours)

    @classmethod
    def from_env(cls) -> "InsightsConfig":
        """Create configuration from environment variables."""
        neo4j_username = getenv("NEO4J_USERNAME")
        neo4j_password = get_secret("NEO4J_PASSWORD")
        postgres_username = getenv("POSTGRES_USERNAME")
        postgres_password = get_secret("POSTGRES_PASSWORD")
        postgres_database = getenv("POSTGRES_DATABASE")

        missing_vars = []
        if not getenv("NEO4J_HOST"):
            missing_vars.append("NEO4J_HOST")
        if not neo4j_username:
            missing_vars.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing_vars.append("NEO4J_PASSWORD")
        if not getenv("POSTGRES_HOST"):
            missing_vars.append("POSTGRES_HOST")
        if not postgres_username:
            missing_vars.append("POSTGRES_USERNAME")
        if not postgres_password:
            missing_vars.append("POSTGRES_PASSWORD")
        if not postgres_database:
            missing_vars.append("POSTGRES_DATABASE")

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        schedule_hours_str = getenv("INSIGHTS_SCHEDULE_HOURS", "24")
        try:
            schedule_hours = int(schedule_hours_str)
            if schedule_hours < 1:
                schedule_hours = 24
        except ValueError:
            schedule_hours = 24

        return cls(
            neo4j_host=_build_neo4j_uri(),
            neo4j_username=cast("str", neo4j_username),
            neo4j_password=cast("str", neo4j_password),
            postgres_host=_build_postgres_connstr(),
            postgres_username=cast("str", postgres_username),
            postgres_password=cast("str", postgres_password),
            postgres_database=cast("str", postgres_database),
            schedule_hours=schedule_hours,
        )
```

Add to `common/__init__.py` exports:

```python
from common.config import InsightsConfig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/common/test_config.py::TestInsightsConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add common/config.py common/__init__.py tests/common/test_config.py
git commit -m "feat(insights): add InsightsConfig to common/config.py"
```

---

### Task 2: PostgreSQL Schema for Insights Tables

**Files:**
- Modify: `schema-init/postgres_schema.py`
- Test: `tests/schema-init/test_postgres_schema.py`

- [ ] **Step 1: Write failing test for insights schema creation**

Add to `tests/schema-init/test_postgres_schema.py` (follow existing test patterns in that file):

```python
class TestInsightsSchema:
    """Tests for insights schema tables."""

    @pytest.mark.asyncio
    async def test_insights_tables_are_defined(self) -> None:
        """Verify the _INSIGHTS_TABLES list contains all 5 insight tables."""
        from schema_init.postgres_schema import _INSIGHTS_TABLES

        table_names = [name for name, _stmt in _INSIGHTS_TABLES]
        assert "insights schema" in table_names
        assert "insights.artist_centrality table" in table_names
        assert "insights.genre_trends table" in table_names
        assert "insights.label_longevity table" in table_names
        assert "insights.monthly_anniversaries table" in table_names
        assert "insights.data_completeness table" in table_names
        assert "insights.computation_log table" in table_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/schema-init/test_postgres_schema.py::TestInsightsSchema -v`
Expected: FAIL — `ImportError: cannot import name '_INSIGHTS_TABLES'`

- [ ] **Step 3: Implement insights schema definitions**

Add to `schema-init/postgres_schema.py` (after `_USER_TABLES`):

```python
# Insights tables — precomputed analytics stored in a dedicated schema.
# All tables include computed_at for cache freshness checks.
_INSIGHTS_TABLES: list[tuple[str, str]] = [
    (
        "insights schema",
        "CREATE SCHEMA IF NOT EXISTS insights",
    ),
    (
        "insights.artist_centrality table",
        """
        CREATE TABLE IF NOT EXISTS insights.artist_centrality (
            rank            INT NOT NULL,
            artist_id       TEXT NOT NULL,
            artist_name     TEXT NOT NULL,
            edge_count      BIGINT NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (rank)
        )
        """,
    ),
    (
        "insights.genre_trends table",
        """
        CREATE TABLE IF NOT EXISTS insights.genre_trends (
            genre           TEXT NOT NULL,
            decade          INT NOT NULL,
            release_count   BIGINT NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (genre, decade)
        )
        """,
    ),
    (
        "insights.label_longevity table",
        """
        CREATE TABLE IF NOT EXISTS insights.label_longevity (
            rank            INT NOT NULL,
            label_id        TEXT NOT NULL,
            label_name      TEXT NOT NULL,
            first_year      INT NOT NULL,
            last_year       INT NOT NULL,
            years_active    INT NOT NULL,
            total_releases  BIGINT NOT NULL,
            peak_decade     INT,
            still_active    BOOLEAN NOT NULL DEFAULT FALSE,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (rank)
        )
        """,
    ),
    (
        "insights.monthly_anniversaries table",
        """
        CREATE TABLE IF NOT EXISTS insights.monthly_anniversaries (
            master_id       TEXT NOT NULL,
            title           TEXT NOT NULL,
            artist_name     TEXT,
            release_year    INT NOT NULL,
            anniversary     INT NOT NULL,
            computed_month  INT NOT NULL,
            computed_year   INT NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (master_id, computed_year, computed_month)
        )
        """,
    ),
    (
        "insights.data_completeness table",
        """
        CREATE TABLE IF NOT EXISTS insights.data_completeness (
            entity_type     TEXT NOT NULL,
            total_count     BIGINT NOT NULL,
            with_image      BIGINT NOT NULL DEFAULT 0,
            with_year       BIGINT NOT NULL DEFAULT 0,
            with_country    BIGINT NOT NULL DEFAULT 0,
            with_genre      BIGINT NOT NULL DEFAULT 0,
            completeness_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (entity_type)
        )
        """,
    ),
    (
        "insights.computation_log table",
        """
        CREATE TABLE IF NOT EXISTS insights.computation_log (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            insight_type    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'running',
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at    TIMESTAMPTZ,
            rows_affected   BIGINT,
            error_message   TEXT,
            duration_ms     BIGINT
        )
        """,
    ),
    (
        "idx_computation_log_type_started",
        "CREATE INDEX IF NOT EXISTS idx_computation_log_type_started ON insights.computation_log (insight_type, started_at DESC)",
    ),
    (
        "idx_anniversaries_month_year",
        "CREATE INDEX IF NOT EXISTS idx_anniversaries_month_year ON insights.monthly_anniversaries (computed_year, computed_month)",
    ),
    (
        "idx_genre_trends_genre",
        "CREATE INDEX IF NOT EXISTS idx_genre_trends_genre ON insights.genre_trends (genre)",
    ),
]
```

Then update `create_postgres_schema()` to include the new tables. Add this block after the user tables loop:

```python
            # ── Insights tables ───────────────────────────────────────────
            for name, stmt in _INSIGHTS_TABLES:
                try:
                    await cursor.execute(stmt)
                    logger.info(f"✅ Schema: {name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to create schema object '{name}': {e}")
                    failure_count += 1
```

Update the `total` count line to include `+ len(_INSIGHTS_TABLES)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/schema-init/test_postgres_schema.py::TestInsightsSchema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add schema-init/postgres_schema.py tests/schema-init/test_postgres_schema.py
git commit -m "feat(insights): add insights schema tables to PostgreSQL schema-init"
```

---

### Task 3: Pydantic Response Models

**Files:**
- Create: `insights/models.py`
- Create: `insights/__init__.py`
- Create: `tests/insights/__init__.py`
- Create: `tests/insights/test_models.py`

- [ ] **Step 1: Create package init files**

Create `insights/__init__.py` — empty file.
Create `tests/insights/__init__.py` — empty file.

- [ ] **Step 2: Write failing tests for all response models**

Create `tests/insights/test_models.py`:

```python
"""Tests for insights Pydantic response models."""

import pytest


class TestArtistCentralityItem:
    def test_valid(self) -> None:
        from insights.models import ArtistCentralityItem

        item = ArtistCentralityItem(rank=1, artist_id="a123", artist_name="Radiohead", edge_count=5432)
        assert item.rank == 1
        assert item.artist_name == "Radiohead"
        assert item.edge_count == 5432

    def test_serialization(self) -> None:
        from insights.models import ArtistCentralityItem

        item = ArtistCentralityItem(rank=1, artist_id="a123", artist_name="Radiohead", edge_count=5432)
        data = item.model_dump()
        assert data == {"rank": 1, "artist_id": "a123", "artist_name": "Radiohead", "edge_count": 5432}


class TestGenreTrendItem:
    def test_valid(self) -> None:
        from insights.models import GenreTrendItem

        item = GenreTrendItem(decade=1990, release_count=12345)
        assert item.decade == 1990
        assert item.release_count == 12345


class TestGenreTrendsResponse:
    def test_valid(self) -> None:
        from insights.models import GenreTrendItem, GenreTrendsResponse

        resp = GenreTrendsResponse(
            genre="Jazz",
            trends=[GenreTrendItem(decade=1960, release_count=5000)],
            peak_decade=1960,
        )
        assert resp.genre == "Jazz"
        assert resp.peak_decade == 1960
        assert len(resp.trends) == 1


class TestLabelLongevityItem:
    def test_valid(self) -> None:
        from insights.models import LabelLongevityItem

        item = LabelLongevityItem(
            rank=1,
            label_id="l456",
            label_name="Blue Note",
            first_year=1939,
            last_year=2025,
            years_active=86,
            total_releases=4500,
            peak_decade=1960,
            still_active=True,
        )
        assert item.years_active == 86
        assert item.still_active is True


class TestAnniversaryItem:
    def test_valid(self) -> None:
        from insights.models import AnniversaryItem

        item = AnniversaryItem(
            master_id="m789",
            title="OK Computer",
            artist_name="Radiohead",
            release_year=1997,
            anniversary=25,
        )
        assert item.anniversary == 25


class TestDataCompletenessItem:
    def test_valid(self) -> None:
        from insights.models import DataCompletenessItem

        item = DataCompletenessItem(
            entity_type="releases",
            total_count=15000000,
            with_image=12000000,
            with_year=14500000,
            with_country=13000000,
            with_genre=14000000,
            completeness_pct=89.67,
        )
        assert item.completeness_pct == 89.67


class TestComputationStatus:
    def test_valid(self) -> None:
        from insights.models import ComputationStatus

        status = ComputationStatus(
            insight_type="artist_centrality",
            last_computed=None,
            status="never_run",
        )
        assert status.status == "never_run"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/insights/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'insights'`

- [ ] **Step 4: Implement all response models**

Create `insights/models.py`:

```python
"""Pydantic response models for the insights service."""

from datetime import datetime

from pydantic import BaseModel


class ArtistCentralityItem(BaseModel):
    """A single artist's centrality ranking."""

    rank: int
    artist_id: str
    artist_name: str
    edge_count: int


class GenreTrendItem(BaseModel):
    """Release count for a genre in a specific decade."""

    decade: int
    release_count: int


class GenreTrendsResponse(BaseModel):
    """Genre trend data across decades."""

    genre: str
    trends: list[GenreTrendItem]
    peak_decade: int | None = None


class LabelLongevityItem(BaseModel):
    """A label's longevity ranking."""

    rank: int
    label_id: str
    label_name: str
    first_year: int
    last_year: int
    years_active: int
    total_releases: int
    peak_decade: int | None = None
    still_active: bool = False


class AnniversaryItem(BaseModel):
    """A release with a notable anniversary this month."""

    master_id: str
    title: str
    artist_name: str | None = None
    release_year: int
    anniversary: int


class DataCompletenessItem(BaseModel):
    """Data completeness metrics for an entity type."""

    entity_type: str
    total_count: int
    with_image: int = 0
    with_year: int = 0
    with_country: int = 0
    with_genre: int = 0
    completeness_pct: float = 0.0


class ComputationStatus(BaseModel):
    """Status of a specific insight computation."""

    insight_type: str
    last_computed: datetime | None = None
    status: str  # "running", "completed", "failed", "never_run"
    duration_ms: int | None = None
```

- [ ] **Step 5: Create insights/pyproject.toml**

Create `insights/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "insights"
version = "0.1.0"
description = "Precomputed analytics and music trends for Discogsography"
requires-python = ">=3.13"

[tool.hatch.build.targets.wheel]
packages = ["insights"]

# Tool configurations inherit from root pyproject.toml
```

- [ ] **Step 6: Add insights to root pyproject.toml workspace**

In `pyproject.toml`, update the `[tool.uv.workspace]` members list:

```toml
members = ["api", "common", "dashboard", "explore", "graphinator", "insights", "schema-init", "tableinator"]
```

Add to `[project.optional-dependencies]`:

```toml
insights = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
]
```

Add `"insights"` to the coverage source list in `[tool.coverage.run]`.

Add `"insights"` to the pythonpath list in `[tool.pytest.ini_options]`.

- [ ] **Step 7: Run uv sync and tests**

Run: `uv sync --all-extras && uv run pytest tests/insights/test_models.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add insights/ tests/insights/ pyproject.toml
git commit -m "feat(insights): add Pydantic response models and package scaffold"
```

---

## Chunk 2: Query Layer

This chunk implements all the database queries — both Neo4j Cypher queries and PostgreSQL queries — that power the insights computations. Each query function takes a driver/pool, runs the query, and returns typed results.

### Task 4: Neo4j Queries — Artist Centrality

**Files:**
- Create: `insights/queries/__init__.py`
- Create: `insights/queries/neo4j_queries.py`
- Create: `tests/insights/test_neo4j_queries.py`

- [ ] **Step 1: Write failing test for artist centrality query**

Create `tests/insights/test_neo4j_queries.py`:

```python
"""Tests for insights Neo4j query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_driver(records: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock Neo4j driver that returns the given records."""
    mock_result = AsyncMock()
    mock_records = [MagicMock(data=MagicMock(return_value=r)) for r in records]
    mock_result.__aiter__ = MagicMock(return_value=iter(mock_records))

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    return mock_driver


class TestQueryArtistCentrality:
    @pytest.mark.asyncio
    async def test_returns_ranked_artists(self) -> None:
        from insights.queries.neo4j_queries import query_artist_centrality

        records = [
            {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
            {"artist_id": "a2", "artist_name": "Artist Two", "edge_count": 50},
        ]
        driver = _make_mock_driver(records)
        result = await query_artist_centrality(driver, limit=100)
        assert len(result) == 2
        assert result[0]["artist_id"] == "a1"
        assert result[0]["edge_count"] == 100

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        from insights.queries.neo4j_queries import query_artist_centrality

        driver = _make_mock_driver([])
        await query_artist_centrality(driver, limit=50)
        call_args = driver.session.return_value.__aenter__.return_value.run.call_args
        # Verify LIMIT is passed as a parameter
        assert call_args[1].get("limit") == 50 or (len(call_args[0]) > 1 and call_args[0][1].get("limit") == 50)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/insights/test_neo4j_queries.py::TestQueryArtistCentrality -v`
Expected: FAIL

- [ ] **Step 3: Implement artist centrality query**

Create `insights/queries/__init__.py` — empty file.

Create `insights/queries/neo4j_queries.py`:

```python
"""Neo4j Cypher queries for insights computations.

Each function takes an AsyncResilientNeo4jDriver (or compatible async driver),
executes a Cypher query, and returns a list of dicts.
"""

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def query_artist_centrality(driver: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Query top artists by total edge count (degree centrality).

    Counts all relationships connected to each Artist node:
    releases, labels, aliases, groups, and collaborations.
    """
    cypher = """
    MATCH (a:Artist)
    WITH a, size([(a)-[]-() | 1]) AS edge_count
    ORDER BY edge_count DESC
    LIMIT $limit
    RETURN a.id AS artist_id, a.name AS artist_name, edge_count
    """
    results: list[dict[str, Any]] = []
    async with driver.session(database="neo4j") as session:
        result = await session.run(cypher, {"limit": limit})
        async for record in result:
            results.append(record.data())
    logger.info("🔍 Artist centrality query complete", count=len(results))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/insights/test_neo4j_queries.py::TestQueryArtistCentrality -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add insights/queries/ tests/insights/test_neo4j_queries.py
git commit -m "feat(insights): add artist centrality Neo4j query"
```

---

### Task 5: Neo4j Queries — Genre Trends, Label Longevity, Anniversaries

**Files:**
- Modify: `insights/queries/neo4j_queries.py`
- Modify: `tests/insights/test_neo4j_queries.py`

- [ ] **Step 1: Write failing tests for genre trends query**

Add to `tests/insights/test_neo4j_queries.py`:

```python
class TestQueryGenreTrends:
    @pytest.mark.asyncio
    async def test_returns_genre_decade_counts(self) -> None:
        from insights.queries.neo4j_queries import query_genre_trends

        records = [
            {"genre": "Rock", "decade": 1970, "release_count": 50000},
            {"genre": "Rock", "decade": 1980, "release_count": 75000},
            {"genre": "Jazz", "decade": 1960, "release_count": 30000},
        ]
        driver = _make_mock_driver(records)
        result = await query_genre_trends(driver)
        assert len(result) == 3
        assert result[0]["genre"] == "Rock"

    @pytest.mark.asyncio
    async def test_filters_by_genre(self) -> None:
        from insights.queries.neo4j_queries import query_genre_trends

        driver = _make_mock_driver([{"genre": "Jazz", "decade": 1960, "release_count": 30000}])
        result = await query_genre_trends(driver, genre="Jazz")
        assert len(result) == 1
        assert result[0]["genre"] == "Jazz"
```

- [ ] **Step 2: Write failing tests for label longevity query**

Add to `tests/insights/test_neo4j_queries.py`:

```python
class TestQueryLabelLongevity:
    @pytest.mark.asyncio
    async def test_returns_ranked_labels(self) -> None:
        from insights.queries.neo4j_queries import query_label_longevity

        records = [
            {
                "label_id": "l1",
                "label_name": "Blue Note",
                "first_year": 1939,
                "last_year": 2025,
                "years_active": 86,
                "total_releases": 4500,
                "peak_decade": 1960,
            },
        ]
        driver = _make_mock_driver(records)
        result = await query_label_longevity(driver, limit=50)
        assert len(result) == 1
        assert result[0]["years_active"] == 86
```

- [ ] **Step 3: Write failing tests for anniversary query**

Add to `tests/insights/test_neo4j_queries.py`:

```python
class TestQueryAnniversaries:
    @pytest.mark.asyncio
    async def test_returns_anniversary_releases(self) -> None:
        from insights.queries.neo4j_queries import query_monthly_anniversaries

        records = [
            {
                "master_id": "m1",
                "title": "OK Computer",
                "artist_name": "Radiohead",
                "release_year": 1997,
            },
        ]
        driver = _make_mock_driver(records)
        result = await query_monthly_anniversaries(driver, current_year=2022, current_month=6)
        assert len(result) == 1
        assert result[0]["master_id"] == "m1"
```

- [ ] **Step 4: Run all tests to verify they fail**

Run: `uv run pytest tests/insights/test_neo4j_queries.py -v`
Expected: FAIL for the 3 new test classes

- [ ] **Step 5: Implement genre trends query**

Add to `insights/queries/neo4j_queries.py`:

```python
async def query_genre_trends(driver: Any, genre: str | None = None) -> list[dict[str, Any]]:
    """Query release counts per genre per decade.

    Groups releases by their genres and the decade of release,
    counting how many releases fall into each genre/decade bucket.
    """
    if genre:
        cypher = """
        MATCH (r:Release)-[:HAS_GENRE]->(g:Genre {name: $genre})
        WHERE r.year IS NOT NULL AND r.year > 0
        WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
        ORDER BY decade
        RETURN genre, decade, release_count
        """
        params: dict[str, Any] = {"genre": genre}
    else:
        cypher = """
        MATCH (r:Release)-[:HAS_GENRE]->(g:Genre)
        WHERE r.year IS NOT NULL AND r.year > 0
        WITH g.name AS genre, (r.year / 10) * 10 AS decade, count(r) AS release_count
        ORDER BY genre, decade
        RETURN genre, decade, release_count
        """
        params = {}

    results: list[dict[str, Any]] = []
    async with driver.session(database="neo4j") as session:
        result = await session.run(cypher, params)
        async for record in result:
            results.append(record.data())
    logger.info("🔍 Genre trends query complete", count=len(results), genre=genre)
    return results
```

- [ ] **Step 6: Implement label longevity query**

Add to `insights/queries/neo4j_queries.py`:

```python
async def query_label_longevity(driver: Any, limit: int = 50) -> list[dict[str, Any]]:
    """Query labels ranked by years of active operation.

    For each label, finds the earliest and latest release year,
    calculates years active, total releases, and peak decade.
    """
    cypher = """
    MATCH (l:Label)<-[:RELEASED_ON]-(r:Release)
    WHERE r.year IS NOT NULL AND r.year > 0
    WITH l,
         min(r.year) AS first_year,
         max(r.year) AS last_year,
         count(r) AS total_releases,
         collect(r.year) AS years
    WITH l, first_year, last_year, total_releases,
         last_year - first_year + 1 AS years_active,
         reduce(acc = {decade: 0, count: 0}, y IN years |
             CASE WHEN acc.count < 1 THEN {decade: (y / 10) * 10, count: 1}
             ELSE acc END
         ) AS _peak_placeholder
    WITH l, first_year, last_year, total_releases, years_active, years
    UNWIND years AS y
    WITH l, first_year, last_year, total_releases, years_active,
         (y / 10) * 10 AS decade, count(*) AS decade_count
    ORDER BY decade_count DESC
    WITH l, first_year, last_year, total_releases, years_active,
         collect({decade: decade, count: decade_count})[0].decade AS peak_decade
    ORDER BY years_active DESC
    LIMIT $limit
    RETURN l.id AS label_id, l.name AS label_name,
           first_year, last_year, years_active,
           total_releases, peak_decade
    """
    results: list[dict[str, Any]] = []
    async with driver.session(database="neo4j") as session:
        result = await session.run(cypher, {"limit": limit})
        async for record in result:
            results.append(record.data())
    logger.info("🔍 Label longevity query complete", count=len(results))
    return results
```

- [ ] **Step 7: Implement monthly anniversaries query**

Add to `insights/queries/neo4j_queries.py`:

```python
async def query_monthly_anniversaries(
    driver: Any,
    current_year: int,
    current_month: int,
    milestone_years: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Query releases with notable anniversaries this month.

    Finds Master releases whose release year creates a milestone
    anniversary (25, 30, 40, 50, 75, 100 years) in the current year.
    """
    if milestone_years is None:
        milestone_years = [25, 30, 40, 50, 75, 100]

    # Build target years from milestones
    target_years = [current_year - m for m in milestone_years]

    cypher = """
    MATCH (m:Master)
    WHERE m.year IN $target_years AND m.year > 0
    OPTIONAL MATCH (m)<-[:MASTER_OF]-(r:Release)<-[:PERFORMED]-(a:Artist)
    WITH m, collect(DISTINCT a.name)[0] AS artist_name
    RETURN m.id AS master_id, m.title AS title, artist_name,
           m.year AS release_year
    ORDER BY m.year ASC
    """
    results: list[dict[str, Any]] = []
    async with driver.session(database="neo4j") as session:
        result = await session.run(cypher, {"target_years": target_years})
        async for record in result:
            results.append(record.data())
    logger.info("🔍 Monthly anniversaries query complete", count=len(results), month=current_month, year=current_year)
    return results
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `uv run pytest tests/insights/test_neo4j_queries.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add insights/queries/neo4j_queries.py tests/insights/test_neo4j_queries.py
git commit -m "feat(insights): add genre trends, label longevity, and anniversary Neo4j queries"
```

---

### Task 6: PostgreSQL Queries — Data Completeness

**Files:**
- Create: `insights/queries/pg_queries.py`
- Create: `tests/insights/test_pg_queries.py`

- [ ] **Step 1: Write failing tests for data completeness query**

Create `tests/insights/test_pg_queries.py`:

```python
"""Tests for insights PostgreSQL query functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_pool(rows: list[tuple[Any, ...]]) -> AsyncMock:
    """Create a mock AsyncPostgreSQLPool that returns given rows."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)
    mock_cursor.execute = AsyncMock()

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


class TestQueryDataCompleteness:
    @pytest.mark.asyncio
    async def test_returns_completeness_for_all_entity_types(self) -> None:
        from insights.queries.pg_queries import query_data_completeness

        # Each call returns a different count — mock will be called 4 times
        mock_pool = _make_mock_pool([(1000,)])
        result = await query_data_completeness(mock_pool)
        # Should have entries for artists, labels, masters, releases
        assert len(result) == 4
        entity_types = {r["entity_type"] for r in result}
        assert entity_types == {"artists", "labels", "masters", "releases"}

    @pytest.mark.asyncio
    async def test_handles_empty_tables(self) -> None:
        from insights.queries.pg_queries import query_data_completeness

        mock_pool = _make_mock_pool([(0,)])
        result = await query_data_completeness(mock_pool)
        for item in result:
            assert item["total_count"] == 0
            assert item["completeness_pct"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/insights/test_pg_queries.py -v`
Expected: FAIL

- [ ] **Step 3: Implement data completeness query**

Create `insights/queries/pg_queries.py`:

```python
"""PostgreSQL queries for insights computations.

Each function takes an AsyncPostgreSQLPool, executes queries against
the Discogs entity tables, and returns typed results.
"""

from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)

# Fields to check for completeness, per entity type.
# Each tuple is (entity_type, list_of_(field_name, jsonb_key)_pairs).
_COMPLETENESS_FIELDS: dict[str, list[tuple[str, str]]] = {
    "artists": [("with_image", "images")],
    "labels": [("with_image", "images")],
    "masters": [("with_year", "year"), ("with_genre", "genres"), ("with_image", "images")],
    "releases": [
        ("with_year", "year"),
        ("with_country", "country"),
        ("with_genre", "genres"),
        ("with_image", "images"),
    ],
}


async def query_data_completeness(pool: Any) -> list[dict[str, Any]]:
    """Compute data completeness scores for each entity type.

    For each entity table, counts total records and how many have
    non-null/non-empty values for key metadata fields.
    """
    results: list[dict[str, Any]] = []

    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)

            for entity_type, fields in _COMPLETENESS_FIELDS.items():
                # Get total count
                await cursor.execute(f"SELECT count(*) FROM {entity_type}")  # noqa: S608
                row = await cursor.fetchall()
                total_count = row[0][0] if row else 0

                item: dict[str, Any] = {
                    "entity_type": entity_type,
                    "total_count": total_count,
                    "with_image": 0,
                    "with_year": 0,
                    "with_country": 0,
                    "with_genre": 0,
                }

                if total_count > 0:
                    for field_name, jsonb_key in fields:
                        # Check for non-null and non-empty values
                        await cursor.execute(
                            f"SELECT count(*) FROM {entity_type} "  # noqa: S608
                            f"WHERE data->>'{jsonb_key}' IS NOT NULL "
                            f"AND data->>'{jsonb_key}' != '' "
                            f"AND data->>'{jsonb_key}' != '[]'"
                        )
                        field_row = await cursor.fetchall()
                        item[field_name] = field_row[0][0] if field_row else 0

                    # Compute overall completeness (average of available field percentages)
                    field_pcts = []
                    for field_name, _ in fields:
                        field_pcts.append(item[field_name] / total_count * 100)
                    item["completeness_pct"] = round(sum(field_pcts) / len(field_pcts), 2) if field_pcts else 0.0
                else:
                    item["completeness_pct"] = 0.0

                results.append(item)

    logger.info("🔍 Data completeness query complete", entity_count=len(results))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/insights/test_pg_queries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add insights/queries/pg_queries.py tests/insights/test_pg_queries.py
git commit -m "feat(insights): add data completeness PostgreSQL queries"
```

---

## Chunk 3: Computation Orchestration and Result Storage

This chunk implements the computation layer that orchestrates query execution, writes results to the insights PostgreSQL tables, and logs computation status.

### Task 7: Computation Orchestrator

**Files:**
- Create: `insights/computations.py`
- Create: `tests/insights/test_computations.py`

- [ ] **Step 1: Write failing tests for store_artist_centrality**

Create `tests/insights/test_computations.py`:

```python
"""Tests for insights computation orchestration."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_pool() -> AsyncMock:
    """Create a mock pool for storing results."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(1,))

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    return mock_pool


class TestComputeAndStoreArtistCentrality:
    @pytest.mark.asyncio
    async def test_queries_neo4j_and_stores_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_artist_centrality") as mock_query:
            mock_query.return_value = [
                {"artist_id": "a1", "artist_name": "Artist One", "edge_count": 100},
            ]
            rows = await compute_and_store_artist_centrality(mock_driver, mock_pool)

        assert rows == 1
        mock_query.assert_called_once_with(mock_driver, limit=100)

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        from insights.computations import compute_and_store_artist_centrality

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_artist_centrality") as mock_query:
            mock_query.return_value = []
            rows = await compute_and_store_artist_centrality(mock_driver, mock_pool)

        assert rows == 0


class TestComputeAndStoreGenreTrends:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_genre_trends

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_genre_trends") as mock_query:
            mock_query.return_value = [
                {"genre": "Rock", "decade": 1990, "release_count": 5000},
            ]
            rows = await compute_and_store_genre_trends(mock_driver, mock_pool)

        assert rows == 1


class TestComputeAndStoreLabelLongevity:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_label_longevity

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_label_longevity") as mock_query:
            mock_query.return_value = [
                {
                    "label_id": "l1",
                    "label_name": "Blue Note",
                    "first_year": 1939,
                    "last_year": 2025,
                    "years_active": 86,
                    "total_releases": 4500,
                    "peak_decade": 1960,
                },
            ]
            rows = await compute_and_store_label_longevity(mock_driver, mock_pool)

        assert rows == 1


class TestComputeAndStoreAnniversaries:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_anniversaries

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_monthly_anniversaries") as mock_query:
            mock_query.return_value = [
                {"master_id": "m1", "title": "OK Computer", "artist_name": "Radiohead", "release_year": 1997},
            ]
            rows = await compute_and_store_anniversaries(mock_driver, mock_pool, current_year=2022, current_month=6)

        assert rows == 1


class TestComputeAndStoreDataCompleteness:
    @pytest.mark.asyncio
    async def test_queries_and_stores(self) -> None:
        from insights.computations import compute_and_store_data_completeness

        mock_pool = _make_mock_pool()

        with patch("insights.computations.query_data_completeness") as mock_query:
            mock_query.return_value = [
                {
                    "entity_type": "releases",
                    "total_count": 15000000,
                    "with_image": 12000000,
                    "with_year": 14500000,
                    "with_country": 13000000,
                    "with_genre": 14000000,
                    "completeness_pct": 89.67,
                },
            ]
            rows = await compute_and_store_data_completeness(mock_pool)

        assert rows == 1


class TestRunAllComputations:
    @pytest.mark.asyncio
    async def test_runs_all_five(self) -> None:
        from insights.computations import run_all_computations

        mock_driver = AsyncMock()
        mock_pool = _make_mock_pool()

        with (
            patch("insights.computations.compute_and_store_artist_centrality", return_value=10) as mock_ac,
            patch("insights.computations.compute_and_store_genre_trends", return_value=20) as mock_gt,
            patch("insights.computations.compute_and_store_label_longevity", return_value=5) as mock_ll,
            patch("insights.computations.compute_and_store_anniversaries", return_value=3) as mock_an,
            patch("insights.computations.compute_and_store_data_completeness", return_value=4) as mock_dc,
        ):
            results = await run_all_computations(mock_driver, mock_pool)

        assert results["artist_centrality"] == 10
        assert results["genre_trends"] == 20
        assert results["label_longevity"] == 5
        assert results["anniversaries"] == 3
        assert results["data_completeness"] == 4
        mock_ac.assert_called_once()
        mock_gt.assert_called_once()
        mock_ll.assert_called_once()
        mock_an.assert_called_once()
        mock_dc.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/insights/test_computations.py -v`
Expected: FAIL

- [ ] **Step 3: Implement computation orchestrator**

Create `insights/computations.py`:

```python
"""Computation orchestration for insights.

Each compute_and_store_* function:
1. Runs the corresponding query against Neo4j or PostgreSQL
2. Clears the previous results from the insights table
3. Inserts the new results
4. Returns the number of rows written
"""

from datetime import UTC, datetime
from typing import Any, cast

import structlog

from insights.queries.neo4j_queries import (
    query_artist_centrality,
    query_genre_trends,
    query_label_longevity,
    query_monthly_anniversaries,
)
from insights.queries.pg_queries import query_data_completeness

logger = structlog.get_logger(__name__)


async def _log_computation(
    pool: Any,
    insight_type: str,
    status: str,
    started_at: datetime,
    rows_affected: int = 0,
    error_message: str | None = None,
) -> None:
    """Write a computation log entry."""
    completed_at = datetime.now(UTC)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            await cursor.execute(
                """
                INSERT INTO insights.computation_log
                    (insight_type, status, started_at, completed_at, rows_affected, duration_ms, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (insight_type, status, started_at, completed_at, rows_affected, duration_ms, error_message),
            )


async def compute_and_store_artist_centrality(driver: Any, pool: Any, limit: int = 100) -> int:
    """Compute artist centrality and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await query_artist_centrality(driver, limit=limit)
        if not results:
            logger.info("📊 No artist centrality results to store")
            await _log_computation(pool, "artist_centrality", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                cursor = cast(Any, cursor)
                await cursor.execute("DELETE FROM insights.artist_centrality")
                for rank, row in enumerate(results, 1):
                    await cursor.execute(
                        """
                        INSERT INTO insights.artist_centrality (rank, artist_id, artist_name, edge_count)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (rank, row["artist_id"], row["artist_name"], row["edge_count"]),
                    )
        logger.info("📊 Artist centrality stored", count=len(results))
        await _log_computation(pool, "artist_centrality", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Artist centrality computation failed", error=str(e))
        await _log_computation(pool, "artist_centrality", "failed", started_at, error_message=str(e))
        raise


async def compute_and_store_genre_trends(driver: Any, pool: Any) -> int:
    """Compute genre trends and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await query_genre_trends(driver)
        if not results:
            await _log_computation(pool, "genre_trends", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                cursor = cast(Any, cursor)
                await cursor.execute("DELETE FROM insights.genre_trends")
                for row in results:
                    await cursor.execute(
                        """
                        INSERT INTO insights.genre_trends (genre, decade, release_count)
                        VALUES (%s, %s, %s)
                        """,
                        (row["genre"], row["decade"], row["release_count"]),
                    )
        logger.info("📊 Genre trends stored", count=len(results))
        await _log_computation(pool, "genre_trends", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Genre trends computation failed", error=str(e))
        await _log_computation(pool, "genre_trends", "failed", started_at, error_message=str(e))
        raise


async def compute_and_store_label_longevity(driver: Any, pool: Any, limit: int = 50) -> int:
    """Compute label longevity and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await query_label_longevity(driver, limit=limit)
        if not results:
            await _log_computation(pool, "label_longevity", "completed", started_at, 0)
            return 0

        current_year = datetime.now(UTC).year
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                cursor = cast(Any, cursor)
                await cursor.execute("DELETE FROM insights.label_longevity")
                for rank, row in enumerate(results, 1):
                    still_active = row["last_year"] >= current_year - 2
                    await cursor.execute(
                        """
                        INSERT INTO insights.label_longevity
                            (rank, label_id, label_name, first_year, last_year,
                             years_active, total_releases, peak_decade, still_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            rank, row["label_id"], row["label_name"],
                            row["first_year"], row["last_year"], row["years_active"],
                            row["total_releases"], row.get("peak_decade"), still_active,
                        ),
                    )
        logger.info("📊 Label longevity stored", count=len(results))
        await _log_computation(pool, "label_longevity", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Label longevity computation failed", error=str(e))
        await _log_computation(pool, "label_longevity", "failed", started_at, error_message=str(e))
        raise


async def compute_and_store_anniversaries(
    driver: Any, pool: Any, current_year: int | None = None, current_month: int | None = None
) -> int:
    """Compute monthly anniversaries and store results."""
    started_at = datetime.now(UTC)
    now = datetime.now(UTC)
    year = current_year or now.year
    month = current_month or now.month

    try:
        results = await query_monthly_anniversaries(driver, current_year=year, current_month=month)
        if not results:
            await _log_computation(pool, "anniversaries", "completed", started_at, 0)
            return 0

        milestone_years = [25, 30, 40, 50, 75, 100]
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                cursor = cast(Any, cursor)
                # Clear previous month's data
                await cursor.execute(
                    "DELETE FROM insights.monthly_anniversaries WHERE computed_year = %s AND computed_month = %s",
                    (year, month),
                )
                for row in results:
                    anniversary = year - row["release_year"]
                    if anniversary in milestone_years:
                        await cursor.execute(
                            """
                            INSERT INTO insights.monthly_anniversaries
                                (master_id, title, artist_name, release_year, anniversary,
                                 computed_month, computed_year)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (master_id, computed_year, computed_month) DO UPDATE
                            SET title = EXCLUDED.title, artist_name = EXCLUDED.artist_name,
                                anniversary = EXCLUDED.anniversary, computed_at = NOW()
                            """,
                            (row["master_id"], row["title"], row.get("artist_name"),
                             row["release_year"], anniversary, month, year),
                        )
        logger.info("📊 Monthly anniversaries stored", count=len(results), year=year, month=month)
        await _log_computation(pool, "anniversaries", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Anniversaries computation failed", error=str(e))
        await _log_computation(pool, "anniversaries", "failed", started_at, error_message=str(e))
        raise


async def compute_and_store_data_completeness(pool: Any) -> int:
    """Compute data completeness and store results."""
    started_at = datetime.now(UTC)
    try:
        results = await query_data_completeness(pool)
        if not results:
            await _log_computation(pool, "data_completeness", "completed", started_at, 0)
            return 0

        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                cursor = cast(Any, cursor)
                await cursor.execute("DELETE FROM insights.data_completeness")
                for row in results:
                    await cursor.execute(
                        """
                        INSERT INTO insights.data_completeness
                            (entity_type, total_count, with_image, with_year,
                             with_country, with_genre, completeness_pct)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            row["entity_type"], row["total_count"],
                            row["with_image"], row["with_year"],
                            row["with_country"], row["with_genre"],
                            row["completeness_pct"],
                        ),
                    )
        logger.info("📊 Data completeness stored", count=len(results))
        await _log_computation(pool, "data_completeness", "completed", started_at, len(results))
        return len(results)
    except Exception as e:
        logger.error("❌ Data completeness computation failed", error=str(e))
        await _log_computation(pool, "data_completeness", "failed", started_at, error_message=str(e))
        raise


async def run_all_computations(driver: Any, pool: Any) -> dict[str, int]:
    """Run all insight computations and return row counts per type."""
    logger.info("🚀 Starting all insight computations...")
    results: dict[str, int] = {}

    results["artist_centrality"] = await compute_and_store_artist_centrality(driver, pool)
    results["genre_trends"] = await compute_and_store_genre_trends(driver, pool)
    results["label_longevity"] = await compute_and_store_label_longevity(driver, pool)
    results["anniversaries"] = await compute_and_store_anniversaries(driver, pool)
    results["data_completeness"] = await compute_and_store_data_completeness(pool)

    total = sum(results.values())
    logger.info("✅ All insight computations complete", total_rows=total, breakdown=results)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/insights/test_computations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add insights/computations.py tests/insights/test_computations.py
git commit -m "feat(insights): add computation orchestration with PostgreSQL storage"
```

---

## Chunk 4: Service Layer — FastAPI App, Scheduler, and Endpoints

This chunk builds the actual insights microservice — the FastAPI app with lifespan management, the async scheduler loop, health endpoint, and all 5 read-only insight API endpoints.

### Task 8: FastAPI Application with Scheduler

**Files:**
- Create: `insights/insights.py`
- Create: `tests/insights/test_insights.py`
- Create: `tests/insights/test_scheduler.py`
- Create: `tests/insights/conftest.py`

- [ ] **Step 1: Write test fixtures**

Create `tests/insights/conftest.py`:

```python
"""Shared fixtures for insights tests."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_neo4j_driver() -> AsyncMock:
    """Mock Neo4j driver."""
    driver = AsyncMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver.session = MagicMock(return_value=session)
    return driver


@pytest.fixture
def mock_pg_pool() -> AsyncMock:
    """Mock PostgreSQL pool."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    pool = AsyncMock()
    pool.connection = MagicMock(return_value=mock_conn)
    return pool


@pytest.fixture
def test_client(mock_neo4j_driver: AsyncMock, mock_pg_pool: AsyncMock) -> TestClient:
    """Create a test client with mocked dependencies."""
    import insights.insights as _module

    _module._neo4j = mock_neo4j_driver
    _module._pool = mock_pg_pool

    from insights.insights import app

    return TestClient(app)
```

- [ ] **Step 2: Write failing tests for endpoints**

Create `tests/insights/test_insights.py`:

```python
"""Tests for insights FastAPI endpoints."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    def test_health_returns_200(self, test_client: TestClient) -> None:
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "insights"
        assert "status" in data


class TestTopArtistsEndpoint:
    def test_returns_artists(self, test_client: TestClient, mock_pg_pool: AsyncMock) -> None:
        mock_cursor = mock_pg_pool.connection.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
        mock_cursor.fetchall.return_value = [
            (1, "a1", "Radiohead", 5432, "2026-03-14T00:00:00+00:00"),
        ]
        from psycopg.rows import dict_row  # noqa: F401

        response = test_client.get("/api/insights/top-artists?limit=10")
        assert response.status_code == 200

    def test_default_limit_is_100(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/top-artists")
        assert response.status_code == 200


class TestGenreTrendsEndpoint:
    def test_requires_genre_param(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/genre-trends")
        assert response.status_code == 422  # Missing required query param

    def test_returns_trends_for_genre(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/genre-trends?genre=Jazz")
        assert response.status_code == 200


class TestLabelLongevityEndpoint:
    def test_returns_labels(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/label-longevity?limit=10")
        assert response.status_code == 200


class TestThisMonthEndpoint:
    def test_returns_anniversaries(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/this-month")
        assert response.status_code == 200


class TestDataCompletenessEndpoint:
    def test_returns_completeness(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/data-completeness")
        assert response.status_code == 200


class TestComputationStatusEndpoint:
    def test_returns_status(self, test_client: TestClient) -> None:
        response = test_client.get("/api/insights/status")
        assert response.status_code == 200
```

- [ ] **Step 3: Write failing tests for scheduler**

Create `tests/insights/test_scheduler.py`:

```python
"""Tests for the insights scheduler loop."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestSchedulerLoop:
    @pytest.mark.asyncio
    async def test_runs_computations_once_then_sleeps(self) -> None:
        """Verify the scheduler calls run_all_computations and then sleeps."""
        from insights.insights import _scheduler_loop

        mock_driver = AsyncMock()
        mock_pool = AsyncMock()

        call_count = 0

        async def mock_run_all(driver: object, pool: object) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError  # Stop after 2nd call
            return {"test": 1}

        with patch("insights.insights.run_all_computations", side_effect=mock_run_all):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(asyncio.CancelledError):
                    await _scheduler_loop(mock_driver, mock_pool, interval_hours=1)

        assert call_count == 2
        mock_sleep.assert_called_with(3600)  # 1 hour in seconds

    @pytest.mark.asyncio
    async def test_continues_on_computation_error(self) -> None:
        """Verify the scheduler continues running even if a computation fails."""
        from insights.insights import _scheduler_loop

        mock_driver = AsyncMock()
        mock_pool = AsyncMock()
        call_count = 0

        async def mock_run_all(driver: object, pool: object) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Neo4j unavailable")
            raise asyncio.CancelledError

        with patch("insights.insights.run_all_computations", side_effect=mock_run_all):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(asyncio.CancelledError):
                    await _scheduler_loop(mock_driver, mock_pool, interval_hours=1)

        assert call_count == 2  # Continued past the error
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/insights/test_insights.py tests/insights/test_scheduler.py -v`
Expected: FAIL

- [ ] **Step 5: Implement the insights FastAPI application**

Create `insights/insights.py`:

```python
"""Insights microservice — precomputed analytics and music trends.

Runs scheduled batch analytics against Neo4j and PostgreSQL,
stores precomputed results in insights.* PostgreSQL tables,
and exposes them via read-only API endpoints.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import structlog
import uvicorn

from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver, HealthServer, setup_logging
from common.config import InsightsConfig
from insights.computations import run_all_computations
from insights.models import (
    AnniversaryItem,
    ArtistCentralityItem,
    ComputationStatus,
    DataCompletenessItem,
    GenreTrendItem,
    GenreTrendsResponse,
    LabelLongevityItem,
)

logger = structlog.get_logger(__name__)

INSIGHTS_PORT = 8008
INSIGHTS_HEALTH_PORT = 8009

# Module-level state
_config: InsightsConfig | None = None
_neo4j: AsyncResilientNeo4jDriver | None = None
_pool: AsyncPostgreSQLPool | None = None
_scheduler_task: asyncio.Task[None] | None = None
_last_computation: datetime | None = None


def get_health_data() -> dict[str, Any]:
    """Return health data for the health server."""
    return {
        "service": "insights",
        "status": "healthy" if _pool and _neo4j else "starting",
        "timestamp": datetime.now(UTC).isoformat(),
        "last_computation": _last_computation.isoformat() if _last_computation else None,
    }


async def _scheduler_loop(driver: Any, pool: Any, interval_hours: int = 24) -> None:
    """Run insight computations on a recurring schedule."""
    global _last_computation
    interval_seconds = interval_hours * 3600

    while True:
        try:
            logger.info("⏰ Scheduler: starting insight computations...")
            await run_all_computations(driver, pool)
            _last_computation = datetime.now(UTC)
            logger.info("✅ Scheduler: computations complete", next_run_hours=interval_hours)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("❌ Scheduler: computation cycle failed, will retry next interval")

        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage service lifecycle — connect to databases and start scheduler."""
    global _config, _neo4j, _pool, _scheduler_task

    setup_logging("insights", log_file=Path("/logs/insights.log"))
    logger.info("🚀 Insights service starting...")

    _config = InsightsConfig.from_env()

    # Start health server
    health_srv = HealthServer(INSIGHTS_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("🏥 Health server started", port=INSIGHTS_HEALTH_PORT)

    # Initialize PostgreSQL
    host, port_str = _config.postgres_host.rsplit(":", 1)
    _pool = AsyncPostgreSQLPool(
        connection_params={
            "host": host,
            "port": int(port_str),
            "dbname": _config.postgres_database,
            "user": _config.postgres_username,
            "password": _config.postgres_password,
        },
        max_connections=5,
        min_connections=1,
    )
    await _pool.initialize()
    logger.info("💾 PostgreSQL pool initialized")

    # Initialize Neo4j
    _neo4j = AsyncResilientNeo4jDriver(
        uri=_config.neo4j_host,
        auth=(_config.neo4j_username, _config.neo4j_password),
        max_retries=5,
        encrypted=False,
    )
    logger.info("🔗 Neo4j driver initialized")

    # Start scheduler
    _scheduler_task = asyncio.create_task(
        _scheduler_loop(_neo4j, _pool, interval_hours=_config.schedule_hours)
    )
    logger.info("⏰ Scheduler started", interval_hours=_config.schedule_hours)

    logger.info("✅ Insights service ready", port=INSIGHTS_PORT)
    yield

    # Shutdown
    logger.info("🔧 Insights service shutting down...")
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    if _neo4j:
        await _neo4j.close()
    if _pool:
        await _pool.close()
    health_srv.stop()
    logger.info("✅ Insights service stopped")


app = FastAPI(
    title="Discogsography Insights",
    version="0.1.0",
    description="Precomputed analytics and music trends",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Service health check endpoint."""
    return JSONResponse(content=get_health_data())


@app.get("/api/insights/top-artists")
async def top_artists(
    limit: int = Query(100, ge=1, le=500),
    metric: str = Query("centrality"),
) -> JSONResponse:
    """Return top artists by centrality (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    async with _pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            await cursor.execute(
                "SELECT rank, artist_id, artist_name, edge_count, computed_at "
                "FROM insights.artist_centrality ORDER BY rank LIMIT %s",
                (limit,),
            )
            rows = await cursor.fetchall()

    items = [
        ArtistCentralityItem(rank=r[0], artist_id=r[1], artist_name=r[2], edge_count=r[3]).model_dump()
        for r in rows
    ]
    return JSONResponse(content={"metric": metric, "items": items, "count": len(items)})


@app.get("/api/insights/genre-trends")
async def genre_trends(genre: str = Query(...)) -> JSONResponse:
    """Return release count per decade for a specific genre (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    async with _pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            await cursor.execute(
                "SELECT genre, decade, release_count FROM insights.genre_trends "
                "WHERE genre = %s ORDER BY decade",
                (genre,),
            )
            rows = await cursor.fetchall()

    trends = [GenreTrendItem(decade=r[1], release_count=r[2]).model_dump() for r in rows]
    peak = max(trends, key=lambda t: t["release_count"])["decade"] if trends else None
    resp = GenreTrendsResponse(genre=genre, trends=[GenreTrendItem(**t) for t in trends], peak_decade=peak)
    return JSONResponse(content=resp.model_dump())


@app.get("/api/insights/label-longevity")
async def label_longevity(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """Return labels ranked by years of active operation (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    async with _pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            await cursor.execute(
                "SELECT rank, label_id, label_name, first_year, last_year, "
                "years_active, total_releases, peak_decade, still_active "
                "FROM insights.label_longevity ORDER BY rank LIMIT %s",
                (limit,),
            )
            rows = await cursor.fetchall()

    items = [
        LabelLongevityItem(
            rank=r[0], label_id=r[1], label_name=r[2], first_year=r[3], last_year=r[4],
            years_active=r[5], total_releases=r[6], peak_decade=r[7], still_active=r[8],
        ).model_dump()
        for r in rows
    ]
    return JSONResponse(content={"items": items, "count": len(items)})


@app.get("/api/insights/this-month")
async def this_month() -> JSONResponse:
    """Return releases with notable anniversaries this calendar month (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    now = datetime.now(UTC)
    async with _pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            await cursor.execute(
                "SELECT master_id, title, artist_name, release_year, anniversary "
                "FROM insights.monthly_anniversaries "
                "WHERE computed_year = %s AND computed_month = %s "
                "ORDER BY anniversary DESC, release_year ASC",
                (now.year, now.month),
            )
            rows = await cursor.fetchall()

    items = [
        AnniversaryItem(
            master_id=r[0], title=r[1], artist_name=r[2], release_year=r[3], anniversary=r[4],
        ).model_dump()
        for r in rows
    ]
    return JSONResponse(content={"month": now.month, "year": now.year, "items": items, "count": len(items)})


@app.get("/api/insights/data-completeness")
async def data_completeness() -> JSONResponse:
    """Return data completeness scores per entity type (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    async with _pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            await cursor.execute(
                "SELECT entity_type, total_count, with_image, with_year, "
                "with_country, with_genre, completeness_pct "
                "FROM insights.data_completeness ORDER BY entity_type"
            )
            rows = await cursor.fetchall()

    items = [
        DataCompletenessItem(
            entity_type=r[0], total_count=r[1], with_image=r[2], with_year=r[3],
            with_country=r[4], with_genre=r[5], completeness_pct=float(r[6]),
        ).model_dump()
        for r in rows
    ]
    return JSONResponse(content={"items": items, "count": len(items)})


@app.get("/api/insights/status")
async def computation_status() -> JSONResponse:
    """Return the latest computation status for each insight type."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    insight_types = ["artist_centrality", "genre_trends", "label_longevity", "anniversaries", "data_completeness"]
    statuses: list[dict[str, Any]] = []

    async with _pool.connection() as conn:
        async with conn.cursor() as cursor:
            cursor = cast(Any, cursor)
            for itype in insight_types:
                await cursor.execute(
                    "SELECT insight_type, status, completed_at, duration_ms "
                    "FROM insights.computation_log "
                    "WHERE insight_type = %s ORDER BY started_at DESC LIMIT 1",
                    (itype,),
                )
                row = await cursor.fetchone()
                if row:
                    statuses.append(
                        ComputationStatus(
                            insight_type=row[0], status=row[1],
                            last_computed=row[2], duration_ms=row[3],
                        ).model_dump()
                    )
                else:
                    statuses.append(
                        ComputationStatus(insight_type=itype, status="never_run").model_dump()
                    )

    return JSONResponse(content={"statuses": statuses})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=INSIGHTS_PORT)  # noqa: S104
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/insights/test_insights.py tests/insights/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add insights/insights.py tests/insights/conftest.py tests/insights/test_insights.py tests/insights/test_scheduler.py
git commit -m "feat(insights): add FastAPI app with scheduler and read-only endpoints"
```

---

## Chunk 5: API Proxy, Infrastructure, and CI Integration

This chunk wires the insights service into the broader platform — API proxy router, Docker configuration, justfile tasks, CI workflow, and codecov.

### Task 9: API Proxy Router

**Files:**
- Create: `api/routers/insights.py`
- Modify: `api/api.py`
- Create: `tests/api/test_insights_proxy.py`

The API service proxies `/api/insights/*` to the insights service using httpx, following the pattern established by the explore proxy.

- [ ] **Step 1: Write failing test for proxy router**

Create `tests/api/test_insights_proxy.py`:

```python
"""Tests for the insights API proxy router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


class TestInsightsProxy:
    def test_proxy_top_artists(self, test_client: TestClient) -> None:
        """Verify /api/insights/top-artists is proxied."""
        with patch("api.routers.insights._forward") as mock_fwd:
            mock_fwd.return_value = {"items": [], "count": 0}
            response = test_client.get("/api/insights/top-artists")
        assert response.status_code == 200

    def test_proxy_genre_trends(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward") as mock_fwd:
            mock_fwd.return_value = {"genre": "Jazz", "trends": [], "peak_decade": None}
            response = test_client.get("/api/insights/genre-trends?genre=Jazz")
        assert response.status_code == 200

    def test_proxy_label_longevity(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward") as mock_fwd:
            mock_fwd.return_value = {"items": [], "count": 0}
            response = test_client.get("/api/insights/label-longevity")
        assert response.status_code == 200

    def test_proxy_this_month(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward") as mock_fwd:
            mock_fwd.return_value = {"items": [], "count": 0}
            response = test_client.get("/api/insights/this-month")
        assert response.status_code == 200

    def test_proxy_data_completeness(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward") as mock_fwd:
            mock_fwd.return_value = {"items": [], "count": 0}
            response = test_client.get("/api/insights/data-completeness")
        assert response.status_code == 200

    def test_proxy_status(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward") as mock_fwd:
            mock_fwd.return_value = {"statuses": []}
            response = test_client.get("/api/insights/status")
        assert response.status_code == 200

    def test_proxy_returns_503_when_insights_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/top-artists")
        assert response.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_insights_proxy.py -v`
Expected: FAIL

- [ ] **Step 3: Implement proxy router**

Create `api/routers/insights.py`:

```python
"""Proxy router for insights service endpoints.

Forwards /api/insights/* requests to the insights microservice
running on port 8008.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()

_INSIGHTS_BASE_URL = "http://insights:8008"
_client: httpx.AsyncClient | None = None


def configure(insights_base_url: str | None = None) -> None:
    """Configure the insights proxy."""
    global _INSIGHTS_BASE_URL
    if insights_base_url:
        _INSIGHTS_BASE_URL = insights_base_url


async def _forward(request: Request, path: str) -> Any:
    """Forward a request to the insights service."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)

    url = f"{_INSIGHTS_BASE_URL}{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    response = await _client.get(url)
    return response.json()


@router.get("/api/insights/top-artists")
async def proxy_top_artists(request: Request) -> JSONResponse:
    """Proxy top artists endpoint."""
    try:
        data = await _forward(request, "/api/insights/top-artists")
        return JSONResponse(content=data)
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/genre-trends")
async def proxy_genre_trends(request: Request) -> JSONResponse:
    """Proxy genre trends endpoint."""
    try:
        data = await _forward(request, "/api/insights/genre-trends")
        return JSONResponse(content=data)
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/label-longevity")
async def proxy_label_longevity(request: Request) -> JSONResponse:
    """Proxy label longevity endpoint."""
    try:
        data = await _forward(request, "/api/insights/label-longevity")
        return JSONResponse(content=data)
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/this-month")
async def proxy_this_month(request: Request) -> JSONResponse:
    """Proxy this month endpoint."""
    try:
        data = await _forward(request, "/api/insights/this-month")
        return JSONResponse(content=data)
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/data-completeness")
async def proxy_data_completeness(request: Request) -> JSONResponse:
    """Proxy data completeness endpoint."""
    try:
        data = await _forward(request, "/api/insights/data-completeness")
        return JSONResponse(content=data)
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/status")
async def proxy_status(request: Request) -> JSONResponse:
    """Proxy computation status endpoint."""
    try:
        data = await _forward(request, "/api/insights/status")
        return JSONResponse(content=data)
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)
```

- [ ] **Step 4: Register proxy router in api/api.py**

Add import at `api/api.py:~44`:

```python
import api.routers.insights as _insights_router
```

Add router include at `api/api.py:~264` (after other router includes):

```python
app.include_router(_insights_router.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_insights_proxy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/insights.py api/api.py tests/api/test_insights_proxy.py
git commit -m "feat(insights): add API proxy router for insights endpoints"
```

---

### Task 10: Dockerfile

**Files:**
- Create: `insights/Dockerfile`

- [ ] **Step 1: Create Dockerfile**

Create `insights/Dockerfile` (follows the established api/Dockerfile pattern):

```dockerfile
# syntax=docker/dockerfile:1

# Build arguments
ARG PYTHON_VERSION=3.13
ARG UID=1000
ARG GID=1000

# nosemgrep: dockerfile.security.missing-user.missing-user
FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /bin/uv

# Set environment for build
ENV UV_SYSTEM_PYTHON=1 \
    UV_CACHE_DIR=/tmp/.cache/uv \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./
COPY common/pyproject.toml ./common/
COPY insights/pyproject.toml ./insights/

# Install dependencies and clean up
# hadolint ignore=SC2015
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev --extra insights && \
    find /app/.venv -type f -name "*.pyc" -delete && \
    find /app/.venv -type f -name "*.pyo" -delete && \
    find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -name "py.typed" -delete 2>/dev/null || true && \
    find /app/.venv -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true

# Copy source files
COPY common/ ./common/
COPY insights/ ./insights/

# Final stage
FROM python:${PYTHON_VERSION}-slim

ARG BUILD_DATE
ARG BUILD_VERSION
ARG VCS_REF
ARG UID=1000
ARG GID=1000

LABEL org.opencontainers.image.title="Discogsography Insights" \
      org.opencontainers.image.description="Precomputed analytics and music trends for Discogsography." \
      org.opencontainers.image.authors="Robert Wlodarczyk <robert@simplicityguy.com>" \
      org.opencontainers.image.url="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.source="https://github.com/SimplicityGuy/discogsography" \
      org.opencontainers.image.vendor="SimplicityGuy" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${BUILD_VERSION:-0.1.0}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/python:${PYTHON_VERSION}-slim" \
      com.discogsography.service="insights" \
      com.discogsography.python.version="${PYTHON_VERSION}"

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN groupadd -r -g ${GID} discogsography && \
    useradd -r -l -u ${UID} -g discogsography -m -s /bin/bash discogsography && \
    mkdir -p /tmp /app /logs && \
    chown -R discogsography:discogsography /tmp /app /logs

WORKDIR /app

COPY --from=builder --chown=discogsography:discogsography /app/.venv /app/.venv
COPY --from=builder --chown=discogsography:discogsography /app/common /app/common
COPY --from=builder --chown=discogsography:discogsography /app/insights /app/insights

# hadolint ignore=SC2016
RUN printf '#!/bin/sh\nset -e\nsleep "${STARTUP_DELAY:-0}"\nexec /app/.venv/bin/python -m insights.insights "$@"\n' > /app/start.sh && \
    chmod +x /app/start.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8009/health || exit 1

USER discogsography:discogsography

ENV HOME=/home/discogsography \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8008 8009

VOLUME ["/logs"]

CMD ["/app/start.sh"]
```

- [ ] **Step 2: Commit**

```bash
git add insights/Dockerfile
git commit -m "feat(insights): add Dockerfile"
```

---

### Task 11: Docker Compose Integration

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add insights service to docker-compose.yml**

Add after the `explore` service block (before `volumes:`):

```yaml
  # Insights service — precomputed analytics and music trends
  insights:
    build:
      context: .
      dockerfile: insights/Dockerfile
      args:
        PYTHON_VERSION: ${PYTHON_VERSION:-3.13}
        UID: ${UID:-1000}
        GID: ${GID:-1000}
    image: discogsography/insights:latest
    container_name: discogsography-insights
    hostname: insights
    user: "${UID:-1000}:${GID:-1000}"
    environment:
      INSIGHTS_SCHEDULE_HOURS: "24"
      NEO4J_HOST: neo4j
      NEO4J_PASSWORD: discogsography
      NEO4J_USERNAME: neo4j
      POSTGRES_DATABASE: discogsography
      POSTGRES_HOST: postgres
      POSTGRES_PASSWORD: discogsography
      POSTGRES_USERNAME: discogsography
      PYTHONUNBUFFERED: "1"
      STARTUP_DELAY: "10"
    depends_on:
      schema-init:
        condition: service_completed_successfully
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
    networks:
      - discogsography
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8009/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s
    restart: unless-stopped
    logging: *default-logging
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - insights_logs:/logs
```

Add `insights_logs:` to the `volumes:` section.

Also update the `api` service `depends_on` to include insights:

```yaml
      insights:
        condition: service_healthy
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(insights): add insights service to docker-compose.yml"
```

---

### Task 12: Coverage, Justfile, CI, and Codecov

**Files:**
- Create: `.coveragerc.insights`
- Modify: `justfile`
- Modify: `.github/workflows/test.yml`
- Modify: `codecov.yml`

- [ ] **Step 1: Create .coveragerc.insights**

Create `.coveragerc.insights`:

```ini
[run]
include = insights/**
relative_files = true
omit =
    */tests/*
    */__init__.py
```

- [ ] **Step 2: Add justfile tasks**

Add to `justfile` (follow the pattern of existing service tasks):

In the test-parallel recipe, add:

```bash
    uv run pytest tests/insights/ -v > /tmp/test-insights.log 2>&1 &
    pid_insights=$!
```

And the corresponding wait:

```bash
    wait $pid_insights || { echo "❌ Insights tests failed"; cat /tmp/test-insights.log; failed=1; }
```

Add the individual test task:

```bash
# Run insights tests with coverage
test-insights:
    uv run pytest tests/insights/ -v \
        --cov --cov-config=.coveragerc.insights --cov-report=xml --cov-report=json --cov-report=term
```

Add the service run task:

```bash
# Run insights service locally
insights:
    uv run python insights/insights.py
```

- [ ] **Step 3: Add test-insights CI job**

Add to `.github/workflows/test.yml` (follow the pattern of existing test jobs):

```yaml
  # ============================================================================
  # INSIGHTS SERVICE TESTS - Runs in parallel with all other test jobs
  # ============================================================================
  test-insights:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: 🔀 Checkout repository
        uses: actions/checkout@v6

      - name: 🔧 Setup Python and UV
        uses: ./.github/actions/setup-python-uv
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: 🔧 Setup Just
        uses: extractions/setup-just@f8a3cce218d9f83db3a2ecd90e41ac3de6cdfd9b # v3
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}

      - name: 📦 Install dependencies
        run: just install

      - name: 🧪 Run insights tests
        run: just test-insights

      - name: 📊 Upload coverage (insights)
        if: always()
        uses: codecov/codecov-action@v5
        with:
          token: ${{ secrets.CODECOV_TOKEN }}
          slug: SimplicityGuy/discogsography
          files: ./coverage.xml
          flags: insights
          name: insights-tests
          fail_ci_if_error: false
          disable_search: true
          verbose: false
```

- [ ] **Step 4: Add insights flag and component to codecov.yml**

Add under `flags:`:

```yaml
  insights:
    paths:
      - "insights/**"
    carryforward: true
```

Add under `individual_components:`:

```yaml
    - component_id: insights
      name: Insights
      paths:
        - "insights/**"
```

- [ ] **Step 5: Commit**

```bash
git add .coveragerc.insights justfile .github/workflows/test.yml codecov.yml
git commit -m "chore(insights): add CI, coverage, justfile, and codecov config"
```

---

### Task 13: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md port table**

In the Quick Reference > Service Ports section, add:

```
- Insights: 8008 (service), 8009 (health)
```

- [ ] **Step 2: Update workspace members reference if mentioned**

Any references to the workspace `members` list in documentation should be updated to include `insights`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with insights service ports"
```

---

## Verification Checklist

After all chunks are complete, verify:

- [ ] `uv sync --all-extras` succeeds
- [ ] `uv run pytest tests/insights/ -v` — all tests pass
- [ ] `uv run pytest tests/schema-init/ -v` — schema tests still pass
- [ ] `uv run pytest tests/api/ -v` — API tests still pass (proxy router)
- [ ] `uv run pytest tests/common/ -v` — common tests still pass (InsightsConfig)
- [ ] `uv run mypy insights/` — no type errors
- [ ] `uv run ruff check insights/` — no lint errors
- [ ] `docker compose build insights` — Docker build succeeds
- [ ] All 5 insight endpoints respond with precomputed data from PostgreSQL
- [ ] Scheduler runs on startup and recomputes on the configured interval
- [ ] Health endpoint on port 8009 returns `{"status": "healthy"}`
- [ ] API proxy on port 8004 forwards `/api/insights/*` to insights service

## Deferred / Out of Scope

These are explicitly NOT included in this plan and can be addressed in follow-up issues:

1. **Dashboard "Insights" panel** — The issue mentions a Dashboard panel consuming these endpoints. This is a separate UI concern and should be its own issue/PR.
2. **Redis caching** — The endpoints read from PostgreSQL which is already fast (<100ms). Redis caching can be layered on later if needed.
3. **WebSocket push on refresh** — Dashboard WebSocket integration is a separate concern.
4. **Neo4j read replicas** — The issue mentions read replicas. This is an infrastructure concern, not a code change. The queries use standard `session.run()` which works with replicas when configured.
5. **Configurable milestone years** — Currently hardcoded to [25, 30, 40, 50, 75, 100]. Can be made configurable via env var in a follow-up.
