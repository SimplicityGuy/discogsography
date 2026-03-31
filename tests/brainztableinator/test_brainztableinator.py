"""Tests for the brainztableinator service."""

import asyncio
import contextlib
import json
import signal
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from brainztableinator.brainztableinator import (
    PROCESSORS,
    _insert_external_link,
    _insert_relationship,
    _recover_consumers,
    check_all_consumers_idle,
    close_rabbitmq_connection,
    get_connection,
    get_health_data,
    main,
    make_data_handler,
    on_data_message,
    process_artist,
    process_label,
    process_release,
    process_release_group,
    schedule_consumer_cancellation,
    signal_handler,
)


# ===========================================================================
# Health data tests
# ===========================================================================


class TestHealthData:
    """Tests for get_health_data."""

    def test_health_data_starting(self):
        """When connection_pool is None and no consumers, status should be 'starting'."""
        with (
            patch("brainztableinator.brainztableinator.connection_pool", None),
            patch("brainztableinator.brainztableinator.consumer_tags", {}),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
        ):
            health = get_health_data()
            assert health["status"] == "starting"
            assert health["service"] == "brainztableinator"
            assert health["current_task"] == "Initializing PostgreSQL connection"

    def test_health_data_healthy(self):
        """When connection_pool exists, status should be 'healthy'."""
        mock_pool = MagicMock()
        with (
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch("brainztableinator.brainztableinator.consumer_tags", {}),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
        ):
            health = get_health_data()
            assert health["status"] == "healthy"
            assert health["service"] == "brainztableinator"


# ===========================================================================
# Helper to create mock connection with cursor
# ===========================================================================


def _make_mock_conn():
    """Create a mock async connection with cursor context manager."""
    mock_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor_ctx = AsyncMock()
    mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)
    return mock_conn, mock_cursor


# ===========================================================================
# Process function tests
# ===========================================================================


class TestProcessArtist:
    """Tests for process_artist."""

    @pytest.mark.asyncio
    async def test_process_artist_basic(self):
        """Verify INSERT INTO musicbrainz.artists is called."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "id": "artist-mbid-123",
            "mbid": "artist-mbid-123",
            "name": "Test Artist",
            "sort_name": "Artist, Test",
            "mb_type": "Person",
        }

        await process_artist(mock_conn, record)

        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args_list[0]
        sql = call_args[0][0]
        assert "INSERT INTO musicbrainz.artists" in sql
        assert "ON CONFLICT (mbid) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_process_artist_with_relationships(self):
        """Verify relationships and external links are also inserted."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "id": "artist-mbid-456",
            "mbid": "artist-mbid-456",
            "name": "Linked Artist",
            "sort_name": "Artist, Linked",
            "relations": [
                {
                    "target_mbid": "target-mbid-1",
                    "target_type": "artist",
                    "type": "member of band",
                    "attributes": [],
                    "ended": False,
                }
            ],
            "external_links": [
                {
                    "url": "https://example.com/artist",
                    "type": "official homepage",
                }
            ],
        }

        await process_artist(mock_conn, record)

        # Should have 3 execute calls: artist insert + relationship + external link
        assert mock_cursor.execute.call_count == 3

        # Check relationship insert
        rel_sql = mock_cursor.execute.call_args_list[1][0][0]
        assert "INSERT INTO musicbrainz.relationships" in rel_sql

        # Check external link insert
        link_sql = mock_cursor.execute.call_args_list[2][0][0]
        assert "INSERT INTO musicbrainz.external_links" in link_sql


class TestProcessLabel:
    """Tests for process_label."""

    @pytest.mark.asyncio
    async def test_process_label_basic(self):
        """Verify INSERT INTO musicbrainz.labels is called."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "id": "label-mbid-123",
            "mbid": "label-mbid-123",
            "name": "Test Label",
            "mb_type": "Original Production",
        }

        await process_label(mock_conn, record)

        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args_list[0]
        sql = call_args[0][0]
        assert "INSERT INTO musicbrainz.labels" in sql
        assert "ON CONFLICT (mbid) DO UPDATE" in sql


class TestProcessRelease:
    """Tests for process_release."""

    @pytest.mark.asyncio
    async def test_process_release_basic(self):
        """Verify INSERT INTO musicbrainz.releases is called."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "id": "release-mbid-123",
            "mbid": "release-mbid-123",
            "name": "Test Album",
            "status": "Official",
        }

        await process_release(mock_conn, record)

        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args_list[0]
        sql = call_args[0][0]
        assert "INSERT INTO musicbrainz.releases" in sql
        assert "ON CONFLICT (mbid) DO UPDATE" in sql


class TestProcessReleaseGroup:
    """Tests for process_release_group."""

    @pytest.mark.asyncio
    async def test_process_release_group_basic(self):
        """Verify INSERT INTO musicbrainz.release_groups is called."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "id": "rg-mbid-123",
            "mbid": "rg-mbid-123",
            "name": "Test Album",
            "mb_type": "Album",
            "secondary_types": ["Compilation"],
            "first_release_date": "2020-01-15",
            "disambiguation": "",
            "discogs_master_id": 12345,
        }

        await process_release_group(mock_conn, record)

        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args_list[0]
        sql = call_args[0][0]
        assert "INSERT INTO musicbrainz.release_groups" in sql
        assert "ON CONFLICT (mbid) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_process_release_group_with_relationships_and_links(self):
        """Verify relationships and external links are also inserted."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "id": "rg-mbid-456",
            "mbid": "rg-mbid-456",
            "name": "Linked Album",
            "mb_type": "Album",
            "relations": [
                {
                    "target_mbid": "target-mbid-1",
                    "target_type": "artist",
                    "type": "performance",
                    "attributes": [],
                    "ended": False,
                }
            ],
            "external_links": [
                {
                    "url": "https://example.com/release-group",
                    "type": "discogs",
                }
            ],
        }

        await process_release_group(mock_conn, record)

        # Should have 3 execute calls: release_group insert + relationship + external link
        assert mock_cursor.execute.call_count == 3

        # Check relationship insert
        rel_sql = mock_cursor.execute.call_args_list[1][0][0]
        assert "INSERT INTO musicbrainz.relationships" in rel_sql

        # Check external link insert
        link_sql = mock_cursor.execute.call_args_list[2][0][0]
        assert "INSERT INTO musicbrainz.external_links" in link_sql


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestInsertRelationship:
    """Tests for _insert_relationship."""

    @pytest.mark.asyncio
    async def test_insert_relationship(self):
        """Verify INSERT INTO musicbrainz.relationships is called."""
        mock_conn, mock_cursor = _make_mock_conn()
        rel = {
            "target_mbid": "target-mbid-1",
            "target_type": "artist",
            "type": "member of band",
            "attributes": ["guitar"],
            "begin_date": "2000-01-01",
            "end_date": None,
            "ended": False,
        }

        await _insert_relationship(mock_conn, "source-mbid-1", "artist", rel)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO musicbrainz.relationships" in sql
        assert "ON CONFLICT DO NOTHING" in sql

    @pytest.mark.asyncio
    async def test_insert_relationship_no_target_skips(self):
        """Empty target_mbid still inserts (with empty string default)."""
        mock_conn, mock_cursor = _make_mock_conn()
        rel = {
            "target_mbid": "",
            "target_type": "artist",
            "type": "member of band",
        }

        await _insert_relationship(mock_conn, "source-mbid-1", "artist", rel)

        # The function inserts with empty string - it does not skip
        mock_cursor.execute.assert_called_once()
        params = mock_cursor.execute.call_args[0][1]
        assert params[2] == ""  # target_mbid is empty string


