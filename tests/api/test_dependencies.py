"""Tests for FastAPI dependency functions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.dependencies import configure, get_optional_user, require_admin, require_user


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


def _make_admin_token(
    admin_id: str = "admin-1",
    email: str = "admin@test.com",
    secret: str = TEST_SECRET,
) -> str:
    """Create a valid admin JWT for testing."""
    import base64
    import hashlib
    import hmac
    import json

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(
        json.dumps(
            {"sub": admin_id, "email": email, "exp": 9_999_999_999, "type": "admin", "jti": "admin:test123"},
            separators=(",", ":"),
        ).encode()
    )
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


class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    @pytest.mark.asyncio
    async def test_raises_503_when_no_secret(self) -> None:
        configure(None)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(_make_credentials("some-token"))
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_403_when_type_is_not_admin(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        token = _make_valid_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_401_when_no_credentials(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_token(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        creds = _make_credentials("bad.token.value")
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_db_verified_admin_succeeds(self) -> None:
        """Valid admin token + DB confirms is_admin=True -> returns payload."""
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"is_admin": True})
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        configure(TEST_SECRET, pool=mock_pool)

        token = _make_admin_token()
        creds = _make_credentials(token)
        result = await require_admin(creds)
        assert result["sub"] == "admin-1"
        assert result["type"] == "admin"

    @pytest.mark.asyncio
    async def test_db_verified_admin_rejects_non_admin(self) -> None:
        """Valid admin token but DB says is_admin=False -> 403."""
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"is_admin": False})
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        configure(TEST_SECRET, pool=mock_pool)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_db_verified_admin_rejects_missing_user(self) -> None:
        """Valid admin token but user not found in DB -> 403."""
        mock_pool = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_conn = AsyncMock()
        cur_ctx = AsyncMock()
        cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
        cur_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=cur_ctx)
        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.connection = MagicMock(return_value=conn_ctx)

        configure(TEST_SECRET, pool=mock_pool)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_revoked_token_rejected(self) -> None:
        """Valid admin token but revoked in Redis -> 401."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")
        configure(TEST_SECRET, redis=mock_redis)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(creds)
        assert exc_info.value.status_code == 401


def _make_token_with_claims(extra_claims: dict, secret: str = TEST_SECRET) -> str:
    """Create a valid HS256 JWT with custom claims merged into the base payload."""
    import base64
    import hashlib
    import hmac
    import json

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = {"sub": "user-1", "email": "test@example.com", "exp": 9_999_999_999}
    payload.update(extra_claims)
    body = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


class TestGetOptionalUserRevocationChecks:
    """Tests for JTI revocation and password-changed checks in get_optional_user."""

    @pytest.mark.asyncio
    async def test_revoked_jti_returns_none(self) -> None:
        """Token with a revoked JTI returns None."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")
        configure(TEST_SECRET, redis=mock_redis)

        token = _make_token_with_claims({"jti": "test-jti-123"})
        creds = _make_credentials(token)
        result = await get_optional_user(creds)

        assert result is None
        mock_redis.get.assert_any_call("revoked:jti:test-jti-123")

    @pytest.mark.asyncio
    async def test_revoked_jti_no_redis_returns_payload(self) -> None:
        """Token with a JTI but no redis configured returns the payload normally."""
        configure(TEST_SECRET)  # no redis

        token = _make_token_with_claims({"jti": "test-jti-123"})
        creds = _make_credentials(token)
        result = await get_optional_user(creds)

        assert result is not None
        assert result["sub"] == "user-1"

    @pytest.mark.asyncio
    async def test_password_changed_before_token_returns_none(self) -> None:
        """Token issued before password change returns None."""
        mock_redis = AsyncMock()

        async def redis_get(key: str) -> str | None:
            if key.startswith("password_changed:"):
                return "2000"
            return None  # revoked:jti:... returns None

        mock_redis.get = AsyncMock(side_effect=redis_get)
        configure(TEST_SECRET, redis=mock_redis)

        token = _make_token_with_claims({"iat": 1000})
        creds = _make_credentials(token)
        result = await get_optional_user(creds)

        assert result is None

    @pytest.mark.asyncio
    async def test_password_changed_after_token_returns_payload(self) -> None:
        """Token issued after password change returns the payload."""
        mock_redis = AsyncMock()

        async def redis_get(key: str) -> str | None:
            if key.startswith("password_changed:"):
                return "2000"
            return None

        mock_redis.get = AsyncMock(side_effect=redis_get)
        configure(TEST_SECRET, redis=mock_redis)

        token = _make_token_with_claims({"iat": 3000})
        creds = _make_credentials(token)
        result = await get_optional_user(creds)

        assert result is not None
        assert result["sub"] == "user-1"


class TestRequireUserTokenChecks:
    """Tests for admin-token rejection, JTI revocation, and password-changed revocation in require_user."""

    @pytest.mark.asyncio
    async def test_rejects_admin_token_with_403(self) -> None:
        configure(TEST_SECRET)
        from fastapi import HTTPException

        token = _make_admin_token()
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_user(creds)
        assert exc_info.value.status_code == 403
        assert "Admin tokens cannot be used" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_revoked_jti_returns_401(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")
        configure(TEST_SECRET, redis=mock_redis)
        from fastapi import HTTPException

        token = _make_token_with_claims({"jti": "test-jti-123"})
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_user(creds)
        assert exc_info.value.status_code == 401
        assert "Token has been revoked" in str(exc_info.value.detail)
        mock_redis.get.assert_any_call("revoked:jti:test-jti-123")

    @pytest.mark.asyncio
    async def test_password_changed_revocation(self) -> None:
        mock_redis = AsyncMock()

        async def redis_get(key: str) -> str | None:
            if key.startswith("password_changed:"):
                return "2000"
            return None

        mock_redis.get = AsyncMock(side_effect=redis_get)
        configure(TEST_SECRET, redis=mock_redis)
        from fastapi import HTTPException

        token = _make_token_with_claims({"iat": 1000})
        creds = _make_credentials(token)
        with pytest.raises(HTTPException) as exc_info:
            await require_user(creds)
        assert exc_info.value.status_code == 401
        assert "Token invalidated by password change" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_password_changed_allows_newer_token(self) -> None:
        mock_redis = AsyncMock()

        async def redis_get(key: str) -> str | None:
            if key.startswith("password_changed:"):
                return "2000"
            return None

        mock_redis.get = AsyncMock(side_effect=redis_get)
        configure(TEST_SECRET, redis=mock_redis)

        token = _make_token_with_claims({"iat": 3000})
        creds = _make_credentials(token)
        result = await require_user(creds)
        assert result["sub"] == "user-1"
