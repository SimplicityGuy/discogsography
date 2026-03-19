"""Tests for GET /api/genre-tree endpoint."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


SAMPLE_GENRE_TREE = [
    {
        "name": "Rock",
        "release_count": 98000,
        "styles": [
            {"name": "Alternative Rock", "release_count": 15000},
            {"name": "Punk", "release_count": 9500},
        ],
    },
    {
        "name": "Electronic",
        "release_count": 75000,
        "styles": [
            {"name": "House", "release_count": 20000},
            {"name": "Techno", "release_count": 18000},
        ],
    },
]


class TestGenreTreeEndpoint:
    """Test the genre-tree API endpoint."""

    def test_genre_tree_success(self, test_client: TestClient) -> None:
        """GET /api/genre-tree returns 200 with genre hierarchy."""
        with patch(
            "api.routers.explore.genre_tree_queries.get_genre_tree",
            new_callable=AsyncMock,
            return_value=SAMPLE_GENRE_TREE,
        ):
            # Clear cache to force a fresh query
            import api.routers.explore as mod

            mod._genre_tree_cache = None
            mod._genre_tree_cache_time = 0

            response = test_client.get("/api/genre-tree")

        assert response.status_code == 200
        data = response.json()
        assert "genres" in data
        assert len(data["genres"]) == 2
        rock = data["genres"][0]
        assert rock["name"] == "Rock"
        assert rock["release_count"] == 98000
        assert len(rock["styles"]) == 2
        assert rock["styles"][0]["name"] == "Alternative Rock"
        assert rock["styles"][0]["release_count"] == 15000

    def test_genre_tree_service_not_ready(self, test_client: TestClient) -> None:
        """GET /api/genre-tree returns 503 when driver is None."""
        import api.routers.explore as explore_module

        original_driver = explore_module._neo4j_driver
        explore_module._neo4j_driver = None

        response = test_client.get("/api/genre-tree")
        assert response.status_code == 503
        assert "error" in response.json()

        explore_module._neo4j_driver = original_driver

    def test_genre_tree_empty_database(self, test_client: TestClient) -> None:
        """GET /api/genre-tree returns empty list when no genres exist."""
        with patch(
            "api.routers.explore.genre_tree_queries.get_genre_tree",
            new_callable=AsyncMock,
            return_value=[],
        ):
            import api.routers.explore as mod

            mod._genre_tree_cache = None
            mod._genre_tree_cache_time = 0

            response = test_client.get("/api/genre-tree")

        assert response.status_code == 200
        data = response.json()
        assert data["genres"] == []

    def test_genre_tree_cache_behavior(self, test_client: TestClient) -> None:
        """GET /api/genre-tree uses cache on second call within TTL."""
        mock_query = AsyncMock(return_value=SAMPLE_GENRE_TREE)

        with patch(
            "api.routers.explore.genre_tree_queries.get_genre_tree",
            mock_query,
        ):
            import api.routers.explore as mod

            mod._genre_tree_cache = None
            mod._genre_tree_cache_time = 0

            # First call — should hit the query
            response1 = test_client.get("/api/genre-tree")
            assert response1.status_code == 200

            # Second call — should use cache, not call query again
            response2 = test_client.get("/api/genre-tree")
            assert response2.status_code == 200

        # Query should only have been called once
        mock_query.assert_awaited_once()

        # Both responses should be identical
        assert response1.json() == response2.json()

    def test_genre_tree_cache_expired(self, test_client: TestClient) -> None:
        """GET /api/genre-tree re-queries when cache has expired."""
        mock_query = AsyncMock(return_value=SAMPLE_GENRE_TREE)

        with patch(
            "api.routers.explore.genre_tree_queries.get_genre_tree",
            mock_query,
        ):
            import api.routers.explore as mod

            mod._genre_tree_cache = None
            mod._genre_tree_cache_time = 0

            # First call
            response1 = test_client.get("/api/genre-tree")
            assert response1.status_code == 200

            # Expire the cache by backdating the timestamp beyond TTL
            import time

            mod._genre_tree_cache_time = time.monotonic() - mod._GENRE_TREE_TTL - 1

            # Second call — cache expired, should query again
            response2 = test_client.get("/api/genre-tree")
            assert response2.status_code == 200

        assert mock_query.await_count == 2
