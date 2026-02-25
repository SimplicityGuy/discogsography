"""Shared JWT authentication utilities."""

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any


def b64url_encode(data: bytes) -> str:
    """Base64url encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(data: str) -> bytes:
    """Base64url decode a string, adding padding as needed."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def decode_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and verify a HS256 JWT. Raises ValueError on failure."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    expected_sig = b64url_encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid token signature")
    payload: dict[str, Any] = json.loads(b64url_decode(body_b64))
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(int(exp), UTC) < datetime.now(UTC):
        raise ValueError("Token has expired")
    return payload


def encrypt_oauth_token(token: str, key: str) -> str:
    """Encrypt an OAuth token using Fernet symmetric encryption."""
    from cryptography.fernet import Fernet

    f = Fernet(key.encode("ascii"))
    return f.encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_oauth_token(token: str, key: str | None) -> str:
    """Decrypt an OAuth token, falling back to plaintext for migration."""
    if not key:
        return token
    from cryptography.fernet import Fernet, InvalidToken

    try:
        f = Fernet(key.encode("ascii"))
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        return token  # fallback to plaintext (migration path)
