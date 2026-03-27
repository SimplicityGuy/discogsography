"""Tests for the collaboration network router endpoints."""

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestCollaboratorsEndpoint:
    """Tests for GET /api/network/artist/{id}/collaborators."""

    def test_success(self, test_client: TestClient) -> None:
        """Returns 200 with multi-hop collaborators."""
        identity = {"artist_id": "123", "artist_name": "Miles Davis"}
        collaborators = [
            {"artist_id": "456", "artist_name": "John Coltrane", "distance": 1, "collaboration_count": 5},
            {"artist_id": "789", "artist_name": "Herbie Hancock", "distance": 2, "collaboration_count": 3},
        ]
        with (
            patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=identity),
            patch("api.queries.network_queries.get_multi_hop_collaborators", new_callable=AsyncMock, return_value=collaborators),
            patch("api.queries.network_queries.count_multi_hop_collaborators", new_callable=AsyncMock, return_value=15),
        ):
            response = test_client.get("/api/network/artist/123/collaborators?depth=2&limit=50")
        assert response.status_code == 200
        data = response.json()
        assert data["artist_id"] == "123"
        assert data["artist_name"] == "Miles Davis"
        assert data["depth"] == 2
        assert len(data["collaborators"]) == 2
        assert data["total"] == 15

    def test_not_found(self, test_client: TestClient) -> None:
        """Returns 404 when artist does not exist."""
        with patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=None):
            response = test_client.get("/api/network/artist/999/collaborators")
        assert response.status_code == 404

    def test_not_ready(self, test_client: TestClient) -> None:
        """Returns 503 when Neo4j is not configured."""
        import api.routers.network as mod

        original = mod._neo4j
        mod._neo4j = None
        try:
            response = test_client.get("/api/network/artist/123/collaborators")
            assert response.status_code == 503
        finally:
            mod._neo4j = original

    def test_depth_validation(self, test_client: TestClient) -> None:
        """Rejects depth > 3."""
        response = test_client.get("/api/network/artist/123/collaborators?depth=5")
        assert response.status_code == 422

    def test_timeout(self, test_client: TestClient) -> None:
        """Returns 504 on Neo4j timeout."""
        from neo4j.exceptions import ClientError as Neo4jClientError

        identity = {"artist_id": "123", "artist_name": "Test"}
        with (
            patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=identity),
            patch(
                "api.queries.network_queries.get_multi_hop_collaborators",
                new_callable=AsyncMock,
                side_effect=Neo4jClientError("TransactionTimedOut"),
            ),
        ):
            response = test_client.get("/api/network/artist/123/collaborators")
        assert response.status_code == 504

    def test_depth_1(self, test_client: TestClient) -> None:
        """Returns only direct collaborators at depth=1."""
        identity = {"artist_id": "123", "artist_name": "Test Artist"}
        collaborators = [
            {"artist_id": "456", "artist_name": "Direct Collab", "distance": 1, "collaboration_count": 3},
        ]
        with (
            patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=identity),
            patch("api.queries.network_queries.get_multi_hop_collaborators", new_callable=AsyncMock, return_value=collaborators),
            patch("api.queries.network_queries.count_multi_hop_collaborators", new_callable=AsyncMock, return_value=1),
        ):
            response = test_client.get("/api/network/artist/123/collaborators?depth=1")
        assert response.status_code == 200
        assert response.json()["depth"] == 1


