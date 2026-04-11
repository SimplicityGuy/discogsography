"""Tests for extraction analysis proxy routes in admin_proxy.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx as httpx_mod
import pytest

from dashboard.admin_proxy import configure, router


def _mock_httpx(method: str = "get", status: int = 200, content: bytes = b"{}") -> tuple[AsyncMock, AsyncMock]:
    """Return (mock_cls, mock_instance) for patching httpx.AsyncClient."""
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.content = content

    mock_instance = AsyncMock()
    setattr(mock_instance, method, AsyncMock(return_value=mock_resp))
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cls = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


def _mock_httpx_error(method: str = "get") -> tuple[AsyncMock, AsyncMock]:
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
# GET /admin/api/extraction-analysis/versions
# ---------------------------------------------------------------------------


class TestEaVersionsProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"versions":["20240101","20240201"]}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/versions", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert "versions" in resp.json()
        mock_instance.get.assert_called_once()
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/versions" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/versions")
        assert resp.status_code == 502
        assert "unavailable" in resp.json()["detail"]

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_auth_header(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"versions":[]}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/extraction-analysis/versions", headers={"Authorization": "Bearer mytoken"})
        call_kwargs = mock_instance.get.call_args
        assert "Bearer mytoken" in str(call_kwargs)


# ---------------------------------------------------------------------------
# GET /admin/api/extraction-analysis/{version}/summary
# ---------------------------------------------------------------------------


class TestEaSummaryProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_with_valid_version(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"version":"20240101","total_violations":5}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/summary", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "20240101"
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/summary" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_dotted_version(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"version":"20240101.0"}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101.0/summary", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        call_url = mock_instance.get.call_args[0][0]
        assert "20240101.0" in call_url

    def test_rejects_path_traversal(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/../../../etc/summary")
        assert resp.status_code in (400, 404)

    def test_rejects_invalid_version(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/ver%2F1/summary")
        assert resp.status_code in (400, 404, 422)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/summary")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /admin/api/extraction-analysis/{version}/violations/{record_id}
# ---------------------------------------------------------------------------


class TestEaViolationDetailProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        payload = b'{"record_id":"abc123","violations":[]}'
        _, mock_instance = _mock_httpx("get", 200, payload)
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20240101/violations/abc123",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        assert resp.json()["record_id"] == "abc123"
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/violations/abc123" in call_url

    def test_rejects_invalid_record_id(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations/bad/record/id")
        assert resp.status_code in (400, 404)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations/abc123")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /admin/api/extraction-analysis/{version}/violations
# ---------------------------------------------------------------------------


class TestEaViolationsProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_without_params(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"violations":[],"total":0}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/violations" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_query_params(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"violations":[],"total":0}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.get(
            "/admin/api/extraction-analysis/20240101/violations?entity_type=artists&severity=error&rule=missing-id&page=2&page_size=25",
            headers={"Authorization": "Bearer tok"},
        )
        call_args = mock_instance.get.call_args
        params = call_args[1].get("params", {})
        assert params.get("entity_type") == "artists"
        assert params.get("severity") == "error"
        assert params.get("rule") == "missing-id"
        assert params.get("page") == "2"
        assert params.get("page_size") == "25"

    def test_rejects_invalid_severity(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations?severity=critical")
        assert resp.status_code == 422

    def test_rejects_invalid_entity_type(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations?entity_type=ARTISTS!")
        assert resp.status_code == 422

    def test_rejects_page_size_too_large(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations?page_size=999")
        assert resp.status_code == 422

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /admin/api/extraction-analysis/{version}/parsing-errors
# ---------------------------------------------------------------------------


class TestEaParsingErrorsProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"parsing_errors":[],"total":0}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20240101/parsing-errors",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/parsing-errors" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_uses_60s_timeout(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b"{}")
        mock_cls_patch.return_value = mock_instance

        proxy_client.get("/admin/api/extraction-analysis/20240101/parsing-errors")
        # Verify timeout=60.0 was passed to AsyncClient constructor
        call_kwargs = mock_cls_patch.call_args
        assert call_kwargs[1].get("timeout") == 60.0

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/parsing-errors")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /admin/api/extraction-analysis/{version}/compare/{other_version}
# ---------------------------------------------------------------------------


class TestEaCompareProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        payload = b'{"version_a":"20240101","version_b":"20240201","delta":[]}'
        _, mock_instance = _mock_httpx("get", 200, payload)
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20240101/compare/20240201",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/compare/20240201" in call_url

    def test_rejects_invalid_other_version(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/compare/../bad")
        assert resp.status_code in (400, 404)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/compare/20240201")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /admin/api/extraction-analysis/{version}/prompt-context
# ---------------------------------------------------------------------------


class TestEaPromptContextProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_body_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":"..."}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/prompt-context",
            json={"rules": ["missing-id"], "entity_type": "artists"},
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        mock_instance.post.assert_called_once()
        call_url = mock_instance.post.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/prompt-context" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_sanitises_body(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":""}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post(
            "/admin/api/extraction-analysis/20240101/prompt-context",
            json={"rules": ["r1"]},
            headers={"Authorization": "Bearer tok"},
        )
        call_kwargs = mock_instance.post.call_args
        body_bytes = call_kwargs[1].get("content", b"")
        # Body must be valid JSON (re-serialised, not raw bytes)
        parsed = json.loads(body_bytes)
        assert parsed["rules"] == ["r1"]

    def test_rejects_malformed_json(self, proxy_client: TestClient) -> None:
        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/prompt-context",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Malformed JSON" in resp.json()["detail"]

    def test_rejects_invalid_version(self, proxy_client: TestClient) -> None:
        resp = proxy_client.post("/admin/api/extraction-analysis/ver%2F1/prompt-context", json={})
        assert resp.status_code in (400, 404, 422)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/prompt-context",
            json={"rules": []},
        )
        assert resp.status_code == 502

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_no_body_posts_without_content_type(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        """Empty/missing body goes through the else branch (line 494 — post without body)."""
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":""}')
        mock_cls_patch.return_value = mock_instance

        # Send with no body at all
        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/prompt-context",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        # Verify the no-body post path was taken
        call_kwargs = mock_instance.post.call_args
        assert call_kwargs[1].get("content") is None


# ---------------------------------------------------------------------------
# Invalid path-segment validation tests (missing lines 378, 394, 396, 420, 447, 463, 465, 481)
# ---------------------------------------------------------------------------


class TestEaInvalidVersionRejections:
    """One test per route that validates the version path segment (line 378, 420, 447, 463, 481).

    Uses '!' which is rejected by the _SAFE_PATH_SEGMENT pattern and is not normalised away by FastAPI.
    """

    def test_summary_invalid_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_summary rejects invalid version with 400 (line 378)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/bad!version/summary")
        assert resp.status_code == 400

    def test_violations_list_invalid_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_violations rejects invalid version with 400 (line 420)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/bad!version/violations")
        assert resp.status_code == 400

    def test_parsing_errors_invalid_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_parsing_errors rejects invalid version with 400 (line 447)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/bad!version/parsing-errors")
        assert resp.status_code == 400

    def test_compare_invalid_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_compare rejects invalid version with 400 (line 463)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/bad!version/compare/20240201")
        assert resp.status_code == 400

    def test_compare_invalid_other_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_compare rejects invalid other_version with 400 (line 465)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/compare/bad!other")
        assert resp.status_code == 400

    def test_prompt_context_invalid_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_prompt_context rejects invalid version with 400 (line 481)."""
        resp = proxy_client.post("/admin/api/extraction-analysis/bad!version/prompt-context", json={})
        assert resp.status_code == 400


