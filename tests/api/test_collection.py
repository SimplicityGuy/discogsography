"""Tests for collection gap analysis endpoints (api/routers/collection.py)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


_MOCK_LABEL_META = {"id": "label-1", "name": "Factory Records"}
_MOCK_ARTIST_META = {"id": "artist-1", "name": "Radiohead"}
_MOCK_MASTER_META = {"id": "master-1", "name": "OK Computer"}
_MOCK_SUMMARY = {"total": 100, "owned": 10, "missing": 90}
_MOCK_RELEASES = [{"id": "r1", "title": "Blue Monday", "year": 1983}]


class TestCollectionFormatsEndpoint:
    """Tests for GET /api/collection/formats."""

    def test_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/collection/formats")
        assert response.status_code in (401, 403)

    def test_success(self, test_client: TestClient, auth_headers: dict[str, str], mock_cur: AsyncMock) -> None:
        mock_cur.fetchall = AsyncMock(return_value=[{"format_name": "CD"}, {"format_name": "Vinyl"}])
        response = test_client.get("/api/collection/formats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "formats" in data
        assert data["formats"] == ["CD", "Vinyl"]

    def test_no_pool_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.collection as collection_module

        original = collection_module._pg_pool
        collection_module._pg_pool = None
        try:
            response = test_client.get("/api/collection/formats", headers=auth_headers)
            assert response.status_code == 503
        finally:
            collection_module._pg_pool = original


class TestLabelGapsEndpoint:
    """Tests for GET /api/collection/gaps/label/{label_id}."""

    def test_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/collection/gaps/label/123")
        assert response.status_code in (401, 403)

    def test_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with (
            patch("api.routers.collection.get_label_metadata", new=AsyncMock(return_value=_MOCK_LABEL_META)),
            patch("api.routers.collection.get_label_gap_summary", new=AsyncMock(return_value=_MOCK_SUMMARY)),
            patch("api.routers.collection.get_label_gaps", new=AsyncMock(return_value=(_MOCK_RELEASES, 1))),
            patch("api.routers.collection._get_cached_summary", return_value=None),
        ):
            response = test_client.get("/api/collection/gaps/label/label-1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["entity"]["type"] == "label"
        assert data["entity"]["name"] == "Factory Records"
        assert data["summary"]["total"] == 100
        assert data["results"] == _MOCK_RELEASES
        assert "pagination" in data

    def test_label_not_found(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with patch("api.routers.collection.get_label_metadata", new=AsyncMock(return_value=None)):
            response = test_client.get("/api/collection/gaps/label/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    def test_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.collection as collection_module

        original = collection_module._neo4j_driver
        collection_module._neo4j_driver = None
        try:
            response = test_client.get("/api/collection/gaps/label/123", headers=auth_headers)
            assert response.status_code == 503
        finally:
            collection_module._neo4j_driver = original


class TestArtistGapsEndpoint:
    """Tests for GET /api/collection/gaps/artist/{artist_id}."""

    def test_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/collection/gaps/artist/123")
        assert response.status_code in (401, 403)

    def test_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with (
            patch("api.routers.collection.get_artist_metadata", new=AsyncMock(return_value=_MOCK_ARTIST_META)),
            patch("api.routers.collection.get_artist_gap_summary", new=AsyncMock(return_value=_MOCK_SUMMARY)),
            patch("api.routers.collection.get_artist_gaps", new=AsyncMock(return_value=(_MOCK_RELEASES, 1))),
            patch("api.routers.collection._get_cached_summary", return_value=None),
        ):
            response = test_client.get("/api/collection/gaps/artist/artist-1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["entity"]["type"] == "artist"
        assert data["entity"]["name"] == "Radiohead"

    def test_artist_not_found(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with patch("api.routers.collection.get_artist_metadata", new=AsyncMock(return_value=None)):
            response = test_client.get("/api/collection/gaps/artist/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    def test_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.collection as collection_module

        original = collection_module._neo4j_driver
        collection_module._neo4j_driver = None
        try:
            response = test_client.get("/api/collection/gaps/artist/123", headers=auth_headers)
            assert response.status_code == 503
        finally:
            collection_module._neo4j_driver = original


class TestMasterGapsEndpoint:
    """Tests for GET /api/collection/gaps/master/{master_id}."""

    def test_no_auth(self, test_client: TestClient) -> None:
        response = test_client.get("/api/collection/gaps/master/123")
        assert response.status_code in (401, 403)

    def test_success(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with (
            patch("api.routers.collection.get_master_metadata", new=AsyncMock(return_value=_MOCK_MASTER_META)),
            patch("api.routers.collection.get_master_gap_summary", new=AsyncMock(return_value=_MOCK_SUMMARY)),
            patch("api.routers.collection.get_master_gaps", new=AsyncMock(return_value=(_MOCK_RELEASES, 1))),
            patch("api.routers.collection._get_cached_summary", return_value=None),
        ):
            response = test_client.get("/api/collection/gaps/master/master-1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["entity"]["type"] == "master"
        assert data["entity"]["name"] == "OK Computer"

    def test_master_not_found(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with patch("api.routers.collection.get_master_metadata", new=AsyncMock(return_value=None)):
            response = test_client.get("/api/collection/gaps/master/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    def test_no_driver_503(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        import api.routers.collection as collection_module

        original = collection_module._neo4j_driver
        collection_module._neo4j_driver = None
        try:
            response = test_client.get("/api/collection/gaps/master/123", headers=auth_headers)
            assert response.status_code == 503
        finally:
            collection_module._neo4j_driver = original


class TestGapsPagination:
    """Tests for pagination query parameters on gap endpoints."""

    def test_limit_exceeds_max(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.get("/api/collection/gaps/label/123?limit=201", headers=auth_headers)
        assert response.status_code == 422

    def test_negative_offset(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        response = test_client.get("/api/collection/gaps/label/123?offset=-1", headers=auth_headers)
        assert response.status_code == 422

    def test_has_more_flag(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with (
            patch("api.routers.collection.get_label_metadata", new=AsyncMock(return_value=_MOCK_LABEL_META)),
            patch("api.routers.collection.get_label_gap_summary", new=AsyncMock(return_value=_MOCK_SUMMARY)),
            patch("api.routers.collection.get_label_gaps", new=AsyncMock(return_value=(_MOCK_RELEASES, 50))),
            patch("api.routers.collection._get_cached_summary", return_value=None),
        ):
            response = test_client.get("/api/collection/gaps/label/label-1?limit=10&offset=0", headers=auth_headers)
        data = response.json()
        assert data["pagination"]["has_more"] is True


class TestFormatFilter:
    """Tests for format query parameter on gap endpoints."""

    def test_format_filter_passed_to_query(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        mock_gaps = AsyncMock(return_value=(_MOCK_RELEASES, 1))
        with (
            patch("api.routers.collection.get_artist_metadata", new=AsyncMock(return_value=_MOCK_ARTIST_META)),
            patch("api.routers.collection.get_artist_gap_summary", new=AsyncMock(return_value=_MOCK_SUMMARY)),
            patch("api.routers.collection.get_artist_gaps", new=mock_gaps),
            patch("api.routers.collection._get_cached_summary", return_value=None),
        ):
            response = test_client.get(
                "/api/collection/gaps/artist/artist-1?formats=Vinyl&formats=CD",
                headers=auth_headers,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["filters"]["formats"] == ["Vinyl", "CD"]
        # Verify the query function was called with format filter
        call_kwargs = mock_gaps.call_args
        assert call_kwargs[0][6] == ["Vinyl", "CD"]  # formats arg


class TestSummaryCache:
    """Tests for summary count caching."""

    def test_cache_hit_skips_query(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        with (
            patch("api.routers.collection.get_label_metadata", new=AsyncMock(return_value=_MOCK_LABEL_META)),
            patch("api.routers.collection._get_cached_summary", return_value=_MOCK_SUMMARY),
            patch("api.routers.collection.get_label_gaps", new=AsyncMock(return_value=([], 0))),
            patch("api.routers.collection.get_label_gap_summary", new=AsyncMock()) as mock_summary,
        ):
            response = test_client.get("/api/collection/gaps/label/label-1", headers=auth_headers)
        assert response.status_code == 200
        mock_summary.assert_not_called()
