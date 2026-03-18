"""Tests for api/syncer.py — collection and wantlist sync logic."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from api.syncer import (
    _auth_header,
    run_full_sync,
    sync_collection,
    sync_wantlist,
)


TEST_USER_UUID = UUID("00000000-0000-0000-0000-000000000001")
TEST_DISCOGS_USERNAME = "test_dj"
TEST_CONSUMER_KEY = "consumer_key"
TEST_CONSUMER_SECRET = "consumer_secret"
TEST_ACCESS_TOKEN = "access_token"
TEST_TOKEN_SECRET = "token_secret"
TEST_USER_AGENT = "TestApp/1.0"


def _make_collection_response(
    releases: list[dict],
    page: int = 1,
    pages: int = 1,
) -> dict:
    """Build a Discogs collection API response."""
    return {
        "releases": releases,
        "pagination": {"page": page, "pages": pages},
    }


def _make_wantlist_response(
    wants: list[dict],
    page: int = 1,
    pages: int = 1,
) -> dict:
    """Build a Discogs wantlist API response."""
    return {
        "wants": wants,
        "pagination": {"page": page, "pages": pages},
    }


def _make_release_item(release_id: int = 123, **overrides: object) -> dict:
    """Build a single collection release item."""
    item: dict = {
        "instance_id": 1000 + release_id,
        "folder_id": 1,
        "rating": 4,
        "date_added": "2025-01-01T00:00:00Z",
        "basic_information": {
            "id": release_id,
            "title": f"Album {release_id}",
            "year": 2020,
            "artists": [{"name": f"Artist {release_id}"}],
            "labels": [{"name": f"Label {release_id}"}],
            "formats": [{"name": "Vinyl"}],
        },
    }
    item.update(overrides)
    return item


def _make_want_item(release_id: int = 456, **overrides: object) -> dict:
    """Build a single wantlist item."""
    item: dict = {
        "id": release_id,
        "rating": 3,
        "notes": "Want this!",
        "date_added": "2025-02-01T00:00:00Z",
        "basic_information": {
            "title": f"Want {release_id}",
            "year": 2021,
            "artists": [{"name": f"Artist {release_id}"}],
            "formats": [{"name": "CD"}],
        },
    }
    item.update(overrides)
    return item


@pytest.fixture
def mock_pg_pool() -> MagicMock:
    """Mock AsyncPostgreSQLPool."""
    pool = MagicMock()
    mock_cur = AsyncMock()
    mock_cur.execute = AsyncMock()
    mock_cur.executemany = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value=None)
    mock_cur.fetchall = AsyncMock(return_value=[])

    mock_conn = AsyncMock()
    cur_ctx = AsyncMock()
    cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    cur_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.cursor = MagicMock(return_value=cur_ctx)

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn_ctx)
    pool._mock_cur = mock_cur
    return pool


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Mock AsyncResilientNeo4jDriver."""
    driver = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock()

    driver.session = MagicMock(return_value=mock_session)
    driver._mock_session = mock_session
    return driver


class TestAuthHeader:
    """Tests for _auth_header."""

    def test_returns_oauth_header_string(self) -> None:
        header = _auth_header(
            "GET",
            "https://api.discogs.com/test",
            "ck",
            "cs",
            "at",
            "ts",
        )
        assert header.startswith("OAuth ")
        assert "oauth_consumer_key" in header
        assert "oauth_signature" in header

    def test_contains_required_oauth_params(self) -> None:
        header = _auth_header("POST", "https://example.com", "k", "s", "t", "ts")
        for param in (
            "oauth_consumer_key",
            "oauth_nonce",
            "oauth_signature_method",
            "oauth_timestamp",
            "oauth_token",
            "oauth_version",
            "oauth_signature",
        ):
            assert param in header