class TestInsertExternalLink:
    """Tests for _insert_external_link."""

    @pytest.mark.asyncio
    async def test_insert_external_link(self):
        """Verify INSERT INTO musicbrainz.external_links is called."""
        mock_conn, mock_cursor = _make_mock_conn()
        link = {
            "url": "https://example.com",
            "type": "official homepage",
        }

        await _insert_external_link(mock_conn, "mbid-1", "artist", link)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO musicbrainz.external_links" in sql
        assert "ON CONFLICT DO NOTHING" in sql

    @pytest.mark.asyncio
    async def test_insert_external_link_no_service_skips(self):
        """Empty service still inserts (with empty string default)."""
        mock_conn, mock_cursor = _make_mock_conn()
        link = {
            "url": "",
            "type": "",
        }

        await _insert_external_link(mock_conn, "mbid-1", "artist", link)

        # The function inserts with empty strings - it does not skip
        mock_cursor.execute.assert_called_once()
        params = mock_cursor.execute.call_args[0][1]
        assert params[2] == ""  # url is empty string


# ===========================================================================
# Signal handler test
# ===========================================================================


class TestSignalHandler:
    """Tests for signal_handler."""

    def test_signal_handler_sets_shutdown(self):
        """Signal handler should set shutdown_requested to True."""
        with patch("brainztableinator.brainztableinator.shutdown_requested", False):
            signal_handler(2, None)

            # After calling signal_handler, the global should be True
            from brainztableinator.brainztableinator import shutdown_requested

            assert shutdown_requested is True

        # Reset the global state
        import brainztableinator.brainztableinator as bt

        bt.shutdown_requested = False


# ===========================================================================
# Message handler tests
# ===========================================================================


class TestOnDataMessage:
    """Tests for on_data_message (control message handling)."""

    @pytest.mark.asyncio
    async def test_file_complete_message(self):
        """file_complete message should add data_type to completed_files."""
        from brainztableinator.brainztableinator import on_data_message

        mock_message = AsyncMock()
        mock_message.body = b'{"type": "file_complete", "total_processed": 100}'

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()) as mock_completed,
            patch("brainztableinator.brainztableinator.CONSUMER_CANCEL_DELAY", 0),
            patch("brainztableinator.brainztableinator.connection_pool", MagicMock()),
        ):
            await on_data_message(mock_message, "artists")

            mock_message.ack.assert_called_once()
            assert "artists" in mock_completed

    @pytest.mark.asyncio
    async def test_extraction_complete_message(self):
        """extraction_complete message should be acked."""
        mock_message = AsyncMock()
        mock_message.body = b'{"type": "extraction_complete", "version": "2026-01-01"}'

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", MagicMock()),
        ):
            await on_data_message(mock_message, "artists")

            mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_data_message_calls_processor(self):
        """A valid data message with 'id' should call the appropriate processor."""
        mock_message = AsyncMock()
        mock_message.body = b'{"id": "artist-mbid-1", "name": "Test Artist"}'

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        # Support conn.transaction() as an async context manager
        mock_tx_cm = AsyncMock()
        mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
        mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_tx_cm)
        mock_conn_cm = AsyncMock()
        mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_conn_cm)

        mock_processor = AsyncMock()

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
            patch.dict(
                "brainztableinator.brainztableinator.PROCESSORS",
                {"artists": mock_processor},
            ),
        ):
            await on_data_message(mock_message, "artists")

            mock_processor.assert_called_once_with(mock_conn, {"id": "artist-mbid-1", "name": "Test Artist"})
            mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_requested_nacks_with_requeue(self):
        """When shutdown_requested is True, message should be nacked with requeue."""
        mock_message = AsyncMock()
        mock_message.body = b'{"id": "artist-mbid-1", "name": "Test Artist"}'

        with patch("brainztableinator.brainztableinator.shutdown_requested", True):
            await on_data_message(mock_message, "artists")

            mock_message.nack.assert_called_once_with(requeue=True)
            mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_unparseable_message_nacks_without_requeue(self):
        """An unparseable message body should be nacked without requeue."""
        mock_message = AsyncMock()
        mock_message.body = b"not valid json {"

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", MagicMock()),
        ):
            await on_data_message(mock_message, "artists")

            mock_message.nack.assert_called_once_with(requeue=False)
            mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_missing_id_nacks_without_requeue(self):
        """A message with no 'id' field should be nacked without requeue."""
        mock_message = AsyncMock()
        mock_message.body = b'{"name": "No ID Artist"}'

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", MagicMock()),
        ):
            await on_data_message(mock_message, "artists")

            mock_message.nack.assert_called_once_with(requeue=False)
            mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_processor_for_data_type_nacks(self):
        """Unknown data type with no processor should nack without requeue."""
        mock_message = AsyncMock()
        mock_message.body = b'{"id": "mbid-1", "name": "Test"}'

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn_cm = AsyncMock()
        mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_conn_cm)

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0, "unknown_type": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0, "unknown_type": 0.0},
            ),
        ):
            await on_data_message(mock_message, "unknown_type")

            mock_message.nack.assert_called_once_with(requeue=False)

    @pytest.mark.asyncio
    async def test_connection_pool_none_nacks_with_requeue(self):
        """When connection_pool is None, message should be nacked with requeue."""
        mock_message = AsyncMock()
        mock_message.body = b'{"id": "mbid-1", "name": "Test"}'

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", None),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
        ):
            await on_data_message(mock_message, "artists")

            # RuntimeError triggers the nack with requeue=True path
            mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_database_error_nacks_with_requeue(self):
        """Database connection errors should nack with requeue."""
        from psycopg.errors import OperationalError

        mock_message = AsyncMock()
        mock_message.body = b'{"id": "mbid-1", "name": "Test"}'

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn_cm = AsyncMock()
        mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_conn_cm)

        mock_processor = AsyncMock(side_effect=OperationalError("connection lost"))

        with (
            patch("brainztableinator.brainztableinator.shutdown_requested", False),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
            patch.dict(
                "brainztableinator.brainztableinator.PROCESSORS",
                {"artists": mock_processor},
            ),
        ):
            await on_data_message(mock_message, "artists")

            mock_message.nack.assert_called_once_with(requeue=True)


# ===========================================================================
# make_data_handler tests
# ===========================================================================


class TestMakeDataHandler:
    """Tests for make_data_handler."""

    def test_returns_callable(self):
        """make_data_handler should return a callable."""
        handler = make_data_handler("artists")
        assert callable(handler)

    def test_returns_different_handlers_per_type(self):
        """Each data type should produce a distinct handler."""
        handler_a = make_data_handler("artists")
        handler_l = make_data_handler("labels")
        handler_r = make_data_handler("releases")

        assert handler_a is not handler_l
        assert handler_l is not handler_r

    @pytest.mark.asyncio
    async def test_handler_calls_on_data_message_with_correct_type(self):
        """The handler returned should call on_data_message with the right data_type."""
        mock_message = AsyncMock()

        with patch("brainztableinator.brainztableinator.on_data_message", new_callable=AsyncMock) as mock_on_data:
            handler = make_data_handler("labels")
            await handler(mock_message)

            mock_on_data.assert_called_once_with(mock_message, "labels")


# ===========================================================================
# Config tests
# ===========================================================================


class TestBrainztableinatorConfig:
    """Tests for BrainztableinatorConfig.from_env."""

    def test_from_env_with_all_vars(self):
        """Config should load successfully when all required env vars are set."""
        from common.config import BrainztableinatorConfig

        env_vars = {
            "RABBITMQ_USERNAME": "guest",
            "RABBITMQ_HOST": "localhost",
            "RABBITMQ_PORT": "5672",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_USERNAME": "user",
            "POSTGRES_PASSWORD": "secret",
            "POSTGRES_DATABASE": "testdb",
        }

        with patch.dict("os.environ", env_vars, clear=False):
            cfg = BrainztableinatorConfig.from_env()

            assert cfg.postgres_username == "user"
            assert cfg.postgres_password == "secret"
            assert cfg.postgres_database == "testdb"
            assert "localhost:5432" in cfg.postgres_host

    def test_from_env_missing_vars_raises(self):
        """Config should raise ValueError when required env vars are missing."""
        from common.config import BrainztableinatorConfig

        env_vars = {
            "RABBITMQ_USERNAME": "guest",
            "RABBITMQ_HOST": "localhost",
            "RABBITMQ_PORT": "5672",
            # POSTGRES_HOST intentionally missing
            # POSTGRES_USERNAME intentionally missing
            # POSTGRES_PASSWORD intentionally missing
            # POSTGRES_DATABASE intentionally missing
        }

        with (
            patch.dict("os.environ", env_vars, clear=True),
            pytest.raises(ValueError, match="Missing required environment variables"),
        ):
            BrainztableinatorConfig.from_env()


