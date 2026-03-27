"""Unit tests for Credits & Provenance router endpoints."""

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


# --- Tests ---


class TestPersonCreditsEndpoint:
    """Tests for GET /api/credits/person/{name}."""

    @patch("api.routers.credits.get_person_credits")
    def test_person_credits_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {
                "release_id": "123",
                "title": "Test Release",
                "year": 1995,
                "role": "Mastered By",
                "category": "mastering",
                "artists": ["Artist A"],
                "labels": ["Label X"],
            },
        ]
        response = test_client.get("/api/credits/person/Bob%20Ludwig")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Bob Ludwig"
        assert data["total_credits"] == 1
        assert len(data["credits"]) == 1
        assert data["credits"][0]["role"] == "Mastered By"

    @patch("api.routers.credits.get_person_credits")
    def test_person_credits_not_found(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = []
        response = test_client.get("/api/credits/person/Nobody")
        assert response.status_code == 404

    def test_person_credits_service_not_ready(self, test_client: TestClient) -> None:
        import api.routers.credits as credits_router

        original = credits_router._neo4j_driver
        credits_router._neo4j_driver = None
        try:
            response = test_client.get("/api/credits/person/Test")
            assert response.status_code == 503
        finally:
            credits_router._neo4j_driver = original


class TestPersonTimelineEndpoint:
    """Tests for GET /api/credits/person/{name}/timeline."""

    @patch("api.routers.credits.get_person_timeline")
    def test_timeline_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {"year": 1990, "category": "mastering", "count": 5},
            {"year": 1991, "category": "mastering", "count": 8},
        ]
        response = test_client.get("/api/credits/person/Bob%20Ludwig/timeline")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Bob Ludwig"
        assert len(data["timeline"]) == 2

    @patch("api.routers.credits.get_person_timeline")
    def test_timeline_not_found(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = []
        response = test_client.get("/api/credits/person/Nobody/timeline")
        assert response.status_code == 404


class TestReleaseCreditsEndpoint:
    """Tests for GET /api/credits/release/{release_id}."""

    @patch("api.routers.credits.get_release_credits")
    def test_release_credits_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {
                "name": "Bob Ludwig",
                "role": "Mastered By",
                "category": "mastering",
                "artist_id": None,
                "artist_name": None,
            },
            {
                "name": "Flood",
                "role": "Producer",
                "category": "production",
                "artist_id": "456",
                "artist_name": "Flood",
            },
        ]
        response = test_client.get("/api/credits/release/123")
        assert response.status_code == 200
        data = response.json()
        assert data["release_id"] == "123"
        assert len(data["credits"]) == 2

    @patch("api.routers.credits.get_release_credits")
    def test_release_credits_not_found(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = []
        response = test_client.get("/api/credits/release/99999")
        assert response.status_code == 404


class TestRoleLeaderboardEndpoint:
    """Tests for GET /api/credits/role/{role}/top."""

    @patch("api.routers.credits.get_role_leaderboard")
    def test_leaderboard_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {"name": "Bob Ludwig", "credit_count": 500},
            {"name": "Bernie Grundman", "credit_count": 400},
        ]
        response = test_client.get("/api/credits/role/mastering/top?limit=20")
        assert response.status_code == 200
        data = response.json()
        assert data["category"] == "mastering"
        assert len(data["entries"]) == 2

    def test_leaderboard_invalid_category(self, test_client: TestClient) -> None:
        response = test_client.get("/api/credits/role/invalid_cat/top")
        assert response.status_code == 400
        assert "Invalid role category" in response.json()["error"]

    @patch("api.routers.credits.get_role_leaderboard")
    def test_leaderboard_with_limit(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [{"name": "Test", "credit_count": 10}]
        response = test_client.get("/api/credits/role/production/top?limit=5")
        assert response.status_code == 200


class TestSharedCreditsEndpoint:
    """Tests for GET /api/credits/shared."""

    @patch("api.routers.credits.get_shared_credits")
    def test_shared_credits_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {
                "release_id": "123",
                "title": "Test Album",
                "year": 1995,
                "person1_role": "Producer",
                "person2_role": "Engineer",
                "artists": ["The Band"],
            },
        ]
        response = test_client.get("/api/credits/shared?person1=Flood&person2=Alan%20Moulder")
        assert response.status_code == 200
        data = response.json()
        assert data["person1"] == "Flood"
        assert data["person2"] == "Alan Moulder"
        assert len(data["shared_releases"]) == 1

    @patch("api.routers.credits.get_shared_credits")
    def test_shared_credits_empty(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = []
        response = test_client.get("/api/credits/shared?person1=A&person2=B")
        assert response.status_code == 200
        assert response.json()["shared_releases"] == []


class TestPersonConnectionsEndpoint:
    """Tests for GET /api/credits/connections/{name}."""

    @patch("api.routers.credits.get_person_connections")
    def test_connections_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {"name": "Connected Person", "shared_count": 10},
        ]
        response = test_client.get("/api/credits/connections/Bob%20Ludwig?depth=1&limit=30")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Bob Ludwig"
        assert len(data["connections"]) == 1


