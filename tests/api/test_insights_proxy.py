"""Tests for the insights API proxy router."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest


class TestInsightsConfigure:
    """Tests for the configure() function."""

    def test_configure_updates_base_url(self) -> None:
        """Lines 26-27: configure sets _INSIGHTS_BASE_URL when url provided."""
        import api.routers.insights as mod

        original = mod._INSIGHTS_BASE_URL
        try:
            mod.configure("http://custom-insights:9000")
            assert mod._INSIGHTS_BASE_URL == "http://custom-insights:9000"
        finally:
            mod._INSIGHTS_BASE_URL = original
            mod.configure()  # restore default (no-op, but sets _INSIGHTS_BASE_URL to whatever it already is)
            mod._INSIGHTS_BASE_URL = original

    def test_configure_no_url_keeps_default(self) -> None:
        """configure() with no argument leaves _INSIGHTS_BASE_URL unchanged."""
        import api.routers.insights as mod

        original = mod._INSIGHTS_BASE_URL
        mod.configure()
        assert original == mod._INSIGHTS_BASE_URL


class TestInsightsProxySuccess:
    """Tests for successful proxy responses (success paths)."""

    def test_proxy_top_artists_success(self, test_client: TestClient) -> None:
        """Line 49: proxy_top_artists returns 200 with data on success."""
        mock_data = {"items": [{"artist": "Miles Davis", "count": 100}]}
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=mock_data)):
            response = test_client.get("/api/insights/top-artists")
        assert response.status_code == 200
        assert response.json() == mock_data

    def test_proxy_genre_trends_success(self, test_client: TestClient) -> None:
        """Line 60: proxy_genre_trends returns 200 with data on success."""
        mock_data = {"trends": [{"genre": "Jazz", "year": 1960, "count": 50}]}
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=mock_data)):
            response = test_client.get("/api/insights/genre-trends")
        assert response.status_code == 200
        assert response.json() == mock_data

    def test_proxy_label_longevity_success(self, test_client: TestClient) -> None:
        """Line 71: proxy_label_longevity returns 200 with data on success."""
        mock_data = {"labels": [{"name": "Blue Note", "years": 80}]}
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=mock_data)):
            response = test_client.get("/api/insights/label-longevity")
        assert response.status_code == 200
        assert response.json() == mock_data

    def test_proxy_this_month_success(self, test_client: TestClient) -> None:
        """Line 82: proxy_this_month returns 200 with data on success."""
        mock_data = {"releases": [], "count": 0}
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=mock_data)):
            response = test_client.get("/api/insights/this-month")
        assert response.status_code == 200
        assert response.json() == mock_data

    def test_proxy_data_completeness_success(self, test_client: TestClient) -> None:
        """Line 93: proxy_data_completeness returns 200 with data on success."""
        mock_data = {"completeness": 0.95}
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=mock_data)):
            response = test_client.get("/api/insights/data-completeness")
        assert response.status_code == 200
        assert response.json() == mock_data

    def test_proxy_status_success(self, test_client: TestClient) -> None:
        """Line 104: proxy_status returns 200 with data on success."""
        mock_data = {"status": "ok", "last_run": "2026-03-15T00:00:00Z"}
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=mock_data)):
            response = test_client.get("/api/insights/status")
        assert response.status_code == 200
        assert response.json() == mock_data


class TestForwardStatusCodePreservation:
    """Tests that _forward preserves upstream HTTP status codes."""

    @pytest.mark.asyncio
    async def test_forward_preserves_422_status(self) -> None:
        """_forward returns upstream 422 instead of masking it as 200."""
        from api.routers.insights import _forward

        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": [{"msg": "field required", "type": "missing"}]}
        mock_response.status_code = 422

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from starlette.datastructures import URL
        from starlette.requests import Request

        mock_request = AsyncMock(spec=Request)
        mock_request.url = URL("http://test/api/insights/genre-trends")

        with patch("api.routers.insights.httpx.AsyncClient", return_value=mock_client):
            result = await _forward(mock_request, "/api/insights/genre-trends")
        assert result.status_code == 422

    def test_proxy_genre_trends_forwards_422(self, test_client: TestClient) -> None:
        """Proxy returns 422 when upstream insights service returns 422."""
        error_response = JSONResponse(
            content={"detail": [{"msg": "field required", "type": "missing"}]},
            status_code=422,
        )
        with patch("api.routers.insights._forward", new=AsyncMock(return_value=error_response)):
            response = test_client.get("/api/insights/genre-trends")
        assert response.status_code == 422


class TestForwardWithQueryString:
    """Tests for _forward appending query strings."""

    @pytest.mark.asyncio
    async def test_forward_appends_query_string(self) -> None:
        """_forward appends ?query when request has a query string."""
        from api.routers.insights import _forward

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from starlette.datastructures import URL
        from starlette.requests import Request

        mock_request = AsyncMock(spec=Request)
        mock_request.url = URL("http://test/api/insights/genre-trends?genre=Jazz")

        with patch("api.routers.insights.httpx.AsyncClient", return_value=mock_client):
            result = await _forward(mock_request, "/api/insights/genre-trends")
        assert result.status_code == 200
        assert result.body == JSONResponse(content={"items": []}).body
        mock_client.get.assert_awaited_once_with("http://insights:8008/api/insights/genre-trends?genre=Jazz")


class TestInsightsProxy:
    def test_proxy_top_artists_503_when_unavailable(self, test_client: TestClient) -> None:
        """Verify /api/insights/top-artists returns 503 when insights service is down."""
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/top-artists")
        assert response.status_code == 503

    def test_proxy_genre_trends_503_when_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/genre-trends?genre=Jazz")
        assert response.status_code == 503

    def test_proxy_label_longevity_503_when_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/label-longevity")
        assert response.status_code == 503

    def test_proxy_this_month_503_when_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/this-month")
        assert response.status_code == 503

    def test_proxy_data_completeness_503_when_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/data-completeness")
        assert response.status_code == 503

    def test_proxy_status_503_when_unavailable(self, test_client: TestClient) -> None:
        with patch("api.routers.insights._forward", side_effect=Exception("Connection refused")):
            response = test_client.get("/api/insights/status")
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_forward_success(self) -> None:
        """Test _forward returns JSON from insights service."""
        from api.routers.insights import _forward

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [], "count": 0}
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from starlette.datastructures import URL
        from starlette.requests import Request

        mock_request = AsyncMock(spec=Request)
        mock_request.url = URL("http://test/api/insights/top-artists")

        with patch("api.routers.insights.httpx.AsyncClient", return_value=mock_client):
            result = await _forward(mock_request, "/api/insights/top-artists")
        assert result.status_code == 200
        assert result.body == JSONResponse(content={"items": [], "count": 0}).body
        mock_client.get.assert_awaited_once_with("http://insights:8008/api/insights/top-artists")


class TestInsightsForwardClient:
    """Tests that _forward uses a per-request httpx.AsyncClient (lines 33-34)."""

    @pytest.mark.asyncio
    async def test_forward_creates_per_request_client(self) -> None:
        """_forward creates a new httpx.AsyncClient as a context manager for each request."""
        from api.routers.insights import _forward

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_response.status_code = 200

        from starlette.datastructures import URL
        from starlette.requests import Request

        mock_request = AsyncMock(spec=Request)
        mock_request.url = URL("http://test/api/insights/top-artists")

        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("api.routers.insights.httpx.AsyncClient", return_value=mock_instance) as mock_cls:
            result = await _forward(mock_request, "/api/insights/top-artists")

        mock_cls.assert_called_once_with(timeout=30.0)
        mock_instance.__aenter__.assert_awaited_once()
        mock_instance.__aexit__.assert_awaited_once()
        assert result.status_code == 200