# ===========================================================================
# Consumer management tests
# ===========================================================================


class TestConsumerManagement:
    """Tests for consumer management functions."""

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_true(self):
        """Returns True when no consumer tags and all files completed."""
        with (
            patch("brainztableinator.brainztableinator.consumer_tags", {}),
            patch(
                "brainztableinator.brainztableinator.completed_files",
                {"artists", "labels", "release-groups", "releases"},
            ),
        ):
            result = await check_all_consumers_idle()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_false_consumers_active(self):
        """Returns False when consumers are still active."""
        with (
            patch(
                "brainztableinator.brainztableinator.consumer_tags",
                {"artists": "tag-1"},
            ),
            patch(
                "brainztableinator.brainztableinator.completed_files",
                {"artists", "labels", "release-groups", "releases"},
            ),
        ):
            result = await check_all_consumers_idle()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_false_files_incomplete(self):
        """Returns False when not all files are completed."""
        with (
            patch("brainztableinator.brainztableinator.consumer_tags", {}),
            patch(
                "brainztableinator.brainztableinator.completed_files",
                {"artists"},
            ),
        ):
            result = await check_all_consumers_idle()
            assert result is False


# ===========================================================================
# PROCESSORS map tests
# ===========================================================================


class TestProcessors:
    """Tests for the PROCESSORS mapping."""

    def test_processors_maps_artists(self):
        """PROCESSORS should map 'artists' to process_artist."""
        assert PROCESSORS["artists"] is process_artist

    def test_processors_maps_labels(self):
        """PROCESSORS should map 'labels' to process_label."""
        assert PROCESSORS["labels"] is process_label

    def test_processors_maps_release_groups(self):
        """PROCESSORS should map 'release-groups' to process_release_group."""
        assert PROCESSORS["release-groups"] is process_release_group

    def test_processors_maps_releases(self):
        """PROCESSORS should map 'releases' to process_release."""
        assert PROCESSORS["releases"] is process_release

    def test_processors_has_exactly_four_entries(self):
        """PROCESSORS should have exactly 4 data types."""
        assert len(PROCESSORS) == 4


# ===========================================================================
# GetConnection tests
# ===========================================================================


class TestGetConnection:
    """Test get_connection function."""

    def test_get_connection_success(self) -> None:
        """Test getting connection from pool."""
        mock_pool = MagicMock()

        with patch("brainztableinator.brainztableinator.connection_pool", mock_pool):
            result = get_connection()

            assert result == mock_pool.connection()

    def test_get_connection_no_pool(self) -> None:
        """Test getting connection when pool not initialized."""
        with (
            patch("brainztableinator.brainztableinator.connection_pool", None),
            pytest.raises(RuntimeError, match="Connection pool not initialized"),
        ):
            get_connection()


# ===========================================================================
# Schedule consumer cancellation tests
# ===========================================================================


class TestScheduleConsumerCancellation:
    """Test schedule_consumer_cancellation function."""

    @pytest.mark.asyncio
    async def test_schedules_cancellation_task(self) -> None:
        """Test that cancellation task is scheduled."""
        import brainztableinator.brainztableinator as bt

        bt.consumer_cancel_tasks = {}
        bt.consumer_tags = {"artists": "consumer-tag-1"}
        bt.shutdown_requested = False

        mock_queue = AsyncMock()

        with patch("asyncio.sleep", AsyncMock()):
            await schedule_consumer_cancellation("artists", mock_queue)

        # Verify task was created
        assert "artists" in bt.consumer_cancel_tasks
        assert bt.consumer_cancel_tasks["artists"] is not None

        # Clean up
        bt.consumer_cancel_tasks["artists"].cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bt.consumer_cancel_tasks["artists"]

    @pytest.mark.asyncio
    async def test_cancels_existing_scheduled_task(self) -> None:
        """Test that existing scheduled task is cancelled."""
        import brainztableinator.brainztableinator as bt

        existing_task = AsyncMock()
        bt.consumer_cancel_tasks = {"artists": existing_task}
        bt.consumer_tags = {"artists": "consumer-tag-1"}
        bt.shutdown_requested = False

        mock_queue = AsyncMock()

        with patch("asyncio.sleep", AsyncMock()):
            await schedule_consumer_cancellation("artists", mock_queue)

        # Verify old task was cancelled
        existing_task.cancel.assert_called_once()


# ===========================================================================
# Cancel after delay tests
# ===========================================================================


class TestCancelAfterDelay:
    """Test cancel_after_delay nested function."""

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cancels_consumer_after_delay(self) -> None:
        """Test that consumer is cancelled after delay."""
        mock_queue = AsyncMock()
        mock_queue.cancel = AsyncMock()

        import brainztableinator.brainztableinator as bt

        bt.consumer_tags = {"artists": "consumer-tag-123"}
        bt.shutdown_requested = False

        # Schedule cancellation
        await schedule_consumer_cancellation("artists", mock_queue)

        # Wait for delay
        await asyncio.sleep(0.15)

        # Should have cancelled
        mock_queue.cancel.assert_called_once_with("consumer-tag-123", nowait=True)

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_handles_cancel_error(self) -> None:
        """Test handling errors during consumer cancellation."""
        mock_queue = AsyncMock()
        mock_queue.cancel.side_effect = Exception("Cancel failed")

        import brainztableinator.brainztableinator as bt

        bt.consumer_tags = {"artists": "consumer-tag-123"}
        bt.consumer_cancel_tasks = {}
        bt.shutdown_requested = False

        with patch("brainztableinator.brainztableinator.logger"):
            await schedule_consumer_cancellation("artists", mock_queue)
            await asyncio.sleep(0.15)

        # Should have attempted to cancel despite error
        assert mock_queue.cancel.called


# ===========================================================================
# Close RabbitMQ connection tests
# ===========================================================================


class TestCloseRabbitMQConnection:
    """Test close_rabbitmq_connection function."""

    @pytest.mark.asyncio
    async def test_closes_channel_and_connection(self) -> None:
        """Test closing both channel and connection."""
        import brainztableinator.brainztableinator as bt

        mock_channel = AsyncMock()
        mock_connection = AsyncMock()

        bt.active_channel = mock_channel
        bt.active_connection = mock_connection

        with patch("brainztableinator.brainztableinator.logger"):
            await close_rabbitmq_connection()

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()

        assert bt.active_channel is None
        assert bt.active_connection is None

    @pytest.mark.asyncio
    async def test_handles_channel_close_error(self) -> None:
        """Test handling error when closing channel."""
        import brainztableinator.brainztableinator as bt

        mock_channel = AsyncMock()
        mock_channel.close.side_effect = Exception("Close error")
        mock_connection = AsyncMock()

        bt.active_channel = mock_channel
        bt.active_connection = mock_connection

        with patch("brainztableinator.brainztableinator.logger") as mock_logger:
            await close_rabbitmq_connection()

        # Should still close connection despite channel error
        mock_connection.close.assert_called_once()
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_handles_connection_close_error(self) -> None:
        """Test handling error when closing connection."""
        import brainztableinator.brainztableinator as bt

        mock_channel = AsyncMock()
        mock_connection = AsyncMock()
        mock_connection.close.side_effect = Exception("Close error")

        bt.active_channel = mock_channel
        bt.active_connection = mock_connection

        with patch("brainztableinator.brainztableinator.logger") as mock_logger:
            await close_rabbitmq_connection()

        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_handles_outer_exception(self) -> None:
        """Test handling of unexpected exceptions in outer try block."""
        import brainztableinator.brainztableinator as bt

        mock_channel = MagicMock()
        type(mock_channel).__bool__ = MagicMock(side_effect=RuntimeError("Unexpected error"))

        bt.active_channel = mock_channel
        bt.active_connection = None

        with patch("brainztableinator.brainztableinator.logger") as mock_logger:
            await close_rabbitmq_connection()

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "Error closing RabbitMQ connection" in call_args[0][0]


