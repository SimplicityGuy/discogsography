"""Tests for api/app_tokens.py — third-party app authorization."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException
import pytest

from api import app_tokens
from api.app_tokens import (
    TOKEN_PREFIX,
    AppTokenAuth,
    configure,
    generate_plaintext_token,
    hash_token,
    list_user_tokens,
    mint_token,
    require_app_token,
    revoke_token,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _make_pool_with_row(row: dict[str, Any] | None) -> MagicMock:
    """Build a mock pool whose cursor.fetchone() returns `row`.

    If `row` doesn't set its own "token_hash", it's auto-filled with whatever
    token_hash the query was actually invoked with, so the defense-in-depth
    `hmac.compare_digest(row["token_hash"], token_hash)` check
    (discogsography-osoc) naturally passes for tests that aren't specifically
    exercising a hash mismatch.
    """
    pool = MagicMock()
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    captured_params: dict[str, Any] = {}

    async def _execute(_query: str, params: tuple[Any, ...] = ()) -> None:
        if params:
            captured_params["token_hash"] = params[0]

    cur.execute = AsyncMock(side_effect=_execute)

    async def _fetchone() -> dict[str, Any] | None:
        if row is None:
            return None
        if "token_hash" not in row and "token_hash" in captured_params:
            return {**row, "token_hash": captured_params["token_hash"]}
        return row

    cur.fetchone = AsyncMock(side_effect=_fetchone)
    cur.fetchall = AsyncMock(return_value=[])
    cur.rowcount = 1 if row is not None else 0
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)
    pool.connection = MagicMock(return_value=conn)
    pool._cur = cur  # expose for assertion
    return pool


def _make_credentials(token: str | None) -> MagicMock | None:
    if token is None:
        return None
    creds = MagicMock()
    creds.credentials = token
    return creds


@pytest.fixture(autouse=True)
def _reset_pool() -> Any:
    """Ensure each test starts with a clean module-level pool reference."""
    original = app_tokens._pool
    yield
    app_tokens._pool = original


# ──────────────────────────────────────────────────────────────────────────────
# Plaintext / hash helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestPlaintextFormat:
    def test_prefix(self) -> None:
        token = generate_plaintext_token()
        assert token.startswith(TOKEN_PREFIX)

    def test_high_entropy(self) -> None:
        """32 random bytes → base64url ≈ 43 chars; well above any guessable threshold."""
        token = generate_plaintext_token()
        body = token[len(TOKEN_PREFIX) :]
        assert len(body) >= 40

    def test_tokens_are_unique(self) -> None:
        tokens = {generate_plaintext_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_no_padding_characters(self) -> None:
        """secrets.token_urlsafe never returns padding; ensure no '=' leaks through."""
        for _ in range(10):
            assert "=" not in generate_plaintext_token()


class TestHashToken:
    def test_sha256_hex_length(self) -> None:
        digest = hash_token("dscg_anything")
        assert len(digest) == 64

    def test_deterministic(self) -> None:
        assert hash_token("dscg_x") == hash_token("dscg_x")

    def test_different_inputs_different_hashes(self) -> None:
        assert hash_token("dscg_a") != hash_token("dscg_b")


class TestLookupActiveTokenQuery:
    """discogsography-ci4a: a deactivated user's app tokens must stop authenticating.

    _lookup_active_token now joins `users` and filters `is_active = TRUE`
    instead of a bare token_hash/revoked_at lookup on app_tokens alone.
    """

    @pytest.mark.asyncio
    async def test_query_joins_users_and_filters_is_active(self) -> None:
        pool = _make_pool_with_row(None)
        configure(pool)
        await app_tokens._lookup_active_token("deadbeef")

        query = pool._cur.execute.call_args.args[0]
        assert "JOIN users" in query
        assert "is_active = TRUE" in query
        assert "revoked_at IS NULL" in query

    @pytest.mark.asyncio
    async def test_selects_token_hash_for_defense_in_depth(self) -> None:
        """The row must project its own token_hash so callers can do a real
        compare_digest check instead of comparing a value to itself
        (discogsography-osoc)."""
        pool = _make_pool_with_row(None)
        configure(pool)
        await app_tokens._lookup_active_token("deadbeef")

        query = pool._cur.execute.call_args.args[0]
        assert "token_hash" in query


# ──────────────────────────────────────────────────────────────────────────────
# require_app_token failure modes — the core security contract
# ──────────────────────────────────────────────────────────────────────────────


class TestRequireAppTokenFailureModes:
    @pytest.mark.asyncio
    async def test_raises_401_when_credentials_missing(self) -> None:
        configure(_make_pool_with_row(None))
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=None)  # type: ignore[arg-type]
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_when_token_lacks_prefix(self) -> None:
        configure(_make_pool_with_row(None))
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials("not_a_dscg_token"))  # type: ignore[arg-type]
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_when_token_empty(self) -> None:
        configure(_make_pool_with_row(None))
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials(""))  # type: ignore[arg-type]
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_when_token_unknown(self) -> None:
        """Token not in DB (or revoked) — same 401 to avoid leaking active-vs-revoked state."""
        configure(_make_pool_with_row(None))
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_403_when_scope_missing(self) -> None:
        row = {
            "id": UUID("00000000-0000-0000-0000-000000000001"),
            "user_id": UUID("00000000-0000-0000-0000-000000000002"),
            "name": "GRUVAX kiosk",
            "scope": ["collection:read"],
        }
        configure(_make_pool_with_row(row))
        dep = require_app_token(["admin:write"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_503_when_pool_not_configured(self) -> None:
        app_tokens._pool = None
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_revoked_lookup_returns_401(self) -> None:
        """The WHERE clause filters revoked rows; the dependency sees None and raises 401.

        This test asserts the contract — the partial-index predicate is verified in P2 schema tests.
        """
        configure(_make_pool_with_row(None))  # None simulates "WHERE revoked_at IS NULL" filtering
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_defense_in_depth_rejects_row_hash_mismatch(self) -> None:
        """discogsography-osoc: the compare_digest guard must be a REAL check
        against the row's own persisted token_hash, not a self-comparison of
        hash_token(plaintext) against itself. Forcing the row's token_hash to
        diverge from the lookup hash must make the guard fire (401) — the
        pre-fix code could never reach this branch."""
        row = {
            "id": UUID("00000000-0000-0000-0000-000000000001"),
            "user_id": UUID("00000000-0000-0000-0000-000000000002"),
            "name": "GRUVAX kiosk",
            "scope": ["collection:read"],
            "token_hash": "0" * 64,  # deliberately wrong — never matches the real lookup hash
        }
        configure(_make_pool_with_row(row))
        dep = require_app_token(["collection:read"])
        with pytest.raises(HTTPException) as exc:
            await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert exc.value.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# require_app_token success path + AppTokenAuth
# ──────────────────────────────────────────────────────────────────────────────


class TestRequireAppTokenSuccess:
    @pytest.mark.asyncio
    async def test_returns_app_token_auth_for_valid_token(self) -> None:
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "user_id": UUID("22222222-2222-2222-2222-222222222222"),
            "name": "GRUVAX kiosk",
            "scope": ["collection:read", "collection:stats"],
        }
        configure(_make_pool_with_row(row))
        dep = require_app_token(["collection:read"])
        auth = await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert isinstance(auth, AppTokenAuth)
        assert auth.user_id == "22222222-2222-2222-2222-222222222222"
        assert auth.token_id == "11111111-1111-1111-1111-111111111111"
        assert auth.name == "GRUVAX kiosk"
        assert "collection:read" in auth.scopes
        # Let any spawned last_used_at task settle so the test doesn't leak.
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_multi_scope_requirement_satisfied(self) -> None:
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "user_id": UUID("22222222-2222-2222-2222-222222222222"),
            "name": "kiosk",
            "scope": ["collection:read", "collection:stats", "extra"],
        }
        configure(_make_pool_with_row(row))
        dep = require_app_token(["collection:read", "collection:stats"])
        auth = await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert isinstance(auth, AppTokenAuth)
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_last_used_at_update_failure_does_not_fail_request(self) -> None:
        """The bookkeeping update is fire-and-forget; even if it throws, the response succeeds."""
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "user_id": UUID("22222222-2222-2222-2222-222222222222"),
            "name": "kiosk",
            "scope": ["collection:read"],
        }
        pool = _make_pool_with_row(row)
        configure(pool)

        # Make the background update raise.
        async def boom(*_: Any) -> None:
            raise RuntimeError("PG unavailable")

        with patch.object(app_tokens, "_touch_last_used_at", side_effect=boom):
            dep = require_app_token(["collection:read"])
            auth = await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert isinstance(auth, AppTokenAuth)
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_scope_check_is_subset_not_equal(self) -> None:
        """Granted scopes may exceed required scopes; that's still authorized."""
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "user_id": UUID("22222222-2222-2222-2222-222222222222"),
            "name": "kiosk",
            "scope": ["collection:read", "collection:write"],
        }
        configure(_make_pool_with_row(row))
        dep = require_app_token(["collection:read"])  # subset
        auth = await dep(credentials=_make_credentials(generate_plaintext_token()))  # type: ignore[arg-type]
        assert auth.scopes == ["collection:read", "collection:write"]
        await asyncio.sleep(0)


