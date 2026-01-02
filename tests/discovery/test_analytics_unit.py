"""Unit tests for Discovery service analytics functionality."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from discovery.analytics import (
    AnalyticsRequest,
    AnalyticsResult,
    MusicAnalytics,
    convert_numpy_to_json_serializable,
    get_analytics,
    get_analytics_instance,
)


class TestConvertNumpyToJsonSerializable:
    """Test numpy conversion utility function."""

    def test_convert_numpy_array(self) -> None:
        """Test converting numpy array to list."""
        arr = np.array([1, 2, 3])
        result = convert_numpy_to_json_serializable(arr)
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_convert_numpy_integer(self) -> None:
        """Test converting numpy integer to Python int."""
        num = np.int64(42)
        result = convert_numpy_to_json_serializable(num)
        assert result == 42
        assert isinstance(result, int)

    def test_convert_numpy_float(self) -> None:
        """Test converting numpy float to Python float."""
        num = np.float64(3.14)
        result = convert_numpy_to_json_serializable(num)
        assert result == 3.14
        assert isinstance(result, float)

    def test_convert_dict_with_numpy(self) -> None:
        """Test converting dict containing numpy values."""
        data = {"array": np.array([1, 2]), "number": np.int64(10), "text": "hello"}
        result = convert_numpy_to_json_serializable(data)
        assert result == {"array": [1, 2], "number": 10, "text": "hello"}

    def test_convert_list_with_numpy(self) -> None:
        """Test converting list containing numpy values."""
        data = [np.array([1, 2]), np.int64(10), "hello"]
        result = convert_numpy_to_json_serializable(data)
        assert result == [[1, 2], 10, "hello"]

    def test_convert_nested_structure(self) -> None:
        """Test converting deeply nested structures."""
        data = {
            "level1": {
                "level2": [np.array([1, 2, 3]), {"num": np.int64(42)}],
                "value": np.float64(3.14),
            }
        }
        result = convert_numpy_to_json_serializable(data)
        assert result == {"level1": {"level2": [[1, 2, 3], {"num": 42}], "value": 3.14}}

    def test_convert_regular_objects_unchanged(self) -> None:
        """Test that regular Python objects pass through unchanged."""
        data = {"string": "test", "int": 42, "float": 3.14, "bool": True, "none": None}
        result = convert_numpy_to_json_serializable(data)
        assert result == data


class TestAnalyticsRequest:
    """Test the AnalyticsRequest model."""

    def test_analytics_request_minimal(self) -> None:
        """Test AnalyticsRequest with minimal data."""
        request = AnalyticsRequest(analysis_type="genre_trends")
        assert request.analysis_type == "genre_trends"
        assert request.time_range is None
        assert request.genre is None
        assert request.artist_name is None
        assert request.label_name is None
        assert request.limit == 20

    def test_analytics_request_full(self) -> None:
        """Test AnalyticsRequest with all fields."""
        request = AnalyticsRequest(
            analysis_type="artist_evolution",
            time_range=(1950, 2020),
            genre="Jazz",
            artist_name="Miles Davis",
            label_name="Blue Note",
            limit=50,
        )
        assert request.analysis_type == "artist_evolution"
        assert request.time_range == (1950, 2020)
        assert request.genre == "Jazz"
        assert request.artist_name == "Miles Davis"
        assert request.label_name == "Blue Note"
        assert request.limit == 50

    def test_analytics_request_analysis_types(self) -> None:
        """Test valid analysis types."""
        types = ["genre_trends", "artist_evolution", "label_insights", "market_analysis"]
        for analysis_type in types:
            request = AnalyticsRequest(analysis_type=analysis_type)
            assert request.analysis_type == analysis_type


class TestAnalyticsResult:
    """Test the AnalyticsResult model."""

    def test_analytics_result_minimal(self) -> None:
        """Test AnalyticsResult with minimal data."""
        result = AnalyticsResult(chart_type="line", chart_data={}, insights=[], metadata={})
        assert result.chart_type == "line"
        assert result.chart_data == {}
        assert result.insights == []
        assert result.metadata == {}

    def test_analytics_result_full(self) -> None:
        """Test AnalyticsResult with all fields."""
        chart_data = {"data": [{"x": 1, "y": 2}], "layout": {"title": "Test Chart"}}
        insights = ["Insight 1", "Insight 2"]
        metadata = {"source": "neo4j", "records": 100}

        result = AnalyticsResult(
            chart_type="bar",
            chart_data=chart_data,
            insights=insights,
            metadata=metadata,
        )
        assert result.chart_type == "bar"
        assert result.chart_data == chart_data
        assert result.insights == insights
        assert result.metadata == metadata


class TestMusicAnalyticsInit:
    """Test MusicAnalytics initialization."""

    def test_music_analytics_init(self) -> None:
        """Test MusicAnalytics initialization."""
        with patch("discovery.analytics.get_config"):
            analytics = MusicAnalytics()
            assert analytics.neo4j_driver is None
            assert analytics.postgres_engine is None

    @pytest.mark.asyncio
    async def test_music_analytics_initialize(self) -> None:
        """Test MusicAnalytics async initialization."""
        with (
            patch("discovery.analytics.get_config") as mock_config,
            patch("discovery.analytics.AsyncGraphDatabase.driver") as mock_neo4j,
            patch("discovery.analytics.create_async_engine") as mock_pg,
        ):
            mock_config.return_value = MagicMock()
            mock_neo4j.return_value = AsyncMock()
            mock_pg.return_value = MagicMock()

            analytics = MusicAnalytics()
            await analytics.initialize()

            assert analytics.neo4j_driver is not None
            assert analytics.postgres_engine is not None
            mock_neo4j.assert_called_once()
            mock_pg.assert_called_once()


class TestAnalyzeGenreTrends:
    """Test analyze_genre_trends method."""

    @pytest.mark.asyncio
    async def test_analyze_genre_trends_success(self) -> None:
        """Test successful genre trends analysis."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            # Mock genre trend data
            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {"genre": "Rock", "year": 2020, "releases": 100},
                    {"genre": "Jazz", "year": 2020, "releases": 50},
                    {"genre": "Rock", "year": 2021, "releases": 120},
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_genre_trends((2020, 2021))

            assert result.chart_type == "line"
            assert len(result.insights) > 0
            assert result.metadata["time_range"] == (2020, 2021)

    @pytest.mark.asyncio
    async def test_analyze_genre_trends_no_data(self) -> None:
        """Test genre trends analysis with no data."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session with no results
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                return
                yield  # pragma: no cover

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_genre_trends((2020, 2021))

            assert result.chart_type == "line"
            assert result.chart_data == {}
            assert "No genre data available" in result.insights[0]

    @pytest.mark.asyncio
    async def test_analyze_genre_trends_default_time_range(self) -> None:
        """Test genre trends analysis with default time range."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [{"genre": "Rock", "year": 2020, "releases": 100}]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_genre_trends()

            assert result.chart_type == "line"
            # Should use default time range (current_year - 30 to current_year)
            assert result.metadata["time_range"] is not None