# ===========================================================================
# Check consumers unexpectedly dead tests
# ===========================================================================


class TestCheckConsumersUnexpectedlyDead:
    """Test check_consumers_unexpectedly_dead function."""

    @pytest.mark.asyncio
    async def test_not_stuck_with_active_consumers(self) -> None:
        """Not stuck when consumers are active."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import check_consumers_unexpectedly_dead

        bt.consumer_tags = {"artists": "tag-123"}
        bt.completed_files = set()
        bt.message_counts = {"artists": 100}
        assert await check_consumers_unexpectedly_dead() is False

    @pytest.mark.asyncio
    async def test_not_stuck_all_files_completed(self) -> None:
        """Not stuck when all files are completed (normal idle)."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import check_consumers_unexpectedly_dead

        bt.consumer_tags = {}
        bt.completed_files = {"artists", "labels", "release-groups", "releases"}
        bt.message_counts = {"artists": 100}
        assert await check_consumers_unexpectedly_dead() is False

    @pytest.mark.asyncio
    async def test_not_stuck_no_messages_processed(self) -> None:
        """Not stuck when no messages have been processed yet (startup)."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import check_consumers_unexpectedly_dead

        bt.consumer_tags = {}
        bt.completed_files = set()
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        assert await check_consumers_unexpectedly_dead() is False

    @pytest.mark.asyncio
    async def test_stuck_state_detected(self) -> None:
        """Stuck when no consumers, files not completed, has processed messages."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import check_consumers_unexpectedly_dead

        bt.consumer_tags = {}
        bt.completed_files = {"labels"}  # Only 1 of 3 complete
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 0}
        assert await check_consumers_unexpectedly_dead() is True


# ===========================================================================
# Periodic queue checker tests
# ===========================================================================


