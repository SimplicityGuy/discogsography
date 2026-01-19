"""Integration tests for Discovery Playground API.

Tests API endpoints, database integration, caching, and error handling.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import pytest
import pytest_asyncio

from discovery.playground_api import (
    HeatmapRequest,
    JourneyRequest,
    PlaygroundAPI,
    SearchRequest,
    TrendRequest,
)


# Fixtures


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock configuration."""
    config = MagicMock()
    config.neo4j_address = "bolt://localhost:7687"
    config.neo4j_username = "neo4j"
    config.neo4j_password = "password"
    config.postgres_address = "localhost:5432"
    config.postgres_username = "postgres"
    config.postgres_password = "password"
    config.postgres_database = "discogsography"
    return config


@pytest.fixture
def mock_cache_manager() -> AsyncMock:
    """Create mock cache manager."""
    cache = AsyncMock()
    cache.initialize = AsyncMock()
    cache.close = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


@pytest.fixture
def mock_neo4j_driver() -> MagicMock:
    """Create mock Neo4j driver."""
    driver = MagicMock()
    session = AsyncMock()

    # Create context manager
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = session
    context_manager.__aexit__.return_value = None

    driver.session.return_value = context_manager
    driver.close = AsyncMock()

    return driver


@pytest.fixture
def mock_pg_engine() -> MagicMock:
    """Create mock PostgreSQL engine."""
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


@pytest_asyncio.fixture
async def api_instance(
    mock_config: MagicMock,
    mock_cache_manager: AsyncMock,
    mock_neo4j_driver: MagicMock,
    mock_pg_engine: MagicMock,
) -> PlaygroundAPI:
    """Create PlaygroundAPI instance with mocked dependencies."""
    with (
        patch("discovery.playground_api.get_config", return_value=mock_config),
        patch("discovery.playground_api.cache_manager", mock_cache_manager),
        patch("discovery.playground_api.AsyncGraphDatabase.driver", return_value=mock_neo4j_driver),
        patch("discovery.playground_api.create_async_engine", return_value=mock_pg_engine),
    ):
        api = PlaygroundAPI()
        await api.initialize()
        yield api
        await api.close()


# Model Tests


def test_search_request_validation() -> None:
    """Test SearchRequest model validation."""
    request = SearchRequest(query="Miles Davis", type="artist", limit=20)
    assert request.query == "Miles Davis"
    assert request.type == "artist"
    assert request.limit == 20


def test_search_request_defaults() -> None:
    """Test SearchRequest default values."""
    request = SearchRequest(query="test")
    assert request.type == "all"
    assert request.limit == 10


def test_journey_request_validation() -> None:
    """Test JourneyRequest model validation."""
    request = JourneyRequest(start_artist_id="123", end_artist_id="456", max_depth=3)
    assert request.start_artist_id == "123"
    assert request.end_artist_id == "456"
    assert request.max_depth == 3


def test_journey_request_defaults() -> None:
    """Test JourneyRequest default values."""
    request = JourneyRequest(start_artist_id="123", end_artist_id="456")
    assert request.max_depth == 5


def test_trend_request_validation() -> None:
    """Test TrendRequest model validation."""
    request = TrendRequest(type="genre", start_year=1960, end_year=1990, top_n=15)
    assert request.type == "genre"
    assert request.start_year == 1960
    assert request.end_year == 1990
    assert request.top_n == 15


def test_trend_request_defaults() -> None:
    """Test TrendRequest default values."""
    request = TrendRequest(type="artist")
    assert request.start_year == 1950
    assert request.end_year == 2024
    assert request.top_n == 20


def test_heatmap_request_validation() -> None:
    """Test HeatmapRequest model validation."""
    request = HeatmapRequest(type="genre", top_n=30)
    assert request.type == "genre"
    assert request.top_n == 30


def test_heatmap_request_defaults() -> None:
    """Test HeatmapRequest default values."""
    request = HeatmapRequest(type="collab")
    assert request.top_n == 20


# PlaygroundAPI Integration Tests


@pytest.mark.asyncio
async def test_playground_api_initialization(
    mock_config: MagicMock,
    mock_cache_manager: AsyncMock,
) -> None:
    """Test PlaygroundAPI initialization."""
    with (
        patch("discovery.playground_api.get_config", return_value=mock_config),
        patch("discovery.playground_api.cache_manager", mock_cache_manager),
        patch("discovery.playground_api.AsyncGraphDatabase.driver") as mock_driver_factory,
        patch("discovery.playground_api.create_async_engine") as mock_engine_factory,
    ):
        # Create a mock driver with async close
        mock_driver = MagicMock()
        mock_driver.close = AsyncMock()
        mock_driver_factory.return_value = mock_driver

        # Create a mock engine with async dispose
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_engine_factory.return_value = mock_engine

        api = PlaygroundAPI()
        await api.initialize()

        # Verify initialization
        mock_cache_manager.initialize.assert_called_once()
        mock_driver_factory.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "password"),
        )
        mock_engine_factory.assert_called_once()

        await api.close()