class TestCreditsAutocompleteEndpoint:
    """Tests for GET /api/credits/autocomplete."""

    @patch("api.routers.credits.autocomplete_person")
    def test_autocomplete_success(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        mock_query.return_value = [
            {"name": "Bob Ludwig", "score": 5.2},
            {"name": "Bob Marley", "score": 3.1},
        ]
        response = test_client.get("/api/credits/autocomplete?q=Bob")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2
        assert data["results"][0]["name"] == "Bob Ludwig"

    def test_autocomplete_query_too_short(self, test_client: TestClient) -> None:
        response = test_client.get("/api/credits/autocomplete?q=B")
        assert response.status_code == 422  # Validation error


class TestPersonProfileEndpoint:
    """Tests for GET /api/credits/person/{name}/profile."""

    def test_profile_success(self, test_client: TestClient) -> None:
        with (
            patch("api.routers.credits.get_person_profile") as mock_profile,
            patch("api.routers.credits.get_person_role_breakdown") as mock_breakdown,
        ):
            mock_profile.return_value = {
                "name": "Bob Ludwig",
                "total_credits": 500,
                "categories": ["mastering"],
                "first_year": 1970,
                "last_year": 2020,
                "artist_id": None,
                "artist_name": None,
            }
            mock_breakdown.return_value = [{"category": "mastering", "count": 500}]
            response = test_client.get("/api/credits/person/Bob%20Ludwig/profile")
            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
            data = response.json()
            assert data["name"] == "Bob Ludwig"
            assert data["total_credits"] == 500
            assert len(data["role_breakdown"]) == 1

    @patch("api.routers.credits.get_person_profile")
    def test_profile_not_found(self, mock_profile: AsyncMock, test_client: TestClient) -> None:
        mock_profile.return_value = None
        response = test_client.get("/api/credits/person/Nobody/profile")
        assert response.status_code == 404


class TestCreditsServiceNotReady:
    """Tests for 503 responses when Neo4j driver is not configured."""

    def _with_driver_none(self, test_client: TestClient, path: str) -> int:
        import api.routers.credits as credits_router

        original = credits_router._neo4j_driver
        credits_router._neo4j_driver = None
        try:
            return test_client.get(path).status_code
        finally:
            credits_router._neo4j_driver = original

    def test_timeline_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/person/Test/timeline") == 503

    def test_profile_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/person/Test/profile") == 503

    def test_release_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/release/123") == 503

    def test_leaderboard_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/role/mastering/top") == 503

    def test_shared_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/shared?person1=A&person2=B") == 503

    def test_connections_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/connections/Test") == 503

    def test_autocomplete_service_not_ready(self, test_client: TestClient) -> None:
        assert self._with_driver_none(test_client, "/api/credits/autocomplete?q=Test") == 503


class TestCreditsRedisCaching:
    """Tests for Redis cache hit/miss paths."""

    @patch("api.routers.credits.get_person_credits")
    def test_person_credits_cache_hit(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        """Test that cached data is returned without querying Neo4j."""
        import api.routers.credits as credits_router

        cached_data = {
            "name": "Bob Ludwig",
            "total_credits": 1,
            "credits": [{"release_id": "1", "title": "Cached", "year": 2000, "role": "Mastered By", "category": "mastering", "artists": [], "labels": []}],
        }
        original_redis = credits_router._redis
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
        credits_router._redis = mock_redis
        try:
            response = test_client.get("/api/credits/person/Bob%20Ludwig")
            assert response.status_code == 200
            assert response.json()["credits"][0]["title"] == "Cached"
            mock_query.assert_not_called()
        finally:
            credits_router._redis = original_redis

    @patch("api.routers.credits.get_person_credits")
    def test_person_credits_cache_miss_sets_cache(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        """Test that cache miss queries Neo4j and stores result."""
        import api.routers.credits as credits_router

        mock_query.return_value = [
            {"release_id": "1", "title": "Fresh", "year": 2000, "role": "Producer", "category": "production", "artists": [], "labels": []},
        ]
        original_redis = credits_router._redis
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        credits_router._redis = mock_redis
        try:
            response = test_client.get("/api/credits/person/Test")
            assert response.status_code == 200
            mock_redis.setex.assert_called_once()
        finally:
            credits_router._redis = original_redis

    @patch("api.routers.credits.get_person_credits")
    def test_person_credits_cache_get_error(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        """Test that Redis get error falls through to Neo4j query."""
        import api.routers.credits as credits_router

        mock_query.return_value = [
            {"release_id": "1", "title": "Fallback", "year": 2000, "role": "Engineer", "category": "engineering", "artists": [], "labels": []},
        ]
        original_redis = credits_router._redis
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis down"))
        credits_router._redis = mock_redis
        try:
            response = test_client.get("/api/credits/person/Test")
            assert response.status_code == 200
            assert response.json()["credits"][0]["title"] == "Fallback"
        finally:
            credits_router._redis = original_redis

    @patch("api.routers.credits.get_role_leaderboard")
    def test_leaderboard_cache_hit(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        """Test leaderboard returns cached data."""
        import api.routers.credits as credits_router

        cached_data = {"category": "mastering", "entries": [{"name": "Cached Person", "credit_count": 999}]}
        original_redis = credits_router._redis
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
        credits_router._redis = mock_redis
        try:
            response = test_client.get("/api/credits/role/mastering/top")
            assert response.status_code == 200
            assert response.json()["entries"][0]["name"] == "Cached Person"
            mock_query.assert_not_called()
        finally:
            credits_router._redis = original_redis

    @patch("api.routers.credits.get_role_leaderboard")
    def test_leaderboard_cache_error(self, mock_query: AsyncMock, test_client: TestClient) -> None:
        """Test leaderboard falls through on Redis error."""
        import api.routers.credits as credits_router

        mock_query.return_value = [{"name": "Test", "credit_count": 10}]
        original_redis = credits_router._redis
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis down"))
        credits_router._redis = mock_redis
        try:
            response = test_client.get("/api/credits/role/mastering/top")
            assert response.status_code == 200
        finally:
            credits_router._redis = original_redis