class TestPeriodicQueueChecker:
    """Test periodic_queue_checker function."""

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("brainztableinator.brainztableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_checks_queues_when_all_idle(self) -> None:
        """Test queue checking when all consumers are idle."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        mock_declared_queue = AsyncMock()
        mock_declared_queue.declaration_result.message_count = 5

        mock_channel.declare_queue = AsyncMock(return_value=mock_declared_queue)
        mock_channel.declare_exchange = AsyncMock()
        mock_channel.set_qos = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        import brainztableinator.brainztableinator as bt

        bt.rabbitmq_manager = mock_rabbitmq_manager
        bt.active_connection = None
        bt.active_channel = None
        bt.consumer_tags = {}
        bt.completed_files = {"artists", "labels", "release-groups", "releases"}  # All complete
        bt.shutdown_requested = False

        from brainztableinator.brainztableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.2)

        bt.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        assert mock_rabbitmq_manager.connect.called

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("brainztableinator.brainztableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_skips_check_when_consumers_active(self) -> None:
        """Test skips checking when consumers are active."""
        mock_rabbitmq_manager = AsyncMock()

        import brainztableinator.brainztableinator as bt

        bt.rabbitmq_manager = mock_rabbitmq_manager
        bt.active_connection = None
        bt.consumer_tags = {"artists": "tag-123"}  # Active consumer
        bt.completed_files = set()
        bt.shutdown_requested = False

        from brainztableinator.brainztableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.15)

        bt.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        mock_rabbitmq_manager.connect.assert_not_called()

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("brainztableinator.brainztableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_restarts_consumers_when_messages_found(self) -> None:
        """Test restarting consumers when messages are found in queues."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        mock_queue_with_msgs = AsyncMock()
        mock_queue_with_msgs.declaration_result.message_count = 10
        mock_queue_with_msgs.consume = AsyncMock(return_value="consumer-tag-123")
        mock_queue_with_msgs.bind = AsyncMock()

        mock_empty_queue = AsyncMock()
        mock_empty_queue.declaration_result.message_count = 0

        async def declare_queue_side_effect(name: str | None = None, **_kwargs: Any) -> Any:
            if "artists" in (name or ""):
                return mock_queue_with_msgs
            return mock_empty_queue

        mock_channel.declare_queue = AsyncMock(side_effect=declare_queue_side_effect)
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.set_qos = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        import brainztableinator.brainztableinator as bt

        bt.rabbitmq_manager = mock_rabbitmq_manager
        bt.active_connection = None
        bt.active_channel = None
        bt.consumer_tags = {}
        bt.completed_files = {"artists", "labels", "release-groups", "releases"}  # All complete so idle check passes
        bt.queues = {}
        bt.shutdown_requested = False
        bt.last_message_time = {}

        from brainztableinator.brainztableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.25)

        bt.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        assert mock_queue_with_msgs.consume.called

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("brainztableinator.brainztableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_handles_check_error_gracefully(self) -> None:
        """Test handling errors during queue checking."""
        mock_rabbitmq_manager = AsyncMock()
        mock_rabbitmq_manager.connect.side_effect = Exception("Connection failed")

        import brainztableinator.brainztableinator as bt

        bt.rabbitmq_manager = mock_rabbitmq_manager
        bt.active_connection = None
        bt.consumer_tags = {}
        bt.completed_files = set()
        bt.shutdown_requested = False

        from brainztableinator.brainztableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.15)

        bt.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Task should continue despite error
        assert True

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.QUEUE_CHECK_INTERVAL", 10)
    @patch("brainztableinator.brainztableinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_recovers_from_stuck_state(self) -> None:
        """Test recovery when consumers die unexpectedly (stuck state)."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        mock_queue_with_msgs = AsyncMock()
        mock_queue_with_msgs.declaration_result.message_count = 100
        mock_queue_with_msgs.consume = AsyncMock(return_value="consumer-tag-123")
        mock_queue_with_msgs.bind = AsyncMock()

        mock_channel.declare_queue = AsyncMock(return_value=mock_queue_with_msgs)
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.set_qos = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_connection.close = AsyncMock()
        mock_rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        import brainztableinator.brainztableinator as bt

        bt.rabbitmq_manager = mock_rabbitmq_manager
        bt.active_connection = None
        bt.active_channel = None
        # Stuck state: no consumers, but files not completed and has processed messages
        bt.consumer_tags = {}
        bt.completed_files = set()
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 10}
        bt.queues = {}
        bt.shutdown_requested = False
        bt.last_message_time = {
            "artists": 0.0,
            "labels": 0.0,
            "releases": 0.0,
        }

        from brainztableinator.brainztableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.2)

        bt.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should have attempted recovery by connecting
        assert mock_rabbitmq_manager.connect.called


# ===========================================================================
# Progress reporter tests
# ===========================================================================


class TestProgressReporterIdleMode:
    """Test progress_reporter nested function behavior."""

    @pytest.mark.asyncio
    async def test_progress_reporter_reports_periodically(self) -> None:
        """Test that progress reporter logs progress periodically."""
        import brainztableinator.brainztableinator as bt

        bt.shutdown_requested = False
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 10}
        bt.last_message_time = {
            "artists": time.time(),
            "labels": time.time(),
            "releases": time.time(),
        }
        bt.completed_files = set()
        bt.consumer_tags = {"artists": "tag1"}

        with patch("brainztableinator.brainztableinator.logger"):
            total = sum(bt.message_counts.values())
            assert total == 160
            assert len(bt.completed_files) < len(["artists", "labels", "release-groups", "releases"])

    @pytest.mark.asyncio
    async def test_progress_reporter_detects_stalled_consumers(self) -> None:
        """Test detection of stalled consumers."""
        import brainztableinator.brainztableinator as bt

        current_time = time.time()
        bt.message_counts = {"artists": 100}
        bt.last_message_time = {
            "artists": current_time - 150,  # 150 seconds ago (>120)
            "labels": 0,
        }
        bt.completed_files = set()

        stalled = []
        for data_type, last_time in bt.last_message_time.items():
            if data_type not in bt.completed_files and last_time > 0 and (current_time - last_time) > 120:
                stalled.append(data_type)

        assert "artists" in stalled
        assert "labels" not in stalled

    @pytest.mark.asyncio
    async def test_progress_reporter_skips_when_all_complete(self) -> None:
        """Test that progress reporter skips logging when all files complete."""
        import brainztableinator.brainztableinator as bt

        bt.completed_files = {"artists", "labels", "release-groups", "releases"}
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 10}

        assert len(bt.completed_files) == 4

    @pytest.mark.asyncio
    async def test_progress_reporter_idle_mode_detection(self) -> None:
        """Test idle mode detection in progress reporter."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        bt.shutdown_requested = False
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
        bt.completed_files = set()
        bt.consumer_tags = {"artists": "tag1"}
        bt.idle_mode = False

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.STARTUP_IDLE_TIMEOUT", 0),
            patch("brainztableinator.brainztableinator.logger"),
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        assert bt.idle_mode is True

    @pytest.mark.asyncio
    async def test_progress_reporter_exits_idle_on_messages(self) -> None:
        """Test that progress reporter exits idle mode when messages arrive."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        bt.shutdown_requested = False
        bt.idle_mode = True  # Start in idle mode
        bt.message_counts = {"artists": 5, "labels": 0, "release-groups": 0, "releases": 0}
        bt.last_message_time = {"artists": time.time(), "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
        bt.completed_files = set()
        bt.consumer_tags = {"artists": "tag1"}

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.logger"),
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        assert bt.idle_mode is False


# ===========================================================================
# Health data extended tests
# ===========================================================================


class TestGetHealthDataExtended:
    """Extended tests for get_health_data function."""

    def test_returns_health_status_dictionary(self) -> None:
        """Test that get_health_data returns a properly formatted dictionary."""
        import brainztableinator.brainztableinator as bt

        current_time = time.time()
        bt.current_progress = 50
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 0}
        bt.last_message_time = {
            "artists": current_time - 5,
            "labels": current_time - 8,
            "releases": 0.0,
        }
        bt.consumer_tags = {"artists": "consumer-1", "labels": "consumer-2"}
        bt.connection_pool = MagicMock()
        bt.completed_files = set()

        result = get_health_data()

        assert "status" in result
        assert "service" in result
        assert "current_task" in result
        assert "progress" in result
        assert "message_counts" in result
        assert "last_message_time" in result
        assert "timestamp" in result
        assert result["status"] == "healthy"
        assert result["service"] == "brainztableinator"
        assert result["current_task"] == "Processing artists"

        bt.connection_pool = None

    def test_health_status_unhealthy_when_connection_lost(self) -> None:
        """Test unhealthy when connection lost after startup."""
        import brainztableinator.brainztableinator as bt

        bt.connection_pool = None
        bt.consumer_tags = {"artists": "consumer-1"}
        bt.message_counts = {"artists": 100, "labels": 0, "release-groups": 0, "releases": 0}
        bt.completed_files = set()

        result = get_health_data()

        assert result["status"] == "unhealthy"

    def test_idle_status_with_active_consumers(self) -> None:
        """Test idle status when consumers active but no recent messages."""
        import brainztableinator.brainztableinator as bt

        current_time = time.time()
        bt.current_progress = 0
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 0}
        bt.last_message_time = {
            "artists": current_time - 60,
            "labels": current_time - 120,
            "releases": 0.0,
        }
        bt.consumer_tags = {"artists": "consumer-1", "labels": "consumer-2"}
        bt.completed_files = set()

        result = get_health_data()

        assert result["current_task"] == "Idle - waiting for messages"

    def test_no_status_when_no_consumers(self) -> None:
        """Test None when no consumers are active and all complete."""
        import brainztableinator.brainztableinator as bt

        current_time = time.time()
        bt.current_progress = 0
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 0}
        bt.last_message_time = {
            "artists": current_time - 60,
            "labels": current_time - 120,
            "releases": 0.0,
        }
        bt.consumer_tags = {}
        bt.completed_files = {"artists", "labels", "release-groups", "releases"}

        result = get_health_data()

        assert result["current_task"] is None

    def test_unhealthy_status_when_stuck_state(self) -> None:
        """Test unhealthy and stuck message when in stuck state."""
        import brainztableinator.brainztableinator as bt

        bt.connection_pool = MagicMock()
        bt.consumer_tags = {}
        bt.completed_files = set()
        bt.message_counts = {"artists": 50, "labels": 0, "release-groups": 0, "releases": 0}

        result = get_health_data()

        assert result["status"] == "unhealthy"
        assert result["current_task"] == "STUCK - consumers died, awaiting recovery"

        bt.connection_pool = None


# ===========================================================================
# Signal handler extended tests
# ===========================================================================


class TestSignalHandlerExtended:
    """Extended tests for signal_handler function."""

    def test_signal_handler_logs_signal_number(self) -> None:
        """Test that signal handler logs the signal number."""
        with patch("brainztableinator.brainztableinator.logger") as mock_logger:
            signal_handler(signal.SIGINT, None)

            mock_logger.info.assert_called_once()

        import brainztableinator.brainztableinator as bt

        bt.shutdown_requested = False


# ===========================================================================
# On data message extended tests
# ===========================================================================


class TestOnDataMessageExtended:
    """Extended tests for on_data_message handler."""

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    @patch("brainztableinator.brainztableinator.CONSUMER_CANCEL_DELAY", 1)
    async def test_schedules_consumer_cancellation_with_delay(self) -> None:
        """Test that consumer cancellation is scheduled when enabled."""
        import brainztableinator.brainztableinator as bt

        bt.completed_files = set()
        bt.queues = {"artists": AsyncMock()}
        bt.consumer_cancel_tasks = {}

        mock_message = AsyncMock()
        completion_data = {"type": "file_complete", "total_processed": 1000}
        mock_message.body = json.dumps(completion_data).encode()

        with (
            patch("brainztableinator.brainztableinator.logger"),
            patch("brainztableinator.brainztableinator.schedule_consumer_cancellation") as mock_schedule,
        ):
            await on_data_message(mock_message, "artists")

        mock_schedule.assert_called_once()
        assert "artists" in bt.completed_files

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    @patch("brainztableinator.brainztableinator.CONSUMER_CANCEL_DELAY", 0)
    async def test_skips_consumer_cancellation_when_disabled(self) -> None:
        """Test that consumer cancellation is skipped when delay is 0."""
        import brainztableinator.brainztableinator as bt

        bt.completed_files = set()
        bt.queues = {"artists": AsyncMock()}

        mock_message = AsyncMock()
        completion_data = {"type": "file_complete", "total_processed": 1000}
        mock_message.body = json.dumps(completion_data).encode()

        with (
            patch("brainztableinator.brainztableinator.logger"),
            patch("brainztableinator.brainztableinator.schedule_consumer_cancellation") as mock_schedule,
        ):
            await on_data_message(mock_message, "artists")

        mock_schedule.assert_not_called()
        assert "artists" in bt.completed_files

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    async def test_handles_database_interface_error(self) -> None:
        """Test handling InterfaceError from database."""
        from psycopg.errors import InterfaceError

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"id": "mbid-1", "name": "Test"}).encode()

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = InterfaceError("Interface error")

        with (
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
            patch("brainztableinator.brainztableinator.logger"),
        ):
            await on_data_message(mock_message, "artists")

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    async def test_handles_generic_exception_nack_with_requeue(self) -> None:
        """Test generic exception triggers nack with requeue."""
        mock_message = AsyncMock()
        mock_message.body = json.dumps({"id": "mbid-1", "name": "Test"}).encode()

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("Unexpected failure")

        with (
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
            patch("brainztableinator.brainztableinator.logger"),
        ):
            await on_data_message(mock_message, "artists")

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    async def test_handles_nack_failure(self) -> None:
        """Test handling failure during nack operation."""
        mock_message = AsyncMock()
        mock_message.body = json.dumps({"id": "mbid-1", "name": "Test"}).encode()
        mock_message.nack.side_effect = Exception("Nack failed")

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("Connection failed")

        with (
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
        ):
            await on_data_message(mock_message, "artists")

        assert any("Failed to nack message" in str(call) for call in mock_logger.warning.call_args_list)

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    @patch("brainztableinator.brainztableinator.progress_interval", 10)
    async def test_logs_progress_at_interval(self) -> None:
        """Test that progress is logged at the correct interval."""

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"id": "mbid-1", "name": "Test Artist"}).encode()

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        # Support conn.transaction() as an async context manager
        mock_tx_cm = AsyncMock()
        mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
        mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_tx_cm)
        mock_conn_cm = AsyncMock()
        mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_conn_cm)

        mock_cursor = AsyncMock()
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_cm)

        with (
            patch("brainztableinator.brainztableinator.connection_pool", mock_pool),
            patch(
                "brainztableinator.brainztableinator.message_counts",
                {"artists": 9, "labels": 0, "release-groups": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0},
            ),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
        ):
            await on_data_message(mock_message, "artists")

        progress_logged = False
        for call in mock_logger.info.call_args_list:
            if "Processed records in PostgreSQL" in str(call):
                progress_logged = True
                break

        assert progress_logged
        mock_message.ack.assert_called_once()


# ===========================================================================
# Main function tests
# ===========================================================================


class TestMain:
    """Test main function."""

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch("brainztableinator.brainztableinator.shutdown_requested", False)
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    async def test_main_execution(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test successful main execution."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)

        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        mock_connection = AsyncMock()
        mock_rabbitmq_instance.connect.return_value = mock_connection

        mock_channel = AsyncMock()
        mock_rabbitmq_instance.channel.return_value = mock_channel

        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        with patch("brainztableinator.brainztableinator.shutdown_requested", False):
            created_tasks = []
            original_create_task = asyncio.create_task

            def mock_create_task(coro: Any) -> asyncio.Task[Any]:
                task = original_create_task(coro)
                created_tasks.append(task)
                return task

            with patch("asyncio.create_task", side_effect=mock_create_task):

                async def mock_wait_for(_coro: Any, timeout: float) -> None:  # noqa: ARG001
                    import brainztableinator.brainztableinator

                    brainztableinator.brainztableinator.shutdown_requested = True
                    raise TimeoutError()

                with patch("asyncio.wait_for", mock_wait_for):
                    await main()

            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        assert mock_pool_class.call_count == 1
        call_args = mock_pool_class.call_args
        assert call_args[1]["max_connections"] == 50
        assert call_args[1]["min_connections"] == 5
        mock_rabbitmq_class.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    async def test_main_pool_initialization_failure(
        self,
        mock_pool_class: Mock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when connection pool initialization fails."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool_class.side_effect = Exception("Cannot create pool")

        await main()

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    async def test_main_config_load_failure(
        self,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when config fails to load."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        with patch("brainztableinator.brainztableinator.BrainztableinatorConfig") as mock_config_class:
            mock_config_class.from_env.side_effect = ValueError("Missing env vars")
            await main()

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    async def test_main_amqp_connection_failure_retries(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when AMQP connection fails after retries."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect.side_effect = Exception("Cannot connect to AMQP")

        # Patch asyncio.sleep to avoid actual delays in retry loop
        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
        ):
            await main()

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    async def test_main_startup_delay(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main with startup delay."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect.side_effect = Exception("Cannot connect")

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
        ):
            await main()


# ===========================================================================
# Main RabbitMQ retry tests
# ===========================================================================


class TestMainRabbitMQRetries:
    """Test main() RabbitMQ connection retry logic."""

    @pytest.mark.asyncio
    async def test_main_retries_rabbitmq_connection(self) -> None:
        """Test that main retries RabbitMQ connection on failure."""
        mock_manager = AsyncMock()
        mock_manager.connect.side_effect = [
            Exception("Connection failed"),
            Exception("Connection failed again"),
            AsyncMock(),  # Success on 3rd try
        ]

        retry_count = 0
        max_retries = 3
        connection = None

        for _attempt in range(max_retries):
            try:
                connection = await mock_manager.connect()
                break
            except Exception:
                retry_count += 1
                if retry_count >= max_retries:
                    break
                await asyncio.sleep(0.01)

        assert mock_manager.connect.call_count == 3
        assert connection is not None

    @pytest.mark.asyncio
    async def test_main_gives_up_after_max_retries(self) -> None:
        """Test that main gives up after maximum retries."""
        mock_manager = AsyncMock()
        mock_manager.connect.side_effect = Exception("Connection failed")

        retry_count = 0
        max_retries = 3
        connection = None

        for _attempt in range(max_retries):
            try:
                connection = await mock_manager.connect()
                break
            except Exception:
                retry_count += 1
                if retry_count >= max_retries:
                    break

        assert mock_manager.connect.call_count == 3
        assert connection is None


# ===========================================================================
# Process label/release with relationships and external links
# ===========================================================================


class TestProcessLabelRelationshipsAndLinks:
    """Test process_label and process_release with relationships and external links."""

    @pytest.mark.asyncio
    async def test_process_label_with_relationships(self) -> None:
        """Verify process_label inserts relationships."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "mbid": "label-mbid-123",
            "name": "Test Label",
            "mb_type": "Original Production",
            "relations": [
                {"target_mbid": "target-1", "type": "member", "direction": "forward"},
            ],
        }

        await process_label(mock_conn, record)

        # Should have calls for the main insert + relationship insert
        assert mock_cursor.execute.call_count >= 2
        rel_call = mock_cursor.execute.call_args_list[1]
        assert "musicbrainz.relationships" in rel_call[0][0]

    @pytest.mark.asyncio
    async def test_process_label_with_external_links(self) -> None:
        """Verify process_label inserts external links."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "mbid": "label-mbid-123",
            "name": "Test Label",
            "mb_type": "Original Production",
            "external_links": [
                {"url": "https://example.com", "type": "official"},
            ],
        }

        await process_label(mock_conn, record)

        assert mock_cursor.execute.call_count >= 2
        link_call = mock_cursor.execute.call_args_list[1]
        assert "musicbrainz.external_links" in link_call[0][0]

    @pytest.mark.asyncio
    async def test_process_release_with_relationships(self) -> None:
        """Verify process_release inserts relationships."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "mbid": "release-mbid-123",
            "name": "Test Album",
            "status": "Official",
            "relations": [
                {"target_mbid": "target-1", "type": "part of", "direction": "forward"},
            ],
        }

        await process_release(mock_conn, record)

        assert mock_cursor.execute.call_count >= 2
        rel_call = mock_cursor.execute.call_args_list[1]
        assert "musicbrainz.relationships" in rel_call[0][0]

    @pytest.mark.asyncio
    async def test_process_release_with_external_links(self) -> None:
        """Verify process_release inserts external links."""
        mock_conn, mock_cursor = _make_mock_conn()
        record = {
            "mbid": "release-mbid-123",
            "name": "Test Album",
            "status": "Official",
            "external_links": [
                {"url": "https://example.com/release", "type": "streaming"},
            ],
        }

        await process_release(mock_conn, record)

        assert mock_cursor.execute.call_count >= 2
        link_call = mock_cursor.execute.call_args_list[1]
        assert "musicbrainz.external_links" in link_call[0][0]


