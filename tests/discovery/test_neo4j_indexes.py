"""Tests for Neo4j index management.

This module tests the index creation, listing, and deletion functionality
for optimizing Neo4j query performance.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discovery.neo4j_indexes import (
    INDEXES,
    create_all_indexes,
    create_index,
    drop_index,
    list_indexes,
)


@pytest.fixture
def mock_neo4j_driver():
    """Mock Neo4j async driver."""
    driver = MagicMock()
    session = AsyncMock()

    # Create a proper async context manager
    async_context = MagicMock()
    async_context.__aenter__ = AsyncMock(return_value=session)
    async_context.__aexit__ = AsyncMock(return_value=None)

    # session() is a sync method that returns an async context manager
    driver.session = MagicMock(return_value=async_context)
    driver.close = AsyncMock()

    return driver


@pytest.fixture
def fulltext_index_def():
    """Sample fulltext index definition."""
    return {
        "name": "test_fulltext",
        "type": "fulltext",
        "label": "Artist",
        "properties": ["name"],
        "description": "Test fulltext index",
    }


@pytest.fixture
def range_index_def():
    """Sample range index definition."""
    return {
        "name": "test_range",
        "type": "range",
        "label": "Artist",
        "properties": ["id"],
        "description": "Test range index",
    }


@pytest.fixture
def composite_index_def():
    """Sample composite index definition."""
    return {
        "name": "test_composite",
        "type": "range",
        "label": "Release",
        "properties": ["year", "title"],
        "description": "Test composite index",
    }


class TestIndexCreation:
    """Test index creation functionality."""

    @pytest.mark.asyncio
    async def test_create_fulltext_index(self, mock_neo4j_driver, fulltext_index_def):
        """Test creating a fulltext index."""
        result = await create_index(mock_neo4j_driver, fulltext_index_def)
        assert result is True

        # Verify session.run was called with correct query
        async_context = mock_neo4j_driver.session.return_value
        session = await async_context.__aenter__()
        assert session.run.called
        query = session.run.call_args[0][0]
        assert "CREATE FULLTEXT INDEX" in query
        assert "test_fulltext" in query
        assert "Artist" in query
        assert "n.name" in query

    @pytest.mark.asyncio
    async def test_create_range_index_single_property(self, mock_neo4j_driver, range_index_def):
        """Test creating a range index with single property."""
        result = await create_index(mock_neo4j_driver, range_index_def)
        assert result is True

        # Verify session.run was called with correct query
        async_context = mock_neo4j_driver.session.return_value
        session = await async_context.__aenter__()
        assert session.run.called
        query = session.run.call_args[0][0]
        assert "CREATE INDEX" in query
        assert "test_range" in query
        assert "Artist" in query
        assert "n.id" in query

    @pytest.mark.asyncio
    async def test_create_composite_range_index(self, mock_neo4j_driver, composite_index_def):
        """Test creating a composite range index with multiple properties."""
        result = await create_index(mock_neo4j_driver, composite_index_def)
        assert result is True

        # Verify session.run was called with correct query
        async_context = mock_neo4j_driver.session.return_value
        session = await async_context.__aenter__()
        assert session.run.called
        query = session.run.call_args[0][0]
        assert "CREATE INDEX" in query
        assert "test_composite" in query
        assert "Release" in query
        # Composite index should have both properties
        assert "n.year" in query
        assert "n.title" in query

    @pytest.mark.asyncio
    async def test_create_index_already_exists(self, mock_neo4j_driver, range_index_def):
        """Test creating an index that already exists (should succeed with IF NOT EXISTS)."""
        result = await create_index(mock_neo4j_driver, range_index_def)
        assert result is True

        # Verify IF NOT EXISTS is in query
        async_context = mock_neo4j_driver.session.return_value
        session = await async_context.__aenter__()
        query = session.run.call_args[0][0]
        assert "IF NOT EXISTS" in query

    @pytest.mark.asyncio
    async def test_create_index_connection_error(self, mock_neo4j_driver, range_index_def):
        """Test error handling during index creation."""
        async_context = mock_neo4j_driver.session.return_value
        session = await async_context.__aenter__()
        session.run.side_effect = Exception("Connection failed")

        result = await create_index(mock_neo4j_driver, range_index_def)
        assert result is False

    @pytest.mark.asyncio
    async def test_create_index_query_error(self, mock_neo4j_driver, range_index_def):
        """Test handling of query execution errors."""
        async_context = mock_neo4j_driver.session.return_value
        session = await async_context.__aenter__()
        session.run.side_effect = Exception("Invalid query syntax")

        result = await create_index(mock_neo4j_driver, range_index_def)
        assert result is False


class TestBulkIndexOperations:
    """Test bulk index operations."""

    @pytest.mark.asyncio
    async def test_create_all_indexes_success(self):
        """Test creating all defined indexes successfully."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = AsyncMock()
            mock_db.driver.return_value = mock_driver

            # Mock successful index creation
            with patch("discovery.neo4j_indexes.create_index", return_value=True) as mock_create:
                await create_all_indexes("bolt://localhost", "neo4j", "password")

                # Verify create_index was called for each defined index
                assert mock_create.call_count == len(INDEXES)

                # Verify driver.close was called
                mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_all_indexes_partial_failure(self):
        """Test creating indexes with some failures."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = AsyncMock()
            mock_db.driver.return_value = mock_driver

            # Mock some successes and some failures
            call_count = [0]

            async def mock_create_index(driver, index_def):
                call_count[0] += 1
                # Fail every 3rd index
                return call_count[0] % 3 != 0

            with patch("discovery.neo4j_indexes.create_index", side_effect=mock_create_index):
                await create_all_indexes("bolt://localhost", "neo4j", "password")

                # Should still complete and close driver
                mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_all_indexes_connection_error(self):
        """Test handling of connection errors during bulk creation."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = AsyncMock()
            mock_db.driver.return_value = mock_driver

            with patch("discovery.neo4j_indexes.create_index", return_value=True):
                # Should complete successfully
                await create_all_indexes("bolt://localhost", "neo4j", "password")

                # Verify driver.close was called
                mock_driver.close.assert_called_once()


