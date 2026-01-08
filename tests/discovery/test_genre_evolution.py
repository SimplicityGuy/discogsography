"""Tests for GenreEvolutionTracker class."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.genre_evolution import GenreEvolutionTracker, GenreTrend


class TestGenreTrendDataclass:
    """Test GenreTrend dataclass."""

    def test_create_genre_trend(self) -> None:
        """Test creating a genre trend."""
        trend = GenreTrend(
            genre="Rock",
            timeline={1980: 100, 1981: 150},
            peak_year=1981,
            peak_count=150,
            total_releases=250,
            growth_rate=0.5,
            status="growing",
        )

        assert trend.genre == "Rock"
        assert trend.peak_year == 1981
        assert trend.peak_count == 150
        assert trend.status == "growing"


class TestGenreEvolutionTrackerInit:
    """Test GenreEvolutionTracker initialization."""

    def test_initialization(self) -> None:
        """Test tracker initializes correctly."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        assert tracker.driver == mock_driver
        assert tracker.genre_timelines == {}
        assert tracker.style_timelines == {}
        assert tracker.genre_cooccurrence == {}


class TestAnalyzeGenreTimeline:
    """Test analyzing genre timeline."""

    @pytest.mark.asyncio
    async def test_analyze_genre_timeline(self) -> None:
        """Test analyzing genre evolution over time."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock genre timeline data
        mock_records = [
            {"genre": "Rock", "year": 1980, "count": 100},
            {"genre": "Rock", "year": 1981, "count": 150},
            {"genre": "Jazz", "year": 1980, "count": 80},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = GenreEvolutionTracker(mock_driver)
        trends = await tracker.analyze_genre_timeline(1980, 2024)

        assert "Rock" in trends
        assert "Jazz" in trends
        assert isinstance(trends["Rock"], GenreTrend)
        assert trends["Rock"].total_releases == 250
        assert tracker.genre_timelines["Rock"][1980] == 100


class TestAnalyzeStyleTimeline:
    """Test analyzing style timeline."""

    @pytest.mark.asyncio
    async def test_analyze_style_timeline(self) -> None:
        """Test analyzing style evolution over time."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {"style": "Alternative", "year": 1990, "count": 50},
            {"style": "Alternative", "year": 1991, "count": 75},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = GenreEvolutionTracker(mock_driver)
        trends = await tracker.analyze_style_timeline(1990, 2024)

        assert "Alternative" in trends
        assert tracker.style_timelines["Alternative"][1990] == 50


class TestAnalyzeTrend:
    """Test trend analysis."""

    def test_analyze_trend_with_data(self) -> None:
        """Test analyzing trend with timeline data."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        timeline = {2015: 50, 2016: 60, 2017: 80, 2018: 100, 2019: 120, 2020: 140}
        trend = tracker._analyze_trend("Rock", timeline, 2010, 2020)

        assert trend.genre == "Rock"
        assert trend.peak_year == 2020
        assert trend.peak_count == 140
        assert trend.total_releases == 550
        assert trend.growth_rate > 0

    def test_analyze_trend_empty_timeline(self) -> None:
        """Test analyzing trend with no data."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        trend = tracker._analyze_trend("Unknown", {}, 2010, 2020)

        assert trend.genre == "Unknown"
        assert trend.peak_year == 0
        assert trend.total_releases == 0
        assert trend.status == "unknown"


class TestDetermineStatus:
    """Test status determination."""

    def test_determine_status_emerging(self) -> None:
        """Test emerging status."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        status = tracker._determine_status(0.6, 50, 2020, 2024)

        assert status == "emerging"

    def test_determine_status_growing(self) -> None:
        """Test growing status."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        status = tracker._determine_status(0.3, 500, 2020, 2024)

        assert status == "growing"

    def test_determine_status_declining(self) -> None:
        """Test declining status."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        status = tracker._determine_status(-0.3, 200, 2015, 2024)

        assert status == "declining"

    def test_determine_status_stable(self) -> None:
        """Test stable status."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        status = tracker._determine_status(0.1, 300, 2020, 2024)

        assert status == "stable"