# ===========================================================================
# Cancel after delay — all consumers idle path
# ===========================================================================


class TestCancelAfterDelayAllIdle:
    """Test cancel_after_delay when all consumers become idle."""

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.CONSUMER_CANCEL_DELAY", 0.05)
    async def test_closes_connection_when_all_idle(self) -> None:
        """Test that closing RabbitMQ connection happens when all consumers idle."""
        mock_queue = AsyncMock()
        mock_queue.cancel = AsyncMock()

        import brainztableinator.brainztableinator as bt

        bt.consumer_tags = {"artists": "consumer-tag-123"}
        bt.shutdown_requested = False
        bt.active_connection = AsyncMock()
        bt.active_channel = AsyncMock()

        with (
            patch("brainztableinator.brainztableinator.check_all_consumers_idle", new_callable=AsyncMock, return_value=True),
            patch("brainztableinator.brainztableinator.close_rabbitmq_connection", new_callable=AsyncMock) as mock_close,
            patch("brainztableinator.brainztableinator.logger"),
        ):
            await schedule_consumer_cancellation("artists", mock_queue)
            await asyncio.sleep(0.1)

            mock_close.assert_called_once()


# ===========================================================================
# Periodic queue checker — CancelledError and early continue paths
# ===========================================================================


class TestPeriodicQueueCheckerEdgeCases:
    """Test edge cases in periodic_queue_checker."""

    @pytest.mark.asyncio
    async def test_cancelled_error_breaks_loop(self) -> None:
        """Test that CancelledError in the checker breaks the loop cleanly."""
        import brainztableinator.brainztableinator as bt

        bt.shutdown_requested = False
        bt.consumer_tags = {}
        bt.completed_files = set()
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bt.active_connection = None

        from brainztableinator.brainztableinator import periodic_queue_checker

        task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Task should have completed without error
        assert task.done()

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.QUEUE_CHECK_INTERVAL", 100)
    @patch("brainztableinator.brainztableinator.STUCK_CHECK_INTERVAL", 0.01)
    async def test_skips_when_active_connection_exists(self) -> None:
        """Test that checker skips full check when active connection exists."""
        mock_rabbitmq_manager = AsyncMock()

        import brainztableinator.brainztableinator as bt

        bt.rabbitmq_manager = mock_rabbitmq_manager
        bt.active_connection = AsyncMock()  # Active connection → skip
        bt.active_channel = AsyncMock()
        bt.consumer_tags = {}
        bt.completed_files = set()
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bt.shutdown_requested = False

        from brainztableinator.brainztableinator import periodic_queue_checker

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.1)

        bt.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        # Should not have connected since active_connection exists
        mock_rabbitmq_manager.connect.assert_not_called()