class TestIndexListing:
    """Test listing existing indexes."""

    @pytest.mark.asyncio
    async def test_list_indexes_success(self):
        """Test listing existing indexes."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = MagicMock()
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            # Setup mock chain
            mock_db.driver.return_value = mock_driver

            # Create proper async context manager
            async_context = MagicMock()
            async_context.__aenter__ = AsyncMock(return_value=mock_session)
            async_context.__aexit__ = AsyncMock(return_value=None)
            mock_driver.session = MagicMock(return_value=async_context)
            mock_driver.close = AsyncMock()

            mock_session.run.return_value = mock_result

            # Mock async iteration
            async def mock_async_iter(self):
                yield {"name": "index1", "type": "RANGE", "state": "ONLINE"}
                yield {"name": "index2", "type": "FULLTEXT", "state": "ONLINE"}

            mock_result.__aiter__ = mock_async_iter

            indexes = await list_indexes("bolt://localhost", "neo4j", "password")

            assert len(indexes) == 2
            assert indexes[0]["name"] == "index1"
            assert indexes[0]["type"] == "RANGE"
            assert indexes[1]["name"] == "index2"
            assert indexes[1]["type"] == "FULLTEXT"

            # Verify driver closed
            mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_indexes_empty(self):
        """Test listing indexes when none exist."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = MagicMock()
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            mock_db.driver.return_value = mock_driver

            # Create proper async context manager
            async_context = MagicMock()
            async_context.__aenter__ = AsyncMock(return_value=mock_session)
            async_context.__aexit__ = AsyncMock(return_value=None)
            mock_driver.session = MagicMock(return_value=async_context)
            mock_driver.close = AsyncMock()

            mock_session.run.return_value = mock_result

            # Mock empty async iteration
            async def mock_async_iter(self):
                return
                yield  # Make it a generator

            mock_result.__aiter__ = mock_async_iter

            indexes = await list_indexes("bolt://localhost", "neo4j", "password")

            assert len(indexes) == 0
            mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_indexes_query_called(self):
        """Test that SHOW INDEXES query is executed."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = MagicMock()
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            mock_db.driver.return_value = mock_driver

            # Create proper async context manager
            async_context = MagicMock()
            async_context.__aenter__ = AsyncMock(return_value=mock_session)
            async_context.__aexit__ = AsyncMock(return_value=None)
            mock_driver.session = MagicMock(return_value=async_context)
            mock_driver.close = AsyncMock()

            mock_session.run.return_value = mock_result

            async def mock_async_iter(self):
                return
                yield

            mock_result.__aiter__ = mock_async_iter

            await list_indexes("bolt://localhost", "neo4j", "password")

            # Verify SHOW INDEXES was called
            mock_session.run.assert_called_once_with("SHOW INDEXES")


class TestIndexDeletion:
    """Test index deletion functionality."""

    @pytest.mark.asyncio
    async def test_drop_index_success(self):
        """Test successful index deletion."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = MagicMock()
            mock_session = AsyncMock()

            mock_db.driver.return_value = mock_driver

            # Create proper async context manager
            async_context = MagicMock()
            async_context.__aenter__ = AsyncMock(return_value=mock_session)
            async_context.__aexit__ = AsyncMock(return_value=None)
            mock_driver.session = MagicMock(return_value=async_context)
            mock_driver.close = AsyncMock()

            result = await drop_index("bolt://localhost", "neo4j", "password", "test_index")

            assert result is True
            mock_session.run.assert_called_once()

            # Verify DROP INDEX query
            query = mock_session.run.call_args[0][0]
            assert "DROP INDEX" in query
            assert "test_index" in query
            assert "IF EXISTS" in query

            # Verify driver closed
            mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_drop_index_error(self):
        """Test error handling during index deletion."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = MagicMock()
            mock_session = AsyncMock()

            mock_db.driver.return_value = mock_driver

            # Create proper async context manager
            async_context = MagicMock()
            async_context.__aenter__ = AsyncMock(return_value=mock_session)
            async_context.__aexit__ = AsyncMock(return_value=None)
            mock_driver.session = MagicMock(return_value=async_context)
            mock_driver.close = AsyncMock()

            mock_session.run.side_effect = Exception("Index not found")

            result = await drop_index("bolt://localhost", "neo4j", "password", "nonexistent")

            assert result is False
            mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_drop_index_connection_error(self):
        """Test handling connection errors during deletion."""
        with patch("discovery.neo4j_indexes.AsyncGraphDatabase") as mock_db:
            mock_driver = MagicMock()
            mock_session = AsyncMock()

            mock_db.driver.return_value = mock_driver

            # Create proper async context manager
            async_context = MagicMock()
            async_context.__aenter__ = AsyncMock(return_value=mock_session)
            async_context.__aexit__ = AsyncMock(return_value=None)
            mock_driver.session = MagicMock(return_value=async_context)
            mock_driver.close = AsyncMock()

            mock_session.run.side_effect = Exception("Connection lost")

            result = await drop_index("bolt://localhost", "neo4j", "password", "test_index")

            assert result is False


class TestIndexDefinitions:
    """Test that all index definitions are properly structured."""

    def test_all_indexes_have_required_fields(self):
        """Test that all index definitions have required fields."""
        required_fields = {"name", "type", "label", "properties", "description"}

        for index in INDEXES:
            assert required_fields.issubset(index.keys()), f"Index {index.get('name')} missing required fields"

    def test_index_types_are_valid(self):
        """Test that all indexes have valid types."""
        valid_types = {"fulltext", "range"}

        for index in INDEXES:
            assert index["type"] in valid_types, f"Index {index['name']} has invalid type: {index['type']}"

    def test_properties_are_non_empty(self):
        """Test that all indexes have at least one property."""
        for index in INDEXES:
            assert len(index["properties"]) > 0, f"Index {index['name']} has no properties"

    def test_names_are_unique(self):
        """Test that all index names are unique."""
        names = [index["name"] for index in INDEXES]
        assert len(names) == len(set(names)), "Duplicate index names found"

    def test_fulltext_indexes_structure(self):
        """Test that fulltext indexes are properly structured."""
        fulltext_indexes = [idx for idx in INDEXES if idx["type"] == "fulltext"]

        for index in fulltext_indexes:
            assert "_fulltext" in index["name"], f"Fulltext index {index['name']} should have _fulltext suffix"
            assert len(index["properties"]) >= 1, f"Fulltext index {index['name']} should have properties"

    def test_range_indexes_structure(self):
        """Test that range indexes are properly structured."""
        range_indexes = [idx for idx in INDEXES if idx["type"] == "range"]

        assert len(range_indexes) > 0, "Should have at least one range index"

        for index in range_indexes:
            assert len(index["properties"]) >= 1, f"Range index {index['name']} should have properties"
