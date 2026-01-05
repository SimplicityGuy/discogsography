"""Live trend tracking and notifications.

This module tracks trending artists, genres, releases, and other entities
in real-time and sends notifications through WebSocket channels.
"""

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from neo4j import AsyncDriver

from discovery.websocket_manager import Channel, WebSocketManager


logger = structlog.get_logger(__name__)


@dataclass
class TrendingItem:
    """A trending item."""

    item_type: str  # artist, release, genre, etc.
    item_id: str
    item_name: str
    score: float
    change: float  # Change from previous period
    rank: int
    metadata: dict[str, Any]


class TrendTracker:
    """Track and broadcast trending items in real-time."""

    def __init__(
        self,
        driver: AsyncDriver,
        websocket_manager: WebSocketManager,
    ) -> None:
        """Initialize trend tracker.

        Args:
            driver: Neo4j async driver instance
            websocket_manager: WebSocket manager for broadcasting
        """
        self.driver = driver
        self.ws_manager = websocket_manager

        # Current trending items
        self.trending: dict[str, list[TrendingItem]] = {}

        # Historical trending data for comparison
        self.trending_history: dict[str, dict[str, list[TrendingItem]]] = defaultdict(dict)

        # Activity tracking (for real-time trends)
        self.recent_activity: dict[str, Counter[str]] = defaultdict(Counter)
        self.activity_window = timedelta(hours=1)

        # Update intervals
        self.update_interval = 300  # 5 minutes
        self.running = False

    async def start(self) -> None:
        """Start the trend tracking background task."""
        self.running = True
        logger.info("🚀 Starting trend tracker...")

        # Fire-and-forget background task
        _ = asyncio.create_task(self._tracking_loop())  # noqa: RUF006

    async def stop(self) -> None:
        """Stop the trend tracking background task."""
        self.running = False
        logger.info("🛑 Stopping trend tracker...")

    async def _tracking_loop(self) -> None:
        """Main tracking loop."""
        while self.running:
            try:
                # Update all trending categories
                await self._update_trending_artists()
                await self._update_trending_genres()
                await self._update_trending_releases()

                # Broadcast updates
                await self._broadcast_trending()

                # Wait for next update
                await asyncio.sleep(self.update_interval)

            except Exception as e:
                logger.error("❌ Error in trend tracking loop", error=str(e))
                await asyncio.sleep(60)  # Wait a bit before retrying

    async def _update_trending_artists(self) -> None:
        """Update trending artists."""
        logger.debug("📊 Updating trending artists...")

        async with self.driver.session() as session:
            # Get recent activity (searches, views, etc.)
            # In a real implementation, this would track actual user interactions
            # For now, we'll use a proxy metric

            result = await session.run(
                """
                MATCH (a:Artist)
                WITH a, size((a)-[]-()) AS connections
                RETURN a.id AS id, a.name AS name, connections
                ORDER BY connections DESC
                LIMIT 20
                """
            )

            trending_artists = []
            rank = 1

            async for record in result:
                artist_id = record["id"]
                artist_name = record["name"]
                score = record["connections"]

                # Calculate change from previous period
                previous = self._get_previous_rank("artist", artist_id)
                change = previous - rank if previous else 0

                trending_artists.append(
                    TrendingItem(
                        item_type="artist",
                        item_id=artist_id,
                        item_name=artist_name,
                        score=float(score),
                        change=float(change),
                        rank=rank,
                        metadata={"connections": score},
                    )
                )

                rank += 1

        # Store current trending
        self.trending["artists"] = trending_artists

        # Save to history
        timestamp = datetime.now(UTC).isoformat()
        self.trending_history["artists"][timestamp] = trending_artists

        logger.info("✅ Updated trending artists", count=len(trending_artists))

    async def _update_trending_genres(self) -> None:
        """Update trending genres."""
        logger.debug("📊 Updating trending genres...")

        async with self.driver.session() as session:
            # Get genres by recent release activity
            result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(g:Genre)
                WHERE r.year >= $recent_year
                WITH g, count(r) AS release_count
                RETURN g.name AS name, release_count
                ORDER BY release_count DESC
                LIMIT 20
                """,
                recent_year=datetime.now().year - 1,
            )

            trending_genres = []
            rank = 1

            async for record in result:
                genre_name = record["name"]
                score = record["release_count"]

                # Calculate change
                previous = self._get_previous_rank("genre", genre_name)
                change = previous - rank if previous else 0

                trending_genres.append(
                    TrendingItem(
                        item_type="genre",
                        item_id=genre_name,
                        item_name=genre_name,
                        score=float(score),
                        change=float(change),
                        rank=rank,
                        metadata={"recent_releases": score},
                    )
                )

                rank += 1

        self.trending["genres"] = trending_genres

        timestamp = datetime.now(UTC).isoformat()
        self.trending_history["genres"][timestamp] = trending_genres

        logger.info("✅ Updated trending genres", count=len(trending_genres))

    async def _update_trending_releases(self) -> None:
        """Update trending releases."""
        logger.debug("📊 Updating trending releases...")

        async with self.driver.session() as session:
            # Get recent popular releases
            result = await session.run(
                """
                MATCH (r:Release)
                WHERE r.year >= $recent_year
                WITH r, size((r)-[]-()) AS connections
                RETURN r.id AS id, r.title AS title, r.year AS year, connections
                ORDER BY connections DESC
                LIMIT 20
                """,
                recent_year=datetime.now().year - 1,
            )

            trending_releases = []
            rank = 1

            async for record in result:
                release_id = record["id"]
                release_title = record["title"]
                score = record["connections"]

                # Calculate change
                previous = self._get_previous_rank("release", release_id)
                change = previous - rank if previous else 0

                trending_releases.append(
                    TrendingItem(
                        item_type="release",
                        item_id=release_id,
                        item_name=release_title,
                        score=float(score),
                        change=float(change),
                        rank=rank,
                        metadata={
                            "year": record["year"],
                            "connections": score,
                        },
                    )
                )

                rank += 1

        self.trending["releases"] = trending_releases

        timestamp = datetime.now(UTC).isoformat()
        self.trending_history["releases"][timestamp] = trending_releases

        logger.info("✅ Updated trending releases", count=len(trending_releases))

    def _get_previous_rank(self, item_type: str, item_id: str) -> int | None:
        """Get previous rank for an item.

        Args:
            item_type: Type of item
            item_id: Item ID

        Returns:
            Previous rank or None
        """
        category_key = f"{item_type}s"  # artists, genres, releases

        if category_key not in self.trending:
            return None

        for rank, item in enumerate(self.trending[category_key], start=1):
            if item.item_id == item_id:
                return rank

        return None

    async def _broadcast_trending(self) -> None:
        """Broadcast trending updates to subscribers."""
        trending_data = {
            "artists": [self._item_to_dict(item) for item in self.trending.get("artists", [])[:10]],
            "genres": [self._item_to_dict(item) for item in self.trending.get("genres", [])[:10]],
            "releases": [self._item_to_dict(item) for item in self.trending.get("releases", [])[:10]],
            "timestamp": datetime.now(UTC).isoformat(),
        }

        await self.ws_manager.send_update(
            Channel.TRENDING.value,
            "trending_update",
            trending_data,
        )

        # Check for significant changes and send notifications
        await self._check_for_notable_changes()

    async def _check_for_notable_changes(self) -> None:
        """Check for notable changes and send notifications."""
        # Check for rapid risers
        for category, items in self.trending.items():
            for item in items[:5]:  # Top 5 items
                if item.change >= 10:  # Moved up 10+ places
                    await self.ws_manager.send_notification(
                        Channel.TRENDING.value,
                        "Rapid Riser!",
                        f"{item.item_name} has jumped {int(item.change)} positions in trending {category}!",
                        data=self._item_to_dict(item),
                        level="success",
                    )

    def _item_to_dict(self, item: TrendingItem) -> dict[str, Any]:
        """Convert trending item to dictionary.

        Args:
            item: Trending item

        Returns:
            Dictionary representation
        """
        return {
            "type": item.item_type,
            "id": item.item_id,
            "name": item.item_name,
            "score": item.score,
            "change": item.change,
            "rank": item.rank,
            "metadata": item.metadata,
        }

    def track_activity(
        self,
        activity_type: str,
        item_id: str,
    ) -> None:
        """Track user activity for real-time trending.

        Args:
            activity_type: Type of activity (view, search, etc.)
            item_id: ID of item being interacted with
        """
        self.recent_activity[activity_type][item_id] += 1

    def get_trending(
        self,
        category: str,
        limit: int = 10,
    ) -> list[TrendingItem]:
        """Get current trending items for a category.

        Args:
            category: Category (artists, genres, releases)
            limit: Number of items to return

        Returns:
            List of trending items
        """
        return self.trending.get(category, [])[:limit]

    def get_trending_summary(self) -> dict[str, Any]:
        """Get summary of all trending items.

        Returns:
            Trending summary
        """
        return {
            "artists": [self._item_to_dict(item) for item in self.trending.get("artists", [])[:10]],
            "genres": [self._item_to_dict(item) for item in self.trending.get("genres", [])[:10]],
            "releases": [self._item_to_dict(item) for item in self.trending.get("releases", [])[:10]],
            "last_updated": datetime.now(UTC).isoformat(),
        }

    def get_trending_history(
        self,
        category: str,
        hours: int = 24,
    ) -> dict[str, list[dict[str, Any]]]:
        """Get trending history for analysis.

        Args:
            category: Category (artists, genres, releases)
            hours: Hours of history to return

        Returns:
            Historical trending data
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        history_data = {}

        for timestamp_str, items in self.trending_history[category].items():
            timestamp = datetime.fromisoformat(timestamp_str)

            if timestamp >= cutoff:
                history_data[timestamp_str] = [self._item_to_dict(item) for item in items]

        return history_data

    async def detect_emerging_trends(self) -> list[dict[str, Any]]:
        """Detect emerging trends (items rapidly gaining popularity).

        Returns:
            List of emerging trends
        """
        emerging = []

        for category, items in self.trending.items():
            for item in items:
                # Items with positive change and lower ranks are emerging
                if item.change > 5 and item.rank > 5:
                    emerging.append(
                        {
                            "category": category,
                            "item": self._item_to_dict(item),
                            "status": "emerging",
                            "reason": f"Moved up {int(item.change)} positions",
                        }
                    )

        # Sort by change
        emerging.sort(key=lambda x: float(x["item"]["change"]), reverse=True)  # type: ignore[index]

        logger.info("🔥 Detected emerging trends", count=len(emerging))

        return emerging[:10]
