"""Tests for api/auth.py — shared JWT and OAuth encryption utilities."""

import base64
import os


class TestB64UrlEncode:
    """Tests for b64url_encode."""

    def test_encode_no_padding(self) -> None:
        from api.auth import b64url_encode

        result = b64url_encode(b"test")
        assert "=" not in result

    def test_encode_urlsafe_chars(self) -> None:
        from api.auth import b64url_encode

        result = b64url_encode(bytes(range(256)))
        assert "+" not in result
        assert "/" not in result

    def test_encode_decode_roundtrip(self) -> None:
        from api.auth import b64url_decode, b64url_encode

        data = b"hello world \x00\xff"
        assert b64url_decode(b64url_encode(data)) == data


class TestEncryptOauthToken:
    """Tests for encrypt_oauth_token."""

    def test_encrypt_returns_string(self) -> None:
        from cryptography.fernet import Fernet

        from api.auth import encrypt_oauth_token

        key = Fernet.generate_key().decode("ascii")
        result = encrypt_oauth_token("my-token", key)
        assert isinstance(result, str)
        assert result != "my-token"

    def test_encrypt_roundtrip(self) -> None:
        from cryptography.fernet import Fernet

        from api.auth import decrypt_oauth_token, encrypt_oauth_token

        key = Fernet.generate_key().decode("ascii")
        encrypted = encrypt_oauth_token("secret-token", key)
        assert decrypt_oauth_token(encrypted, key) == "secret-token"

    def test_encrypt_different_each_time(self) -> None:
        """Fernet uses a random IV so each encryption is unique."""
        from cryptography.fernet import Fernet

        from api.auth import encrypt_oauth_token

        key = Fernet.generate_key().decode("ascii")
        assert encrypt_oauth_token("tok", key) != encrypt_oauth_token("tok", key)


class TestDecryptOauthToken:
    """Tests for decrypt_oauth_token."""

    def test_no_key_returns_plaintext(self) -> None:
        from api.auth import decrypt_oauth_token

        assert decrypt_oauth_token("plaintext-token", None) == "plaintext-token"

    def test_decrypt_valid_token(self) -> None:
        from cryptography.fernet import Fernet

        from api.auth import decrypt_oauth_token, encrypt_oauth_token

        key = Fernet.generate_key().decode("ascii")
        encrypted = encrypt_oauth_token("my-secret", key)
        assert decrypt_oauth_token(encrypted, key) == "my-secret"

    def test_invalid_token_raises(self) -> None:
        """InvalidToken exception → raises ValueError when a key is provided."""
        from cryptography.fernet import Fernet
        import pytest

        from api.auth import decrypt_oauth_token

        key = Fernet.generate_key().decode("ascii")
        with pytest.raises(ValueError, match="Failed to decrypt OAuth token"):
            decrypt_oauth_token("not-encrypted", key)

    def test_wrong_key_raises(self) -> None:
        """Wrong key → raises ValueError rather than silently returning garbage."""
        from cryptography.fernet import Fernet
        import pytest

        from api.auth import decrypt_oauth_token, encrypt_oauth_token

        key1 = Fernet.generate_key().decode("ascii")
        key2 = Fernet.generate_key().decode("ascii")
        encrypted = encrypt_oauth_token("secret", key1)
        with pytest.raises(ValueError, match="Failed to decrypt OAuth token"):
            decrypt_oauth_token(encrypted, key2)


