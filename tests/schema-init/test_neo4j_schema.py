"""Tests for schema-init/neo4j_schema.py."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from neo4j_schema import SCHEMA_STATEMENTS, create_neo4j_schema


@pytest.fixture
def mock_driver() -> MagicMock:
    """Mock AsyncResilientNeo4jDriver whose session() is a coroutine."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock()
    # session() is an async method on AsyncResilientNeo4jDriver
    driver.session = AsyncMock(return_value=mock_session)
    return driver


class TestSchemaStatements:
    """Verify the SCHEMA_STATEMENTS catalogue is well-formed."""

    def test_not_empty(self) -> None:
        assert len(SCHEMA_STATEMENTS) > 0

    def test_each_entry_is_name_cypher_pair(self) -> None:
        for entry in SCHEMA_STATEMENTS:
            assert len(entry) == 2, f"Expected (name, cypher) pair, got: {entry!r}"
            name, cypher = entry
            assert isinstance(name, str) and name
            assert isinstance(cypher, str) and cypher

    def test_all_statements_use_if_not_exists(self) -> None:
        for name, cypher in SCHEMA_STATEMENTS:
            assert "IF NOT EXISTS" in cypher, f"Schema object '{name}' is missing IF NOT EXISTS"

    def test_no_drop_statements(self) -> None:
        """Schema creation must never drop existing objects."""
        for name, cypher in SCHEMA_STATEMENTS:
            assert "DROP" not in cypher.upper(), f"Schema object '{name}' contains a DROP statement"

    def test_constraints_present(self) -> None:
        constraint_names = {n for n, c in SCHEMA_STATEMENTS if "CONSTRAINT" in c}
        assert constraint_names >= {
            "artist_id",
            "label_id",
            "master_id",
            "release_id",
            "genre_name",
            "style_name",
        }

    def test_sha256_indexes_present(self) -> None:
        index_names = {n for n, _ in SCHEMA_STATEMENTS}
        assert index_names >= {
            "artist_sha256",
            "label_sha256",
            "master_sha256",
            "release_sha256",
        }

    def test_fulltext_indexes_present(self) -> None:
        fulltext = [(n, c) for n, c in SCHEMA_STATEMENTS if "FULLTEXT" in c]
        names = {n for n, _ in fulltext}
        assert names >= {
            "artist_name_fulltext",
            "release_title_fulltext",
            "label_name_fulltext",
        }

    def test_constraints_listed_before_range_indexes(self) -> None:
        """Constraints must come first so their backing indexes exist before
        any additional range/fulltext index statements run."""
        positions = {n: i for i, (n, _) in enumerate(SCHEMA_STATEMENTS)}
        constraint_max = max(
            positions[n]
            for n in positions
            if "CONSTRAINT" in dict(SCHEMA_STATEMENTS).get(n, "")
            if any(cypher for name, cypher in SCHEMA_STATEMENTS if name == n and "CONSTRAINT" in cypher)
        )
        first_non_constraint = next(i for i, (_, cypher) in enumerate(SCHEMA_STATEMENTS) if "CONSTRAINT" not in cypher)
        assert constraint_max < first_non_constraint, "All CONSTRAINT statements must appear before INDEX statements"

    def test_total_statement_count(self) -> None:
        # 7 constraints + 5 range indexes + 3 fulltext = 15
        assert len(SCHEMA_STATEMENTS) == 15


class TestCreateNeo4jSchema:
    """Test create_neo4j_schema end-to-end with a mock driver."""

    @pytest.mark.asyncio
    async def test_runs_all_schema_statements(self, mock_driver: MagicMock) -> None:
        await create_neo4j_schema(mock_driver)

        mock_driver.session.assert_awaited_once_with(database="neo4j")
        session = mock_driver.session.return_value
        assert session.run.await_count == len(SCHEMA_STATEMENTS)

    @pytest.mark.asyncio
    async def test_continues_after_individual_failure(self, mock_driver: MagicMock) -> None:
        """A single failing statement must not abort the rest."""
        session = mock_driver.session.return_value
        call_count = 0

        async def flaky(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise Exception("Simulated Neo4j error")

        session.run = AsyncMock(side_effect=flaky)

        # Must not raise
        await create_neo4j_schema(mock_driver)
        assert session.run.await_count == len(SCHEMA_STATEMENTS)

    @pytest.mark.asyncio
    async def test_all_statements_use_if_not_exists(self, mock_driver: MagicMock) -> None:
        """Every Cypher statement sent to Neo4j must be idempotent."""
        session = mock_driver.session.return_value
        captured: list[str] = []

        async def capture(cypher: str, *_: Any, **__: Any) -> None:
            captured.append(cypher)

        session.run = AsyncMock(side_effect=capture)
        await create_neo4j_schema(mock_driver)

        for stmt in captured:
            assert "IF NOT EXISTS" in stmt

    @pytest.mark.asyncio
    async def test_all_succeed_count(self, mock_driver: MagicMock) -> None:
        """All statements should succeed when driver works correctly."""
        session = mock_driver.session.return_value
        session.run = AsyncMock()

        await create_neo4j_schema(mock_driver)

        assert session.run.await_count == len(SCHEMA_STATEMENTS)

    @pytest.mark.asyncio
    async def test_all_fail_gracefully(self, mock_driver: MagicMock) -> None:
        """All statements failing should not raise — schema init is best-effort."""
        session = mock_driver.session.return_value
        session.run = AsyncMock(side_effect=Exception("Neo4j unavailable"))

        # Must not raise even if all statements fail
        await create_neo4j_schema(mock_driver)

        assert session.run.await_count == len(SCHEMA_STATEMENTS)
