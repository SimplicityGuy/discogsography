"""Tests for the curator syncer module."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from curator.syncer import (
    PAGE_SIZE,
    SYNC_DELAY_SECONDS,
    _auth_header,
    _build_oauth_header,
    _hmac_sha1,
    _oauth_escape,
    run_full_sync,
    sync_collection,
    sync_wantlist,
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


class TestHmacSha1:
    """Tests for _hmac_sha1."""

    def test_returns_base64_string(self) -> None:
        import base64

        sig = _hmac_sha1("GET", "https://api.discogs.com/token", {"k": "v"}, "csecret", "tokensec")
        # Should be valid base64
        base64.b64decode(sig + "==")

    def test_different_methods_give_different_sigs(self) -> None:
        params = {"oauth_nonce": "abc", "oauth_timestamp": "1234"}
        sig_get = _hmac_sha1("GET", "https://api.discogs.com/token", params, "csecret", "tsecret")
        sig_post = _hmac_sha1("POST", "https://api.discogs.com/token", params, "csecret", "tsecret")
        assert sig_get != sig_post

    def test_different_secrets_give_different_sigs(self) -> None:
        params = {"k": "v"}
        sig1 = _hmac_sha1("GET", "https://example.com", params, "secret1", "")
        sig2 = _hmac_sha1("GET", "https://example.com", params, "secret2", "")
        assert sig1 != sig2

    def test_empty_token_secret(self) -> None:
        # Should work without raising
        sig = _hmac_sha1("GET", "https://example.com", {"k": "v"}, "csecret", "")
        assert isinstance(sig, str)
        assert len(sig) > 0


class TestAuthHeader:
    """Tests for _auth_header."""

    def test_returns_oauth_header_string(self) -> None:
        header = _auth_header(
            method="GET",
            url="https://api.discogs.com/users/testuser/collection/folders/0/releases",
            consumer_key="ckey",
            consumer_secret="csecret",  # noqa: S106
            access_token="acctok",  # noqa: S106
            token_secret="accsec",  # noqa: S106
        )
        assert header.startswith("OAuth ")
        assert "oauth_consumer_key" in header
        assert "oauth_signature" in header
        assert "oauth_timestamp" in header
        assert "oauth_nonce" in header

    def test_different_calls_produce_different_nonces(self) -> None:
        kwargs = {
            "method": "GET",
            "url": "https://api.discogs.com/test",
            "consumer_key": "ckey",
            "consumer_secret": "csecret",
            "access_token": "acctok",
            "token_secret": "accsec",
        }
        h1 = _auth_header(**kwargs)
        h2 = _auth_header(**kwargs)
        # Nonces should differ (random)
        nonce1 = [p for p in h1.split(", ") if "oauth_nonce" in p]
        nonce2 = [p for p in h2.split(", ") if "oauth_nonce" in p]
        assert nonce1 != nonce2


def _make_mock_pg_pool(cur: AsyncMock) -> MagicMock:
    """Build a mock AsyncPostgreSQLPool."""
    pool = MagicMock()
    cur_ctx = AsyncMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)

    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=cur_ctx)

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn_ctx)
    return pool


def _make_mock_neo4j() -> MagicMock:
    """Build a mock AsyncResilientNeo4jDriver."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock()

    async def _factory(*_args: Any, **_kwargs: Any) -> Any:
        return mock_session

    driver.session = MagicMock(side_effect=_factory)
    return driver


def _make_collection_response(releases: list[dict[str, Any]], total_pages: int = 1) -> MagicMock:
    """Build a mock httpx response for collection API."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"releases": releases, "pagination": {"pages": total_pages}})
    return resp


def _make_wantlist_response(wants: list[dict[str, Any]], total_pages: int = 1) -> MagicMock:
    """Build a mock httpx response for wantlist API."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"wants": wants, "pagination": {"pages": total_pages}})
    return resp


class TestSyncCollection:
    """Tests for sync_collection."""

    @pytest.mark.asyncio
    async def test_empty_collection_returns_zero(self) -> None:
        cur = AsyncMock()
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json = MagicMock(return_value={"releases": [], "pagination": {"pages": 1}})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=empty_resp)

        with patch("curator.syncer.httpx.AsyncClient", return_value=mock_client):
            total = await sync_collection(
                user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
                discogs_username="testuser",
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                token_secret="tsecret",  # noqa: S106
                user_agent="TestAgent/1.0",
                pg_pool=pool,
                neo4j_driver=driver,
            )

        assert total == 0

    @pytest.mark.asyncio
    async def test_single_page_collection_synced(self) -> None:
        cur = AsyncMock()
        cur.execute = AsyncMock()
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        releases = [
            {
                "basic_information": {
                    "id": 12345,
                    "title": "Test Album",
                    "year": 2020,
                    "artists": [{"name": "Test Artist"}],
                    "labels": [{"name": "Test Label"}],
                    "formats": [{"name": "Vinyl"}],
                },
                "instance_id": 111,
                "folder_id": 1,
                "rating": 4,
                "date_added": "2023-01-01T00:00:00-08:00",
            }
        ]
        resp = _make_collection_response(releases, total_pages=1)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with (
            patch("curator.syncer.httpx.AsyncClient", return_value=mock_client),
            patch("curator.syncer.asyncio.sleep", new=AsyncMock()),
        ):
            total = await sync_collection(
                user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
                discogs_username="testuser",
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                token_secret="tsecret",  # noqa: S106
                user_agent="TestAgent/1.0",
                pg_pool=pool,
                neo4j_driver=driver,
            )

        assert total == 1

    @pytest.mark.asyncio
    async def test_api_error_breaks_loop(self) -> None:
        cur = AsyncMock()
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.json = MagicMock(return_value={})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=error_resp)

        with patch("curator.syncer.httpx.AsyncClient", return_value=mock_client):
            total = await sync_collection(
                user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
                discogs_username="testuser",
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                token_secret="tsecret",  # noqa: S106
                user_agent="TestAgent/1.0",
                pg_pool=pool,
                neo4j_driver=driver,
            )

        assert total == 0


