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

    def test_allows_dots(self) -> None:
        # Dots are allowed to support version strings like "20240101.0"
        assert _validate_path_segment("foo.bar") is True

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

    def test_allows_id_with_dots(self, proxy_client: TestClient) -> None:
        # Dots are now allowed in path segments (needed for version strings)
        # foo.bar passes validation; the upstream API returns the actual status
        # We just verify the proxy doesn't reject it at the validation layer.
        # Without a mock the upstream call fails with a connection error → 502.
        resp = proxy_client.get("/admin/api/extractions/foo.bar")
        assert resp.status_code != 400

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

    def test_allows_queue_with_dots(self, proxy_client: TestClient) -> None:
        # Dots are now allowed in path segments; the upstream will handle validity.
        # Without a mock the upstream call fails with a connection error → 502.
        resp = proxy_client.post("/admin/api/dlq/purge/bad.queue.name")
        assert resp.status_code != 400

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
# Additional path-segment validation tests for lines 145 and 258
# ---------------------------------------------------------------------------


class TestExtractionIdValidationRejectsInvalidChars:
    def test_rejects_extraction_id_with_exclamation(self, proxy_client: TestClient) -> None:
        """proxy_get_extraction returns 400 for extraction_id containing '!' (line 145).

        The '!' character fails _SAFE_PATH_SEGMENT and is not normalised away by FastAPI.
        """
        resp = proxy_client.get("/admin/api/extractions/bad!id")
        assert resp.status_code == 400

    def test_rejects_extraction_id_with_space(self, proxy_client: TestClient) -> None:
        """proxy_get_extraction returns 400 for extraction_id containing a space (line 145)."""
        resp = proxy_client.get("/admin/api/extractions/bad%20id")
        assert resp.status_code == 400


class TestDlqPurgeInvalidQueueValidation:
    def test_rejects_queue_name_with_invalid_chars(self, proxy_client: TestClient) -> None:
        """proxy_dlq_purge returns 400 for queue names containing '!' (line 258).

        The '!' character fails _SAFE_PATH_SEGMENT and is not normalised away by FastAPI.
        """
        resp = proxy_client.post("/admin/api/dlq/purge/bad!queue")
        assert resp.status_code == 400


