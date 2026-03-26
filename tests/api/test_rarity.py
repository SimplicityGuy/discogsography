"""Tests for rarity API endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


_MOCK_RARITY_ROW = {
    "release_id": 456,
    "title": "Test Release",
    "artist_name": "Test Artist",
    "year": 1968,
    "rarity_score": 87.2,
    "tier": "ultra-rare",
    "hidden_gem_score": 72.1,
    "pressing_scarcity": 95.0,
    "label_catalog": 80.0,
    "format_rarity": 70.0,
    "temporal_scarcity": 92.0,
    "graph_isolation": 65.0,
}

_MOCK_LIST_ITEM = {
    "release_id": 456,
    "title": "Test Release",
    "artist_name": "Test Artist",
    "year": 1968,
    "rarity_score": 87.2,
    "tier": "ultra-rare",
    "hidden_gem_score": 72.1,
}


class TestGetReleaseRarity:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_for_release",
            new=AsyncMock(return_value=_MOCK_RARITY_ROW),
        ):
            response = test_client.get("/api/rarity/456")
        assert response.status_code == 200
        data = response.json()
        assert data["release_id"] == 456
        assert data["tier"] == "ultra-rare"
        assert "breakdown" in data
        assert data["breakdown"]["pressing_scarcity"]["score"] == 95.0

    def test_not_found(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_for_release",
            new=AsyncMock(return_value=None),
        ):
            response = test_client.get("/api/rarity/999")
        assert response.status_code == 404

    def test_503_when_not_ready(self, test_client: TestClient) -> None:
        import api.routers.rarity as rarity_router

        original = rarity_router._pg_pool
        rarity_router._pg_pool = None
        try:
            response = test_client.get("/api/rarity/456")
            assert response.status_code == 503
        finally:
            rarity_router._pg_pool = original


class TestRarityLeaderboard:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_leaderboard",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 100)),
        ):
            response = test_client.get("/api/rarity/leaderboard")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100
        assert len(data["items"]) == 1

    def test_pagination(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_leaderboard",
            new=AsyncMock(return_value=([], 0)),
        ):
            response = test_client.get("/api/rarity/leaderboard?page=2&page_size=10")
        assert response.status_code == 200

    def test_tier_filter(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_leaderboard",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 1)),
        ):
            response = test_client.get("/api/rarity/leaderboard?tier=ultra-rare")
        assert response.status_code == 200


class TestHiddenGems:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_hidden_gems",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 50)),
        ):
            response = test_client.get("/api/rarity/hidden-gems")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 50

    def test_min_rarity_param(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_hidden_gems",
            new=AsyncMock(return_value=([], 0)),
        ):
            response = test_client.get("/api/rarity/hidden-gems?min_rarity=61")
        assert response.status_code == 200


class TestArtistRarity:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_artist",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 5)),
        ):
            response = test_client.get("/api/rarity/artist/123")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5

    def test_not_found(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_artist",
            new=AsyncMock(return_value=None),
        ):
            response = test_client.get("/api/rarity/artist/nonexistent")
        assert response.status_code == 404


class TestLabelRarity:
    def test_success(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_label",
            new=AsyncMock(return_value=([_MOCK_LIST_ITEM], 10)),
        ):
            response = test_client.get("/api/rarity/label/456")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10

    def test_not_found(self, test_client: TestClient) -> None:
        with patch(
            "api.routers.rarity.get_rarity_by_label",
            new=AsyncMock(return_value=None),
        ):
            response = test_client.get("/api/rarity/label/nonexistent")
        assert response.status_code == 404