@pytest.mark.asyncio
async def test_playground_api_close(api_instance: PlaygroundAPI) -> None:
    """Test PlaygroundAPI close method."""
    # Close is called in the fixture cleanup
    pass


@pytest.mark.asyncio
async def test_search_all_types(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test search with all types."""
    # Mock query results
    artist_result = AsyncMock()
    release_result = AsyncMock()
    label_result = AsyncMock()

    async def artist_records(self: Any) -> Any:
        yield {"id": "1", "name": "Miles Davis", "real_name": "Miles Dewey Davis III"}

    async def release_records(self: Any) -> Any:
        yield {"id": "2", "title": "Kind of Blue", "year": 1959}

    async def label_records(self: Any) -> Any:
        yield {"id": "3", "name": "Blue Note"}

    artist_result.__aiter__ = artist_records
    release_result.__aiter__ = release_records
    label_result.__aiter__ = label_records

    # Mock session.run to return different results for different queries
    session = await mock_neo4j_driver.session().__aenter__()
    call_count = [0]

    async def mock_run(*args: Any, **kwargs: Any) -> Any:
        call_count[0] += 1
        if call_count[0] == 1:
            return artist_result
        elif call_count[0] == 2:
            return release_result
        else:
            return label_result

    session.run = mock_run

    # Test search
    result = await api_instance.search("test", "all", 10)

    # Check paginated response structure
    assert "items" in result
    assert "has_more" in result
    assert "next_cursor" in result
    assert "page_info" in result

    # Check items
    assert "artists" in result["items"]
    assert "releases" in result["items"]
    assert "labels" in result["items"]
    assert len(result["items"]["artists"]) == 1
    assert len(result["items"]["releases"]) == 1
    assert len(result["items"]["labels"]) == 1


@pytest.mark.asyncio
async def test_search_artist_only(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test search with artist type only."""
    artist_result = AsyncMock()

    async def artist_records(self: Any) -> Any:
        yield {"id": "1", "name": "Miles Davis", "real_name": "Miles Dewey Davis III"}

    artist_result.__aiter__ = artist_records

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=artist_result)

    result = await api_instance.search("Miles", "artist", 10)

    # Check paginated response
    assert "items" in result
    assert len(result["items"]["artists"]) == 1
    assert len(result["items"]["releases"]) == 0
    assert len(result["items"]["labels"]) == 0