class TestAnalyzeArtistEvolution:
    """Test analyze_artist_evolution method."""

    @pytest.mark.asyncio
    async def test_analyze_artist_evolution_success(self) -> None:
        """Test successful artist evolution analysis."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result1 = AsyncMock()
            mock_result2 = AsyncMock()

            # Mock release data
            async def mock_releases(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {
                        "year": 1959,
                        "title": "Kind of Blue",
                        "genres": ["Jazz"],
                        "styles": ["Modal"],
                    },
                    {
                        "year": 1969,
                        "title": "Bitches Brew",
                        "genres": ["Jazz", "Fusion"],
                        "styles": ["Jazz-Rock"],
                    },
                ]:
                    yield record

            # Mock collaborator data
            async def mock_collabs(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {"collaborator": "John Coltrane", "collaborations": 5},
                    {"collaborator": "Herbie Hancock", "collaborations": 3},
                ]:
                    yield record

            mock_result1.__aiter__ = mock_releases
            mock_result2.__aiter__ = mock_collabs

            # Mock session to return different results for different queries
            call_count = [0]  # Use list to avoid closure issues

            async def mock_run(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
                call_count[0] += 1
                return mock_result1 if call_count[0] == 1 else mock_result2

            mock_session.run = mock_run

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_artist_evolution("Miles Davis")

            assert result.chart_type == "scatter"
            assert len(result.insights) > 0
            assert result.metadata["artist"] == "Miles Davis"

    @pytest.mark.asyncio
    async def test_analyze_artist_evolution_no_data(self) -> None:
        """Test artist evolution analysis with no data."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session with no results
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                return
                yield  # pragma: no cover

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_artist_evolution("Unknown Artist")

            assert result.chart_type == "scatter"
            assert result.chart_data == {}
            assert "No release data found" in result.insights[0]


