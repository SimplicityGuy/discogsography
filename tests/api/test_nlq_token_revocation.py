"""Regression tests for discogsography-aexv.

``_extract_user_id`` in api/routers/nlq.py hand-rolled Bearer validation: it
verified the signature and ``exp`` via ``decode_token`` and returned ``sub``
directly, performing NEITHER the ``revoked:jti:{jti}`` check nor the
``password_changed:{user_id}`` check that every other auth site performs. The
helper was sync and so could not await Redis, and the resolved user_id unlocks
the authenticated NLQ collection tools — so a token revoked by logout or a
password change kept reading the victim's private collection data until it expired.

These tests pin the NLQ site's revocation behavior and the shared helper
(``api.auth.token_revocation_reason``) that all auth sites now delegate to, so a
future site cannot silently become a seventh divergent copy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.auth import REASON_CREDENTIALS_CHANGED, REASON_REVOKED, token_revocation_reason


SECRET = "test-nlq-secret"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_jwt(claims: dict[str, Any], secret: str = SECRET) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = _b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _access_token(*, jti: str = "jti-1", iat: int = 1_000, sub: str = "user-1") -> str:
    return _sign_jwt({"sub": sub, "email": "x@y.com", "exp": 9_999_999_999, "iat": iat, "jti": jti})


def _fake_request(token: str) -> Any:
    """Minimal object exposing the .headers.get() interface _extract_user_id uses."""

    class _Headers:
        def get(self, key: str, default: str = "") -> str:
            return f"Bearer {token}" if key.lower() == "authorization" else default

    class _Req:
        headers = _Headers()

    return _Req()


def _redis_returning(mapping: dict[str, Any]) -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda key: mapping.get(key))
    return redis


@pytest.mark.asyncio
async def test_nlq_rejects_a_token_revoked_by_logout() -> None:
    """A logged-out token must not resolve to a user in the NLQ router."""
    from api.routers import nlq as nlq_router

    redis = _redis_returning({"revoked:jti:jti-1": "1"})
    nlq_router.configure(nlq_router.NLQConfig(), engine=None, redis=redis, jwt_secret=SECRET)

    assert await nlq_router._extract_user_id(_fake_request(_access_token())) is None


@pytest.mark.asyncio
async def test_nlq_rejects_token_invalidated_by_password_change() -> None:
    """A token issued before a password change must not resolve to a user."""
    from api.routers import nlq as nlq_router

    redis = _redis_returning({"password_changed:user-1": "2000"})
    nlq_router.configure(nlq_router.NLQConfig(), engine=None, redis=redis, jwt_secret=SECRET)

    assert await nlq_router._extract_user_id(_fake_request(_access_token(iat=1_000))) is None


@pytest.mark.asyncio
async def test_nlq_rejects_token_issued_in_the_same_second_as_password_change() -> None:
    """Boundary: the comparison is inclusive (issued_at <= changed_at)."""
    from api.routers import nlq as nlq_router

    redis = _redis_returning({"password_changed:user-1": "2000"})
    nlq_router.configure(nlq_router.NLQConfig(), engine=None, redis=redis, jwt_secret=SECRET)

    assert await nlq_router._extract_user_id(_fake_request(_access_token(iat=2_000))) is None


@pytest.mark.asyncio
async def test_nlq_accepts_token_issued_after_password_change() -> None:
    """A token minted after the change is still valid — revocation is not a blanket ban."""
    from api.routers import nlq as nlq_router

    redis = _redis_returning({"password_changed:user-1": "2000"})
    nlq_router.configure(nlq_router.NLQConfig(), engine=None, redis=redis, jwt_secret=SECRET)

    assert await nlq_router._extract_user_id(_fake_request(_access_token(iat=2_001))) == "user-1"


@pytest.mark.asyncio
async def test_nlq_accepts_live_token() -> None:
    """A live token with no revocation state resolves normally."""
    from api.routers import nlq as nlq_router

    redis = _redis_returning({})
    nlq_router.configure(nlq_router.NLQConfig(), engine=None, redis=redis, jwt_secret=SECRET)

    assert await nlq_router._extract_user_id(_fake_request(_access_token())) == "user-1"


@pytest.mark.asyncio
async def test_nlq_fails_closed_when_redis_errors() -> None:
    """If revocation state can't be read, the query degrades to anonymous, not authenticated."""
    from api.routers import nlq as nlq_router

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    nlq_router.configure(nlq_router.NLQConfig(), engine=None, redis=redis, jwt_secret=SECRET)

    assert await nlq_router._extract_user_id(_fake_request(_access_token())) is None


@pytest.mark.asyncio
async def test_revoked_token_does_not_unlock_authenticated_tools() -> None:
    """End-to-end: a revoked token must reach the engine with user_id=None.

    ``NLQEngine.run`` extends the tool set with the authenticated collection tools
    only when ``context.user_id`` is set, so this is the actual privilege boundary.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.nlq.engine import NLQResult
    from api.routers import nlq as nlq_router

    redis = _redis_returning({"revoked:jti:jti-1": "1"})
    engine = AsyncMock()
    engine.run = AsyncMock(return_value=NLQResult(summary="ok", entities=[], tools_used=[]))

    original_config = nlq_router._nlq_config
    try:
        nlq_router.configure(nlq_router.NLQConfig(enabled=True, api_key="sk-test"), engine=engine, redis=redis, jwt_secret=SECRET)
        app = FastAPI()
        app.include_router(nlq_router.router)
        with TestClient(app) as client:
            response = client.post(
                "/api/nlq/query",
                json={"query": "what are my collection blind spots"},
                headers={"Authorization": f"Bearer {_access_token()}"},
            )
    finally:
        nlq_router.configure(original_config, engine=None, redis=None, jwt_secret=None)

    assert response.status_code == 200
    ctx = engine.run.call_args[0][1]
    assert ctx.user_id is None, "a revoked token must not unlock the authenticated collection tools"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({}, None),
        ({"revoked:jti:jti-1": "1"}, REASON_REVOKED),
        ({"password_changed:user-1": "2000"}, REASON_CREDENTIALS_CHANGED),
    ],
)
async def test_shared_helper_classifies_token_revocation(state: dict[str, Any], expected: str | None) -> None:
    """The single implementation every auth site delegates to."""
    payload = {"sub": "user-1", "jti": "jti-1", "iat": 1_000}

    assert await token_revocation_reason(payload, _redis_returning(state)) == expected


@pytest.mark.asyncio
async def test_shared_helper_without_redis_is_permissive() -> None:
    """No Redis configured means no revocation store — tokens stand on signature alone."""
    payload = {"sub": "user-1", "jti": "jti-1", "iat": 1_000}

    assert await token_revocation_reason(payload, None) is None
