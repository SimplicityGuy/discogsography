"""Tests for the collector syncer module."""

from collector.syncer import (
    PAGE_SIZE,
    SYNC_DELAY_SECONDS,
    _build_oauth_header,
    _oauth_escape,
)


class TestOAuthEscape:
    """Tests for OAuth percent-encoding."""

    def test_alphanumeric_unchanged(self) -> None:
        assert _oauth_escape("abc123") == "abc123"

    def test_space_encoded(self) -> None:
        assert _oauth_escape("hello world") == "hello%20world"

    def test_special_chars_encoded(self) -> None:
        result = _oauth_escape("foo&bar=baz")
        assert "&" not in result
        assert "=" not in result

    def test_empty_string(self) -> None:
        assert _oauth_escape("") == ""

    def test_slash_encoded(self) -> None:
        # safe="" means slash must be encoded
        assert "/" not in _oauth_escape("/path/to/resource")


class TestBuildOAuthHeader:
    """Tests for OAuth Authorization header construction."""

    def test_header_starts_with_oauth(self) -> None:
        params = {"oauth_consumer_key": "key", "oauth_token": "tok"}
        header = _build_oauth_header(params)
        assert header.startswith("OAuth ")

    def test_params_sorted(self) -> None:
        params = {"z_param": "z", "a_param": "a"}
        header = _build_oauth_header(params)
        # a_param should appear before z_param
        assert header.index("a_param") < header.index("z_param")

    def test_values_quoted(self) -> None:
        params = {"key": "value"}
        header = _build_oauth_header(params)
        assert 'key="value"' in header

    def test_multiple_params(self) -> None:
        params = {
            "oauth_consumer_key": "consumer",
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_version": "1.0",
        }
        header = _build_oauth_header(params)
        assert "oauth_consumer_key" in header
        assert "oauth_signature_method" in header
        assert "oauth_version" in header


class TestSyncerConstants:
    """Tests for syncer module constants."""

    def test_page_size_is_100(self) -> None:
        assert PAGE_SIZE == 100

    def test_sync_delay_is_half_second(self) -> None:
        assert SYNC_DELAY_SECONDS == 0.5