class TestAnalyzeLabelInsights:
    """Test analyze_label_insights method."""

    @pytest.mark.asyncio
    async def test_analyze_label_insights_specific_label(self) -> None:
        """Test label insights for specific label."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {
                        "label": "Blue Note",
                        "artist": "Miles Davis",
                        "year": 1959,
                        "genres": ["Jazz"],
                        "releases": 10,
                        "artists": 0,
                        "first_release": None,
                        "last_release": None,
                    },
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_label_insights("Blue Note")

            assert result.chart_type == "bar"
            assert len(result.insights) > 0
            assert result.metadata["label"] == "Blue Note"

    @pytest.mark.asyncio
    async def test_analyze_label_insights_market_overview(self) -> None:
        """Test label insights market overview."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {
                        "label": "Blue Note",
                        "artists": 50,
                        "releases": 500,
                        "first_release": 1950,
                        "last_release": 2020,
                    },
                    {
                        "label": "Columbia",
                        "artists": 60,
                        "releases": 600,
                        "first_release": 1940,
                        "last_release": 2021,
                    },
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_label_insights()

            assert result.chart_type == "bar"
            assert len(result.insights) > 0
            assert result.metadata["label"] is None


class TestAnalyzeMarketTrends:
    """Test analyze_market_trends method."""

    @pytest.mark.asyncio
    async def test_analyze_market_trends_format(self) -> None:
        """Test market trends analysis for formats."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {"year": 2020, "format_type": "Vinyl", "releases": 100},
                    {"year": 2020, "format_type": "CD", "releases": 200},
                    {"year": 2021, "format_type": "Digital", "releases": 300},
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_market_trends("format")

            assert result.chart_type == "area"
            assert len(result.insights) > 0
            assert result.metadata["focus"] == "format"

    @pytest.mark.asyncio
    async def test_analyze_market_trends_regional(self) -> None:
        """Test market trends analysis for regions."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()

            # Create mock Neo4j session
            mock_session = AsyncMock()
            mock_result = AsyncMock()

            async def mock_records(self: Any) -> Any:  # noqa: ARG001
                for record in [
                    {"year": 2020, "country": "USA", "releases": 1000},
                    {"year": 2020, "country": "UK", "releases": 500},
                ]:
                    yield record

            mock_result.__aiter__ = mock_records
            mock_session.run.return_value = mock_result

            # Create proper async context manager mock
            mock_context_manager = AsyncMock()
            mock_context_manager.__aenter__.return_value = mock_session
            mock_context_manager.__aexit__.return_value = None

            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_context_manager

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_driver

            result = await analytics.analyze_market_trends("regional")

            assert result.chart_type == "line"
            assert len(result.insights) > 0
            assert result.metadata["focus"] == "regional"


