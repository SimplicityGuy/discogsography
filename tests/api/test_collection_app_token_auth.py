"""Tests for /api/user/collection family under both JWT and app-token auth.

P5: the three endpoints accept either a first-party JWT (existing behavior, kept
intact) OR a `dscg_…` app token with scope `collection:read`. Rate limits apply
per token via `bearer_token_key_func`.
"""

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from api.app_tokens import generate_plaintext_token, hash_token
from tests.api.conftest import TEST_USER_ID


_APP_USER_ID = "99999999-9999-9999-9999-999999999999"
_APP_TOKEN_ID = "11111111-1111-1111-1111-111111111111"


def _make_active_row(scopes: list[str] | None = None, token_id: str = _APP_TOKEN_ID) -> dict[str, Any]:
    """A typical active `app_tokens` row as returned by `_lookup_active_token`."""
    return {
        "id": UUID(token_id),
        "user_id": UUID(_APP_USER_ID),
        "name": "GRUVAX kiosk",
        "scope": scopes if scopes is not None else ["collection:read"],
    }


@pytest.fixture
def app_token_headers(mock_cur: AsyncMock) -> dict[str, str]:
    """Authorization header whose lookup yields a valid active app token row."""
    mock_cur.fetchone = AsyncMock(return_value=_make_active_row())
    return {"Authorization": f"Bearer {generate_plaintext_token()}"}


@pytest.fixture
def app_token_headers_wrong_scope(mock_cur: AsyncMock) -> dict[str, str]:
    """Active token but lacks `collection:read`."""
    mock_cur.fetchone = AsyncMock(return_value=_make_active_row(scopes=["other:scope"]))
    return {"Authorization": f"Bearer {generate_plaintext_token()}"}


@pytest.fixture
def app_token_headers_revoked(mock_cur: AsyncMock) -> dict[str, str]:
    """Lookup yields None — token is unknown or revoked."""
    mock_cur.fetchone = AsyncMock(return_value=None)
    return {"Authorization": f"Bearer {generate_plaintext_token()}"}


# ──────────────────────────────────────────────────────────────────────────────
# /api/user/collection
# ──────────────────────────────────────────────────────────────────────────────


