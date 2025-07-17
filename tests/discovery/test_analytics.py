"""Tests for the music analytics engine."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discovery.analytics import AnalyticsRequest, AnalyticsResult, MusicAnalytics, get_analytics


class TestMusicAnalytics:
    """Test the MusicAnalytics class."""

    @pytest.fixture
    async def analytics(self, mock_neo4j_driver, mock_postgres_engine):
        """Create a MusicAnalytics instance with mocked dependencies."""
        with patch("discovery.analytics.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                neo4j_address="bolt://localhost:7687",
                neo4j_username="neo4j",
                neo4j_password="password",
                postgres_address="localhost:5432",
                postgres_username="postgres",
                postgres_password="password",
                postgres_database="test",
            )

            analytics = MusicAnalytics()
            analytics.neo4j_driver = mock_neo4j_driver
            analytics.postgres_engine = mock_postgres_engine

            return analytics

    async def test_initialize(self, analytics):
        """Test analytics initialization."""
        with (
            patch("discovery.analytics.AsyncGraphDatabase.driver"),
            patch("discovery.analytics.create_async_engine"),
        ):
            await analytics.initialize()
            # Should not raise any exceptions

    async def test_analyze_genre_trends(self, analytics, mock_neo4j_driver):
        """Test genre trends analysis."""
        # Mock database results
        mock_result = AsyncMock()
        mock_records = [
            {"genre": "Jazz", "year": 1990, "releases": 100},
            {"genre": "Jazz", "year": 1995, "releases": 150},
            {"genre": "Rock", "year": 1990, "releases": 200},
            {"genre": "Rock", "year": 1995, "releases": 180},
        ]
        mock_result.__aiter__ = AsyncMock(return_value=iter(mock_records))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_genre_trends((1990, 2000))

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "line"
        assert isinstance(result.insights, list)
        assert len(result.insights) > 0

    async def test_analyze_genre_trends_no_data(self, analytics, mock_neo4j_driver):
        """Test genre trends analysis with no data."""
        # Mock empty database results
        mock_result = AsyncMock()
        mock_result.__aiter__ = AsyncMock(return_value=iter([]))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_genre_trends()

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "line"
        assert "No genre data available" in result.insights[0]

    async def test_analyze_artist_evolution(self, analytics, mock_neo4j_driver):
        """Test artist evolution analysis."""
        # Mock database results for releases
        mock_result = AsyncMock()
        mock_records = [
            {
                "year": 1955,
                "title": "Birth of the Cool",
                "genres": ["Jazz"],
                "styles": ["Cool Jazz"],
            },
            {"year": 1959, "title": "Kind of Blue", "genres": ["Jazz"], "styles": ["Modal Jazz"]},
        ]
        mock_result.__aiter__ = AsyncMock(return_value=iter(mock_records))

        # Mock collaborations result
        mock_collab_result = AsyncMock()
        mock_collab_records = [
            {"collaborator": "John Coltrane", "collaborations": 5},
            {"collaborator": "Bill Evans", "collaborations": 3},
        ]
        mock_collab_result.__aiter__ = AsyncMock(return_value=iter(mock_collab_records))

        # Set up session mock to return different results for different queries
        session_mock = mock_neo4j_driver.session.return_value.__aenter__.return_value
        session_mock.run.side_effect = [mock_result, mock_collab_result]

        result = await analytics.analyze_artist_evolution("Miles Davis")

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "scatter"
        assert isinstance(result.insights, list)

    async def test_analyze_artist_evolution_no_data(self, analytics, mock_neo4j_driver):
        """Test artist evolution with no data."""
        mock_result = AsyncMock()
        mock_result.__aiter__ = AsyncMock(return_value=iter([]))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_artist_evolution("Unknown Artist")

        assert isinstance(result, AnalyticsResult)
        assert "No release data found" in result.insights[0]

    async def test_analyze_label_insights_specific(self, analytics, mock_neo4j_driver):
        """Test label insights for specific label."""
        mock_result = AsyncMock()
        mock_records = [
            {
                "label": "Blue Note",
                "artist": "Miles Davis",
                "year": 1959,
                "genres": ["Jazz"],
                "releases": 10,
            }
        ]
        mock_result.__aiter__ = AsyncMock(return_value=iter(mock_records))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_label_insights("Blue Note")

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "bar"

    async def test_analyze_label_insights_market_overview(self, analytics, mock_neo4j_driver):
        """Test label insights market overview."""
        mock_result = AsyncMock()
        mock_records = [
            {
                "label": "Blue Note",
                "artists": 50,
                "releases": 500,
                "first_release": 1939,
                "last_release": 2023,
            }
        ]
        mock_result.__aiter__ = AsyncMock(return_value=iter(mock_records))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_label_insights()

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "bar"

    async def test_analyze_market_trends_format(self, analytics, mock_neo4j_driver):
        """Test market trends analysis for formats."""
        mock_result = AsyncMock()
        mock_records = [
            {"year": 1990, "format_type": "Vinyl", "releases": 100},
            {"year": 1995, "format_type": "CD", "releases": 200},
            {"year": 2000, "format_type": "Digital", "releases": 150},
        ]
        mock_result.__aiter__ = AsyncMock(return_value=iter(mock_records))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_market_trends("format")

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "area"

    async def test_analyze_market_trends_regional(self, analytics, mock_neo4j_driver):
        """Test market trends analysis for regions."""
        mock_result = AsyncMock()
        mock_records = [
            {"year": 1990, "country": "US", "releases": 500},
            {"year": 1995, "country": "UK", "releases": 300},
        ]
        mock_result.__aiter__ = AsyncMock(return_value=iter(mock_records))
        mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = (
            mock_result
        )

        result = await analytics.analyze_market_trends("regional")

        assert isinstance(result, AnalyticsResult)
        assert result.chart_type == "line"

    async def test_close(self, analytics):
        """Test closing the analytics engine."""
        await analytics.close()
        if analytics.neo4j_driver:
            analytics.neo4j_driver.close.assert_called_once()


class TestAnalyticsModels:
    """Test analytics request/result models."""

    def test_analytics_request_model(self):
        """Test AnalyticsRequest model validation."""
        request = AnalyticsRequest(analysis_type="genre_trends", time_range=(1990, 2020), limit=25)

        assert request.analysis_type == "genre_trends"
        assert request.time_range == (1990, 2020)
        assert request.limit == 25

    def test_analytics_request_defaults(self):
        """Test AnalyticsRequest default values."""
        request = AnalyticsRequest(analysis_type="genre_trends")

        assert request.limit == 20
        assert request.time_range is None

    def test_analytics_result_model(self):
        """Test AnalyticsResult model."""
        result = AnalyticsResult(
            chart_type="line",
            chart_data={"test": "data"},
            insights=["Test insight"],
            metadata={"total": 100},
        )

        assert result.chart_type == "line"
        assert result.chart_data == {"test": "data"}
        assert "Test insight" in result.insights
        assert result.metadata["total"] == 100


class TestAnalyticsAPI:
    """Test the analytics API functions."""

    @pytest.mark.asyncio
    async def test_get_analytics_genre_trends(self, mock_analytics, sample_analytics_data):
        """Test getting genre trends analytics."""
        with patch("discovery.analytics.analytics", mock_analytics):
            mock_analytics.analyze_genre_trends.return_value = sample_analytics_data

            request = AnalyticsRequest(analysis_type="genre_trends")

            result = await get_analytics(request)

            assert result["chart_type"] == "line"
            assert len(result["insights"]) > 0

    @pytest.mark.asyncio
    async def test_get_analytics_artist_evolution(self, mock_analytics, sample_analytics_data):
        """Test getting artist evolution analytics."""
        with patch("discovery.analytics.analytics", mock_analytics):
            mock_analytics.analyze_artist_evolution.return_value = sample_analytics_data

            request = AnalyticsRequest(analysis_type="artist_evolution", artist_name="Miles Davis")

            result = await get_analytics(request)

            assert result["chart_type"] == "line"

    @pytest.mark.asyncio
    async def test_get_analytics_label_insights(self, mock_analytics, sample_analytics_data):
        """Test getting label insights analytics."""
        with patch("discovery.analytics.analytics", mock_analytics):
            mock_analytics.analyze_label_insights.return_value = sample_analytics_data

            request = AnalyticsRequest(analysis_type="label_insights", label_name="Blue Note")

            result = await get_analytics(request)

            assert result["chart_type"] == "line"

    @pytest.mark.asyncio
    async def test_get_analytics_market_analysis(self, mock_analytics, sample_analytics_data):
        """Test getting market analysis analytics."""
        with patch("discovery.analytics.analytics", mock_analytics):
            mock_analytics.analyze_market_trends.return_value = sample_analytics_data

            request = AnalyticsRequest(analysis_type="market_analysis")

            result = await get_analytics(request)

            assert result["chart_type"] == "line"

    @pytest.mark.asyncio
    async def test_get_analytics_invalid_type(self, mock_analytics):
        """Test handling invalid analytics type."""
        with patch("discovery.analytics.analytics", mock_analytics):
            request = AnalyticsRequest(analysis_type="invalid")

            result = await get_analytics(request)

            assert result["chart_type"] == "bar"
            assert "Invalid analysis type" in result["insights"]
