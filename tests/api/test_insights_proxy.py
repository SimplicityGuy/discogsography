"""Tests for the insights API proxy router."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest


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
        import api.routers.insights as mod
        from api.routers.insights import _forward

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [], "count": 0}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        original_client = mod._client
        mod._client = mock_client

        try:
            from starlette.datastructures import URL
            from starlette.requests import Request

            mock_request = AsyncMock(spec=Request)
            mock_request.url = URL("http://test/api/insights/top-artists")

            result = await _forward(mock_request, "/api/insights/top-artists")
            assert result == {"items": [], "count": 0}
            mock_client.get.assert_awaited_once_with("http://insights:8008/api/insights/top-artists")
        finally:
            mod._client = original_client
