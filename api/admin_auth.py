"""Admin authentication utilities.

Handles admin-specific JWT creation and password verification.
Admin tokens include "type": "admin" claim and use "admin:" jti prefix
to maintain complete isolation from Discogs user tokens.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import secrets

from api.auth import _verify_password, b64url_encode


def create_admin_token(
    admin_id: str,
    email: str,
    jwt_secret: str,
    expire_minutes: int = 30,
) -> tuple[str, int]:
    """Create a HS256 JWT for an admin user.

    Returns (token, expires_in_seconds).
    """
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload: dict[str, object] = {
        "sub": admin_id,
        "email": email,
        "type": "admin",
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
        "jti": f"admin:{secrets.token_hex(16)}",
    }

    header = b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = b64url_encode(hmac.new(jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}", expire_minutes * 60


def verify_admin_password(plain_password: str, hashed_password: str) -> bool:
    """Verify an admin password against its PBKDF2-SHA256 hash."""
    return _verify_password(plain_password, hashed_password)
