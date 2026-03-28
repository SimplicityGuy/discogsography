"""Tests for common.oauth — OAuth 1.0a utility functions."""

from common.oauth import _build_oauth_header, _hmac_sha1_signature, _oauth_escape


class TestOAuthEscape:
    def test_escapes_special_characters(self) -> None:
        assert _oauth_escape("hello world") == "hello%20world"

    def test_escapes_ampersand(self) -> None:
        assert _oauth_escape("a&b") == "a%26b"

    def test_empty_string(self) -> None:
        assert _oauth_escape("") == ""

    def test_no_escaping_for_unreserved(self) -> None:
        assert _oauth_escape("abc123") == "abc123"


class TestBuildOAuthHeader:
    def test_formats_header_correctly(self) -> None:
        params = {"oauth_consumer_key": "key123", "oauth_nonce": "abc"}
        result = _build_oauth_header(params)
        assert result.startswith("OAuth ")
        assert 'oauth_consumer_key="key123"' in result
        assert 'oauth_nonce="abc"' in result

    def test_params_are_sorted(self) -> None:
        params = {"z_param": "z", "a_param": "a"}
        result = _build_oauth_header(params)
        # a_param should come before z_param
        assert result.index("a_param") < result.index("z_param")

    def test_values_are_percent_encoded(self) -> None:
        params = {"key": "val with spaces"}
        result = _build_oauth_header(params)
        assert 'key="val%20with%20spaces"' in result


class TestHmacSha1Signature:
    def test_returns_base64_string(self) -> None:
        sig = _hmac_sha1_signature(
            method="GET",
            url="https://api.discogs.com/oauth/request_token",
            oauth_params={"oauth_consumer_key": "key", "oauth_nonce": "nonce"},
            consumer_secret="secret",  # noqa: S106
        )
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_deterministic(self) -> None:
        kwargs = {
            "method": "POST",
            "url": "https://example.com/resource",
            "oauth_params": {"oauth_consumer_key": "k", "oauth_timestamp": "123"},
            "consumer_secret": "cs",
            "token_secret": "ts",
        }
        assert _hmac_sha1_signature(**kwargs) == _hmac_sha1_signature(**kwargs)

    def test_method_case_insensitive(self) -> None:
        kwargs = {
            "url": "https://example.com",
            "oauth_params": {"a": "1"},
            "consumer_secret": "s",
        }
        assert _hmac_sha1_signature(method="get", **kwargs) == _hmac_sha1_signature(method="GET", **kwargs)

    def test_different_secrets_produce_different_signatures(self) -> None:
        common = {
            "method": "GET",
            "url": "https://example.com",
            "oauth_params": {"a": "1"},
        }
        sig1 = _hmac_sha1_signature(**common, consumer_secret="secret1")  # noqa: S106
        sig2 = _hmac_sha1_signature(**common, consumer_secret="secret2")  # noqa: S106
        assert sig1 != sig2

    def test_empty_token_secret(self) -> None:
        sig = _hmac_sha1_signature(
            method="GET",
            url="https://example.com",
            oauth_params={"a": "1"},
            consumer_secret="cs",  # noqa: S106
            token_secret="",
        )
        assert isinstance(sig, str)
