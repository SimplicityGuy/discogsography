"""Tests for api/routers/taste.py endpoints."""

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from tests.api.conftest import make_test_jwt


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_test_jwt()}"}


def _patch_min_count(count: int = 0) -> Any:
    """Patch get_collection_count to return a fixed value."""
    return patch("api.routers.taste.get_collection_count", new_callable=AsyncMock, return_value=count)


def _patch_query(name: str, return_value: Any = None) -> Any:
    """Patch a taste query function."""
    return patch(f"api.routers.taste.{name}", new_callable=AsyncMock, return_value=return_value)


# ---------------------------------------------------------------------------
# Minimum collection guard
# ---------------------------------------------------------------------------


class TestTasteMinimumItemsGuard:
    def test_heatmap_rejects_small_collection(self, test_client: TestClient) -> None:
        with _patch_min_count(5):
            resp = test_client.get("/api/taste/heatmap", headers=_auth_headers())
        assert resp.status_code == 422
        assert "at least" in resp.json()["detail"]

    def test_fingerprint_rejects_small_collection(self, test_client: TestClient) -> None:
        with _patch_min_count(3):
            resp = test_client.get("/api/taste/fingerprint", headers=_auth_headers())
        assert resp.status_code == 422

    def test_blindspots_rejects_small_collection(self, test_client: TestClient) -> None:
        with _patch_min_count(9):
            resp = test_client.get("/api/taste/blindspots", headers=_auth_headers())
        assert resp.status_code == 422

    def test_card_rejects_small_collection(self, test_client: TestClient) -> None:
        with _patch_min_count(0):
            resp = test_client.get("/api/taste/card", headers=_auth_headers())
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Heatmap endpoint
# ---------------------------------------------------------------------------


class TestTasteHeatmap:
    def test_returns_heatmap(self, test_client: TestClient) -> None:
        cells = [{"genre": "Rock", "decade": 1990, "count": 15}]
        with (
            _patch_min_count(50),
            _patch_query("get_taste_heatmap", return_value=(cells, 50)),
        ):
            resp = test_client.get("/api/taste/heatmap", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 50
        assert len(data["cells"]) == 1
        assert data["cells"][0]["genre"] == "Rock"


# ---------------------------------------------------------------------------
# Fingerprint endpoint
# ---------------------------------------------------------------------------


class TestTasteFingerprint:
    def test_returns_full_fingerprint(self, test_client: TestClient) -> None:
        cells = [{"genre": "Rock", "decade": 1990, "count": 15}]
        obscurity = {"score": 0.6, "median_collectors": 2.0, "total_releases": 50}
        drift = [{"year": "2020", "top_genre": "Rock", "count": 10}]
        blind = [{"genre": "Jazz", "artist_overlap": 3, "example_release": "Kind of Blue"}]

        with (
            _patch_min_count(50),
            _patch_query("get_taste_heatmap", return_value=(cells, 50)),
            _patch_query("get_obscurity_score", return_value=obscurity),
            _patch_query("get_taste_drift", return_value=drift),
            _patch_query("get_blind_spots", return_value=blind),
        ):
            resp = test_client.get("/api/taste/fingerprint", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "heatmap" in data
        assert "obscurity" in data
        assert "drift" in data
        assert "blind_spots" in data
        assert data["peak_decade"] == 1990

    def test_peak_decade_none_when_no_cells(self, test_client: TestClient) -> None:
        obscurity = {"score": 1.0, "median_collectors": 0.0, "total_releases": 10}
        with (
            _patch_min_count(10),
            _patch_query("get_taste_heatmap", return_value=([], 10)),
            _patch_query("get_obscurity_score", return_value=obscurity),
            _patch_query("get_taste_drift", return_value=[]),
            _patch_query("get_blind_spots", return_value=[]),
        ):
            resp = test_client.get("/api/taste/fingerprint", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["peak_decade"] is None


# ---------------------------------------------------------------------------
# Blindspots endpoint
# ---------------------------------------------------------------------------


class TestTasteBlindspots:
    def test_returns_blindspots(self, test_client: TestClient) -> None:
        spots = [{"genre": "Jazz", "artist_overlap": 3, "example_release": None}]
        with (
            _patch_min_count(50),
            _patch_query("get_blind_spots", return_value=spots),
        ):
            resp = test_client.get("/api/taste/blindspots", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["blind_spots"]) == 1
        assert data["blind_spots"][0]["genre"] == "Jazz"


# ---------------------------------------------------------------------------
# Card endpoint
# ---------------------------------------------------------------------------


class TestTasteCard:
    def test_returns_svg(self, test_client: TestClient) -> None:
        cells = [{"genre": "Rock", "decade": 1990, "count": 15}]
        obscurity = {"score": 0.5, "median_collectors": 5.0, "total_releases": 20}
        drift = [{"year": "2020", "top_genre": "Rock", "count": 10}]
        labels = [{"label": "Warp", "count": 5}]

        with (
            _patch_min_count(20),
            _patch_query("get_taste_heatmap", return_value=(cells, 20)),
            _patch_query("get_obscurity_score", return_value=obscurity),
            _patch_query("get_taste_drift", return_value=drift),
            _patch_query("get_top_labels", return_value=labels),
        ):
            resp = test_client.get("/api/taste/card", headers=_auth_headers())
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers["content-type"]
        assert resp.text.startswith("<svg")


# ---------------------------------------------------------------------------
# No auth
# ---------------------------------------------------------------------------


class TestTasteNoAuth:
    def test_heatmap_requires_auth(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/taste/heatmap")
        assert resp.status_code in (401, 403)

    def test_fingerprint_requires_auth(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/taste/fingerprint")
        assert resp.status_code in (401, 403)
