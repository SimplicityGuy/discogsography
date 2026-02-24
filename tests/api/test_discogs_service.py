"""Tests for api/services/discogs.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.discogs import (
    DISCOGS_ACCESS_TOKEN_URL,
    DISCOGS_AUTHORIZE_URL,
    DISCOGS_IDENTITY_URL,
    DISCOGS_REQUEST_TOKEN_URL,
    REDIS_OAUTH_STATE_TTL,
    REDIS_STATE_PREFIX,
    DiscogsOAuthError,
    _build_oauth_header,
    _hmac_sha1_signature,
    _oauth_escape,
    exchange_oauth_verifier,
    fetch_discogs_identity,
    request_oauth_token,
)


class TestOAuthEscape:
    """Tests for _oauth_escape."""

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
        assert "/" not in _oauth_escape("/path/to/resource")

    def test_tilde_unreserved(self) -> None:
        # RFC 3986 unreserved: letters, digits, '-', '.', '_', '~'
        result = _oauth_escape("abc-def_ghi.jkl~mno")
        assert result == "abc-def_ghi.jkl~mno"


class TestBuildOAuthHeader:
    """Tests for _build_oauth_header."""

    def test_header_starts_with_oauth(self) -> None:
        params = {"oauth_consumer_key": "key", "oauth_token": "tok"}
        header = _build_oauth_header(params)
        assert header.startswith("OAuth ")

    def test_params_sorted_alphabetically(self) -> None:
        params = {"z_param": "z", "a_param": "a"}
        header = _build_oauth_header(params)
        assert header.index("a_param") < header.index("z_param")

    def test_values_quoted(self) -> None:
        params = {"key": "value"}
        header = _build_oauth_header(params)
        assert 'key="value"' in header

    def test_values_percent_encoded(self) -> None:
        params = {"key": "hello world"}
        header = _build_oauth_header(params)
        assert "hello%20world" in header

    def test_multiple_params_comma_separated(self) -> None:
        params = {"a": "1", "b": "2"}
        header = _build_oauth_header(params)
        assert ", " in header


class TestHmacSha1Signature:
    """Tests for _hmac_sha1_signature."""

    def test_returns_base64_string(self) -> None:
        sig = _hmac_sha1_signature("GET", "https://example.com", {"k": "v"}, "secret")
        # base64 chars only
        import base64

        base64.b64decode(sig + "==")  # should not raise

    def test_different_methods_produce_different_sigs(self) -> None:
        params = {"oauth_nonce": "abc", "oauth_timestamp": "1234"}
        sig_get = _hmac_sha1_signature("GET", "https://api.discogs.com/token", params, "csecret")
        sig_post = _hmac_sha1_signature("POST", "https://api.discogs.com/token", params, "csecret")
        assert sig_get != sig_post

    def test_different_secrets_produce_different_sigs(self) -> None:
        params = {"k": "v"}
        sig1 = _hmac_sha1_signature("GET", "https://example.com", params, "secret1")
        sig2 = _hmac_sha1_signature("GET", "https://example.com", params, "secret2")
        assert sig1 != sig2

    def test_with_token_secret(self) -> None:
        params = {"k": "v"}
        sig_no_token = _hmac_sha1_signature("GET", "https://example.com", params, "csecret", "")
        sig_with_token = _hmac_sha1_signature("GET", "https://example.com", params, "csecret", "tokensecret")
        assert sig_no_token != sig_with_token


class TestDiscogsOAuthConstants:
    """Tests for module-level constants."""

    def test_request_token_url(self) -> None:
        assert "discogs.com" in DISCOGS_REQUEST_TOKEN_URL
        assert "oauth/request_token" in DISCOGS_REQUEST_TOKEN_URL

    def test_authorize_url(self) -> None:
        assert "discogs.com" in DISCOGS_AUTHORIZE_URL
        assert "oauth/authorize" in DISCOGS_AUTHORIZE_URL

    def test_access_token_url(self) -> None:
        assert "discogs.com" in DISCOGS_ACCESS_TOKEN_URL
        assert "oauth/access_token" in DISCOGS_ACCESS_TOKEN_URL

    def test_identity_url(self) -> None:
        assert "discogs.com" in DISCOGS_IDENTITY_URL
        assert "oauth/identity" in DISCOGS_IDENTITY_URL

    def test_redis_ttl_is_600(self) -> None:
        assert REDIS_OAUTH_STATE_TTL == 600

    def test_redis_state_prefix(self) -> None:
        assert REDIS_STATE_PREFIX == "discogs:oauth:state:"


class TestDiscogsOAuthError:
    """Tests for DiscogsOAuthError."""

    def test_is_exception(self) -> None:
        err = DiscogsOAuthError("something failed")
        assert isinstance(err, Exception)
        assert str(err) == "something failed"


def _make_mock_httpx_client(status_code: int, text: str) -> tuple[MagicMock, MagicMock]:
    """Build a mock httpx.AsyncClient that returns the given response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json = MagicMock(return_value={})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)

    return mock_client, mock_response


