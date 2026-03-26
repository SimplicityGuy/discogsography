"""Tests for the brainztableinator service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainztableinator.brainztableinator import (
    PROCESSORS,
    _insert_external_link,
    _insert_relationship,
    check_all_consumers_idle,
    get_health_data,
    make_data_handler,
    on_data_message,
    process_artist,
    process_label,
    process_release,
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
                {"artists": 0, "labels": 0, "releases": 0},
            ),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "releases": 0.0},
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
                {"artists": 0, "labels": 0, "releases": 0},
            ),
            patch("brainztableinator.brainztableinator.completed_files", set()),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "releases": 0.0},
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
                {"artists": 0, "labels": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "releases": 0.0},
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
                {"artists": 0, "labels": 0, "releases": 0, "unknown_type": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "releases": 0.0, "unknown_type": 0.0},
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
                {"artists": 0, "labels": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "releases": 0.0},
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
                {"artists": 0, "labels": 0, "releases": 0},
            ),
            patch(
                "brainztableinator.brainztableinator.last_message_time",
                {"artists": 0.0, "labels": 0.0, "releases": 0.0},
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
                {"artists", "labels", "releases"},
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
                {"artists", "labels", "releases"},
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

    def test_processors_maps_releases(self):
        """PROCESSORS should map 'releases' to process_release."""
        assert PROCESSORS["releases"] is process_release

    def test_processors_has_exactly_three_entries(self):
        """PROCESSORS should have exactly 3 data types."""
        assert len(PROCESSORS) == 3
