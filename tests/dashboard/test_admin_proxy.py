"""Tests for admin proxy router."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx as httpx_mod
import pytest

from dashboard.admin_proxy import configure, router


@pytest.fixture
def proxy_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    configure("localhost", 8004)
    return app


@pytest.fixture
def proxy_client(proxy_app: FastAPI) -> TestClient:
    return TestClient(proxy_app)


class TestLoginProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_login(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"access_token":"tok","token_type":"bearer","expires_in":1800}'
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/login",
            json={"email": "a@b.com", "password": "testtest"},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()


class TestTriggerProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_auth_header(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 202
        mock_resp.content = b'{"id":"abc","status":"running"}'
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/extractions/trigger",
            headers={"Authorization": "Bearer mytoken"},
        )
        assert resp.status_code == 202
        # Verify auth header was forwarded
        call_args = mock_instance.post.call_args
        assert "Bearer mytoken" in str(call_args)


class TestApiUnreachable:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502(self, mock_cls: AsyncMock, proxy_client: TestClient) -> None:
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance

        resp = proxy_client.post(
            "/admin/api/login",
            json={"email": "a@b.com", "password": "testtest"},
        )
        assert resp.status_code == 502
