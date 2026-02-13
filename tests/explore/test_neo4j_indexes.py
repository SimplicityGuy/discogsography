"""Tests for Explore service Neo4j index creation."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from explore.neo4j_indexes import INDEXES, create_all_indexes, create_index


@pytest.fixture
def mock_driver() -> MagicMock:
    """Create a mock async Neo4j driver."""
    driver = MagicMock()
    mock_session = AsyncMock()

    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock()

    driver.session = MagicMock(return_value=mock_session)
    driver.close = AsyncMock()
    return driver


class TestIndexDefinitions:
    """Test that index definitions are properly configured."""

    def test_indexes_not_empty(self) -> None:
        assert len(INDEXES) > 0

    def test_all_indexes_have_required_fields(self) -> None:
        for index_def in INDEXES:
            assert "name" in index_def
            assert "type" in index_def
            assert "label" in index_def
            assert "properties" in index_def
            assert "description" in index_def

    def test_fulltext_indexes_exist(self) -> None:
        fulltext = [i for i in INDEXES if i["type"] == "fulltext"]
        assert len(fulltext) >= 3  # artist, release, label

    def test_range_indexes_exist(self) -> None:
        range_indexes = [i for i in INDEXES if i["type"] == "range"]
        assert len(range_indexes) >= 4  # id indexes + year + genre + style


class TestCreateIndex:
    """Test the create_index function."""

    @pytest.mark.asyncio
    async def test_create_fulltext_index(self, mock_driver: MagicMock) -> None:
        index_def: dict[str, Any] = {
            "name": "test_fulltext",
            "type": "fulltext",
            "label": "Artist",
            "properties": ["name"],
            "description": "Test fulltext index",
        }
        result = await create_index(mock_driver, index_def)
        assert result is True

        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run.assert_called_once()
        query = mock_session.run.call_args[0][0]
        assert "FULLTEXT" in query
        assert "IF NOT EXISTS" in query

    @pytest.mark.asyncio
    async def test_create_single_property_range_index(self, mock_driver: MagicMock) -> None:
        index_def: dict[str, Any] = {
            "name": "test_range",
            "type": "range",
            "label": "Release",
            "properties": ["id"],
            "description": "Test range index",
        }
        result = await create_index(mock_driver, index_def)
        assert result is True

        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run.assert_called_once()
        query = mock_session.run.call_args[0][0]
        assert "IF NOT EXISTS" in query
        assert "FULLTEXT" not in query

    @pytest.mark.asyncio
    async def test_create_multi_property_range_index(self, mock_driver: MagicMock) -> None:
        index_def: dict[str, Any] = {
            "name": "test_multi",
            "type": "range",
            "label": "Release",
            "properties": ["year", "country"],
            "description": "Test multi-property index",
        }
        result = await create_index(mock_driver, index_def)
        assert result is True

        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run.assert_called_once()
        query = mock_session.run.call_args[0][0]
        assert "n.year" in query
        assert "n.country" in query

    @pytest.mark.asyncio
    async def test_create_index_failure(self, mock_driver: MagicMock) -> None:
        mock_session = mock_driver.session().__aenter__.return_value
        mock_session.run = AsyncMock(side_effect=Exception("Connection refused"))

        index_def: dict[str, Any] = {
            "name": "test_fail",
            "type": "range",
            "label": "Artist",
            "properties": ["id"],
            "description": "Should fail",
        }
        result = await create_index(mock_driver, index_def)
        assert result is False


class TestCreateAllIndexes:
    """Test the create_all_indexes function."""

    @pytest.mark.asyncio
    async def test_create_all_indexes_success(self) -> None:
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock()
        mock_driver.session = MagicMock(return_value=mock_session)
        mock_driver.close = AsyncMock()

        with patch("explore.neo4j_indexes.AsyncGraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            await create_all_indexes("bolt://localhost:7687", "neo4j", "password")

            mock_gdb.driver.assert_called_once_with("bolt://localhost:7687", auth=("neo4j", "password"))
            mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_all_indexes_with_failures(self) -> None:
        """Test that create_all_indexes counts successes and failures."""
        call_count = 0

        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        async def side_effect_run(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            # Fail every 3rd call
            if call_count % 3 == 0:
                raise Exception("Simulated failure")

        mock_session.run = AsyncMock(side_effect=side_effect_run)
        mock_driver.session = MagicMock(return_value=mock_session)
        mock_driver.close = AsyncMock()

        with patch("explore.neo4j_indexes.AsyncGraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            await create_all_indexes("bolt://localhost:7687", "neo4j", "password")

            # Driver should always be closed, even with failures
            mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_all_indexes_closes_driver_on_error(self) -> None:
        """Test that driver is closed even when all indexes fail."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=Exception("All fail"))
        mock_driver.session = MagicMock(return_value=mock_session)
        mock_driver.close = AsyncMock()

        with patch("explore.neo4j_indexes.AsyncGraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            await create_all_indexes("bolt://localhost:7687", "neo4j", "password")

            # Driver must be closed in finally block
            mock_driver.close.assert_awaited_once()