class TestCloseAndGlobalInstance:
    """Test close method and global instance management."""

    @pytest.mark.asyncio
    async def test_close_with_connections(self) -> None:
        """Test closing analytics with active connections."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            mock_neo4j = AsyncMock()
            mock_pg = AsyncMock()

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_neo4j
            analytics.postgres_engine = mock_pg

            await analytics.close()

            mock_neo4j.close.assert_called_once()
            mock_pg.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_connections(self) -> None:
        """Test closing analytics without connections."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock()
            analytics = MusicAnalytics()
            analytics.neo4j_driver = None
            analytics.postgres_engine = None

            # Should not raise error
            await analytics.close()

    def test_get_analytics_instance(self) -> None:
        """Test global analytics instance management."""
        with (
            patch("discovery.analytics.get_config") as mock_config,
            patch("discovery.analytics.analytics", None),
        ):
            mock_config.return_value = MagicMock()

            instance1 = get_analytics_instance()
            instance2 = get_analytics_instance()

            # Should return same instance
            assert instance1 is instance2
            assert isinstance(instance1, MusicAnalytics)


class TestGetAnalytics:
    """Test the main get_analytics function."""

    @pytest.mark.asyncio
    async def test_get_analytics_genre_trends(self) -> None:
        """Test getting genre trends analytics."""
        with patch("discovery.analytics.get_analytics_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.analyze_genre_trends.return_value = AnalyticsResult(
                chart_type="line",
                chart_data={},
                insights=["Test insight"],
                metadata={},
            )
            mock_getter.return_value = mock_instance

            request = AnalyticsRequest(analysis_type="genre_trends", time_range=(2000, 2020))
            result = await get_analytics(request)

            assert result.chart_type == "line"
            mock_instance.analyze_genre_trends.assert_called_once_with((2000, 2020))

    @pytest.mark.asyncio
    async def test_get_analytics_artist_evolution(self) -> None:
        """Test getting artist evolution analytics."""
        with patch("discovery.analytics.get_analytics_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.analyze_artist_evolution.return_value = AnalyticsResult(
                chart_type="scatter",
                chart_data={},
                insights=["Test insight"],
                metadata={},
            )
            mock_getter.return_value = mock_instance

            request = AnalyticsRequest(analysis_type="artist_evolution", artist_name="Miles Davis")
            result = await get_analytics(request)

            assert result.chart_type == "scatter"
            mock_instance.analyze_artist_evolution.assert_called_once_with("Miles Davis")

    @pytest.mark.asyncio
    async def test_get_analytics_label_insights(self) -> None:
        """Test getting label insights analytics."""
        with patch("discovery.analytics.get_analytics_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.analyze_label_insights.return_value = AnalyticsResult(
                chart_type="bar",
                chart_data={},
                insights=["Test insight"],
                metadata={},
            )
            mock_getter.return_value = mock_instance

            request = AnalyticsRequest(analysis_type="label_insights", label_name="Blue Note")
            result = await get_analytics(request)

            assert result.chart_type == "bar"
            mock_instance.analyze_label_insights.assert_called_once_with("Blue Note")

    @pytest.mark.asyncio
    async def test_get_analytics_market_analysis(self) -> None:
        """Test getting market analysis analytics."""
        with patch("discovery.analytics.get_analytics_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_instance.analyze_market_trends.return_value = AnalyticsResult(
                chart_type="area",
                chart_data={},
                insights=["Test insight"],
                metadata={},
            )
            mock_getter.return_value = mock_instance

            request = AnalyticsRequest(analysis_type="market_analysis")
            result = await get_analytics(request)

            assert result.chart_type == "area"
            mock_instance.analyze_market_trends.assert_called_once_with("format")

    @pytest.mark.asyncio
    async def test_get_analytics_invalid_type(self) -> None:
        """Test analytics with invalid type returns error."""
        with patch("discovery.analytics.get_analytics_instance") as mock_getter:
            mock_instance = AsyncMock()
            mock_getter.return_value = mock_instance

            request = AnalyticsRequest(analysis_type="invalid_type")
            result = await get_analytics(request)

            assert result.chart_type == "bar"
            assert result.chart_data == {}
            assert "Invalid analysis type" in result.insights[0]