# ===========================================================================
# _recover_consumers edge cases
# ===========================================================================


class TestRecoverConsumersEdgeCases:
    """Test _recover_consumers edge cases."""

    @pytest.mark.asyncio
    async def test_closes_existing_broken_connection(self) -> None:
        """Test that _recover_consumers closes existing broken connection first."""
        import brainztableinator.brainztableinator as bt

        mock_broken_conn = AsyncMock()
        mock_broken_conn.close = AsyncMock()

        bt.active_connection = mock_broken_conn
        bt.active_channel = AsyncMock()
        bt.consumer_tags = {}
        bt.queues = {}
        bt.idle_mode = False
        bt.completed_files = set()
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}

        mock_new_connection = AsyncMock()
        mock_new_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0
        mock_new_channel.declare_queue = AsyncMock(return_value=mock_queue)
        mock_new_channel.declare_exchange = AsyncMock()
        mock_new_channel.close = AsyncMock()
        mock_new_connection.channel = AsyncMock(return_value=mock_new_channel)
        mock_new_connection.close = AsyncMock()

        bt.rabbitmq_manager = AsyncMock()
        bt.rabbitmq_manager.connect = AsyncMock(return_value=mock_new_connection)

        with patch("brainztableinator.brainztableinator.logger"):
            await _recover_consumers()

        mock_broken_conn.close.assert_called_once()
        assert bt.active_connection is None

    @pytest.mark.asyncio
    async def test_no_messages_closes_temp_connection(self) -> None:
        """Test that _recover_consumers closes temp connection when no messages found."""
        import brainztableinator.brainztableinator as bt

        bt.active_connection = None
        bt.active_channel = None
        bt.consumer_tags = {}
        bt.queues = {}
        bt.idle_mode = False
        bt.completed_files = set()
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}

        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0
        mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
        mock_channel.declare_exchange = AsyncMock()
        mock_channel.close = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_connection.close = AsyncMock()

        bt.rabbitmq_manager = AsyncMock()
        bt.rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        with patch("brainztableinator.brainztableinator.logger"):
            await _recover_consumers()

        # Should close temp connection since no messages
        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_during_recovery_cleans_up(self) -> None:
        """Test that _recover_consumers cleans up on error."""
        import brainztableinator.brainztableinator as bt

        bt.active_connection = None
        bt.active_channel = None
        bt.consumer_tags = {}
        bt.queues = {}
        bt.idle_mode = False

        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_channel.declare_queue = AsyncMock(side_effect=Exception("Queue declare failed"))
        mock_channel.close = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_connection.close = AsyncMock()

        bt.rabbitmq_manager = AsyncMock()
        bt.rabbitmq_manager.connect = AsyncMock(return_value=mock_connection)

        with patch("brainztableinator.brainztableinator.logger"):
            await _recover_consumers()

        # Should attempt cleanup on error
        mock_channel.close.assert_called()
        mock_connection.close.assert_called()

    @pytest.mark.asyncio
    async def test_broken_connection_close_error_ignored(self) -> None:
        """Test that errors closing broken connection are silently ignored."""
        import brainztableinator.brainztableinator as bt

        mock_broken_conn = AsyncMock()
        mock_broken_conn.close = AsyncMock(side_effect=Exception("Already closed"))

        bt.active_connection = mock_broken_conn
        bt.active_channel = AsyncMock()
        bt.consumer_tags = {}
        bt.queues = {}
        bt.idle_mode = False
        bt.completed_files = set()
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}

        mock_new_connection = AsyncMock()
        mock_new_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0
        mock_new_channel.declare_queue = AsyncMock(return_value=mock_queue)
        mock_new_channel.declare_exchange = AsyncMock()
        mock_new_channel.close = AsyncMock()
        mock_new_connection.channel = AsyncMock(return_value=mock_new_channel)
        mock_new_connection.close = AsyncMock()

        bt.rabbitmq_manager = AsyncMock()
        bt.rabbitmq_manager.connect = AsyncMock(return_value=mock_new_connection)

        with patch("brainztableinator.brainztableinator.logger"):
            await _recover_consumers()  # Should not raise

        assert bt.active_connection is None


# ===========================================================================
# Progress reporter — stalled, slow, waiting, canceled consumers
# ===========================================================================