class TestHkdfKeyDerivation:
    """Tests for derive_encryption_key, get_oauth_encryption_key, get_totp_encryption_key."""

    def _make_master_key(self) -> str:
        """Generate a random 32-byte master key encoded as urlsafe base64."""
        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

    def test_derive_key_returns_valid_fernet_key(self) -> None:
        """Derived key must be accepted by Fernet without error."""
        from cryptography.fernet import Fernet

        from api.auth import derive_encryption_key

        master_key = self._make_master_key()
        derived = derive_encryption_key(master_key, b"test-purpose")
        # Fernet expects a 32-byte url-safe base64 key (44 chars with padding)
        Fernet(derived.encode("ascii"))  # raises if invalid

    def test_different_purposes_produce_different_keys(self) -> None:
        """Same master key with different info strings must produce different keys."""
        from api.auth import derive_encryption_key

        master_key = self._make_master_key()
        key_oauth = derive_encryption_key(master_key, b"oauth-tokens")
        key_totp = derive_encryption_key(master_key, b"totp-secrets")
        assert key_oauth != key_totp

    def test_same_inputs_produce_same_key(self) -> None:
        """Key derivation must be deterministic."""
        from api.auth import derive_encryption_key

        master_key = self._make_master_key()
        key_a = derive_encryption_key(master_key, b"oauth-tokens")
        key_b = derive_encryption_key(master_key, b"oauth-tokens")
        assert key_a == key_b

    def test_get_oauth_encryption_key_none_master(self) -> None:
        """get_oauth_encryption_key returns None when master key is None."""
        from api.auth import get_oauth_encryption_key

        assert get_oauth_encryption_key(None) is None

    def test_get_oauth_encryption_key_with_master(self) -> None:
        """get_oauth_encryption_key returns a non-None string when master key is provided."""
        from api.auth import get_oauth_encryption_key

        master_key = self._make_master_key()
        result = get_oauth_encryption_key(master_key)
        assert result is not None
        assert isinstance(result, str)

    def test_get_totp_encryption_key_none_master(self) -> None:
        """get_totp_encryption_key returns None when master key is None."""
        from api.auth import get_totp_encryption_key

        assert get_totp_encryption_key(None) is None

    def test_get_totp_encryption_key_with_master(self) -> None:
        """get_totp_encryption_key returns a non-None string when master key is provided."""
        from api.auth import get_totp_encryption_key

        master_key = self._make_master_key()
        result = get_totp_encryption_key(master_key)
        assert result is not None
        assert isinstance(result, str)

    def test_oauth_and_totp_keys_differ_for_same_master(self) -> None:
        """OAuth and TOTP derived keys must be different for the same master key."""
        from api.auth import get_oauth_encryption_key, get_totp_encryption_key

        master_key = self._make_master_key()
        assert get_oauth_encryption_key(master_key) != get_totp_encryption_key(master_key)


class TestTotpUtilities:
    """Tests for TOTP secret generation, encryption, and verification."""

    def test_generate_totp_secret_returns_base32(self) -> None:
        import re

        from api.auth import generate_totp_secret

        secret = generate_totp_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 16
        assert re.match(r"^[A-Z2-7]+=*$", secret)

    def test_encrypt_decrypt_totp_secret_roundtrip(self) -> None:
        from cryptography.fernet import Fernet

        from api.auth import decrypt_totp_secret, encrypt_totp_secret

        key = Fernet.generate_key().decode("ascii")
        secret = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_totp_secret(secret, key)
        assert encrypted != secret
        assert decrypt_totp_secret(encrypted, key) == secret

    def test_verify_totp_code_valid(self) -> None:
        import pyotp

        from api.auth import verify_totp_code

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp_code(secret, code) is True

    def test_verify_totp_code_invalid(self) -> None:
        import pyotp

        from api.auth import verify_totp_code

        secret = pyotp.random_base32()
        assert verify_totp_code(secret, "000000") is False

    def test_generate_recovery_codes(self) -> None:
        from api.auth import generate_recovery_codes

        plaintext, hashes = generate_recovery_codes()
        assert len(plaintext) == 8
        assert len(hashes) == 8
        assert all(len(h) == 64 for h in hashes)
        assert len(set(plaintext)) == 8

    def test_hash_recovery_code_deterministic(self) -> None:
        from api.auth import hash_recovery_code

        code = "test-recovery-code"
        h1 = hash_recovery_code(code)
        h2 = hash_recovery_code(code)
        assert h1 == h2
        assert len(h1) == 64

    def test_create_challenge_token_format(self) -> None:
        from api.auth import create_challenge_token, decode_token

        token = create_challenge_token("user-123", "test@example.com", "test-secret")
        payload = decode_token(token, "test-secret")
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "2fa_challenge"
        assert "jti" in payload
        assert "exp" in payload