class TestCentralityEndpoint:
    """Tests for GET /api/network/artist/{id}/centrality."""

    def test_success(self, test_client: TestClient) -> None:
        """Returns 200 with centrality scores."""
        result = {
            "artist_id": "123",
            "artist_name": "Miles Davis",
            "degree": 500,
            "collaborator_count": 120,
            "collaboration_releases": 85,
            "group_count": 3,
            "alias_count": 1,
        }
        with patch("api.queries.network_queries.get_artist_centrality", new_callable=AsyncMock, return_value=result):
            response = test_client.get("/api/network/artist/123/centrality")
        assert response.status_code == 200
        data = response.json()
        assert data["artist_id"] == "123"
        assert data["centrality"]["degree"] == 500
        assert data["centrality"]["collaborator_count"] == 120
        assert data["centrality"]["collaboration_releases"] == 85
        assert data["centrality"]["group_count"] == 3
        assert data["centrality"]["alias_count"] == 1

    def test_not_found(self, test_client: TestClient) -> None:
        """Returns 404 when artist does not exist."""
        with patch("api.queries.network_queries.get_artist_centrality", new_callable=AsyncMock, return_value=None):
            response = test_client.get("/api/network/artist/999/centrality")
        assert response.status_code == 404

    def test_not_ready(self, test_client: TestClient) -> None:
        """Returns 503 when Neo4j is not configured."""
        import api.routers.network as mod

        original = mod._neo4j
        mod._neo4j = None
        try:
            response = test_client.get("/api/network/artist/123/centrality")
            assert response.status_code == 503
        finally:
            mod._neo4j = original

    def test_timeout(self, test_client: TestClient) -> None:
        """Returns 504 on Neo4j timeout."""
        from neo4j.exceptions import ClientError as Neo4jClientError

        with patch(
            "api.queries.network_queries.get_artist_centrality",
            new_callable=AsyncMock,
            side_effect=Neo4jClientError("TransactionTimedOut"),
        ):
            response = test_client.get("/api/network/artist/123/centrality")
        assert response.status_code == 504

    def test_cache_hit(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Returns cached result on Redis hit."""
        cached = {
            "artist_id": "123",
            "artist_name": "Cached Artist",
            "centrality": {"degree": 100, "collaborator_count": 50, "collaboration_releases": 30, "group_count": 2, "alias_count": 0},
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))
        with patch("api.queries.network_queries.get_artist_centrality") as mock_query:
            response = test_client.get("/api/network/artist/123/centrality")
        assert response.status_code == 200
        assert response.json() == cached
        mock_query.assert_not_called()

    def test_cache_miss_stores_result(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Stores result in Redis on cache miss."""
        mock_redis.get = AsyncMock(return_value=None)
        result = {
            "artist_id": "123",
            "artist_name": "Miles Davis",
            "degree": 500,
            "collaborator_count": 120,
            "collaboration_releases": 85,
            "group_count": 3,
            "alias_count": 1,
        }
        with patch("api.queries.network_queries.get_artist_centrality", new_callable=AsyncMock, return_value=result):
            response = test_client.get("/api/network/artist/123/centrality")
        assert response.status_code == 200
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == "network:centrality:123"
        assert call_args[1] == 3600


class TestClusterEndpoint:
    """Tests for GET /api/network/cluster/{id}."""

    def test_success(self, test_client: TestClient) -> None:
        """Returns 200 with cluster detection results."""
        identity = {"artist_id": "123", "artist_name": "Miles Davis"}
        clusters = [
            {
                "cluster_label": "Jazz",
                "members": [
                    {"artist_id": "456", "artist_name": "John Coltrane", "shared_releases": 10},
                    {"artist_id": "789", "artist_name": "Herbie Hancock", "shared_releases": 8},
                ],
                "size": 2,
            },
            {
                "cluster_label": "Funk",
                "members": [
                    {"artist_id": "111", "artist_name": "Sly Stone", "shared_releases": 2},
                ],
                "size": 1,
            },
        ]
        with (
            patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=identity),
            patch("api.queries.network_queries.get_artist_cluster", new_callable=AsyncMock, return_value=clusters),
        ):
            response = test_client.get("/api/network/cluster/123")
        assert response.status_code == 200
        data = response.json()
        assert data["artist_id"] == "123"
        assert data["total_clusters"] == 2
        assert data["total_members"] == 3
        assert data["clusters"][0]["cluster_label"] == "Jazz"

    def test_not_found(self, test_client: TestClient) -> None:
        """Returns 404 when artist does not exist."""
        with patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=None):
            response = test_client.get("/api/network/cluster/999")
        assert response.status_code == 404

    def test_not_ready(self, test_client: TestClient) -> None:
        """Returns 503 when Neo4j is not configured."""
        import api.routers.network as mod

        original = mod._neo4j
        mod._neo4j = None
        try:
            response = test_client.get("/api/network/cluster/123")
            assert response.status_code == 503
        finally:
            mod._neo4j = original

    def test_timeout(self, test_client: TestClient) -> None:
        """Returns 504 on Neo4j timeout."""
        from neo4j.exceptions import ClientError as Neo4jClientError

        identity = {"artist_id": "123", "artist_name": "Test"}
        with (
            patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=identity),
            patch(
                "api.queries.network_queries.get_artist_cluster",
                new_callable=AsyncMock,
                side_effect=Neo4jClientError("TransactionTimedOut"),
            ),
        ):
            response = test_client.get("/api/network/cluster/123")
        assert response.status_code == 504

    def test_empty_clusters(self, test_client: TestClient) -> None:
        """Returns empty clusters when artist has no collaborators."""
        identity = {"artist_id": "123", "artist_name": "Solo Artist"}
        with (
            patch("api.queries.network_queries.get_artist_identity", new_callable=AsyncMock, return_value=identity),
            patch("api.queries.network_queries.get_artist_cluster", new_callable=AsyncMock, return_value=[]),
        ):
            response = test_client.get("/api/network/cluster/123")
        assert response.status_code == 200
        data = response.json()
        assert data["total_clusters"] == 0
        assert data["total_members"] == 0

    def test_cache_hit(self, test_client: TestClient, mock_redis: AsyncMock) -> None:
        """Returns cached result on Redis hit."""
        cached = {
            "artist_id": "123",
            "artist_name": "Cached",
            "clusters": [],
            "total_clusters": 0,
            "total_members": 0,
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))
        with patch("api.queries.network_queries.get_artist_identity") as mock_id:
            response = test_client.get("/api/network/cluster/123")
        assert response.status_code == 200
        assert response.json() == cached
        mock_id.assert_not_called()

    def test_limit_validation(self, test_client: TestClient) -> None:
        """Rejects limit > 200."""
        response = test_client.get("/api/network/cluster/123?limit=500")
        assert response.status_code == 422


class TestConfigure:
    """Tests for configure() function."""

    def test_configure_sets_state(self) -> None:
        """configure() stores neo4j and redis references."""
        import api.routers.network as mod

        original_neo4j = mod._neo4j
        original_redis = mod._redis
        mock_neo4j = AsyncMock()
        mock_redis = AsyncMock()
        try:
            mod.configure(mock_neo4j, mock_redis)
            assert mod._neo4j is mock_neo4j
            assert mod._redis is mock_redis
        finally:
            mod._neo4j = original_neo4j
            mod._redis = original_redis

    def test_configure_without_redis(self) -> None:
        """configure() without redis sets _redis to None."""
        import api.routers.network as mod

        original_neo4j = mod._neo4j
        original_redis = mod._redis
        try:
            mod.configure(AsyncMock())
            assert mod._redis is None
        finally:
            mod._neo4j = original_neo4j
            mod._redis = original_redis
