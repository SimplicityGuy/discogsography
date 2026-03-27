"""Unit tests for Credits & Provenance router endpoints."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# --- Helpers ---


def _make_mock_session(
    single_return: dict[str, Any] | None = None,
    query_returns: list[dict[str, Any]] | None = None,
) -> AsyncMock:
    """Create a mock session that handles both single and multi-record queries."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    mock_result = AsyncMock()
    if single_return is not None:
        mock_result.single = AsyncMock(return_value=single_return)
    else:
        mock_result.single = AsyncMock(return_value=None)

    if query_returns is not None:
        mock_result.__aiter__ = MagicMock(return_value=iter(query_returns))
    else:
        mock_result.__aiter__ = MagicMock(return_value=iter([]))

    session.run = AsyncMock(return_value=mock_result)
    return session


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
