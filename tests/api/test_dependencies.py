"""Tests for FastAPI dependency functions."""

from unittest.mock import MagicMock

import pytest

from api.dependencies import configure, get_optional_user, require_user


# Use a known JWT secret for tests
TEST_SECRET = "test-jwt-secret-for-unit-tests"


def _make_credentials(token: str) -> MagicMock:
    """Create a mock HTTPAuthorizationCredentials."""
    creds = MagicMock()
    creds.credentials = token
    return creds


def _make_valid_token(secret: str = TEST_SECRET) -> str:
    """Create a valid HS256 JWT for testing."""
    import base64
    import hashlib
    import hmac
    import json

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({"sub": "user-1", "email": "test@example.com", "exp": 9_999_999_999}, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


class TestConfigure:
    def test_sets_jwt_secret(self) -> None:
        configure(TEST_SECRET)
        # Verify it took effect by using require_user with a valid token
        # (just verify configure doesn't raise)

    def test_sets_none_secret(self) -> None:
        configure(None)


class TestGetOptionalUser:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_credentials(self) -> None:
        configure(TEST_SECRET)
        result = await get_optional_user(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_secret(self) -> None:
        configure(None)
        creds = _make_credentials("some-token")
        result = await get_optional_user(creds)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_payload_for_valid_token(self) -> None:
        configure(TEST_SECRET)
        token = _make_valid_token()
        creds = _make_credentials(token)
        result = await get_optional_user(creds)
        assert result is not None
        assert result["sub"] == "user-1"
        assert result["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_token(self) -> None:
        configure(TEST_SECRET)
        creds = _make_credentials("invalid.token.here")
        result = await get_optional_user(creds)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_secret(self) -> None:
        configure(TEST_SECRET)
        token = _make_valid_token(secret="wrong-secret-key-for-testing-1234")  # noqa: S106
        creds = _make_credentials(token)
        result = await get_optional_user(creds)
        assert result is None


class TestRequireUser:
    @pytest.mark.asyncio
    async def test_raises_503_when_no_secret(self) -> None:
        configure(None)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_user(MagicMock())
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_401_when_no_credentials(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_user(None)
        assert exc_info.value.status_code == 401
        assert "Authentication required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_returns_payload_for_valid_token(self) -> None:
        configure(TEST_SECRET)
        token = _make_valid_token()
        creds = _make_credentials(token)
        result = await require_user(creds)
        assert result["sub"] == "user-1"

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_token(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        creds = _make_credentials("bad.token.value")
        with pytest.raises(HTTPException) as exc_info:
            await require_user(creds)
        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_raises_401_for_expired_token(self) -> None:
        """Test with an expired JWT (exp in the past)."""
        import base64
        import hashlib
        import hmac
        import json

        configure(TEST_SECRET)
        from fastapi import HTTPException

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(json.dumps({"sub": "user-1", "exp": 1000000000}, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        sig = b64url(hmac.new(TEST_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
        expired_token = f"{header}.{body}.{sig}"

        creds = _make_credentials(expired_token)
        with pytest.raises(HTTPException) as exc_info:
            await require_user(creds)
        assert exc_info.value.status_code == 401
