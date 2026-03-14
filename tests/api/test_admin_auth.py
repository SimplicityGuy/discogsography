"""Tests for admin authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

from api.admin_auth import create_admin_token, verify_admin_password
from api.auth import _hash_password


TEST_JWT_SECRET = "test-admin-secret-key-for-testing"
TEST_ADMIN_ID = "00000000-0000-0000-0000-000000000099"
TEST_ADMIN_EMAIL = "admin@test.com"


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification (for test assertions)."""
    _, body, _ = token.split(".")
    padding = 4 - len(body) % 4
    if padding != 4:
        body += "=" * padding
    return json.loads(base64.urlsafe_b64decode(body))


def _make_admin_jwt(
    admin_id: str = TEST_ADMIN_ID,
    email: str = TEST_ADMIN_EMAIL,
    exp: int = 9_999_999_999,
    secret: str = TEST_JWT_SECRET,
    token_type: str = "admin",  # noqa: S107
) -> str:
    """Create an admin JWT for testing."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(
        json.dumps(
            {
                "sub": admin_id,
                "email": email,
                "exp": exp,
                "type": token_type,
                "jti": f"admin:{secrets.token_hex(16)}",
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{body}".encode("ascii")
    sig = b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


class TestCreateAdminToken:
    def test_returns_token_and_ttl(self) -> None:
        token, expires_in = create_admin_token(TEST_ADMIN_ID, TEST_ADMIN_EMAIL, TEST_JWT_SECRET)
        assert isinstance(token, str)
        assert token.count(".") == 2
        assert isinstance(expires_in, int)
        assert expires_in > 0

    def test_token_has_admin_type_claim(self) -> None:
        token, _ = create_admin_token(TEST_ADMIN_ID, TEST_ADMIN_EMAIL, TEST_JWT_SECRET)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "admin"
        assert payload["sub"] == TEST_ADMIN_ID
        assert payload["email"] == TEST_ADMIN_EMAIL

    def test_token_has_jti_with_admin_prefix(self) -> None:
        token, _ = create_admin_token(TEST_ADMIN_ID, TEST_ADMIN_EMAIL, TEST_JWT_SECRET)
        payload = _decode_jwt_payload(token)
        assert payload["jti"].startswith("admin:")


class TestVerifyAdminPassword:
    def test_correct_password(self) -> None:
        hashed = _hash_password("securepassword123")
        assert verify_admin_password("securepassword123", hashed) is True

    def test_wrong_password(self) -> None:
        hashed = _hash_password("securepassword123")
        assert verify_admin_password("wrongpassword", hashed) is False

    def test_empty_password(self) -> None:
        hashed = _hash_password("securepassword123")
        assert verify_admin_password("", hashed) is False