class TestAnalyzeGenreCrossover:
    """Test genre crossover analysis."""

    @pytest.mark.asyncio
    async def test_analyze_genre_crossover(self) -> None:
        """Test analyzing genre cross-pollination."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        mock_records = [
            {
                "genre1": "Rock",
                "genre2": "Electronic",
                "count": 50,
                "years": [2015, 2016, 2017],
            },
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = GenreEvolutionTracker(mock_driver)
        crossover = await tracker.analyze_genre_crossover(2010, 2024, min_cooccurrence=10)

        assert ("Rock", "Electronic") in crossover
        assert crossover[("Rock", "Electronic")]["count"] == 50
        assert crossover[("Rock", "Electronic")]["year_range"] == (2015, 2017)


class TestGetDecadeSummary:
    """Test getting decade summary."""

    @pytest.mark.asyncio
    async def test_get_decade_summary(self) -> None:
        """Test getting summary for a decade."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Mock genre result
        genre_result = AsyncMock()

        async def genre_iter(self):
            yield {"genre": "Rock", "count": 1000}
            yield {"genre": "Pop", "count": 800}

        genre_result.__aiter__ = genre_iter

        # Mock style result
        style_result = AsyncMock()

        async def style_iter(self):
            yield {"style": "Alternative", "count": 500}

        style_result.__aiter__ = style_iter

        # Mock label result
        label_result = AsyncMock()

        async def label_iter(self):
            yield {"label": "Warner", "count": 300}

        label_result.__aiter__ = label_iter

        # Setup session to return different results for each query
        call_count = 0

        async def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return genre_result
            if call_count == 2:
                return style_result
            return label_result

        mock_session.run = mock_run
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = GenreEvolutionTracker(mock_driver)
        summary = await tracker.get_decade_summary(1980)

        assert summary["decade"] == "1980s"
        assert summary["year_range"] == (1980, 1989)
        assert len(summary["top_genres"]) == 2
        assert summary["top_genres"][0]["genre"] == "Rock"
        assert len(summary["top_styles"]) == 1
        assert len(summary["top_labels"]) == 1


class TestFindEmergingGenres:
    """Test finding emerging genres."""

    @pytest.mark.asyncio
    async def test_find_emerging_genres(self) -> None:
        """Test finding emerging genres."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        # Setup timelines
        tracker.genre_timelines = {
            "NewGenre": {2020: 20, 2021: 30, 2022: 40, 2023: 50, 2024: 60},
            "OldGenre": {2020: 100, 2021: 95, 2022: 90, 2023: 85, 2024: 80},
        }

        emerging = await tracker.find_emerging_genres(min_growth_rate=1.0, min_recent_releases=20)

        # Should find NewGenre as emerging
        assert len(emerging) > 0
        assert any(g["genre"] == "NewGenre" for g in emerging)

    @pytest.mark.asyncio
    async def test_find_emerging_genres_empty_timelines(self) -> None:
        """Test finding emerging genres with empty timelines."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        async def async_iter(self):
            return
            yield  # Make it a generator

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = GenreEvolutionTracker(mock_driver)
        emerging = await tracker.find_emerging_genres()

        assert emerging == []


class TestCompareDecades:
    """Test comparing decades."""

    @pytest.mark.asyncio
    async def test_compare_decades(self) -> None:
        """Test comparing two decades."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        # Mock get_decade_summary
        summary1 = {
            "decade": "1980s",
            "year_range": (1980, 1989),
            "top_genres": [{"genre": "Rock", "count": 1000}, {"genre": "Pop", "count": 800}],
            "top_styles": [],
            "top_labels": [],
        }

        summary2 = {
            "decade": "1990s",
            "year_range": (1990, 1999),
            "top_genres": [{"genre": "Pop", "count": 1200}, {"genre": "Hip-Hop", "count": 900}],
            "top_styles": [],
            "top_labels": [],
        }

        async def mock_get_decade_summary(decade: int):
            return summary1 if decade == 1980 else summary2

        tracker.get_decade_summary = mock_get_decade_summary  # type: ignore

        comparison = await tracker.compare_decades(1980, 1990)

        assert comparison["decade1"]["decade"] == "1980s"
        assert comparison["decade2"]["decade"] == "1990s"
        assert "Pop" in comparison["common_genres"]
        assert "Hip-Hop" in comparison["new_genres"]
        assert "Rock" in comparison["disappeared_genres"]


class TestGetGenreLifecycle:
    """Test getting genre lifecycle."""

    def test_get_genre_lifecycle(self) -> None:
        """Test getting complete lifecycle of a genre."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        tracker.genre_timelines = {
            "Rock": {
                1960: 50,
                1970: 100,
                1980: 200,
                1990: 180,
                2000: 150,
            }
        }

        lifecycle = tracker.get_genre_lifecycle("Rock")

        assert lifecycle["genre"] == "Rock"
        assert lifecycle["emergence_year"] == 1960
        assert lifecycle["peak_year"] == 1980
        assert lifecycle["peak_count"] == 200
        assert "current_status" in lifecycle

    def test_get_genre_lifecycle_not_found(self) -> None:
        """Test lifecycle for unknown genre."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        lifecycle = tracker.get_genre_lifecycle("Unknown")

        assert "error" in lifecycle
        assert lifecycle["error"] == "Genre not found"


class TestExportEvolutionData:
    """Test exporting evolution data."""

    def test_export_evolution_data(self) -> None:
        """Test exporting all evolution data."""
        mock_driver = MagicMock()
        tracker = GenreEvolutionTracker(mock_driver)

        tracker.genre_timelines = {"Rock": {1980: 100}}
        tracker.style_timelines = {"Alternative": {1990: 50}}
        tracker.genre_cooccurrence = {("Rock", "Electronic"): 25}

        export = tracker.export_evolution_data()

        assert "genre_timelines" in export
        assert "style_timelines" in export
        assert "genre_cooccurrence" in export
        assert export["genre_timelines"]["Rock"][1980] == 100
        assert "Rock_Electronic" in export["genre_cooccurrence"]
