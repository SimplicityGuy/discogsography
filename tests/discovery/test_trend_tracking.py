"""Tests for TrendTracker class."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.trend_tracking import TrendingItem, TrendTracker


class TestTrendingItemDataclass:
    """Test TrendingItem dataclass."""

    def test_create_trending_item(self) -> None:
        """Test creating a trending item."""
        item = TrendingItem(
            item_type="artist",
            item_id="1",
            item_name="Test Artist",
            score=100.0,
            change=5.0,
            rank=1,
            metadata={"connections": 100},
        )

        assert item.item_type == "artist"
        assert item.item_id == "1"
        assert item.item_name == "Test Artist"
        assert item.score == 100.0
        assert item.change == 5.0
        assert item.rank == 1
        assert item.metadata["connections"] == 100


class TestTrendTrackerInit:
    """Test TrendTracker initialization."""

    def test_initialization(self) -> None:
        """Test tracker initializes correctly."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        assert tracker.driver == mock_driver
        assert tracker.ws_manager == mock_ws_manager
        assert tracker.trending == {}
        assert tracker.update_interval == 300
        assert tracker.running is False


class TestStartStop:
    """Test start/stop methods."""

    @pytest.mark.asyncio
    async def test_start_tracker(self) -> None:
        """Test starting the tracker."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        await tracker.start()

        assert tracker.running is True

    @pytest.mark.asyncio
    async def test_stop_tracker(self) -> None:
        """Test stopping the tracker."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()

        tracker = TrendTracker(mock_driver, mock_ws_manager)
        tracker.running = True

        await tracker.stop()

        assert tracker.running is False


class TestUpdateTrendingArtists:
    """Test updating trending artists."""

    @pytest.mark.asyncio
    async def test_update_trending_artists(self) -> None:
        """Test updating trending artists from Neo4j."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock Neo4j data
        mock_records = [
            {"id": "1", "name": "Artist A", "connections": 100},
            {"id": "2", "name": "Artist B", "connections": 50},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        await tracker._update_trending_artists()

        assert "artists" in tracker.trending
        assert len(tracker.trending["artists"]) == 2
        assert tracker.trending["artists"][0].item_name == "Artist A"
        assert tracker.trending["artists"][0].rank == 1

    @pytest.mark.asyncio
    async def test_update_trending_artists_empty(self) -> None:
        """Test updating with no trending artists."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        async def async_iter(self):
            return
            yield  # Make it a generator

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        await tracker._update_trending_artists()

        assert "artists" in tracker.trending
        assert len(tracker.trending["artists"]) == 0


class TestUpdateTrendingGenres:
    """Test updating trending genres."""

    @pytest.mark.asyncio
    async def test_update_trending_genres(self) -> None:
        """Test updating trending genres from Neo4j."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock Neo4j data
        mock_records = [
            {"name": "Rock", "release_count": 500},
            {"name": "Jazz", "release_count": 300},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        await tracker._update_trending_genres()

        assert "genres" in tracker.trending
        assert len(tracker.trending["genres"]) == 2
        assert tracker.trending["genres"][0].item_name == "Rock"
        assert tracker.trending["genres"][0].score == 500.0


class TestUpdateTrendingReleases:
    """Test updating trending releases."""

    @pytest.mark.asyncio
    async def test_update_trending_releases(self) -> None:
        """Test updating trending releases from Neo4j."""
        mock_driver = MagicMock()
        mock_ws_manager = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()

        # Mock Neo4j data
        mock_records = [
            {"id": "r1", "title": "Album A", "year": 2023, "connections": 150},
            {"id": "r2", "title": "Album B", "year": 2024, "connections": 100},
        ]

        async def async_iter(self):
            for record in mock_records:
                yield record

        mock_result.__aiter__ = async_iter
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_driver.session.return_value.__aexit__.return_value = None

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        await tracker._update_trending_releases()

        assert "releases" in tracker.trending
        assert len(tracker.trending["releases"]) == 2
        assert tracker.trending["releases"][0].item_name == "Album A"
        assert tracker.trending["releases"][0].metadata["year"] == 2023


class TestGetPreviousRank:
    """Test getting previous rank."""

    def test_get_previous_rank_found(self) -> None:
        """Test getting previous rank when item exists."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        # Set up some trending items
        tracker.trending["artists"] = [
            TrendingItem("artist", "1", "Artist A", 100.0, 0, 1, {}),
            TrendingItem("artist", "2", "Artist B", 90.0, 0, 2, {}),
            TrendingItem("artist", "3", "Artist C", 80.0, 0, 3, {}),
        ]

        rank = tracker._get_previous_rank("artist", "2")
        assert rank == 2

    def test_get_previous_rank_not_found(self) -> None:
        """Test getting previous rank when item doesn't exist."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        tracker.trending["artists"] = [
            TrendingItem("artist", "1", "Artist A", 100.0, 0, 1, {}),
        ]

        rank = tracker._get_previous_rank("artist", "999")
        assert rank is None

    def test_get_previous_rank_empty_category(self) -> None:
        """Test getting previous rank when category doesn't exist."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        rank = tracker._get_previous_rank("nonexistent", "1")
        assert rank is None


class TestBroadcastTrending:
    """Test broadcasting trending updates."""

    @pytest.mark.asyncio
    async def test_broadcast_trending(self) -> None:
        """Test broadcasting trending updates to WebSocket subscribers."""
        mock_driver = MagicMock()
        mock_ws_manager = AsyncMock()

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        # Set up some trending data
        tracker.trending["artists"] = [TrendingItem("artist", "1", "Artist A", 100.0, 5.0, 1, {"connections": 100})]
        tracker.trending["genres"] = [TrendingItem("genre", "Rock", "Rock", 500.0, 3.0, 1, {"recent_releases": 500})]
        tracker.trending["releases"] = [TrendingItem("release", "r1", "Album A", 150.0, 2.0, 1, {"year": 2023})]

        await tracker._broadcast_trending()

        mock_ws_manager.send_update.assert_called_once()
        call_args = mock_ws_manager.send_update.call_args
        assert call_args[0][1] == "trending_update"

        # Should also call _check_for_notable_changes
        mock_ws_manager.send_notification.assert_not_called()  # No items with change >= 10