class TestEaViolationDetailInvalidSegments:
    """Invalid version and record_id checks for violation detail (lines 394, 396).

    Uses '!' which is rejected by the _SAFE_PATH_SEGMENT pattern and is not normalised away by FastAPI.
    """

    def test_violation_detail_invalid_version_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_violation_detail rejects invalid version with 400 (line 394)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/bad!version/violations/abc123")
        assert resp.status_code == 400

    def test_violation_detail_invalid_record_id_returns_400(self, proxy_client: TestClient) -> None:
        """proxy_ea_violation_detail rejects invalid record_id with 400 (line 396)."""
        resp = proxy_client.get("/admin/api/extraction-analysis/20240101/violations/bad!record")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /admin/api/extraction-analysis/{version}/skipped
# ---------------------------------------------------------------------------


class TestEaSkippedProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"skipped":[],"total":0,"page":1,"page_size":50}')
        mock_cls_patch.return_value = mock_instance
        resp = proxy_client.get("/admin/api/extraction-analysis/20260401/skipped", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert "skipped" in resp.json()
        mock_instance.get.assert_called_once()
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20260401/skipped" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_passes_query_params(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"skipped":[],"total":0,"page":1,"page_size":50}')
        mock_cls_patch.return_value = mock_instance
        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20260401/skipped?entity_type=artists&page=2",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_instance.get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params.get("entity_type") == "artists"
        assert params.get("page") == "2"

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_rejects_invalid_version(self, _mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/../etc/skipped")
        assert resp.status_code in (400, 404)

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance
        resp = proxy_client.get("/admin/api/extraction-analysis/20260401/skipped")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /admin/api/extraction-analysis/{version}/generate-ai-prompt
# ---------------------------------------------------------------------------


class TestEaGenerateAiPromptProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_body_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":"analysis","ai_generated":true}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/generate-ai-prompt",
            json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        mock_instance.post.assert_called_once()
        call_url = mock_instance.post.call_args[0][0]
        assert "/api/admin/extraction-analysis/20240101/generate-ai-prompt" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_uses_120s_timeout(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        """AI prompt proxy uses 120s timeout for Claude API latency."""
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":""}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post(
            "/admin/api/extraction-analysis/20240101/generate-ai-prompt",
            json={"rules": [{"rule": "r1", "entity_type": "artists"}]},
            headers={"Authorization": "Bearer tok"},
        )
        call_kwargs = mock_cls_patch.call_args
        assert call_kwargs[1]["timeout"] == 120.0

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_sanitises_body(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":""}')
        mock_cls_patch.return_value = mock_instance

        proxy_client.post(
            "/admin/api/extraction-analysis/20240101/generate-ai-prompt",
            json={"rules": [{"rule": "r1", "entity_type": "artists"}]},
            headers={"Authorization": "Bearer tok"},
        )
        call_kwargs = mock_instance.post.call_args
        body_bytes = call_kwargs[1].get("content", b"")
        parsed = json.loads(body_bytes)
        assert parsed["rules"] == [{"rule": "r1", "entity_type": "artists"}]

    def test_rejects_malformed_json(self, proxy_client: TestClient) -> None:
        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/generate-ai-prompt",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Malformed JSON" in resp.json()["detail"]

    def test_rejects_invalid_version(self, proxy_client: TestClient) -> None:
        resp = proxy_client.post("/admin/api/extraction-analysis/bad!version/generate-ai-prompt", json={})
        assert resp.status_code == 400

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("post")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/generate-ai-prompt",
            json={"rules": [{"rule": "r1", "entity_type": "artists"}]},
        )
        assert resp.status_code == 502

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_no_body_posts_without_content_type(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        """Empty/missing body goes through the else branch."""
        _, mock_instance = _mock_httpx("post", 200, b'{"prompt":""}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extraction-analysis/20240101/generate-ai-prompt",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_instance.post.call_args
        assert call_kwargs[1].get("content") is None