class TestSyncCollection:
    """Tests for sync_collection."""

    @pytest.mark.asyncio
    async def test_single_page_success(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        release = _make_release_item(123)
        response_data = _make_collection_response([release], page=1, pages=1)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 1
        mock_pg_pool._mock_cur.executemany.assert_awaited_once()
        mock_neo4j._mock_session.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limited_429_retries(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        release = _make_release_item(1)
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = _make_collection_response([release])

        rate_limited = MagicMock()
        rate_limited.status_code = 429

        with (
            patch("api.syncer.httpx.AsyncClient") as mock_client_cls,
            patch("api.syncer.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[rate_limited, success_response])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 1
        mock_sleep.assert_any_await(60)

    @pytest.mark.asyncio
    async def test_non_200_breaks_loop(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        error_response = MagicMock()
        error_response.status_code = 500

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_releases_breaks_loop(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        empty_response = MagicMock()
        empty_response.status_code = 200
        empty_response.json.return_value = _make_collection_response([])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=empty_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_missing_release_id_skipped(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        """Items without basic_information.id are skipped."""
        item_no_id = {"basic_information": {"title": "No ID"}, "instance_id": 1, "folder_id": 1}
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _make_collection_response([item_no_id])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 0
        mock_pg_pool._mock_cur.executemany.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_pages(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = _make_collection_response([_make_release_item(1)], page=1, pages=2)

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = _make_collection_response([_make_release_item(2)], page=2, pages=2)

        with (
            patch("api.syncer.httpx.AsyncClient") as mock_client_cls,
            patch("api.syncer.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[page1, page2])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 2

    @pytest.mark.asyncio
    async def test_missing_artists_labels_formats(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        """Items with empty artists/labels/formats still sync."""
        item = {
            "instance_id": 999,
            "folder_id": 1,
            "rating": 0,
            "date_added": "2025-01-01T00:00:00Z",
            "basic_information": {
                "id": 777,
                "title": "Minimal",
                "year": 2020,
                "artists": [],
                "labels": [],
                "formats": [],
            },
        }
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _make_collection_response([item])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_collection(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 1


class TestSyncWantlist:
    """Tests for sync_wantlist."""

    @pytest.mark.asyncio
    async def test_single_page_success(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        want = _make_want_item(456)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _make_wantlist_response([want])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_wantlist(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 1
        mock_pg_pool._mock_cur.executemany.assert_awaited_once()
        mock_neo4j._mock_session.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limited_429(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        want = _make_want_item(1)
        success = MagicMock()
        success.status_code = 200
        success.json.return_value = _make_wantlist_response([want])

        rate_limited = MagicMock()
        rate_limited.status_code = 429

        with (
            patch("api.syncer.httpx.AsyncClient") as mock_client_cls,
            patch("api.syncer.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[rate_limited, success])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_wantlist(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_non_200_breaks(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        error = MagicMock()
        error.status_code = 403

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_wantlist(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_wants_breaks(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _make_wantlist_response([])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_wantlist(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_missing_want_id_skipped(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        """Items without top-level 'id' are skipped."""
        item_no_id = {"basic_information": {"title": "No ID"}, "rating": 0}
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _make_wantlist_response([item_no_id])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_wantlist(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_missing_formats_and_artists(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        """Want items with empty artists/formats still sync."""
        item = {
            "id": 888,
            "rating": 0,
            "date_added": "2025-01-01T00:00:00Z",
            "basic_information": {
                "title": "Minimal Want",
                "year": 2021,
                "artists": [],
                "formats": [],
            },
        }
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _make_wantlist_response([item])

        with patch("api.syncer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sync_wantlist(
                TEST_USER_UUID,
                TEST_DISCOGS_USERNAME,
                TEST_CONSUMER_KEY,
                TEST_CONSUMER_SECRET,
                TEST_ACCESS_TOKEN,
                TEST_TOKEN_SECRET,
                TEST_USER_AGENT,
                mock_pg_pool,
                mock_neo4j,
            )

        assert result == 1


class TestRunFullSync:
    """Tests for run_full_sync."""

    @pytest.mark.asyncio
    async def test_success(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        mock_pg_pool._mock_cur.fetchone.return_value = {
            "access_token": "enc_at",
            "access_secret": "enc_as",
            "provider_username": TEST_DISCOGS_USERNAME,
        }
        mock_pg_pool._mock_cur.fetchall.return_value = [
            {"key": "discogs_consumer_key", "value": "ck"},
            {"key": "discogs_consumer_secret", "value": "cs"},
        ]

        with (
            patch("api.syncer.sync_collection", new_callable=AsyncMock, return_value=10) as mock_coll,
            patch("api.syncer.sync_wantlist", new_callable=AsyncMock, return_value=5) as mock_want,
            patch("api.syncer.decrypt_oauth_token", side_effect=lambda val, _key: val),
        ):
            result = await run_full_sync(
                TEST_USER_UUID,
                "sync-123",
                mock_pg_pool,
                mock_neo4j,
                TEST_USER_AGENT,
            )

        assert result["status"] == "completed"
        assert result["collection_count"] == 10
        assert result["wantlist_count"] == 5
        assert result["error"] is None
        mock_coll.assert_awaited_once()
        mock_want.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_token_raises_valueerror(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        mock_pg_pool._mock_cur.fetchone.return_value = None

        result = await run_full_sync(
            TEST_USER_UUID,
            "sync-err",
            mock_pg_pool,
            mock_neo4j,
            TEST_USER_AGENT,
        )

        assert result["status"] == "failed"
        assert "No Discogs OAuth token" in result["error"]

    @pytest.mark.asyncio
    async def test_no_credentials_raises_valueerror(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        mock_pg_pool._mock_cur.fetchone.return_value = {
            "access_token": "at",
            "access_secret": "as",
            "provider_username": "user",
        }
        mock_pg_pool._mock_cur.fetchall.return_value = []  # no app_config rows

        with patch("api.syncer.decrypt_oauth_token", side_effect=lambda val, _key: val):
            result = await run_full_sync(
                TEST_USER_UUID,
                "sync-err",
                mock_pg_pool,
                mock_neo4j,
                TEST_USER_AGENT,
            )

        assert result["status"] == "failed"
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_exception_records_error(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        mock_pg_pool._mock_cur.fetchone.return_value = {
            "access_token": "at",
            "access_secret": "as",
            "provider_username": "user",
        }
        mock_pg_pool._mock_cur.fetchall.return_value = [
            {"key": "discogs_consumer_key", "value": "ck"},
            {"key": "discogs_consumer_secret", "value": "cs"},
        ]

        with (
            patch("api.syncer.sync_collection", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("api.syncer.decrypt_oauth_token", side_effect=lambda val, _key: val),
        ):
            result = await run_full_sync(
                TEST_USER_UUID,
                "sync-err",
                mock_pg_pool,
                mock_neo4j,
                TEST_USER_AGENT,
            )

        assert result["status"] == "failed"
        assert result["error"] == "boom"

    @pytest.mark.asyncio
    async def test_sync_history_update_failure_handled(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        """If updating sync_history fails, the function still returns a result."""
        mock_pg_pool._mock_cur.fetchone.return_value = {
            "access_token": "at",
            "access_secret": "as",
            "provider_username": "user",
        }
        mock_pg_pool._mock_cur.fetchall.return_value = [
            {"key": "discogs_consumer_key", "value": "ck"},
            {"key": "discogs_consumer_secret", "value": "cs"},
        ]

        call_count = 0

        async def failing_execute(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            # First few calls succeed (token fetch + config fetch),
            # then the sync_history UPDATE fails
            if call_count > 2:
                raise RuntimeError("DB write failed")

        mock_pg_pool._mock_cur.execute = AsyncMock(side_effect=failing_execute)

        with (
            patch("api.syncer.sync_collection", new_callable=AsyncMock, return_value=5),
            patch("api.syncer.sync_wantlist", new_callable=AsyncMock, return_value=3),
            patch("api.syncer.decrypt_oauth_token", side_effect=lambda val, _key: val),
        ):
            result = await run_full_sync(
                TEST_USER_UUID,
                "sync-id",
                mock_pg_pool,
                mock_neo4j,
                TEST_USER_AGENT,
            )

        # Should still return completed even if sync_history update fails
        assert result["sync_id"] == "sync-id"
        assert result["collection_count"] == 5
        assert result["wantlist_count"] == 3

    @pytest.mark.asyncio
    async def test_with_encryption_key(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        mock_pg_pool._mock_cur.fetchone.return_value = {
            "access_token": "enc_at",
            "access_secret": "enc_as",
            "provider_username": "user",
        }
        mock_pg_pool._mock_cur.fetchall.return_value = [
            {"key": "discogs_consumer_key", "value": "enc_ck"},
            {"key": "discogs_consumer_secret", "value": "enc_cs"},
        ]

        with (
            patch("api.syncer.sync_collection", new_callable=AsyncMock, return_value=0),
            patch("api.syncer.sync_wantlist", new_callable=AsyncMock, return_value=0),
            patch("api.syncer.decrypt_oauth_token", side_effect=lambda val, _key: f"dec_{val}") as mock_decrypt,
        ):
            result = await run_full_sync(
                TEST_USER_UUID,
                "sync-enc",
                mock_pg_pool,
                mock_neo4j,
                TEST_USER_AGENT,
                oauth_encryption_key="my-key",
            )

        assert result["status"] == "completed"
        # decrypt_oauth_token should be called for access_token, access_secret,
        # consumer_key, consumer_secret
        assert mock_decrypt.call_count == 4

    @pytest.mark.asyncio
    async def test_return_dict_structure(self, mock_pg_pool: MagicMock, mock_neo4j: MagicMock) -> None:
        mock_pg_pool._mock_cur.fetchone.return_value = None

        result = await run_full_sync(
            TEST_USER_UUID,
            "sync-struct",
            mock_pg_pool,
            mock_neo4j,
            TEST_USER_AGENT,
        )

        assert set(result.keys()) == {"sync_id", "status", "collection_count", "wantlist_count", "error"}