class TestQueueHistoryInvalidGranularity:
    def test_rejects_invalid_granularity_pattern(self, proxy_client: TestClient) -> None:
        """proxy_queue_history returns 422 for granularity not matching pattern (line 287 branch)."""
        resp = proxy_client.get("/admin/api/queues/history?granularity=bad")
        assert resp.status_code == 422

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_granularity_param(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        """proxy_queue_history forwards granularity param when provided (line 287)."""
        _, mock_instance = _mock_httpx("get", 200, b'{"queues":{}}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/queues/history?granularity=1hour")
        assert resp.status_code == 200
        call_kwargs = mock_instance.get.call_args
        params = call_kwargs[1].get("params", {})
        assert params.get("granularity") == "1hour"


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

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_with_range_and_granularity(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        """Test that range and granularity params are forwarded."""
        mock_response = MagicMock()
        mock_response.content = b'{"range":"7d","granularity":"1hour","services":{},"api_endpoints":{}}'
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = proxy_client.get(
            "/admin/api/health/history?range=7d&granularity=1hour",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        call_args = mock_client.get.call_args
        params = call_args[1].get("params", {})
        assert params.get("range") == "7d"
        assert params.get("granularity") == "1hour"

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_api_unavailable(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        """Test error handling when API is unreachable."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = proxy_client.get("/admin/api/health/history")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Phase 4 — Audit Log proxy route
# ---------------------------------------------------------------------------


class TestAuditLogProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_proxy_audit_log(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_resp = MagicMock()
        mock_resp.content = b'{"entries":[],"total":0,"page":1,"page_size":50}'
        mock_resp.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/audit-log",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_proxy_audit_log_with_params(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        """Test that query parameters are forwarded."""
        mock_resp = MagicMock()
        mock_resp.content = b'{"entries":[],"total":0,"page":2,"page_size":25}'
        mock_resp.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/audit-log?page=2&page_size=25&action=dlq.purge&admin_id=abc-123",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        # Verify params were forwarded
        call_args = mock_instance.get.call_args
        params = call_args[1].get("params", {})
        assert params.get("page") == "2"
        assert params.get("page_size") == "25"
        assert params.get("action") == "dlq.purge"
        assert params.get("admin_id") == "abc-123"

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_proxy_audit_log_api_unreachable(self, mock_client_cls: AsyncMock, proxy_client: TestClient) -> None:
        """Test error handling when API is unreachable."""
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(side_effect=httpx_mod.ConnectError("Connection refused"))
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/audit-log",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /admin/api/extractions/trigger-musicbrainz
# ---------------------------------------------------------------------------


class TestTriggerMusicBrainzProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_trigger_musicbrainz(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 202, b'{"id":"abc","status":"running"}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/extractions/trigger-musicbrainz", headers={"Authorization": "Bearer mytoken"})
        assert resp.status_code == 202
        call_kwargs = mock_instance.post.call_args
        assert "Bearer mytoken" in str(call_kwargs)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_injects_source_musicbrainz(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 202, b'{"id":"abc","status":"running"}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post("/admin/api/extractions/trigger-musicbrainz", headers={"Authorization": "Bearer tok"})
        call_kwargs = mock_instance.post.call_args
        assert '"source":"musicbrainz"' in str(call_kwargs) or b'"source":"musicbrainz"' in call_kwargs.kwargs.get("content", b"")

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_merges_body_with_source_injection(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 202, b'{"id":"abc","status":"running"}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post(
            "/admin/api/extractions/trigger-musicbrainz",
            json={"force_reprocess": True},
            headers={"Authorization": "Bearer tok"},
        )
        call_kwargs = mock_instance.post.call_args
        content = call_kwargs.kwargs.get("content", b"")
        import json as _json

        body = _json.loads(content)
        assert body["source"] == "musicbrainz"
        assert body["force_reprocess"] is True

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_trigger_musicbrainz_targets_trigger_endpoint(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 202, b'{"id":"abc","status":"running"}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post("/admin/api/extractions/trigger-musicbrainz", headers={"Authorization": "Bearer tok"})
        call_url = mock_instance.post.call_args[0][0]
        assert call_url.endswith("/api/admin/extractions/trigger")

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_trigger_musicbrainz_unreachable(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post("/admin/api/extractions/trigger-musicbrainz")
        assert resp.status_code == 502


class TestMalformedJsonBody:
    def test_login_malformed_json_returns_400(self, proxy_client: TestClient) -> None:
        """POST /admin/api/login with malformed JSON body returns 400."""
        resp = proxy_client.post(
            "/admin/api/login",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Malformed JSON" in resp.json()["detail"]

    def test_trigger_malformed_json_returns_400(self, proxy_client: TestClient) -> None:
        """POST /admin/api/extractions/trigger with malformed JSON body returns 400."""
        resp = proxy_client.post(
            "/admin/api/extractions/trigger",
            content=b"{{bad json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Malformed JSON" in resp.json()["detail"]

    def test_trigger_musicbrainz_malformed_json_returns_400(self, proxy_client: TestClient) -> None:
        """POST /admin/api/extractions/trigger-musicbrainz with malformed JSON returns 400."""
        resp = proxy_client.post(
            "/admin/api/extractions/trigger-musicbrainz",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Malformed JSON" in resp.json()["detail"]

    def test_trigger_musicbrainz_non_dict_body_returns_400(self, proxy_client: TestClient) -> None:
        """POST /admin/api/extractions/trigger-musicbrainz with JSON array body returns 400."""
        resp = proxy_client.post(
            "/admin/api/extractions/trigger-musicbrainz",
            content=b"[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "JSON object" in resp.json()["detail"]

    def test_trigger_musicbrainz_sanitised_body_decode_error_returns_400(self, proxy_client: TestClient) -> None:
        """POST trigger-musicbrainz returns 400 when sanitised body fails json.loads (lines 189-190)."""
        # Mock _validated_json_body to return bytes that fail json.loads
        with patch("dashboard.admin_proxy._validated_json_body", new_callable=AsyncMock, return_value=b"\xff\xfe"):
            resp = proxy_client.post(
                "/admin/api/extractions/trigger-musicbrainz",
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 400
        assert "Malformed JSON" in resp.json()["detail"]


class TestAuthHeaderForwarding:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_no_auth_header_sent_when_absent(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"extractions":[]}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/extractions")
        call_kwargs = mock_instance.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" not in headers
