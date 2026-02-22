"""Tests for explore service user personalization queries."""

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# Set env vars before importing explore modules
os.environ.setdefault("NEO4J_ADDRESS", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "testpassword")

from explore.user_queries import check_releases_user_status


def _make_driver(rows: list[dict[str, Any]]) -> MagicMock:
    """Build a mock AsyncResilientNeo4jDriver that returns given rows."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_result = AsyncMock()

    async def _aiter(_self: Any) -> Any:  # type: ignore[override]
        for row in rows:
            yield row

    mock_result.__aiter__ = _aiter
    mock_result.single = AsyncMock(return_value=rows[0] if rows else None)

    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver.session = AsyncMock(return_value=mock_session)
    return driver


class TestCheckReleasesUserStatus:
    """Tests for check_releases_user_status."""

    @pytest.mark.asyncio
    async def test_empty_ids_returns_empty(self) -> None:
        driver = MagicMock()
        result = await check_releases_user_status(driver, "user-1", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_status_dict(self) -> None:
        rows = [
            {"release_id": "10", "in_collection": True, "in_wantlist": False},
            {"release_id": "20", "in_collection": False, "in_wantlist": True},
        ]
        driver = _make_driver(rows)
        result = await check_releases_user_status(driver, "user-1", ["10", "20"])

        assert result["10"]["in_collection"] is True
        assert result["10"]["in_wantlist"] is False
        assert result["20"]["in_collection"] is False
        assert result["20"]["in_wantlist"] is True


class TestJwtVerification:
    """Tests for the JWT verification helpers in explore.explore."""

    def test_valid_token_returns_payload(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        from explore.explore import _verify_jwt

        secret = "test-secret"

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body_data = {"sub": "user-123", "exp": 9999999999}
        body = b64url(json.dumps(body_data, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        payload = _verify_jwt(token, secret)
        assert payload is not None
        assert payload["sub"] == "user-123"

    def test_wrong_secret_returns_none(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        from explore.explore import _verify_jwt

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"sub": "x"}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(b"correct-secret", signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        assert _verify_jwt(token, "wrong-secret") is None

    def test_malformed_token_returns_none(self) -> None:
        from explore.explore import _verify_jwt

        assert _verify_jwt("not.a.valid.jwt.parts", "secret") is None
        assert _verify_jwt("only.two", "secret") is None

    def test_expired_token_returns_none(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        from explore.explore import _verify_jwt

        secret = "test-secret"

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
        # exp = 1 (epoch 1970-01-01 00:00:01 UTC, long expired)
        body = b64url(json.dumps({"sub": "user", "exp": 1}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        assert _verify_jwt(token, secret) is None
