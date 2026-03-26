"""Tests for auth router — password reset and 2FA endpoints."""

import base64
from dataclasses import replace
import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pyotp
import pytest

from api.auth import (
    create_challenge_token,
    encrypt_totp_secret,
    generate_recovery_codes,
    get_totp_encryption_key,
    hash_recovery_code,
)
import api.routers.auth as auth_router
from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_EMAIL, TEST_USER_ID, make_sample_user_row, make_test_jwt


_TEST_MASTER_KEY = base64.urlsafe_b64encode(b"test-master-key-padded-to-32!!").decode("ascii")


def _make_challenge_token() -> str:
    """Create a valid 2FA challenge token for the test user."""
    return create_challenge_token(TEST_USER_ID, TEST_USER_EMAIL, TEST_JWT_SECRET)


def _make_encrypted_totp_secret() -> tuple[str, str]:
    """Create an encrypted TOTP secret and return (plaintext_secret, encrypted_secret)."""
    totp_key = get_totp_encryption_key(_TEST_MASTER_KEY)
    assert totp_key is not None
    secret = pyotp.random_base32()
    encrypted = encrypt_totp_secret(secret, totp_key)
    return secret, encrypted


class TestResetRequest:
    """Tests for POST /api/auth/reset-request."""

    def test_reset_request_known_email(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        response = test_client.post("/api/auth/reset-request", json={"email": TEST_USER_EMAIL})
        assert response.status_code == 200
        assert "message" in response.json()
        mock_redis.setex.assert_called()

    def test_reset_request_unknown_email_same_response(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)
        response = test_client.post("/api/auth/reset-request", json={"email": "unknown@example.com"})
        assert response.status_code == 200
        assert "message" in response.json()

    def test_reset_request_normalizes_email(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
    ) -> None:
        mock_cur.fetchone = AsyncMock(return_value=None)
        response = test_client.post("/api/auth/reset-request", json={"email": " Test@Example.COM "})
        assert response.status_code == 200


class TestResetConfirm:
    """Tests for POST /api/auth/reset-confirm."""

    def test_reset_confirm_valid_token(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
    ) -> None:
        mock_redis.get = AsyncMock(
            return_value=json.dumps(
                {
                    "user_id": TEST_USER_ID,
                    "email": TEST_USER_EMAIL,
                }
            )
        )
        response = test_client.post(
            "/api/auth/reset-confirm",
            json={"token": "valid-token", "new_password": "newpassword123"},
        )
        assert response.status_code == 200
        assert "reset" in response.json()["message"].lower()
        mock_redis.delete.assert_called()

    def test_reset_confirm_invalid_token(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
    ) -> None:
        mock_redis.get = AsyncMock(return_value=None)
        response = test_client.post(
            "/api/auth/reset-confirm",
            json={"token": "invalid-token", "new_password": "newpassword123"},
        )
        assert response.status_code == 400

    def test_reset_confirm_short_password(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/reset-confirm",
            json={"token": "some-token", "new_password": "short"},
        )
        assert response.status_code == 422  # Pydantic validation


class TestTwoFactorSetup:
    """Tests for POST /api/auth/2fa/setup."""

    def test_setup_returns_secret_and_qr_uri(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        import base64
        from dataclasses import replace

        import api.routers.auth as auth_router

        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        mock_redis.get = AsyncMock(return_value=None)
        # Temporarily set encryption master key for 2FA setup
        test_key = base64.urlsafe_b64encode(b"test-master-key-padded-to-32!!").decode("ascii")
        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=test_key)
        try:
            response = test_client.post("/api/auth/2fa/setup", headers=auth_headers)
        finally:
            auth_router._config = original_config
        assert response.status_code == 200
        data = response.json()
        assert "secret" in data
        assert "otpauth_uri" in data
        assert "recovery_codes" in data
        assert len(data["recovery_codes"]) == 8
        assert "otpauth://totp/" in data["otpauth_uri"]


class TestTwoFactorVerify:
    """Tests for POST /api/auth/2fa/verify."""

    def test_verify_invalid_challenge_token(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/verify",
            json={"challenge_token": "invalid.token.here", "code": "123456"},
        )
        assert response.status_code == 401


class TestTwoFactorDisable:
    """Tests for POST /api/auth/2fa/disable."""

    def test_disable_requires_auth(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/disable",
            json={"code": "123456", "password": "testpassword"},
        )
        assert response.status_code in (401, 403)


class TestPasswordChangedRevocation:
    """Tests for password_changed_at session revocation in _get_current_user."""

    def test_token_revoked_after_password_change(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
        mock_cur: AsyncMock,
    ) -> None:
        """Token issued before password change should be rejected."""
        import base64
        import hashlib
        import hmac
        import time

        from tests.api.conftest import TEST_JWT_SECRET, TEST_USER_ID

        # Create a JWT with an explicit iat in the past
        old_iat = int(time.time()) - 120

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64url(
            json.dumps(
                {
                    "sub": TEST_USER_ID,
                    "email": "test@example.com",
                    "exp": int(time.time()) + 3600,
                    "iat": old_iat,
                },
                separators=(",", ":"),
            ).encode()
        )
        sig = b64url(hmac.new(TEST_JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
        token = f"{header}.{body}.{sig}"

        # password_changed timestamp is AFTER iat
        pw_changed_ts = str(int(time.time()) - 60)

        async def redis_get_side_effect(key: str) -> str | None:
            if "password_changed:" in key:
                return pw_changed_ts
            return None  # jti not revoked

        mock_redis.get = AsyncMock(side_effect=redis_get_side_effect)
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())

        response = test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_valid_when_no_password_change(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
        mock_cur: AsyncMock,
    ) -> None:
        """Token should work when no password change recorded."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())

        response = test_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {make_test_jwt()}"},
        )
        assert response.status_code == 200


class TestTwoFactorRecovery:
    """Tests for POST /api/auth/2fa/recovery."""

    def test_recovery_invalid_challenge(self, test_client: TestClient) -> None:
        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": "bad.token.here", "code": "some-recovery-code"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Login with 2FA enabled (lines 182-187)
# ---------------------------------------------------------------------------


class TestLoginWith2FA:
    """Tests for the 2FA challenge flow triggered during login."""

    def test_login_with_totp_enabled_returns_challenge(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Login with totp_enabled=True should return challenge token, not access token."""
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = True
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.setex = AsyncMock()

        response = test_client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": "testpassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("requires_2fa") is True
        assert "challenge_token" in data
        assert "message" in data
        # Verify challenge JTI was stored in Redis
        mock_redis.setex.assert_called()
        call_args = mock_redis.setex.call_args
        assert "2fa_challenge:" in call_args[0][0]

    def test_login_without_totp_returns_access_token(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Login without totp_enabled should return access token directly."""
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = False
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.get = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": "testpassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "requires_2fa" not in data


# ---------------------------------------------------------------------------
# 2FA Setup — encryption not configured (line 342)
# ---------------------------------------------------------------------------


class TestTwoFactorSetupEncryption:
    """Additional tests for POST /api/auth/2fa/setup."""

    def test_setup_returns_503_when_encryption_not_configured(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Setup should fail with 503 if encryption_master_key is not set."""
        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=None)
        try:
            response = test_client.post("/api/auth/2fa/setup", headers=auth_headers)
        finally:
            auth_router._config = original_config
        assert response.status_code == 503
        assert "Encryption" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 2FA Confirm (lines 420-430)
# ---------------------------------------------------------------------------


class TestTwoFactorConfirm:
    """Tests for POST /api/auth/2fa/confirm."""

    def test_confirm_happy_path_enables_totp(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Valid TOTP code confirms setup and enables totp_enabled=TRUE."""
        secret, encrypted_secret = _make_encrypted_totp_secret()
        mock_cur.fetchone = AsyncMock(return_value={"totp_secret": encrypted_secret})
        mock_redis.get = AsyncMock(return_value=None)

        valid_code = pyotp.TOTP(secret).now()

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/confirm",
                headers=auth_headers,
                json={"code": valid_code},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 200
        assert "enabled" in response.json()["message"].lower()

    def test_confirm_invalid_code_returns_400(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Invalid TOTP code should return 400."""
        _secret, encrypted_secret = _make_encrypted_totp_secret()
        mock_cur.fetchone = AsyncMock(return_value={"totp_secret": encrypted_secret})
        mock_redis.get = AsyncMock(return_value=None)

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/confirm",
                headers=auth_headers,
                json={"code": "000000"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 400
        assert "Invalid TOTP" in response.json()["detail"]

    def test_confirm_no_setup_returns_400(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Confirm without prior setup (no totp_secret) should return 400."""
        mock_cur.fetchone = AsyncMock(return_value={"totp_secret": None})
        mock_redis.get = AsyncMock(return_value=None)

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/confirm",
                headers=auth_headers,
                json={"code": "123456"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 400
        assert "2FA not set up" in response.json()["detail"]

    def test_confirm_no_row_returns_400(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """No DB row at all should also return 400."""
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/confirm",
                headers=auth_headers,
                json={"code": "123456"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 400

    def test_confirm_no_encryption_returns_503(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Confirm without encryption key should return 503."""
        mock_cur.fetchone = AsyncMock(return_value={"totp_secret": "some_encrypted_secret"})
        mock_redis.get = AsyncMock(return_value=None)

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=None)
        try:
            response = test_client.post(
                "/api/auth/2fa/confirm",
                headers=auth_headers,
                json={"code": "123456"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 503


# ---------------------------------------------------------------------------
# 2FA Verify — TOTP login verification (lines 433-499)
# ---------------------------------------------------------------------------


class TestTwoFactorVerifyFull:
    """Additional tests for POST /api/auth/2fa/verify."""

    def test_verify_happy_path_returns_access_token(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Valid challenge token and valid TOTP code should return access token."""
        secret, encrypted_secret = _make_encrypted_totp_secret()
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_redis.delete = AsyncMock()
        mock_cur.fetchone = AsyncMock(
            return_value={
                "totp_secret": encrypted_secret,
                "totp_failed_attempts": 0,
                "totp_locked_until": None,
            }
        )

        valid_code = pyotp.TOTP(secret).now()

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/verify",
                json={"challenge_token": challenge_token, "code": valid_code},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_verify_invalid_totp_code_returns_401_and_increments_attempts(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Invalid TOTP code should return 401 and increment failed attempts."""
        _secret, encrypted_secret = _make_encrypted_totp_secret()
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_cur.fetchone = AsyncMock(
            return_value={
                "totp_secret": encrypted_secret,
                "totp_failed_attempts": 0,
                "totp_locked_until": None,
            }
        )

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/verify",
                json={"challenge_token": challenge_token, "code": "000000"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 401
        assert "Invalid TOTP" in response.json()["detail"]
        # DB update should have been called to increment attempts
        mock_cur.execute.assert_called()

    def test_verify_account_locked_returns_429(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Account locked due to too many failed attempts should return 429."""
        from datetime import UTC, datetime, timedelta

        _secret, encrypted_secret = _make_encrypted_totp_secret()
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        # locked_until is in the future
        locked_until = datetime.now(UTC) + timedelta(minutes=10)
        mock_cur.fetchone = AsyncMock(
            return_value={
                "totp_secret": encrypted_secret,
                "totp_failed_attempts": 5,
                "totp_locked_until": locked_until,
            }
        )

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/verify",
                json={"challenge_token": challenge_token, "code": "123456"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 429
        assert "locked" in response.json()["detail"].lower()

    def test_verify_challenge_expired_returns_401(
        self,
        test_client: TestClient,
        mock_redis: AsyncMock,
    ) -> None:
        """Missing challenge token in Redis should return 401."""
        challenge_token = _make_challenge_token()
        # Redis returns None — challenge expired or not found
        mock_redis.get = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/2fa/verify",
            json={"challenge_token": challenge_token, "code": "123456"},
        )
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower() or "used" in response.json()["detail"].lower()

    def test_verify_five_failures_triggers_lockout(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """5th failed attempt should trigger 15-minute lockout via SQL update."""
        _secret, encrypted_secret = _make_encrypted_totp_secret()
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_cur.fetchone = AsyncMock(
            return_value={
                "totp_secret": encrypted_secret,
                "totp_failed_attempts": 4,  # This is the 5th attempt
                "totp_locked_until": None,
            }
        )

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/verify",
                json={"challenge_token": challenge_token, "code": "000000"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 401
        # The SQL executed should include the lockout interval
        executed_sqls = [str(call) for call in mock_cur.execute.call_args_list]
        assert any("15 minutes" in sql for sql in executed_sqls)

    def test_verify_wrong_token_type_returns_401(
        self,
        test_client: TestClient,
    ) -> None:
        """Challenge token with wrong type claim should return 401."""
        # Use a regular access token (not a 2fa_challenge type)
        regular_token = make_test_jwt()
        response = test_client.post(
            "/api/auth/2fa/verify",
            json={"challenge_token": regular_token, "code": "123456"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2FA Recovery (lines 521-579)
# ---------------------------------------------------------------------------


class TestTwoFactorRecoveryFull:
    """Additional tests for POST /api/auth/2fa/recovery."""

    def _make_recovery_setup(self) -> tuple[list[str], list[str]]:
        """Generate recovery codes and return (plaintext_codes, hashed_codes)."""
        plaintext_codes, hashed_codes = generate_recovery_codes()
        return plaintext_codes, hashed_codes

    def test_recovery_happy_path_returns_access_token(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Valid challenge + valid recovery code should return access token and remove used code."""
        plaintext_codes, hashed_codes = self._make_recovery_setup()
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_redis.delete = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"totp_recovery_codes": json.dumps(hashed_codes)})

        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": challenge_token, "code": plaintext_codes[0]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_recovery_invalid_code_returns_401(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Invalid recovery code should return 401."""
        _plaintext_codes, hashed_codes = self._make_recovery_setup()
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_cur.fetchone = AsyncMock(return_value={"totp_recovery_codes": json.dumps(hashed_codes)})

        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": challenge_token, "code": "invalid-recovery-code-xyz"},
        )
        assert response.status_code == 401
        assert "Invalid recovery code" in response.json()["detail"]

    def test_recovery_last_code_includes_warning(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Using the last recovery code should include a warning in the response."""
        # Only one recovery code remaining
        plaintext_codes, _ = self._make_recovery_setup()
        last_code = plaintext_codes[0]
        last_hashed = [hash_recovery_code(last_code)]
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_redis.delete = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value={"totp_recovery_codes": json.dumps(last_hashed)})

        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": challenge_token, "code": last_code},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "warning" in data
        assert "last recovery code" in data["warning"].lower()

    def test_recovery_no_codes_available_returns_401(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """No recovery codes stored should return 401."""
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_cur.fetchone = AsyncMock(return_value={"totp_recovery_codes": None})

        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": challenge_token, "code": "some-code"},
        )
        assert response.status_code == 401

    def test_recovery_no_user_row_returns_401(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """No user row should return 401."""
        challenge_token = _make_challenge_token()

        mock_redis.get = AsyncMock(return_value=TEST_USER_ID)
        mock_cur.fetchone = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": challenge_token, "code": "some-code"},
        )
        assert response.status_code == 401

    def test_recovery_wrong_token_type_returns_401(
        self,
        test_client: TestClient,
    ) -> None:
        """Regular access token (not 2fa_challenge type) should return 401."""
        regular_token = make_test_jwt()
        response = test_client.post(
            "/api/auth/2fa/recovery",
            json={"challenge_token": regular_token, "code": "some-recovery-code"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2FA Disable (lines 588-634)
# ---------------------------------------------------------------------------


class TestTwoFactorDisableFull:
    """Additional tests for POST /api/auth/2fa/disable."""

    def test_disable_happy_path(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Valid TOTP code + correct password should disable 2FA."""
        secret, encrypted_secret = _make_encrypted_totp_secret()
        # Build user row with hashed password matching "testpassword"
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = True
        user_row["totp_secret"] = encrypted_secret
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.get = AsyncMock(return_value=None)

        valid_code = pyotp.TOTP(secret).now()

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/disable",
                headers=auth_headers,
                json={"code": valid_code, "password": "testpassword"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 200
        assert "disabled" in response.json()["message"].lower()

    def test_disable_wrong_password_returns_401(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Wrong password should return 401."""
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = True
        user_row["totp_secret"] = "some-encrypted-secret"
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.get = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/2fa/disable",
            headers=auth_headers,
            json={"code": "123456", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "Incorrect password" in response.json()["detail"]

    def test_disable_wrong_totp_code_returns_400(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Wrong TOTP code should return 400."""
        _secret, encrypted_secret = _make_encrypted_totp_secret()
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = True
        user_row["totp_secret"] = encrypted_secret
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.get = AsyncMock(return_value=None)

        original_config = auth_router._config
        auth_router._config = replace(original_config, encryption_master_key=_TEST_MASTER_KEY)
        try:
            response = test_client.post(
                "/api/auth/2fa/disable",
                headers=auth_headers,
                json={"code": "000000", "password": "testpassword"},
            )
        finally:
            auth_router._config = original_config

        assert response.status_code == 400
        assert "Invalid TOTP" in response.json()["detail"]

    def test_disable_totp_not_enabled_returns_400(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Trying to disable 2FA when it's not enabled should return 400."""
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = False
        user_row["totp_secret"] = None
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.get = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/2fa/disable",
            headers=auth_headers,
            json={"code": "123456", "password": "testpassword"},
        )
        assert response.status_code == 400
        assert "not enabled" in response.json()["detail"].lower()

    def test_disable_user_not_found_returns_404(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """If user not found in DB, should return 404."""
        mock_cur.fetchone = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/2fa/disable",
            headers=auth_headers,
            json={"code": "123456", "password": "testpassword"},
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("totp_enabled,totp_secret", [(True, None), (False, "some-secret")])
    def test_disable_inconsistent_state_returns_400(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
        totp_enabled: bool,
        totp_secret: str | None,
    ) -> None:
        """Inconsistent state (enabled but no secret, or secret but not enabled) returns 400."""
        user_row = make_sample_user_row()
        user_row["totp_enabled"] = totp_enabled
        user_row["totp_secret"] = totp_secret
        mock_cur.fetchone = AsyncMock(return_value=user_row)
        mock_redis.get = AsyncMock(return_value=None)

        response = test_client.post(
            "/api/auth/2fa/disable",
            headers=auth_headers,
            json={"code": "123456", "password": "testpassword"},
        )
        assert response.status_code == 400
