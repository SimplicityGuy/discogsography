"""Locust load testing suite for Discovery service.

This module defines realistic user behavior patterns for load testing
the Discovery service endpoints.

Usage:
    # Run with web UI
    locust -f tests/load/locustfile.py --host=http://localhost:8005

    # Run headless with specific parameters
    locust -f tests/load/locustfile.py --host=http://localhost:8005 \
           --users 100 --spawn-rate 10 --run-time 5m --headless

    # Run with custom configuration
    locust -f tests/load/locustfile.py --host=http://localhost:8005 \
           --config tests/load/locust.conf
"""

import random

from locust import HttpUser, between, task


# Sample search queries for realistic testing
SEARCH_QUERIES = [
    "Beatles",
    "Miles Davis",
    "Pink Floyd",
    "Led Zeppelin",
    "David Bowie",
    "The Doors",
    "Jimi Hendrix",
    "Bob Dylan",
    "The Rolling Stones",
    "Queen",
    "Jazz",
    "Rock",
    "Electronic",
    "Classical",
    "Hip Hop",
]

# Sample artist IDs for graph exploration
ARTIST_IDS = [
    "artist_1",
    "artist_100",
    "artist_500",
    "artist_1000",
    "artist_5000",
]

# Sample node IDs for detailed views
NODE_IDS = [
    "artist_1",
    "artist_50",
    "artist_100",
    "release_1",
    "release_100",
]


class SearchUser(HttpUser):
    """User that primarily searches for music."""

    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks
    weight = 3  # Higher weight = more of these users

    @task(5)
    def search_artists(self) -> None:
        """Search for artists."""
        query = random.choice(SEARCH_QUERIES)
        self.client.get(
            "/api/search",
            params={
                "q": query,
                "type": "artist",
                "limit": 10,
            },
            name="/api/search?type=artist",
        )

    @task(3)
    def search_releases(self) -> None:
        """Search for releases."""
        query = random.choice(SEARCH_QUERIES)
        self.client.get(
            "/api/search",
            params={
                "q": query,
                "type": "release",
                "limit": 10,
            },
            name="/api/search?type=release",
        )

    @task(2)
    def search_all(self) -> None:
        """Search all types."""
        query = random.choice(SEARCH_QUERIES)
        self.client.get(
            "/api/search",
            params={
                "q": query,
                "type": "all",
                "limit": 10,
            },
            name="/api/search?type=all",
        )

    @task(1)
    def search_with_pagination(self) -> None:
        """Search with pagination (simulate browsing multiple pages)."""
        query = random.choice(SEARCH_QUERIES)

        # First page
        response = self.client.get(
            "/api/search",
            params={
                "q": query,
                "type": "artist",
                "limit": 10,
            },
            name="/api/search?type=artist [page 1]",
        )

        # Second page if available
        if response.status_code == 200:
            data = response.json()
            if data.get("next_cursor"):
                self.client.get(
                    "/api/search",
                    params={
                        "q": query,
                        "type": "artist",
                        "limit": 10,
                        "cursor": data["next_cursor"],
                    },
                    name="/api/search?type=artist [page 2]",
                )


class GraphExplorerUser(HttpUser):
    """User that explores the music knowledge graph."""

    wait_time = between(2, 5)  # Wait 2-5 seconds between tasks
    weight = 2

    @task(5)
    def explore_graph(self) -> None:
        """Explore graph data for an artist."""
        node_id = random.choice(ARTIST_IDS)
        self.client.get(
            "/api/graph",
            params={
                "node_id": node_id,
                "depth": 2,
                "limit": 50,
            },
            name="/api/graph?depth=2",
        )

    @task(3)
    def explore_deep_graph(self) -> None:
        """Explore deeper graph relationships."""
        node_id = random.choice(ARTIST_IDS)
        self.client.get(
            "/api/graph",
            params={
                "node_id": node_id,
                "depth": 3,
                "limit": 30,
            },
            name="/api/graph?depth=3",
        )

    @task(2)
    def graph_with_pagination(self) -> None:
        """Explore graph with pagination."""
        node_id = random.choice(ARTIST_IDS)

        # First page
        response = self.client.get(
            "/api/graph",
            params={
                "node_id": node_id,
                "depth": 2,
                "limit": 50,
            },
            name="/api/graph?depth=2 [page 1]",
        )

        # Second page if available
        if response.status_code == 200:
            data = response.json()
            if data.get("next_cursor"):
                self.client.get(
                    "/api/graph",
                    params={
                        "node_id": node_id,
                        "depth": 2,
                        "limit": 50,
                        "cursor": data["next_cursor"],
                    },
                    name="/api/graph?depth=2 [page 2]",
                )

    @task(1)
    def get_artist_details(self) -> None:
        """Get detailed information about an artist."""
        artist_id = random.choice(ARTIST_IDS)
        self.client.get(
            f"/api/artists/{artist_id}",
            name="/api/artists/{artist_id}",
        )