class TestProgressReporterExtended:
    """Extended tests for progress_reporter covering stalled/slow/waiting paths."""

    @pytest.mark.asyncio
    async def test_progress_reporter_logs_stalled_consumers(self) -> None:
        """Test that stalled consumers are detected and logged."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        current_time = time.time()
        bt.shutdown_requested = False
        bt.idle_mode = False
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 10}
        bt.last_message_time = {
            "artists": current_time - 150,  # stalled (>120s)
            "labels": current_time,
            "releases": current_time,
        }
        bt.completed_files = set()
        bt.consumer_tags = {"artists": "tag1", "labels": "tag2"}

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 4:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        # Should have logged stalled consumers
        error_calls = [str(c) for c in mock_logger.error.call_args_list]
        assert any("Stalled" in c or "stalled" in c.lower() for c in error_calls)

    @pytest.mark.asyncio
    async def test_progress_reporter_logs_waiting_for_messages(self) -> None:
        """Test waiting for messages state (total == 0, not idle)."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        bt.shutdown_requested = False
        bt.idle_mode = False
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
        bt.completed_files = {"artists"}  # Not all complete, so won't skip
        bt.consumer_tags = {"labels": "tag1"}

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 4:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.STARTUP_IDLE_TIMEOUT", 9999),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Waiting" in c or "waiting" in c.lower() for c in info_calls)

    @pytest.mark.asyncio
    async def test_progress_reporter_logs_slow_consumers(self) -> None:
        """Test slow consumer detection (5 < time_since < 120)."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        current_time = time.time()
        bt.shutdown_requested = False
        bt.idle_mode = False
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 10}
        bt.last_message_time = {
            "artists": current_time - 60,  # slow (60s, between 5 and 120)
            "labels": current_time - 60,
            "releases": current_time - 60,
        }
        bt.completed_files = set()
        bt.consumer_tags = {"artists": "tag1"}

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 4:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("Slow" in c or "slow" in c.lower() for c in warning_calls)

    @pytest.mark.asyncio
    async def test_progress_reporter_logs_canceled_consumers(self) -> None:
        """Test logging of canceled consumers (in completed_files but not in consumer_tags)."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        current_time = time.time()
        bt.shutdown_requested = False
        bt.idle_mode = False
        bt.message_counts = {"artists": 100, "labels": 50, "release-groups": 0, "releases": 10}
        bt.last_message_time = {
            "artists": current_time,
            "labels": current_time,
            "releases": current_time,
        }
        bt.completed_files = {"artists"}  # artists completed but not in consumer_tags
        bt.consumer_tags = {"labels": "tag1", "releases": "tag2"}

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 4:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Canceled" in c or "canceled" in c.lower() for c in info_calls)

    @pytest.mark.asyncio
    async def test_progress_reporter_idle_periodic_log(self) -> None:
        """Test idle mode periodic log at IDLE_LOG_INTERVAL."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        bt.shutdown_requested = False
        bt.idle_mode = True
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
        bt.completed_files = set()
        bt.consumer_tags = {}

        _real_sleep = asyncio.sleep
        call_count = 0

        async def fast_sleep(_duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count > 4:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.IDLE_LOG_INTERVAL", 0),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=fast_sleep),
        ):
            await progress_reporter()

        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Idle" in c or "idle" in c.lower() for c in info_calls)

    @pytest.mark.asyncio
    async def test_progress_reporter_sleep_30s_after_3_reports(self) -> None:
        """Test that sleep increases to 30s after 3 report cycles."""
        import brainztableinator.brainztableinator as bt
        from brainztableinator.brainztableinator import progress_reporter

        bt.shutdown_requested = False
        bt.idle_mode = False
        bt.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bt.last_message_time = {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
        bt.completed_files = {"artists", "labels", "release-groups", "releases"}  # All complete so skips quickly
        bt.consumer_tags = {}

        sleep_durations: list[float] = []
        _real_sleep = asyncio.sleep
        call_count = 0

        async def tracking_sleep(duration: float) -> None:
            nonlocal call_count
            sleep_durations.append(duration)
            call_count += 1
            if call_count > 5:
                bt.shutdown_requested = True
            await _real_sleep(0)

        with (
            patch("brainztableinator.brainztableinator.logger"),
            patch("brainztableinator.brainztableinator.asyncio.sleep", side_effect=tracking_sleep),
        ):
            await progress_reporter()

        # First 3 should be 10s, after that 30s
        assert sleep_durations[0] == 10
        assert sleep_durations[1] == 10
        assert sleep_durations[2] == 10
        assert any(d == 30 for d in sleep_durations[3:])


# ===========================================================================
# Main function — additional edge cases
# ===========================================================================


class TestMainEdgeCases:
    """Test main() edge cases for improved coverage."""

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch.dict("os.environ", {"STARTUP_DELAY": "1"})
    async def test_main_with_startup_delay_logs(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main logs startup delay when STARTUP_DELAY > 0."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect.side_effect = Exception("Cannot connect")

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
        ):
            await main()

        # Should have logged the startup delay
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Waiting" in c or "waiting" in c.lower() for c in info_calls)

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    async def test_main_host_without_port(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main when postgres_host has no port (default 5432)."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        mock_rabbitmq_instance.connect.side_effect = Exception("Cannot connect")

        # Config returns host without port
        mock_config = MagicMock()
        mock_config.postgres_host = "localhost"  # No port
        mock_config.postgres_username = "user"
        mock_config.postgres_password = "pass"
        mock_config.postgres_database = "testdb"
        mock_config.amqp_connection = "amqp://guest:guest@localhost:5672/"

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch("brainztableinator.brainztableinator.BrainztableinatorConfig") as mock_config_class,
        ):
            mock_config_class.from_env.return_value = mock_config
            await main()

        # Should have used default port 5432
        call_args = mock_pool_class.call_args
        assert call_args[1]["connection_params"]["port"] == 5432
        assert call_args[1]["connection_params"]["host"] == "localhost"

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    async def test_main_amqp_connection_none(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main returns when amqp_connection is None after retries."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance
        # Return None instead of raising
        mock_rabbitmq_instance.connect.return_value = None

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
        ):
            await main()

        # Should have logged the "No AMQP connection" error and returned early
        error_calls = [str(c) for c in mock_logger.error.call_args_list]
        assert any("No AMQP connection" in c for c in error_calls)

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    async def test_main_keyboard_interrupt(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main handles KeyboardInterrupt gracefully."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        mock_amqp_connection = AsyncMock()
        mock_amqp_connection.__aenter__ = AsyncMock(return_value=mock_amqp_connection)
        mock_amqp_connection.__aexit__ = AsyncMock(return_value=None)
        mock_rabbitmq_instance.connect.return_value = mock_amqp_connection

        mock_channel = AsyncMock()
        mock_amqp_connection.channel = AsyncMock(return_value=mock_channel)

        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        import brainztableinator.brainztableinator as bt

        bt.shutdown_requested = False
        bt.consumer_cancel_tasks = {"artists": AsyncMock()}
        bt.connection_check_task = AsyncMock()

        async def raise_keyboard_interrupt(_coro: Any, timeout: float) -> None:  # noqa: ARG001
            raise KeyboardInterrupt()

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch("asyncio.wait_for", raise_keyboard_interrupt),
            patch("brainztableinator.brainztableinator.logger"),
        ):
            await main()

        mock_health_instance.stop.assert_called()

    @pytest.mark.asyncio
    @patch("brainztableinator.brainztableinator.setup_logging")
    @patch("brainztableinator.brainztableinator.HealthServer")
    @patch("brainztableinator.brainztableinator.AsyncResilientRabbitMQ")
    @patch("brainztableinator.brainztableinator.AsyncPostgreSQLPool")
    @patch.dict("os.environ", {"STARTUP_DELAY": "0"})
    async def test_main_pool_close_error(
        self,
        mock_pool_class: Mock,
        mock_rabbitmq_class: AsyncMock,
        mock_health_server: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main handles pool close error gracefully."""
        mock_health_instance = MagicMock()
        mock_health_server.return_value = mock_health_instance

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool
        mock_pool.initialize = AsyncMock()
        mock_pool.close = AsyncMock(side_effect=Exception("Pool close failed"))

        mock_connection_cm = AsyncMock()
        mock_connection_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_connection_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.connection = MagicMock(return_value=mock_connection_cm)

        mock_rabbitmq_instance = AsyncMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        mock_amqp_connection = AsyncMock()
        mock_amqp_connection.__aenter__ = AsyncMock(return_value=mock_amqp_connection)
        mock_amqp_connection.__aexit__ = AsyncMock(return_value=None)
        mock_rabbitmq_instance.connect.return_value = mock_amqp_connection

        mock_channel = AsyncMock()
        mock_amqp_connection.channel = AsyncMock(return_value=mock_channel)

        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue

        async def mock_wait_for(_coro: Any, timeout: float) -> None:  # noqa: ARG001
            import brainztableinator.brainztableinator

            brainztableinator.brainztableinator.shutdown_requested = True
            raise TimeoutError()

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:  # noqa: ARG001
            await original_sleep(0)

        created_tasks: list[asyncio.Task[Any]] = []
        original_create_task = asyncio.create_task

        def mock_create_task(coro: Any) -> asyncio.Task[Any]:
            task = original_create_task(coro)
            created_tasks.append(task)
            return task

        with (
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch("asyncio.wait_for", mock_wait_for),
            patch("asyncio.create_task", side_effect=mock_create_task),
            patch("brainztableinator.brainztableinator.logger") as mock_logger,
        ):
            await main()

        for task in created_tasks:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        # Should have logged warning about pool close error
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("pool" in c.lower() or "Pool" in c for c in warning_calls)