# ──────────────────────────────────────────────────────────────────────────────
# mint_token / list_user_tokens / revoke_token CRUD
# ──────────────────────────────────────────────────────────────────────────────


class TestMintToken:
    @pytest.mark.asyncio
    async def test_returns_id_and_plaintext(self) -> None:
        new_id = UUID("33333333-3333-3333-3333-333333333333")
        pool = _make_pool_with_row({"id": new_id})
        configure(pool)
        token_id, plaintext = await mint_token(
            user_id="22222222-2222-2222-2222-222222222222",
            name="GRUVAX kiosk",
            scopes=["collection:read"],
        )
        assert token_id == new_id
        assert plaintext.startswith(TOKEN_PREFIX)

    @pytest.mark.asyncio
    async def test_persists_hash_not_plaintext(self) -> None:
        """The INSERT must pass token_hash (SHA-256 hex), never the plaintext."""
        new_id = UUID("33333333-3333-3333-3333-333333333333")
        pool = _make_pool_with_row({"id": new_id})
        configure(pool)
        _, plaintext = await mint_token(
            user_id="22222222-2222-2222-2222-222222222222",
            name="kiosk",
            scopes=["collection:read"],
        )
        # Verify the parameters passed to execute
        call_args = pool._cur.execute.await_args
        bind_params = call_args[0][1]
        assert plaintext not in bind_params, "Plaintext token must NEVER be persisted"
        assert hash_token(plaintext) in bind_params

    @pytest.mark.asyncio
    async def test_raises_when_pool_not_configured(self) -> None:
        app_tokens._pool = None
        with pytest.raises(RuntimeError, match="configure"):
            await mint_token("u", "n", ["s"])