class AnalyticsUser(HttpUser):
    """User that views analytics and trends."""

    wait_time = between(3, 8)  # Wait 3-8 seconds between tasks
    weight = 1  # Fewer analytics users

    @task(5)
    def view_genre_trends(self) -> None:
        """View genre trends over time."""
        start_year = random.choice([1960, 1970, 1980, 1990, 2000])
        end_year = start_year + 20

        self.client.get(
            "/api/trends",
            params={
                "type": "genre",
                "start_year": start_year,
                "end_year": end_year,
                "top_n": 20,
                "limit": 20,
            },
            name="/api/trends?type=genre",
        )

    @task(3)
    def view_artist_trends(self) -> None:
        """View artist trends over time."""
        start_year = random.choice([1960, 1970, 1980, 1990, 2000])
        end_year = start_year + 20

        self.client.get(
            "/api/trends",
            params={
                "type": "artist",
                "start_year": start_year,
                "end_year": end_year,
                "top_n": 20,
                "limit": 20,
            },
            name="/api/trends?type=artist",
        )

    @task(2)
    def view_genre_heatmap(self) -> None:
        """View genre similarity heatmap."""
        self.client.get(
            "/api/heatmap",
            params={
                "type": "genre",
                "top_n": 20,
                "limit": 100,
            },
            name="/api/heatmap?type=genre",
        )

    @task(1)
    def view_collab_heatmap(self) -> None:
        """View collaboration heatmap."""
        self.client.get(
            "/api/heatmap",
            params={
                "type": "collab",
                "top_n": 20,
                "limit": 100,
            },
            name="/api/heatmap?type=collab",
        )


class MonitoringUser(HttpUser):
    """User that checks service health and metrics."""

    wait_time = between(10, 30)  # Check less frequently
    weight = 0.5  # Very few monitoring users

    @task(5)
    def check_cache_stats(self) -> None:
        """Check cache statistics."""
        self.client.get("/api/cache/stats", name="/api/cache/stats")

    @task(3)
    def check_db_pool_stats(self) -> None:
        """Check database pool statistics."""
        self.client.get("/api/db/pool/stats", name="/api/db/pool/stats")

    @task(1)
    def check_metrics(self) -> None:
        """Check Prometheus metrics."""
        self.client.get("/metrics", name="/metrics")


class RealisticUser(HttpUser):
    """Realistic user that combines multiple behaviors."""

    wait_time = between(2, 10)  # Varied wait times
    weight = 5  # Most users are realistic users

    def on_start(self) -> None:
        """Called when a user starts."""
        # Simulate initial page load by checking cache stats
        self.client.get("/api/cache/stats", name="[startup] /api/cache/stats")

    @task(10)
    def search_workflow(self) -> None:
        """Complete search workflow: search -> view details."""
        # Search for something
        query = random.choice(SEARCH_QUERIES)
        response = self.client.get(
            "/api/search",
            params={
                "q": query,
                "type": "artist",
                "limit": 10,
            },
            name="[workflow] search artists",
        )

        # If we got results, view details of the first one
        if response.status_code == 200:
            data = response.json()
            artists = data.get("items", {}).get("artists", [])
            if artists:
                # Simulate viewing artist details
                artist_id = artists[0].get("id", "artist_1")
                self.client.get(
                    f"/api/artists/{artist_id}",
                    name="[workflow] view artist details",
                )

    @task(5)
    def browse_graph_workflow(self) -> None:
        """Complete graph browsing workflow."""
        # Start with a random artist
        node_id = random.choice(ARTIST_IDS)

        # View their graph
        response = self.client.get(
            "/api/graph",
            params={
                "node_id": node_id,
                "depth": 2,
                "limit": 50,
            },
            name="[workflow] explore graph",
        )

        # If successful, maybe paginate
        if response.status_code == 200 and random.random() < 0.3:  # 30% chance
            data = response.json()
            if data.get("next_cursor"):
                self.client.get(
                    "/api/graph",
                    params={
                        "node_id": node_id,
                        "depth": 2,
                        "limit": 50,
                        "cursor": data["next_cursor"],
                    },
                    name="[workflow] explore graph page 2",
                )

    @task(3)
    def analytics_workflow(self) -> None:
        """Complete analytics workflow."""
        # View trends
        start_year = random.choice([1970, 1980, 1990, 2000])
        self.client.get(
            "/api/trends",
            params={
                "type": "genre",
                "start_year": start_year,
                "end_year": start_year + 20,
                "top_n": 20,
                "limit": 20,
            },
            name="[workflow] view trends",
        )

        # View heatmap
        if random.random() < 0.5:  # 50% chance
            self.client.get(
                "/api/heatmap",
                params={
                    "type": "genre",
                    "top_n": 20,
                    "limit": 100,
                },
                name="[workflow] view heatmap",
            )

    @task(1)
    def mixed_search(self) -> None:
        """Search across multiple types."""
        query = random.choice(SEARCH_QUERIES)

        # Search all types
        self.client.get(
            "/api/search",
            params={
                "q": query,
                "type": "all",
                "limit": 10,
            },
            name="[workflow] search all",
        )
