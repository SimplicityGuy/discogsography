"""Tests for api/auth.py — shared JWT and OAuth encryption utilities."""


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

    def test_invalid_token_falls_back_to_plaintext(self) -> None:
        """InvalidToken exception → fallback to returning the token as-is (migration)."""
        from cryptography.fernet import Fernet

        from api.auth import decrypt_oauth_token

        key = Fernet.generate_key().decode("ascii")
        # "not-encrypted" is not valid Fernet ciphertext
        result = decrypt_oauth_token("not-encrypted", key)
        assert result == "not-encrypted"

    def test_wrong_key_falls_back_to_plaintext(self) -> None:
        from cryptography.fernet import Fernet

        from api.auth import decrypt_oauth_token, encrypt_oauth_token

        key1 = Fernet.generate_key().decode("ascii")
        key2 = Fernet.generate_key().decode("ascii")
        encrypted = encrypt_oauth_token("secret", key1)
        # Wrong key → fallback to plaintext migration path
        result = decrypt_oauth_token(encrypted, key2)
        assert result == encrypted  # returns ciphertext unchanged