class TestListUserTokens:
    @pytest.mark.asyncio
    async def test_partitions_active_and_revoked(self) -> None:
        rows = [
            {"id": "a", "name": "active1", "scope": ["s"], "created_at": "t", "last_used_at": None, "revoked_at": None},
            {"id": "b", "name": "revoked1", "scope": ["s"], "created_at": "t", "last_used_at": None, "revoked_at": "t"},
            {"id": "c", "name": "active2", "scope": ["s"], "created_at": "t", "last_used_at": "t", "revoked_at": None},
        ]
        pool = _make_pool_with_row(None)
        pool._cur.fetchall = AsyncMock(return_value=rows)
        configure(pool)
        active, revoked = await list_user_tokens("user-1")
        assert {r["name"] for r in active} == {"active1", "active2"}
        assert {r["name"] for r in revoked} == {"revoked1"}

    @pytest.mark.asyncio
    async def test_never_returns_token_hash(self) -> None:
        """The SELECT must not include token_hash — verified by inspecting the SQL."""
        pool = _make_pool_with_row(None)
        pool._cur.fetchall = AsyncMock(return_value=[])
        configure(pool)
        await list_user_tokens("user-1")
        sql_used = str(pool._cur.execute.await_args[0][0])
        assert "token_hash" not in sql_used


class TestRevokeToken:
    @pytest.mark.asyncio
    async def test_returns_true_when_row_updated(self) -> None:
        pool = _make_pool_with_row({})
        pool._cur.rowcount = 1
        configure(pool)
        result = await revoke_token("t-1", "u-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_match(self) -> None:
        pool = _make_pool_with_row(None)
        pool._cur.rowcount = 0
        configure(pool)
        result = await revoke_token("t-1", "u-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_is_scoped_to_owning_user(self) -> None:
        """The WHERE clause must include user_id — a token belonging to another user must NOT be revokable."""
        pool = _make_pool_with_row({})
        pool._cur.rowcount = 1
        configure(pool)
        await revoke_token("t-1", "u-1")
        sql_used = str(pool._cur.execute.await_args[0][0])
        assert "user_id" in sql_used

    @pytest.mark.asyncio
    async def test_update_skips_already_revoked(self) -> None:
        """The WHERE clause must include revoked_at IS NULL so revoke is idempotent."""
        pool = _make_pool_with_row({})
        pool._cur.rowcount = 0
        configure(pool)
        await revoke_token("t-1", "u-1")
        sql_used = str(pool._cur.execute.await_args[0][0])
        assert "revoked_at IS NULL" in sql_used


# ──────────────────────────────────────────────────────────────────────────────
# Re-export from api.dependencies
# ──────────────────────────────────────────────────────────────────────────────


class TestReExport:
    def test_require_app_token_importable_from_dependencies(self) -> None:
        from api.dependencies import AppTokenAuth as DepAuth, require_app_token as dep_require

        assert dep_require is require_app_token
        assert DepAuth is AppTokenAuth
