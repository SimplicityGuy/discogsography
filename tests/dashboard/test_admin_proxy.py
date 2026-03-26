"""Tests for admin proxy router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx as httpx_mod
import pytest

from dashboard.admin_proxy import _validate_path_segment, configure, router


def _mock_httpx(method: str = "post", status: int = 200, content: bytes = b"{}") -> tuple[AsyncMock, AsyncMock]:
    """Return (mock_cls, mock_instance) for patching httpx.AsyncClient."""
    mock_resp = AsyncMock()
    mock_resp.status_code = status
    mock_resp.content = content

    mock_instance = AsyncMock()
    setattr(mock_instance, method, AsyncMock(return_value=mock_resp))
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cls = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


def _mock_httpx_error(method: str = "post") -> tuple[AsyncMock, AsyncMock]:
    """Return mocks that raise ConnectError."""
    mock_instance = AsyncMock()
    setattr(mock_instance, method, AsyncMock(side_effect=httpx_mod.ConnectError("refused")))
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cls = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


@pytest.fixture
def proxy_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    configure("localhost", 8004)
    return app


@pytest.fixture
def proxy_client(proxy_app: FastAPI) -> TestClient:
    return TestClient(proxy_app)


# ---------------------------------------------------------------------------
# configure + helpers
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_sets_base_url(self) -> None:
        configure("myhost", 9999)
        from dashboard.admin_proxy import _api_base_url

        assert _api_base_url == "http://myhost:9999"
        # Reset for other tests
        configure("localhost", 8004)


class TestValidatePathSegment:
    def test_valid_uuid(self) -> None:
        assert _validate_path_segment("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_alphanumeric(self) -> None:
        assert _validate_path_segment("graphinator-artists-dlq") is True

    def test_rejects_slashes(self) -> None:
        assert _validate_path_segment("../etc/passwd") is False

    def test_rejects_dots(self) -> None:
        assert _validate_path_segment("foo.bar") is False

    def test_rejects_empty(self) -> None:
        assert _validate_path_segment("") is False

    def test_rejects_spaces(self) -> None:
        assert _validate_path_segment("foo bar") is False


# ---------------------------------------------------------------------------
# POST /admin/api/login
# ---------------------------------------------------------------------------


class TestLoginProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_login_with_body(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _mock_cls, mock_instance = _mock_httpx("post", 200, b'{"access_token":"tok","token_type":"bearer","expires_in":1800}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/login", json={"email": "a@b.com", "password": "testtest"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()
        mock_instance.post.assert_called_once()

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_login_without_body(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _mock_cls, mock_instance = _mock_httpx("post", 422, b'{"detail":"body required"}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/login")
        assert resp.status_code == 422

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_login_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/login", json={"email": "a@b.com", "password": "x"})
        assert resp.status_code == 502
        assert "unavailable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /admin/api/logout
# ---------------------------------------------------------------------------


class TestLogoutProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_logout(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"logged_out":true}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/logout", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["logged_out"] is True

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_logout_forwards_auth_header(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"logged_out":true}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post("/admin/api/logout", headers={"Authorization": "Bearer mytoken"})
        call_kwargs = mock_instance.post.call_args
        assert "Bearer mytoken" in str(call_kwargs)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_logout_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/logout")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /admin/api/extractions
# ---------------------------------------------------------------------------


class TestListExtractionsProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_list(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"extractions":[],"total":0}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extractions", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_list_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extractions")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /admin/api/extractions/{id}
# ---------------------------------------------------------------------------


class TestGetExtractionProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_get(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"id":"abc-123","status":"completed"}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extractions/abc-123", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_rejects_invalid_id(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extractions/../../../etc/passwd")
        assert resp.status_code in (400, 404)  # FastAPI may reject before handler

    def test_rejects_id_with_dots(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extractions/foo.bar")
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_get_extraction_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extractions/abc-123")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /admin/api/extractions/trigger
# ---------------------------------------------------------------------------


class TestTriggerProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_trigger(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 202, b'{"id":"abc","status":"running"}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/extractions/trigger", headers={"Authorization": "Bearer mytoken"})
        assert resp.status_code == 202
        call_kwargs = mock_instance.post.call_args
        assert "Bearer mytoken" in str(call_kwargs)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_trigger_with_body(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 202, b'{"id":"abc","status":"running"}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extractions/trigger",
            json={"force_reprocess": True},
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 202

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_trigger_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/extractions/trigger")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /admin/api/dlq/purge/{queue}
# ---------------------------------------------------------------------------


class TestDlqPurgeProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_purge(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"queue":"graphinator-artists-dlq","messages_purged":0}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/dlq/purge/graphinator-artists-dlq",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        assert resp.json()["queue"] == "graphinator-artists-dlq"

    def test_rejects_invalid_queue_name(self, proxy_client: TestClient) -> None:
        resp = proxy_client.post("/admin/api/dlq/purge/../../etc")
        assert resp.status_code in (400, 404)

    def test_rejects_queue_with_dots(self, proxy_client: TestClient) -> None:
        resp = proxy_client.post("/admin/api/dlq/purge/bad.queue.name")
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_purge_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/dlq/purge/graphinator-artists-dlq")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Auth header forwarding
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 2 — User Activity & Storage proxy routes
# ---------------------------------------------------------------------------


class TestUserStatsProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_user_stats(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"total_users":5,"active_users":3}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/users/stats", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["total_users"] == 5

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_user_stats_forwards_auth_header(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"total_users":1}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/users/stats", headers={"Authorization": "Bearer mytoken"})
        call_kwargs = mock_instance.get.call_args
        assert "Bearer mytoken" in str(call_kwargs)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_user_stats_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/users/stats")
        assert resp.status_code == 502
        assert "unavailable" in resp.json()["detail"]


class TestSyncActivityProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_sync_activity(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"activity":[]}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/users/sync-activity", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert "activity" in resp.json()

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_sync_activity_forwards_auth_header(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"activity":[]}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/users/sync-activity", headers={"Authorization": "Bearer mytoken"})
        call_kwargs = mock_instance.get.call_args
        assert "Bearer mytoken" in str(call_kwargs)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_sync_activity_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/users/sync-activity")
        assert resp.status_code == 502
        assert "unavailable" in resp.json()["detail"]


class TestStorageProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_storage(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"neo4j":{"size_bytes":1024},"postgres":{"size_bytes":2048}}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/storage", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert "neo4j" in resp.json()

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_storage_forwards_auth_header(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"neo4j":{},"postgres":{}}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/storage", headers={"Authorization": "Bearer mytoken"})
        call_kwargs = mock_instance.get.call_args
        assert "Bearer mytoken" in str(call_kwargs)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_storage_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/storage")
        assert resp.status_code == 502
        assert "unavailable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Phase 3 — Queue Health Trends & System Health proxy routes
# ---------------------------------------------------------------------------


class TestQueueHistoryProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_with_query_params(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"range":"7d","granularity":"1hour","queues":{},"dlq_summary":{}}'
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = proxy_client.get(
            "/admin/api/queues/history?range=7d",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        call_url = mock_client.get.call_args[0][0]
        assert "/api/admin/queues/history" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_api_unavailable(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        resp = proxy_client.get("/admin/api/queues/history")
        assert resp.status_code == 502


class TestHealthHistoryProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_request(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = b'{"range":"24h","granularity":"15min","services":{},"api_endpoints":{}}'
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        resp = proxy_client.get(
            "/admin/api/health/history",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200


class TestAuthHeaderForwarding:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_no_auth_header_sent_when_absent(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"extractions":[]}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/extractions")
        call_kwargs = mock_instance.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" not in headers
