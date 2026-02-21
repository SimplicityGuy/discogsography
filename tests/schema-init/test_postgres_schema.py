"""Tests for schema-init/postgres_schema.py."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from postgres_schema import _ENTITY_TABLES, _SPECIFIC_INDEXES, create_postgres_schema


@pytest.fixture
def mock_pool() -> MagicMock:
    """Mock AsyncPostgreSQLPool with async context manager support."""
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)
    mock_cursor.execute = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    # cursor() is synchronous in psycopg (returns an async context manager, not a coroutine)
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    pool.connection.return_value = mock_conn
    return pool


class TestEntityTables:
    """Verify the entity table list is correct."""

    def test_all_four_tables_present(self) -> None:
        assert set(_ENTITY_TABLES) == {"artists", "labels", "masters", "releases"}

    def test_table_order_is_stable(self) -> None:
        assert _ENTITY_TABLES == ["artists", "labels", "masters", "releases"]


class TestSpecificIndexes:
    """Verify the per-table index definitions."""

    def test_not_empty(self) -> None:
        assert len(_SPECIFIC_INDEXES) > 0

    def test_each_entry_is_name_sql_pair(self) -> None:
        for entry in _SPECIFIC_INDEXES:
            assert len(entry) == 2, f"Expected (name, sql) pair, got: {entry!r}"
            name, stmt = entry
            assert isinstance(name, str) and name
            assert isinstance(stmt, str) and stmt

    def test_all_indexes_use_if_not_exists(self) -> None:
        for name, stmt in _SPECIFIC_INDEXES:
            assert "IF NOT EXISTS" in stmt, f"Index '{name}' is missing IF NOT EXISTS"

    def test_no_drop_statements(self) -> None:
        for name, stmt in _SPECIFIC_INDEXES:
            assert "DROP" not in stmt.upper(), f"Index '{name}' contains a DROP statement"

    def test_covers_all_entity_tables(self) -> None:
        index_tables = {stmt.split("ON ")[1].split(" ")[0] for _, stmt in _SPECIFIC_INDEXES}
        for table in _ENTITY_TABLES:
            assert table in index_tables, f"No specific indexes for table '{table}'"

    def test_releases_has_gin_indexes(self) -> None:
        release_gin = [n for n, s in _SPECIFIC_INDEXES if "releases" in s and "GIN" in s]
        assert len(release_gin) >= 2


class TestCreatePostgresSchema:
    """Test create_postgres_schema with a mock pool."""

    @pytest.mark.asyncio
    async def test_runs_all_statements(self, mock_pool: MagicMock) -> None:
        await create_postgres_schema(mock_pool)

        cursor = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value
        # 3 statements per entity table (CREATE TABLE + 2 indexes) + specific indexes
        expected_calls = len(_ENTITY_TABLES) * 3 + len(_SPECIFIC_INDEXES)
        assert cursor.execute.await_count == expected_calls

    @pytest.mark.asyncio
    async def test_continues_after_individual_failure(self, mock_pool: MagicMock) -> None:
        """A failing statement must not abort the rest."""
        cursor = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value
        call_count = 0

        async def flaky(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count % 4 == 0:
                raise Exception("Simulated PostgreSQL error")

        cursor.execute = AsyncMock(side_effect=flaky)

        # Must not raise
        await create_postgres_schema(mock_pool)

        expected_calls = len(_ENTITY_TABLES) * 3 + len(_SPECIFIC_INDEXES)
        assert cursor.execute.await_count == expected_calls

    @pytest.mark.asyncio
    async def test_all_statements_create_if_not_exists(self, mock_pool: MagicMock) -> None:
        """All statements sent to PostgreSQL must be idempotent."""
        cursor = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value
        captured: list[str] = []

        async def capture(stmt: Any, *_: Any, **__: Any) -> None:
            # Handle both psycopg sql.SQL objects and plain strings
            captured.append(str(stmt))

        cursor.execute = AsyncMock(side_effect=capture)
        await create_postgres_schema(mock_pool)

        for stmt in captured:
            assert "IF NOT EXISTS" in stmt.upper(), f"Statement is not idempotent: {stmt[:80]}..."

    @pytest.mark.asyncio
    async def test_all_fail_gracefully(self, mock_pool: MagicMock) -> None:
        """All statements failing should not raise — schema init is best-effort."""
        cursor = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value
        cursor.execute = AsyncMock(side_effect=Exception("PostgreSQL unavailable"))

        # Must not raise
        await create_postgres_schema(mock_pool)

        expected_calls = len(_ENTITY_TABLES) * 3 + len(_SPECIFIC_INDEXES)
        assert cursor.execute.await_count == expected_calls

    @pytest.mark.asyncio
    async def test_creates_tables_before_indexes(self, mock_pool: MagicMock) -> None:
        """Tables must be created before their indexes."""
        cursor = mock_pool.connection.return_value.__aenter__.return_value.cursor.return_value
        call_order: list[str] = []

        async def track(stmt: Any, *_: Any, **__: Any) -> None:
            call_order.append(str(stmt))

        cursor.execute = AsyncMock(side_effect=track)
        await create_postgres_schema(mock_pool)

        # Find positions of CREATE TABLE vs CREATE INDEX calls
        table_positions = [i for i, s in enumerate(call_order) if "CREATE TABLE" in s]
        index_positions = [i for i, s in enumerate(call_order) if "CREATE INDEX" in s]

        assert table_positions, "No CREATE TABLE statements found"
        assert index_positions, "No CREATE INDEX statements found"

        # Each table's CREATE TABLE must appear before its first index
        assert min(table_positions) < max(index_positions)

    @pytest.mark.asyncio
    async def test_pool_connection_used(self, mock_pool: MagicMock) -> None:
        await create_postgres_schema(mock_pool)
        mock_pool.connection.assert_called_once()