class TestRequestOauthToken:
    """Tests for request_oauth_token."""

    @pytest.mark.asyncio
    async def test_success_returns_token_dict(self) -> None:
        response_text = "oauth_token=reqtok&oauth_token_secret=reqsec&oauth_callback_confirmed=true"
        mock_client, _ = _make_mock_httpx_client(200, response_text)

        with patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client):
            result = await request_oauth_token("ckey", "csecret", "TestAgent/1.0")

        assert result["oauth_token"] == "reqtok"
        assert result["oauth_token_secret"] == "reqsec"

    @pytest.mark.asyncio
    async def test_non_200_raises_error(self) -> None:
        mock_client, _ = _make_mock_httpx_client(401, "Unauthorized")

        with patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client), pytest.raises(DiscogsOAuthError, match="401"):
            await request_oauth_token("ckey", "csecret", "TestAgent/1.0")

    @pytest.mark.asyncio
    async def test_missing_token_in_response_raises_error(self) -> None:
        # Response is 200 but missing oauth_token
        mock_client, _ = _make_mock_httpx_client(200, "some=unexpected&response=here")

        with (
            patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(DiscogsOAuthError, match="Invalid response"),
        ):
            await request_oauth_token("ckey", "csecret", "TestAgent/1.0")


class TestExchangeOauthVerifier:
    """Tests for exchange_oauth_verifier."""

    @pytest.mark.asyncio
    async def test_success_returns_access_tokens(self) -> None:
        response_text = "oauth_token=acctok&oauth_token_secret=accsec"
        mock_client, _ = _make_mock_httpx_client(200, response_text)

        with patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client):
            result = await exchange_oauth_verifier(
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                oauth_token="reqtok",  # noqa: S106
                oauth_token_secret="reqsec",  # noqa: S106
                oauth_verifier="verif",
                user_agent="TestAgent/1.0",
            )

        assert result["oauth_token"] == "acctok"
        assert result["oauth_token_secret"] == "accsec"

    @pytest.mark.asyncio
    async def test_non_200_raises_error(self) -> None:
        mock_client, _ = _make_mock_httpx_client(401, "Bad verifier")

        with patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client), pytest.raises(DiscogsOAuthError, match="401"):
            await exchange_oauth_verifier(
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                oauth_token="reqtok",  # noqa: S106
                oauth_token_secret="reqsec",  # noqa: S106
                oauth_verifier="badverif",
                user_agent="TestAgent/1.0",
            )

    @pytest.mark.asyncio
    async def test_missing_tokens_in_response_raises_error(self) -> None:
        mock_client, _ = _make_mock_httpx_client(200, "invalid_key=value")

        with (
            patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(DiscogsOAuthError, match="Invalid response"),
        ):
            await exchange_oauth_verifier(
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                oauth_token="reqtok",  # noqa: S106
                oauth_token_secret="reqsec",  # noqa: S106
                oauth_verifier="verif",
                user_agent="TestAgent/1.0",
            )


class TestFetchDiscogsIdentity:
    """Tests for fetch_discogs_identity."""

    @pytest.mark.asyncio
    async def test_success_returns_identity_dict(self) -> None:
        identity_data = {"id": 12345, "username": "discogs_user", "resource_url": "https://api.discogs.com/users/discogs_user"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_response.json = MagicMock(return_value=identity_data)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_discogs_identity(
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                access_token_secret="accsec",  # noqa: S106
                user_agent="TestAgent/1.0",
            )

        assert result["username"] == "discogs_user"
        assert result["id"] == 12345

    @pytest.mark.asyncio
    async def test_non_200_raises_error(self) -> None:
        mock_client, _ = _make_mock_httpx_client(403, "Forbidden")

        with patch("api.services.discogs.httpx.AsyncClient", return_value=mock_client), pytest.raises(DiscogsOAuthError, match="403"):
            await fetch_discogs_identity(
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                access_token_secret="accsec",  # noqa: S106
                user_agent="TestAgent/1.0",
            )
