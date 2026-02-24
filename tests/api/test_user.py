"""Tests for user endpoints in the API service (api/routers/user.py)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestUserCollectionEndpoint:
    """Tests for GET /api/user/collection."""

    def test_collection_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection")
        assert response.status_code in (401, 403)

    def test_collection_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = ([{"id": "r1", "name": "OK Computer"}], 1)
        with patch("api.routers.user.get_user_collection", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/collection", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "releases" in data
        assert "total" in data
        assert data["total"] == 1

    def test_collection_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/collection", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserWantlistEndpoint:
    """Tests for GET /api/user/wantlist."""

    def test_wantlist_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/wantlist")
        assert response.status_code in (401, 403)

    def test_wantlist_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = ([{"id": "r2", "name": "Kid A"}], 1)
        with patch("api.routers.user.get_user_wantlist", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/wantlist", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "releases" in data

    def test_wantlist_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.user as user_module

        original = user_module._neo4j_driver
        user_module._neo4j_driver = None
        try:
            response = test_client.get("/api/user/wantlist", headers=auth_headers)
            assert response.status_code == 503
        finally:
            user_module._neo4j_driver = original


class TestUserRecommendationsEndpoint:
    """Tests for GET /api/user/recommendations."""

    def test_recommendations_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/recommendations")
        assert response.status_code in (401, 403)

    def test_recommendations_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = [{"id": "r3", "name": "Amnesiac"}]
        with patch("api.routers.user.get_user_recommendations", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/recommendations", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert data["total"] == 1


class TestUserCollectionStatsEndpoint:
    """Tests for GET /api/user/collection/stats."""

    def test_stats_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection/stats")
        assert response.status_code in (401, 403)

    def test_stats_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_stats = {"genres": [], "decades": [], "labels": []}
        with patch("api.routers.user.get_user_collection_stats", new=AsyncMock(return_value=mock_stats)):
            response = test_client.get("/api/user/collection/stats", headers=auth_headers)
        assert response.status_code == 200


class TestUserStatusEndpoint:
    """Tests for GET /api/user/status."""

    def test_status_no_auth_returns_all_false(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/status?ids=1,2,3")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        for rid in ["1", "2", "3"]:
            assert data["status"][rid]["in_collection"] is False
            assert data["status"][rid]["in_wantlist"] is False

    def test_status_with_auth(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_result = {"r1": {"in_collection": True, "in_wantlist": False}}
        with patch("api.routers.user.check_releases_user_status", new=AsyncMock(return_value=mock_result)):
            response = test_client.get("/api/user/status?ids=r1,r2", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"]["r1"]["in_collection"] is True
        assert data["status"]["r2"]["in_collection"] is False  # default

    def test_status_empty_ids(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/status?ids=,,,")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == {}