class TestCollectionAppTokenAuth:
    def test_app_token_success_returns_user_id_and_releases(
        self, test_client: TestClient, app_token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from api.routers import user as user_router

        monkeypatch.setattr(user_router, "get_user_collection", AsyncMock(return_value=([{"id": "r1"}], 1)))
        response = test_client.get("/api/user/collection?limit=10&offset=0", headers=app_token_headers)
        assert response.status_code == 200
        body = response.json()
        # user_id must be the app token's *owner*, not the caller's IP or any JWT sub.
        assert body["user_id"] == _APP_USER_ID
        assert body["releases"] == [{"id": "r1"}]
        assert body["total"] == 1

    def test_app_token_wrong_scope_returns_403(self, test_client: TestClient, app_token_headers_wrong_scope: dict[str, str]) -> None:
        response = test_client.get("/api/user/collection", headers=app_token_headers_wrong_scope)
        assert response.status_code == 403
        assert "collection:read" in response.json()["detail"]

    def test_revoked_or_unknown_app_token_returns_401(self, test_client: TestClient, app_token_headers_revoked: dict[str, str]) -> None:
        response = test_client.get("/api/user/collection", headers=app_token_headers_revoked)
        assert response.status_code == 401

    def test_missing_auth_returns_401(self, test_client: TestClient) -> None:
        response = test_client.get("/api/user/collection")
        assert response.status_code == 401

    def test_jwt_path_still_works_and_includes_user_id(
        self, test_client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: first-party JWT auth still resolves and now also surfaces user_id."""
        from api.routers import user as user_router

        monkeypatch.setattr(user_router, "get_user_collection", AsyncMock(return_value=([], 0)))
        response = test_client.get("/api/user/collection", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["user_id"] == TEST_USER_ID


# ──────────────────────────────────────────────────────────────────────────────
# /api/user/collection/stats
# ──────────────────────────────────────────────────────────────────────────────


class TestCollectionStatsAppTokenAuth:
    def test_app_token_success(self, test_client: TestClient, app_token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        from api.routers import user as user_router

        monkeypatch.setattr(user_router, "get_user_collection_stats", AsyncMock(return_value={"total": 42, "by_genre": {}}))
        response = test_client.get("/api/user/collection/stats", headers=app_token_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == _APP_USER_ID
        assert body["total"] == 42

    def test_app_token_wrong_scope_returns_403(self, test_client: TestClient, app_token_headers_wrong_scope: dict[str, str]) -> None:
        response = test_client.get("/api/user/collection/stats", headers=app_token_headers_wrong_scope)
        assert response.status_code == 403

    def test_jwt_path_includes_user_id(self, test_client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        from api.routers import user as user_router

        monkeypatch.setattr(user_router, "get_user_collection_stats", AsyncMock(return_value={"total": 7}))
        response = test_client.get("/api/user/collection/stats", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["user_id"] == TEST_USER_ID


# ──────────────────────────────────────────────────────────────────────────────
# /api/user/collection/timeline
# ──────────────────────────────────────────────────────────────────────────────


class TestCollectionTimelineAppTokenAuth:
    def test_app_token_success(self, test_client: TestClient, app_token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        import api.routers.user as user_router

        user_router._timeline_cache.clear()
        monkeypatch.setattr(user_router, "get_user_collection_timeline", AsyncMock(return_value={"buckets": [{"year": 2020, "count": 3}]}))
        response = test_client.get("/api/user/collection/timeline?bucket=year", headers=app_token_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == _APP_USER_ID
        assert body["buckets"] == [{"year": 2020, "count": 3}]

    def test_app_token_wrong_scope_returns_403(self, test_client: TestClient, app_token_headers_wrong_scope: dict[str, str]) -> None:
        response = test_client.get("/api/user/collection/timeline", headers=app_token_headers_wrong_scope)
        assert response.status_code == 403

    def test_jwt_path_includes_user_id(self, test_client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        import api.routers.user as user_router

        user_router._timeline_cache.clear()
        monkeypatch.setattr(user_router, "get_user_collection_timeline", AsyncMock(return_value={"buckets": []}))
        response = test_client.get("/api/user/collection/timeline", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["user_id"] == TEST_USER_ID

    def test_cache_hit_still_returns_user_id(
        self, test_client: TestClient, app_token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First call populates cache (with user_id); second call hits cache and still includes user_id."""
        import api.routers.user as user_router

        user_router._timeline_cache.clear()
        monkeypatch.setattr(user_router, "get_user_collection_timeline", AsyncMock(return_value={"buckets": [1]}))

        first = test_client.get("/api/user/collection/timeline?bucket=year", headers=app_token_headers)
        assert first.status_code == 200
        assert first.json()["user_id"] == _APP_USER_ID

        # Second request hits the cache — query function should NOT be called again.
        second = test_client.get("/api/user/collection/timeline?bucket=year", headers=app_token_headers)
        assert second.status_code == 200
        assert second.json()["user_id"] == _APP_USER_ID


# ──────────────────────────────────────────────────────────────────────────────
# Rate limits
# ──────────────────────────────────────────────────────────────────────────────


class TestRateLimits:
    def test_429_returned_after_60_requests_in_a_minute(
        self, test_client: TestClient, app_token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 60/minute limit must engage and return 429 + Retry-After."""
        from api.routers import user as user_router

        monkeypatch.setattr(user_router, "get_user_collection", AsyncMock(return_value=([], 0)))
        last_response = None
        for _ in range(65):
            last_response = test_client.get("/api/user/collection", headers=app_token_headers)
            if last_response.status_code == 429:
                break
        assert last_response is not None
        assert last_response.status_code == 429
        # slowapi sets Retry-After on the 429 response
        header_keys_lower = {k.lower() for k in last_response.headers}
        assert "retry-after" in header_keys_lower

    def test_two_different_tokens_have_independent_buckets(
        self, test_client: TestClient, mock_cur: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second app token must call freely even after the first is throttled.

        Verifies per-token rate-limit key. Without this, IP-based rate limiting would
        let a noisy neighbour lock everyone out.
        """
        from api.routers import user as user_router

        monkeypatch.setattr(user_router, "get_user_collection", AsyncMock(return_value=([], 0)))

        # Token A → drive to 429
        mock_cur.fetchone = AsyncMock(return_value=_make_active_row())
        headers_a = {"Authorization": f"Bearer {generate_plaintext_token()}"}
        seen_429 = False
        for _ in range(65):
            r = test_client.get("/api/user/collection", headers=headers_a)
            if r.status_code == 429:
                seen_429 = True
                break
        assert seen_429, "Test setup failed: did not reach 429 on token A"

        # Token B → brand-new plaintext → different hash → fresh bucket
        mock_cur.fetchone = AsyncMock(return_value=_make_active_row(token_id="22222222-2222-2222-2222-222222222222"))  # noqa: S106
        headers_b = {"Authorization": f"Bearer {generate_plaintext_token()}"}
        r_b = test_client.get("/api/user/collection", headers=headers_b)
        assert r_b.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# bearer_token_key_func unit tests
# ──────────────────────────────────────────────────────────────────────────────


class TestBearerTokenKeyFunc:
    def _req(self, auth: str | None, host: str = "127.0.0.1") -> Any:
        class _R:
            pass

        r = _R()
        r.headers = {"authorization": auth} if auth is not None else {}
        r.client = type("C", (), {"host": host})()
        return r

    def test_distinct_tokens_yield_distinct_keys(self) -> None:
        from api.limiter import bearer_token_key_func

        k1 = bearer_token_key_func(self._req("Bearer abc123"))
        k2 = bearer_token_key_func(self._req("Bearer xyz789"))
        assert k1 != k2
        assert k1.startswith("tok:")
        assert k2.startswith("tok:")

    def test_same_token_yields_same_key(self) -> None:
        from api.limiter import bearer_token_key_func

        assert bearer_token_key_func(self._req("Bearer SAME")) == bearer_token_key_func(self._req("Bearer SAME"))

    def test_falls_back_to_ip_without_bearer(self) -> None:
        from api.limiter import bearer_token_key_func

        key = bearer_token_key_func(self._req(None, host="10.20.30.40"))
        assert key.startswith("ip:")
        assert "10.20.30.40" in key

    def test_empty_bearer_falls_back_to_ip(self) -> None:
        """`Authorization: Bearer ` with no token MUST fall back to IP."""
        from api.limiter import bearer_token_key_func

        key = bearer_token_key_func(self._req("Bearer   "))
        assert key.startswith("ip:")

    def test_plaintext_token_never_appears_in_key(self) -> None:
        """The key uses a 16-hex-char hash slice — the plaintext must not leak."""
        from api.limiter import bearer_token_key_func

        plaintext = "dscg_super_secret_value"
        key = bearer_token_key_func(self._req(f"Bearer {plaintext}"))
        assert plaintext not in key
        assert key == "tok:" + hash_token(plaintext)[:16]
