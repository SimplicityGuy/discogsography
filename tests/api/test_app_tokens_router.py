"""Tests for api/routers/app_tokens.py — settings UI backend."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

import api.app_tokens as app_tokens_module
from tests.api.conftest import TEST_USER_ID, make_test_jwt


_AUTH_HEADER = {"Authorization": f"Bearer {make_test_jwt()}"}
_NEW_TOKEN_ID = UUID("11111111-1111-1111-1111-111111111111")


def _fake_mint_token() -> tuple[UUID, str]:
    """Static stand-in for app_tokens.mint_token in tests."""
    return _NEW_TOKEN_ID, "dscg_test_plaintext_token_value_here"


def _patch_module_pool(mock_pool: Any) -> None:
    """Wire the module-level pool used by app_tokens.mint_token / list / revoke."""
    app_tokens_module._pool = mock_pool


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/user/app-tokens
# ──────────────────────────────────────────────────────────────────────────────


class TestMintAppToken:
    def test_requires_authentication(self, test_client: TestClient) -> None:
        resp = test_client.post("/api/user/app-tokens", json={"name": "kiosk", "scopes": ["collection:read"]})
        assert resp.status_code == 401

    def test_returns_plaintext_token_and_201(self, test_client: TestClient, mock_pool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_module_pool(mock_pool)

        async def _mint(user_id: str, name: str, scopes: list[str]) -> tuple[UUID, str]:  # noqa: ARG001
            return _NEW_TOKEN_ID, "dscg_PLAINTEXT_SECRET"

        async def _list(user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:  # noqa: ARG001
            return (
                [
                    {
                        "id": _NEW_TOKEN_ID,
                        "name": "kiosk",
                        "scope": ["collection:read"],
                        "created_at": datetime(2026, 5, 26, tzinfo=UTC),
                        "last_used_at": None,
                        "revoked_at": None,
                    }
                ],
                [],
            )

        monkeypatch.setattr("api.routers.app_tokens._mint_token", _mint)
        monkeypatch.setattr("api.routers.app_tokens._list_user_tokens", _list)

        resp = test_client.post(
            "/api/user/app-tokens",
            json={"name": "kiosk", "scopes": ["collection:read"]},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == str(_NEW_TOKEN_ID)
        assert body["name"] == "kiosk"
        assert body["scopes"] == ["collection:read"]
        assert body["token"] == "dscg_PLAINTEXT_SECRET"
        assert body["created_at"] is not None

    def test_rejects_unknown_scope(self, test_client: TestClient) -> None:
        resp = test_client.post(
            "/api/user/app-tokens",
            json={"name": "kiosk", "scopes": ["collection:read", "admin:everything"]},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "admin:everything" in resp.json()["detail"]

    def test_rejects_whitespace_only_name(self, test_client: TestClient, mock_pool: Any) -> None:
        _patch_module_pool(mock_pool)
        resp = test_client.post(
            "/api/user/app-tokens",
            json={"name": "   ", "scopes": ["collection:read"]},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_rejects_empty_scopes_via_validation(self, test_client: TestClient) -> None:
        resp = test_client.post(
            "/api/user/app-tokens",
            json={"name": "kiosk", "scopes": []},
            headers=_AUTH_HEADER,
        )
        # Pydantic v2 returns 422 for failed Field(min_length=1) validation
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/user/app-tokens
# ──────────────────────────────────────────────────────────────────────────────


class TestListAppTokens:
    def test_requires_authentication(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/user/app-tokens")
        assert resp.status_code == 401

    def test_partitions_active_and_revoked(self, test_client: TestClient, mock_pool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_module_pool(mock_pool)

        async def _list(user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:  # noqa: ARG001
            active = [
                {
                    "id": UUID("22222222-2222-2222-2222-222222222222"),
                    "name": "kiosk-A",
                    "scope": ["collection:read"],
                    "created_at": datetime(2026, 5, 26, tzinfo=UTC),
                    "last_used_at": None,
                    "revoked_at": None,
                }
            ]
            revoked = [
                {
                    "id": UUID("33333333-3333-3333-3333-333333333333"),
                    "name": "old-kiosk",
                    "scope": ["collection:read"],
                    "created_at": datetime(2026, 5, 1, tzinfo=UTC),
                    "last_used_at": None,
                    "revoked_at": datetime(2026, 5, 10, tzinfo=UTC),
                }
            ]
            return active, revoked

        monkeypatch.setattr("api.routers.app_tokens._list_user_tokens", _list)

        resp = test_client.get("/api/user/app-tokens", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["active"]) == 1
        assert len(body["revoked"]) == 1
        assert body["active"][0]["name"] == "kiosk-A"
        assert body["active"][0]["scopes"] == ["collection:read"]
        assert body["revoked"][0]["name"] == "old-kiosk"

    def test_active_row_never_contains_token_hash(self, test_client: TestClient, mock_pool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """The router maps rows explicitly; even if list_user_tokens added token_hash it must not leak."""
        _patch_module_pool(mock_pool)

        async def _list(user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:  # noqa: ARG001
            return (
                [
                    {
                        "id": UUID("44444444-4444-4444-4444-444444444444"),
                        "name": "kiosk",
                        "scope": ["collection:read"],
                        "created_at": datetime(2026, 5, 26, tzinfo=UTC),
                        "last_used_at": None,
                        "revoked_at": None,
                        # Simulated leak from the inner CRUD — must be stripped by the router.
                        "token_hash": "should-never-leak",
                    }
                ],
                [],
            )

        monkeypatch.setattr("api.routers.app_tokens._list_user_tokens", _list)

        resp = test_client.get("/api/user/app-tokens", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        body_text = resp.text
        assert "should-never-leak" not in body_text
        assert "token_hash" not in body_text


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/user/app-tokens/{token_id}
# ──────────────────────────────────────────────────────────────────────────────


class TestRevokeAppToken:
    def test_requires_authentication(self, test_client: TestClient) -> None:
        resp = test_client.delete("/api/user/app-tokens/00000000-0000-0000-0000-000000000099")
        assert resp.status_code == 401

    def test_returns_204_on_success(self, test_client: TestClient, mock_pool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_module_pool(mock_pool)

        captured: dict[str, Any] = {}

        async def _revoke(token_id: str, user_id: str) -> bool:
            captured["token_id"] = token_id
            captured["user_id"] = user_id
            return True

        monkeypatch.setattr("api.routers.app_tokens._revoke_token", _revoke)

        resp = test_client.delete(
            "/api/user/app-tokens/00000000-0000-0000-0000-000000000099",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 204
        # 204 must have empty body
        assert resp.content == b""
        # Owner scoping: revoke_token must have been called with the JWT's user_id
        assert captured["user_id"] == TEST_USER_ID
        assert captured["token_id"] == "00000000-0000-0000-0000-000000000099"

    def test_returns_404_when_no_active_row(self, test_client: TestClient, mock_pool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A token belonging to a different user, an unknown id, or an already-revoked
        token all surface as 404 — we do not disclose token existence to non-owners."""
        _patch_module_pool(mock_pool)

        async def _revoke(token_id: str, user_id: str) -> bool:  # noqa: ARG001
            return False

        monkeypatch.setattr("api.routers.app_tokens._revoke_token", _revoke)

        resp = test_client.delete(
            "/api/user/app-tokens/00000000-0000-0000-0000-000000000099",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 404
