"""Shared JWT authentication utilities."""

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes as _hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF as _HKDF
import pyotp


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


def _hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 with a random salt.

    Returns a string in format: <hex_salt>:<hex_key>
    """
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + key.hex()


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its PBKDF2-SHA256 hash."""
    try:
        salt_hex, key_hex = hashed_password.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        actual_key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(actual_key, expected_key)
    except (ValueError, TypeError):
        return False


# Pre-computed dummy hash for timing attack protection in login
_DUMMY_HASH: str = _hash_password("__dummy_password_for_timing__")


def encrypt_oauth_token(token: str, key: str) -> str:
    """Encrypt an OAuth token using Fernet symmetric encryption."""
    f = Fernet(key.encode("ascii"))
    return f.encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_oauth_token(token: str, key: str | None) -> str:
    """Decrypt an OAuth token.

    If no key is configured (no-encryption mode), returns the token as-is.
    If a key is provided but decryption fails, raises ValueError — silent
    fallback would return garbage or expose plaintext to callers.
    """
    if not key or not token:
        return token

    try:
        f = Fernet(key.encode("ascii"))
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Failed to decrypt OAuth token: {exc}") from exc


def derive_encryption_key(master_key: str, info: bytes) -> str:
    """Derive a Fernet-compatible key from a master key using HKDF-SHA256."""
    master_bytes = base64.urlsafe_b64decode(master_key)
    hkdf = _HKDF(algorithm=_hashes.SHA256(), length=32, salt=None, info=info)
    derived = hkdf.derive(master_bytes)
    return base64.urlsafe_b64encode(derived).decode("ascii")


def get_oauth_encryption_key(master_key: str | None) -> str | None:
    """Derive the OAuth token encryption key from the master key."""
    if not master_key:
        return None
    return derive_encryption_key(master_key, b"oauth-tokens")


def get_totp_encryption_key(master_key: str | None) -> str | None:
    """Derive the TOTP secret encryption key from the master key."""
    if not master_key:
        return None
    return derive_encryption_key(master_key, b"totp-secrets")


def generate_totp_secret() -> str:
    """Generate a random TOTP secret in base32 format."""
    return pyotp.random_base32()


def encrypt_totp_secret(secret: str, key: str) -> str:
    """Encrypt a TOTP secret using Fernet symmetric encryption."""
    f = Fernet(key.encode("ascii"))
    return f.encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_totp_secret(encrypted: str, key: str) -> str:
    """Decrypt a TOTP secret."""
    try:
        f = Fernet(key.encode("ascii"))
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Failed to decrypt TOTP secret: {exc}") from exc


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret. Accepts ±1 time window."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_recovery_codes() -> tuple[list[str], list[str]]:
    """Generate 8 recovery codes. Returns (plaintext_codes, sha256_hashes)."""
    plaintext = [secrets.token_urlsafe(12) for _ in range(8)]
    hashes = [hash_recovery_code(code) for code in plaintext]
    return plaintext, hashes


def hash_recovery_code(code: str) -> str:
    """SHA-256 hash a recovery code."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create_challenge_token(user_id: str, email: str, secret_key: str) -> str:
    """Create a short-lived 2FA challenge JWT (5 min TTL).

    This token proves the password was correct but is NOT a full access token.
    """
    expire = datetime.now(UTC) + timedelta(minutes=5)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "type": "2fa_challenge",
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
        "jti": secrets.token_hex(16),
    }
    header = b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = b64url_encode(hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"