@pytest.mark.asyncio
async def test_search_database_not_initialized() -> None:
    """Test search when database is not initialized."""
    api = PlaygroundAPI()

    with pytest.raises(HTTPException) as exc_info:
        await api.search("test", "all", 10)

    assert exc_info.value.status_code == 500
    assert "Database not initialized" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_graph_data_success(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_graph_data with successful result."""
    # Mock query result
    mock_result = AsyncMock()

    # Create mock nodes
    center_node = MagicMock()
    center_node.__getitem__ = lambda self, key: {"id": "1", "name": "Miles Davis"}.get(key)
    center_node.get = lambda key, default="": {"name": "Miles Davis", "id": "1"}.get(key, default)
    center_node.labels = ["Artist"]

    connected_node = MagicMock()
    connected_node.__getitem__ = lambda self, key: {"id": "2", "title": "Kind of Blue"}.get(key)
    connected_node.get = lambda key, default="": {"title": "Kind of Blue", "id": "2"}.get(key, default)
    connected_node.labels = ["Release"]

    # Mock relationship
    mock_rel = MagicMock()
    mock_rel.type = "BY"

    async def mock_records(self: Any) -> Any:
        yield {
            "center": center_node,
            "connected": connected_node,
            "rels": [mock_rel],
            "path_nodes": [center_node, connected_node],
        }

    mock_result.__aiter__ = mock_records

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.get_graph_data("1", depth=2, limit=50)

    assert "nodes" in result
    assert "links" in result
    assert len(result["nodes"]) == 2
    assert len(result["links"]) == 1


@pytest.mark.asyncio
async def test_get_graph_data_database_not_initialized() -> None:
    """Test get_graph_data when database is not initialized."""
    api = PlaygroundAPI()

    with pytest.raises(HTTPException) as exc_info:
        await api.get_graph_data("1", 2, 50)

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_find_music_journey_success(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test find_music_journey with successful path."""
    mock_result = AsyncMock()

    mock_record = {
        "path": MagicMock(),
        "nodes": [
            {"id": "1", "name": "Miles Davis", "type": "Artist", "properties": {}},
            {"id": "2", "name": "Kind of Blue", "type": "Release", "properties": {}},
            {"id": "3", "name": "John Coltrane", "type": "Artist", "properties": {}},
        ],
        "relationships": [
            {"type": "BY", "properties": {}},
            {"type": "BY", "properties": {}},
        ],
    }

    mock_result.single = AsyncMock(return_value=mock_record)

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.find_music_journey("1", "3", 5)

    assert "journey" in result
    assert result["journey"]["length"] == 2
    assert len(result["journey"]["nodes"]) == 3


@pytest.mark.asyncio
async def test_find_music_journey_no_path(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test find_music_journey when no path exists."""
    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=None)

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.find_music_journey("1", "999", 5)

    assert result["journey"] is None
    assert "No path found" in result["message"]


@pytest.mark.asyncio
async def test_find_music_journey_database_not_initialized() -> None:
    """Test find_music_journey when database is not initialized."""
    api = PlaygroundAPI()

    with pytest.raises(HTTPException) as exc_info:
        await api.find_music_journey("1", "2", 5)

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_get_trends_genre(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_trends with genre type."""
    mock_result = AsyncMock()

    async def mock_records(self: Any) -> Any:
        yield {
            "year": 1959,
            "top_genres": [{"genre": "Jazz", "count": 100}],
        }
        yield {
            "year": 1960,
            "top_genres": [{"genre": "Jazz", "count": 120}],
        }

    mock_result.__aiter__ = mock_records

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.get_trends("genre", 1959, 1960, 20)

    assert result["type"] == "genre"
    assert len(result["trends"]) == 2
    assert result["trends"][0]["year"] == 1959


@pytest.mark.asyncio
async def test_get_trends_artist(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_trends with artist type."""
    mock_result = AsyncMock()

    async def mock_records(self: Any) -> Any:
        yield {
            "year": 1959,
            "top_artists": [{"artist": "Miles Davis", "releases": 5}],
        }

    mock_result.__aiter__ = mock_records

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.get_trends("artist", 1959, 1960, 20)

    assert result["type"] == "artist"
    assert len(result["trends"]) == 1


@pytest.mark.asyncio
async def test_get_trends_database_not_initialized() -> None:
    """Test get_trends when database is not initialized."""
    api = PlaygroundAPI()
    result = await api.get_trends("genre", 1950, 2024, 20)

    assert result["trends"] == []
    assert result["type"] == "genre"


@pytest.mark.asyncio
async def test_get_heatmap_genre(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_heatmap with genre type."""
    mock_result = AsyncMock()

    async def mock_records(self: Any) -> Any:
        yield {"artist1": "Miles Davis", "artist2": "John Coltrane", "shared_genres": 5}
        yield {"artist1": "Miles Davis", "artist2": "Bill Evans", "shared_genres": 3}

    mock_result.__aiter__ = mock_records

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.get_heatmap("genre", 20)

    assert result["type"] == "genre"
    assert len(result["heatmap"]) == 2
    assert len(result["labels"]) == 3  # 3 unique artists


@pytest.mark.asyncio
async def test_get_heatmap_collab(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_heatmap with collaboration type."""
    mock_result = AsyncMock()

    async def mock_records(self: Any) -> Any:
        yield {"artist1": "Miles Davis", "artist2": "John Coltrane", "collaborated": 1}
        yield {"artist1": "Miles Davis", "artist2": "Bill Evans", "collaborated": 0}  # Should be filtered

    mock_result.__aiter__ = mock_records

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.get_heatmap("collab", 20)

    assert result["type"] == "collab"
    assert len(result["heatmap"]) == 1  # Only collaborated pairs


@pytest.mark.asyncio
async def test_get_heatmap_invalid_type(api_instance: PlaygroundAPI) -> None:
    """Test get_heatmap with invalid type."""
    result = await api_instance.get_heatmap("invalid", 20)

    assert result["heatmap"] == []
    assert result["labels"] == []
    assert result["type"] == "invalid"


@pytest.mark.asyncio
async def test_get_artist_details_success(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_artist_details with successful result."""
    mock_result = AsyncMock()

    mock_artist = {
        "id": "1",
        "name": "Miles Davis",
        "real_name": "Miles Dewey Davis III",
        "profile": "Legendary jazz musician",
        "urls": ["https://example.com"],
    }

    mock_record = {
        "a": mock_artist,
        "release_count": 50,
        "groups": ["Miles Davis Quintet"],
        "aliases": ["Miles"],
        "collaborators": ["John Coltrane", "Bill Evans"],
    }

    mock_result.single = AsyncMock(return_value=mock_record)

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    result = await api_instance.get_artist_details("1")

    assert result["id"] == "1"
    assert result["name"] == "Miles Davis"
    assert result["release_count"] == 50
    assert len(result["collaborators"]) == 2


@pytest.mark.asyncio
async def test_get_artist_details_not_found(api_instance: PlaygroundAPI, mock_neo4j_driver: MagicMock) -> None:
    """Test get_artist_details when artist is not found."""
    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=None)

    session = await mock_neo4j_driver.session().__aenter__()
    session.run = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await api_instance.get_artist_details("999")

    assert exc_info.value.status_code == 404
    assert "Artist not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_artist_details_database_not_initialized() -> None:
    """Test get_artist_details when database is not initialized."""
    api = PlaygroundAPI()

    with pytest.raises(HTTPException) as exc_info:
        await api.get_artist_details("1")

    assert exc_info.value.status_code == 500