class TestCheckForNotableChanges:
    """Test checking for notable changes."""

    @pytest.mark.asyncio
    async def test_check_for_notable_changes_rapid_riser(self) -> None:
        """Test detecting rapid risers (change >= 10)."""
        mock_driver = MagicMock()
        mock_ws_manager = AsyncMock()

        tracker = TrendTracker(mock_driver, mock_ws_manager)

        # Set up item with large positive change
        tracker.trending["artists"] = [TrendingItem("artist", "1", "Rising Artist", 100.0, 15.0, 2, {"connections": 100})]

        await tracker._check_for_notable_changes()

        mock_ws_manager.send_notification.assert_called_once()
        call_args = mock_ws_manager.send_notification.call_args
        assert "Rapid Riser!" in call_args[0][1]
        assert "15" in call_args[0][2]  # Change amount mentioned


class TestItemToDict:
    """Test converting trending item to dictionary."""

    def test_item_to_dict(self) -> None:
        """Test item to dict conversion."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        item = TrendingItem(
            item_type="artist",
            item_id="1",
            item_name="Test Artist",
            score=100.0,
            change=5.0,
            rank=1,
            metadata={"connections": 100},
        )

        result = tracker._item_to_dict(item)

        assert result["type"] == "artist"
        assert result["id"] == "1"
        assert result["name"] == "Test Artist"
        assert result["score"] == 100.0
        assert result["change"] == 5.0
        assert result["rank"] == 1
        assert result["metadata"]["connections"] == 100


class TestTrackActivity:
    """Test tracking user activity."""

    def test_track_activity(self) -> None:
        """Test tracking user activity."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        tracker.track_activity("view", "artist_1")
        tracker.track_activity("view", "artist_1")
        tracker.track_activity("view", "artist_2")

        assert tracker.recent_activity["view"]["artist_1"] == 2
        assert tracker.recent_activity["view"]["artist_2"] == 1


class TestGetTrending:
    """Test getting trending items."""

    def test_get_trending(self) -> None:
        """Test getting trending items for a category."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        # Set up trending data
        tracker.trending["artists"] = [TrendingItem("artist", str(i), f"Artist {i}", float(100 - i), 0, i, {}) for i in range(1, 21)]

        # Get top 10
        result = tracker.get_trending("artists", limit=10)

        assert len(result) == 10
        assert result[0].item_name == "Artist 1"

    def test_get_trending_empty_category(self) -> None:
        """Test getting trending for empty category."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        result = tracker.get_trending("nonexistent", limit=10)

        assert result == []


class TestGetTrendingSummary:
    """Test getting trending summary."""

    def test_get_trending_summary(self) -> None:
        """Test getting summary of all trending items."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        tracker.trending["artists"] = [TrendingItem("artist", "1", "Artist A", 100.0, 0, 1, {})]
        tracker.trending["genres"] = [TrendingItem("genre", "Rock", "Rock", 500.0, 0, 1, {})]
        tracker.trending["releases"] = [TrendingItem("release", "r1", "Album A", 150.0, 0, 1, {})]

        result = tracker.get_trending_summary()

        assert "artists" in result
        assert "genres" in result
        assert "releases" in result
        assert "last_updated" in result
        assert len(result["artists"]) == 1
        assert result["artists"][0]["name"] == "Artist A"


class TestGetTrendingHistory:
    """Test getting trending history."""

    def test_get_trending_history(self) -> None:
        """Test getting historical trending data."""
        from datetime import UTC, datetime, timedelta

        tracker = TrendTracker(MagicMock(), MagicMock())

        # Set up some history
        now = datetime.now(UTC)
        timestamp1 = (now - timedelta(hours=2)).isoformat()
        timestamp2 = (now - timedelta(hours=30)).isoformat()  # Outside 24hr window

        tracker.trending_history["artists"][timestamp1] = [TrendingItem("artist", "1", "Artist A", 100.0, 0, 1, {})]
        tracker.trending_history["artists"][timestamp2] = [TrendingItem("artist", "2", "Artist B", 90.0, 0, 2, {})]

        # Get history for last 24 hours
        result = tracker.get_trending_history("artists", hours=24)

        # Should only include timestamp1, not timestamp2
        assert timestamp1 in result
        assert timestamp2 not in result
        assert len(result[timestamp1]) == 1


class TestDetectEmergingTrends:
    """Test detecting emerging trends."""

    @pytest.mark.asyncio
    async def test_detect_emerging_trends(self) -> None:
        """Test detecting items rapidly gaining popularity."""
        tracker = TrendTracker(MagicMock(), MagicMock())

        # Set up items with different change patterns
        tracker.trending["artists"] = [
            TrendingItem("artist", "1", "Top Artist", 100.0, 2.0, 1, {}),  # Not emerging (rank 1)
            TrendingItem("artist", "2", "Emerging Artist", 90.0, 8.0, 6, {}),  # Emerging!
            TrendingItem("artist", "3", "Another", 80.0, 3.0, 8, {}),  # Low change
        ]

        result = await tracker.detect_emerging_trends()

        assert len(result) == 1
        assert result[0]["item"]["name"] == "Emerging Artist"
        assert result[0]["status"] == "emerging"
        assert "8" in result[0]["reason"]