class TestSyncWantlist:
    """Tests for sync_wantlist."""

    @pytest.mark.asyncio
    async def test_empty_wantlist_returns_zero(self) -> None:
        cur = AsyncMock()
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        empty_resp = _make_wantlist_response([], total_pages=1)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=empty_resp)

        with patch("curator.syncer.httpx.AsyncClient", return_value=mock_client):
            total = await sync_wantlist(
                user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
                discogs_username="testuser",
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                token_secret="tsecret",  # noqa: S106
                user_agent="TestAgent/1.0",
                pg_pool=pool,
                neo4j_driver=driver,
            )

        assert total == 0

    @pytest.mark.asyncio
    async def test_wantlist_items_synced(self) -> None:
        cur = AsyncMock()
        cur.execute = AsyncMock()
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        wants = [
            {
                "id": 99999,  # top-level release ID for wantlist
                "basic_information": {
                    "title": "Wanted Album",
                    "year": 2019,
                    "artists": [{"name": "Some Artist"}],
                    "formats": [{"name": "CD"}],
                },
                "rating": 0,
                "notes": "My notes",
                "date_added": "2022-06-01T00:00:00-07:00",
            }
        ]
        resp = _make_wantlist_response(wants, total_pages=1)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with (
            patch("curator.syncer.httpx.AsyncClient", return_value=mock_client),
            patch("curator.syncer.asyncio.sleep", new=AsyncMock()),
        ):
            total = await sync_wantlist(
                user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
                discogs_username="testuser",
                consumer_key="ckey",
                consumer_secret="csecret",  # noqa: S106
                access_token="acctok",  # noqa: S106
                token_secret="tsecret",  # noqa: S106
                user_agent="TestAgent/1.0",
                pg_pool=pool,
                neo4j_driver=driver,
            )

        assert total == 1


class TestRunFullSync:
    """Tests for run_full_sync."""

    @pytest.mark.asyncio
    async def test_no_oauth_token_fails_gracefully(self) -> None:
        cur = AsyncMock()
        cur.fetchone = AsyncMock(return_value=None)  # no OAuth token
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        result = await run_full_sync(
            user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
            sync_id="sync-123",
            pg_pool=pool,
            neo4j_driver=driver,
            discogs_user_agent="TestAgent/1.0",
        )

        assert result["status"] == "failed"
        assert result["error"] is not None
        assert "No Discogs OAuth token" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_app_credentials_fails_gracefully(self) -> None:
        cur = AsyncMock()
        # First fetchone returns the OAuth token; fetchall returns empty config
        cur.fetchone = AsyncMock(
            return_value={
                "access_token": "acctok",
                "access_secret": "accsec",
                "provider_username": "discogs_user",
            }
        )
        cur.fetchall = AsyncMock(return_value=[])  # No app credentials
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        result = await run_full_sync(
            user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
            sync_id="sync-123",
            pg_pool=pool,
            neo4j_driver=driver,
            discogs_user_agent="TestAgent/1.0",
        )

        assert result["status"] == "failed"
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_full_sync(self) -> None:
        cur = AsyncMock()
        # OAuth token
        cur.fetchone = AsyncMock(
            return_value={
                "access_token": "acctok",
                "access_secret": "accsec",
                "provider_username": "discogs_user",
            }
        )
        # App config with both keys
        cur.fetchall = AsyncMock(
            return_value=[
                {"key": "discogs_consumer_key", "value": "ckey"},
                {"key": "discogs_consumer_secret", "value": "csecret"},
            ]
        )
        pool = _make_mock_pg_pool(cur)
        driver = _make_mock_neo4j()

        with (
            patch("curator.syncer.sync_collection", new=AsyncMock(return_value=10)),
            patch("curator.syncer.sync_wantlist", new=AsyncMock(return_value=5)),
        ):
            result = await run_full_sync(
                user_uuid=UUID("00000000-0000-0000-0000-000000000001"),
                sync_id="sync-456",
                pg_pool=pool,
                neo4j_driver=driver,
                discogs_user_agent="TestAgent/1.0",
            )

        assert result["status"] == "completed"
        assert result["collection_count"] == 10
        assert result["wantlist_count"] == 5
        assert result["error"] is None
