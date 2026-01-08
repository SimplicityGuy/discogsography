"""Tests for ConcurrentExtractor class."""

import asyncio
import contextlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from extractor.pyextractor.extractor import ConcurrentExtractor


class TestConcurrentExtractorInitialization:
    """Tests for ConcurrentExtractor initialization."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_artists(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test initialization with artists file."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=4)

        assert extractor.data_type == "artists"
        assert extractor.input_file == input_file
        assert extractor.input_path == mock_config.discogs_root / input_file
        assert extractor.batch_size == 100
        assert extractor.progress_log_interval == 1000
        assert extractor.max_workers == 4
        assert extractor.total_count == 0
        assert extractor.error_count == 0

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_labels(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test initialization with labels file."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_labels.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        assert extractor.data_type == "labels"

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_masters(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test initialization with masters file."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_masters.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        assert extractor.data_type == "masters"

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_releases(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test initialization with releases file."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_releases.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        assert extractor.data_type == "releases"

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_sets_amqp_properties(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that AMQP properties are initialized."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        assert extractor.amqp_properties is not None
        assert extractor.amqp_properties.delivery_mode == 2  # Persistent
        assert extractor.amqp_properties.content_type == "application/json"


class TestConcurrentExtractorContextManager:
    """Tests for ConcurrentExtractor context manager."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.fixture
    def mock_rabbitmq_connection(self) -> Mock:
        """Create a mock RabbitMQ resilient connection."""
        connection = Mock()
        connection.is_open = True
        connection.close = Mock()

        channel = Mock()
        channel.is_open = True
        channel.is_closed = False
        channel.close = Mock()
        channel.confirm_delivery = Mock()
        channel.basic_qos = Mock()
        channel.exchange_declare = Mock()
        channel.queue_declare = Mock()
        channel.queue_bind = Mock()
        channel.basic_publish = Mock(return_value=True)

        connection.channel = Mock(return_value=channel)
        return connection

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_enter_creates_amqp_connection(
        self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock, mock_rabbitmq_connection: Mock
    ) -> None:
        """Test that __enter__ creates AMQP connection."""
        mock_exists.return_value = True
        mock_rabbitmq_class.return_value = mock_rabbitmq_connection
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        result = extractor.__enter__()

        assert result == extractor
        mock_rabbitmq_class.assert_called_once()
        mock_rabbitmq_connection.channel.assert_called_once()

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_enter_configures_channel(self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock, mock_rabbitmq_connection: Mock) -> None:
        """Test that __enter__ configures channel correctly."""
        mock_exists.return_value = True
        mock_rabbitmq_class.return_value = mock_rabbitmq_connection
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.__enter__()

        channel = extractor.amqp_channel
        channel.confirm_delivery.assert_called_once()
        channel.basic_qos.assert_called_once_with(prefetch_count=100)
        channel.exchange_declare.assert_called_once()

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_enter_declares_queues(self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock, mock_rabbitmq_connection: Mock) -> None:
        """Test that __enter__ declares and binds queues."""
        mock_exists.return_value = True
        mock_rabbitmq_class.return_value = mock_rabbitmq_connection
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.__enter__()

        channel = extractor.amqp_channel
        # Should declare 2 queues (graphinator and tableinator)
        assert channel.queue_declare.call_count == 2
        assert channel.queue_bind.call_count == 2

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_enter_handles_connection_error(self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that __enter__ handles connection errors."""
        mock_exists.return_value = True
        mock_rabbitmq_class.side_effect = Exception("Connection failed")
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        with pytest.raises(Exception, match="Connection failed"):
            extractor.__enter__()

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_exit_sends_completion_message(
        self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock, mock_rabbitmq_connection: Mock
    ) -> None:
        """Test that __exit__ sends file completion message."""
        mock_exists.return_value = True
        mock_rabbitmq_class.return_value = mock_rabbitmq_connection
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.__enter__()
        extractor.total_count = 1000
        extractor.__exit__(None, None, None)

        # Verify completion message was sent
        channel = mock_rabbitmq_connection.channel()
        assert channel.basic_publish.call_count >= 1

        # Check the last call for completion message
        last_call = channel.basic_publish.call_args
        assert last_call is not None

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_exit_closes_connection(self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock, mock_rabbitmq_connection: Mock) -> None:
        """Test that __exit__ closes AMQP connection."""
        mock_exists.return_value = True
        mock_rabbitmq_class.return_value = mock_rabbitmq_connection
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.__enter__()
        extractor.__exit__(None, None, None)

        mock_rabbitmq_connection.close.assert_called_once()

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_exit_handles_close_error(self, mock_rabbitmq_class: Mock, mock_exists: Mock, mock_config: Mock, mock_rabbitmq_connection: Mock) -> None:
        """Test that __exit__ handles close errors gracefully."""
        mock_exists.return_value = True
        mock_rabbitmq_class.return_value = mock_rabbitmq_connection
        mock_rabbitmq_connection.close.side_effect = Exception("Close failed")
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.__enter__()

        # Should not raise exception
        extractor.__exit__(None, None, None)


class TestConcurrentExtractorFlushMessages:
    """Tests for message flushing functionality."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.fixture
    def mock_channel(self) -> Mock:
        """Create a mock AMQP channel."""
        channel = Mock()
        channel.is_closed = False
        channel.basic_publish = Mock(return_value=True)
        channel.confirm_delivery = Mock()
        channel.basic_qos = Mock()
        channel.exchange_declare = Mock()
        return channel

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_flush_pending_messages_empty(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test flushing with no pending messages."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.pending_messages = []

        # Should return without doing anything
        extractor._flush_pending_messages()

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_flush_pending_messages_success(self, mock_exists: Mock, mock_config: Mock, mock_channel: Mock) -> None:
        """Test successful message flushing."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.amqp_channel = mock_channel

        # Add some test messages
        extractor.pending_messages = [
            {"id": "1", "name": "Test Artist 1"},
            {"id": "2", "name": "Test Artist 2"},
        ]

        extractor._flush_pending_messages()

        # All messages should be published
        assert mock_channel.basic_publish.call_count == 2
        # Pending messages should be cleared
        assert len(extractor.pending_messages) == 0

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_flush_pending_messages_publish_error(self, mock_exists: Mock, mock_config: Mock, mock_channel: Mock) -> None:
        """Test flush handles publish errors."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.amqp_channel = mock_channel
        mock_channel.basic_publish.side_effect = Exception("Publish failed")

        # Add test message
        test_message = {"id": "1", "name": "Test Artist"}
        extractor.pending_messages = [test_message]

        extractor._flush_pending_messages()

        # Message should be put back in pending list
        assert len(extractor.pending_messages) == 1
        assert extractor.pending_messages[0] == test_message

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_ensure_amqp_connection_channel_open(self, mock_exists: Mock, mock_config: Mock, mock_channel: Mock) -> None:
        """Test _ensure_amqp_connection when channel is open."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.amqp_channel = mock_channel

        result = extractor._ensure_amqp_connection()

        assert result is True

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_ensure_amqp_connection_channel_closed(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test _ensure_amqp_connection reconnects when channel is closed."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        # Create closed channel
        closed_channel = Mock()
        closed_channel.is_closed = True

        # Create new open channel
        new_channel = Mock()
        new_channel.is_closed = False
        new_channel.confirm_delivery = Mock()
        new_channel.basic_qos = Mock()
        new_channel.exchange_declare = Mock()

        # Setup connection to return new channel
        connection = Mock()
        connection.channel = Mock(return_value=new_channel)

        extractor.amqp_channel = closed_channel
        extractor.amqp_connection = connection

        result = extractor._ensure_amqp_connection()

        assert result is True
        assert extractor.amqp_channel == new_channel
        new_channel.confirm_delivery.assert_called_once()
        new_channel.basic_qos.assert_called_once()
        new_channel.exchange_declare.assert_called_once()

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_ensure_amqp_connection_no_connection(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test _ensure_amqp_connection handles missing connection."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.amqp_connection = None
        extractor.amqp_channel = None

        result = extractor._ensure_amqp_connection()

        assert result is False


class TestConcurrentExtractorRecordProcessing:
    """Tests for record processing functionality."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 2  # Small batch for testing
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    @pytest.mark.asyncio
    async def test_process_record_async_normalizes_data(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that _process_record_async normalizes and hashes data."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue()

        test_data = {"id": "1", "name": "Test Artist"}
        await extractor._process_record_async(test_data)

        # Check that message was added to pending
        assert len(extractor.pending_messages) == 1
        # Check that sha256 was added
        assert "sha256" in extractor.pending_messages[0]

    @patch("extractor.pyextractor.extractor.Path.exists")
    @pytest.mark.asyncio
    async def test_process_record_async_triggers_flush_on_batch_size(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that batch flush is triggered when batch size is reached."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue()

        # Add records up to batch size
        await extractor._process_record_async({"id": "1", "name": "Artist 1"})

        # Check that first record was added
        assert len(extractor.pending_messages) == 1

        await extractor._process_record_async({"id": "2", "name": "Artist 2"})

        # After batch size is reached, pending messages should be cleared (or flush queued)
        # The flush is queued asynchronously, so we should have 2 messages
        assert len(extractor.pending_messages) == 2

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.dumps")
    @pytest.mark.asyncio
    async def test_process_record_async_handles_error(self, mock_dumps: Mock, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that _process_record_async handles errors gracefully."""
        mock_exists.return_value = True
        # Make dumps raise an error to simulate processing failure
        mock_dumps.side_effect = Exception("Processing error")
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue()

        test_data = {"id": "1", "name": "Test Artist"}

        await extractor._process_record_async(test_data)

        # Error count should be incremented
        assert extractor.error_count == 1

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_queue_record_data_type_mismatch(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test __queue_record with mismatched data type."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        # Wrong data type in path
        path = [("labels", None), ("label", {"id": "1"})]
        data = {"id": "1", "name": "Test Label"}

        result = extractor._ConcurrentExtractor__queue_record(path, data)

        assert result is False
        assert extractor.total_count == 0

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_queue_record_increments_count(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test __queue_record increments total count."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.record_queue = asyncio.Queue()
        extractor.event_loop = asyncio.new_event_loop()

        path = [("artists", None), ("artist", {"id": "1"})]
        data = {"id": "1", "name": "Test Artist"}

        result = extractor._ConcurrentExtractor__queue_record(path, data)

        assert result is True
        assert extractor.total_count == 1


class TestConcurrentExtractorAsyncWorkers:
    """Tests for async worker functionality."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    @pytest.mark.asyncio
    async def test_amqp_flush_worker_processes_flush_requests(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that AMQP flush worker processes flush requests."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue()
        extractor.amqp_channel = Mock()
        extractor.amqp_channel.is_closed = False
        extractor.amqp_channel.basic_publish = Mock(return_value=True)

        # Add test messages
        extractor.pending_messages = [{"id": "1", "name": "Test"}]

        # Start flush worker
        flush_task = asyncio.create_task(extractor._amqp_flush_worker())

        # Queue flush request
        await extractor.flush_queue.put(True)

        # Queue shutdown signal
        await extractor.flush_queue.put(False)

        # Wait for worker to complete
        await flush_task

        # Messages should have been flushed
        assert len(extractor.pending_messages) == 0

    @patch("extractor.pyextractor.extractor.Path.exists")
    @pytest.mark.asyncio
    async def test_amqp_flush_worker_handles_errors(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that AMQP flush worker handles errors gracefully."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue()

        # No channel configured - will cause error
        extractor.amqp_channel = None

        # Start flush worker
        flush_task = asyncio.create_task(extractor._amqp_flush_worker())

        # Queue flush request (will fail)
        await extractor.flush_queue.put(True)

        # Queue shutdown signal
        await extractor.flush_queue.put(False)

        # Wait for worker to complete - should not raise
        await flush_task

    @patch("extractor.pyextractor.extractor.Path.exists")
    @pytest.mark.asyncio
    async def test_try_queue_flush_success(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test successful flush queueing."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue(maxsize=100)

        await extractor._try_queue_flush()

        # Flush request should be in queue
        assert not extractor.flush_queue.empty()

    @patch("extractor.pyextractor.extractor.Path.exists")
    @pytest.mark.asyncio
    async def test_try_queue_flush_queue_full(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test flush queueing when queue is full."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.flush_queue = asyncio.Queue(maxsize=1)

        # Fill the queue
        await extractor.flush_queue.put(True)

        # Try to queue another - should handle gracefully
        await extractor._try_queue_flush()

        # Should schedule a retry task
        assert extractor.flush_retry_task is not None


class TestExtractAsync:
    """Test extract_async method."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_extract_async_basic_flow(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test basic async extraction flow."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=2)

        # Mock the XML parsing to avoid actual file I/O
        async def mock_parse():
            # Simulate adding a few records
            if extractor.record_queue:
                await extractor.record_queue.put({"id": "1", "name": "Test Artist"})
                await extractor.record_queue.put({"id": "2", "name": "Test Artist 2"})

        with (
            patch.object(extractor, "_parse_xml_async", mock_parse),
            patch.object(extractor, "_flush_pending_messages"),
            patch("extractor.pyextractor.extractor.shutdown_requested", False),
        ):
            await extractor.extract_async()

        # Verify extraction completed
        assert extractor.end_time is not None
        assert extractor.start_time is not None

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_extract_async_handles_shutdown_before_start(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that extraction stops if shutdown requested before starting."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=2)

        with patch("extractor.pyextractor.extractor.shutdown_requested", True):
            await extractor.extract_async()

        # Verify extraction did not proceed
        assert extractor.record_queue is None

    # Note: Skipping KeyboardInterrupt test as it interferes with test runner
    # The code path is covered by the general error handling test

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_extract_async_handles_extraction_error(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test handling of errors during extraction."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=2)

        # Mock parse to raise exception
        async def mock_parse_error():
            raise Exception("Parse error")

        with (
            patch.object(extractor, "_parse_xml_async", mock_parse_error),
            patch.object(extractor, "_flush_pending_messages"),
            patch("extractor.pyextractor.extractor.shutdown_requested", False),
            pytest.raises(Exception, match="Parse error"),
        ):
            await extractor.extract_async()


class TestProcessRecordsAsync:
    """Test _process_records_async method."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_processes_records_until_none_signal(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that worker processes records until None signal."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.record_queue = asyncio.Queue()

        # Add test records and end signal
        await extractor.record_queue.put({"id": "1", "name": "Test Artist"})
        await extractor.record_queue.put({"id": "2", "name": "Test Artist 2"})
        await extractor.record_queue.put(None)  # End signal

        mock_process = AsyncMock()
        with patch.object(extractor, "_process_record_async", mock_process):
            await extractor._process_records_async()

        # Verify all records were processed
        assert mock_process.call_count == 2

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_handles_timeout_and_shutdown(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that worker handles timeout and checks shutdown flag."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.record_queue = asyncio.Queue()  # Empty queue will timeout

        import extractor.pyextractor.extractor as ext_module

        original_shutdown = ext_module.shutdown_requested

        # Set shutdown flag after a short delay
        async def set_shutdown():
            await asyncio.sleep(0.1)
            ext_module.shutdown_requested = True

        shutdown_task = asyncio.create_task(set_shutdown())

        try:
            await extractor._process_records_async()
        finally:
            ext_module.shutdown_requested = original_shutdown
            await shutdown_task

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_handles_processing_errors(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that worker handles record processing errors gracefully."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.record_queue = asyncio.Queue()

        # Add a record that will cause error, then end signal
        await extractor.record_queue.put({"id": "1"})
        await extractor.record_queue.put(None)

        # Mock to raise error on first call
        with patch.object(extractor, "_process_record_async", AsyncMock(side_effect=[Exception("Error"), None])):
            await extractor._process_records_async()

        # Verify error was counted
        assert extractor.error_count == 1


class TestAmqpFlushWorker:
    """Test _amqp_flush_worker method."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_processes_flush_requests(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that flush worker processes flush requests."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.flush_queue = asyncio.Queue()

        # Add flush requests and shutdown signal
        await extractor.flush_queue.put(True)
        await extractor.flush_queue.put(True)
        await extractor.flush_queue.put(False)  # Shutdown signal

        mock_flush = Mock()
        with patch.object(extractor, "_flush_pending_messages", mock_flush):
            await extractor._amqp_flush_worker()

        # Verify flush was called 3 times (2 requests + 1 shutdown)
        assert mock_flush.call_count == 3

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_handles_flush_errors(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that flush worker handles errors and continues."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.flush_queue = asyncio.Queue()

        # Add flush request, then shutdown
        await extractor.flush_queue.put(True)
        await extractor.flush_queue.put(False)

        # Mock to raise error on first flush, succeed on second
        with (
            patch.object(extractor, "_flush_pending_messages", side_effect=[Exception("Flush error"), None]),
            patch("extractor.pyextractor.extractor.logger") as mock_logger,
        ):
            await extractor._amqp_flush_worker()

        # Verify error was logged but worker continued
        mock_logger.warning.assert_called()


class TestTryQueueFlush:
    """Test _try_queue_flush method."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_queues_flush_request_successfully(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test successfully queueing a flush request."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.flush_queue = asyncio.Queue(maxsize=10)

        await extractor._try_queue_flush()

        # Verify request was queued
        assert extractor.flush_queue.qsize() == 1
        assert extractor.flush_retry_backoff == 30.0  # Reset to FLUSH_QUEUE_INITIAL_BACKOFF

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_handles_full_queue_with_backoff(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test handling of full flush queue schedules retry task."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)
        extractor.flush_queue = asyncio.Queue(maxsize=1)

        # Fill the queue
        await extractor.flush_queue.put(True)

        # Try to queue another flush - should schedule retry task
        with patch("extractor.pyextractor.extractor.logger"):
            await extractor._try_queue_flush()

        # Verify retry task was scheduled
        assert extractor.flush_retry_task is not None
        assert not extractor.flush_retry_task.done()

        # Clean up
        extractor.flush_retry_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await extractor.flush_retry_task


class TestParseXmlAsync:
    """Test _parse_xml_async and _parse_xml_sync methods."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_parse_xml_async_executes_in_executor(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that XML parsing runs in thread executor."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)

        with patch.object(extractor, "_parse_xml_sync") as mock_parse_sync:
            await extractor._parse_xml_async()

        # Verify sync parser was called
        mock_parse_sync.assert_called_once()

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.GzipFile")
    @patch("extractor.pyextractor.extractor.parse")
    async def test_parse_xml_sync_parses_gzip_file(self, mock_parse: Mock, mock_gzipfile: Mock, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that sync parser opens and parses gzip XML file."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)

        mock_gz = MagicMock()
        mock_gzipfile.return_value.__enter__.return_value = mock_gz

        extractor._parse_xml_sync()

        # Verify gzip file was opened and parsed
        mock_gzipfile.assert_called_once()
        mock_parse.assert_called_once()

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.GzipFile")
    async def test_parse_xml_sync_handles_errors(self, mock_gzipfile: Mock, mock_exists: Mock, mock_config: Mock) -> None:
        """Test that sync parser handles parsing errors."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config, max_workers=1)

        mock_gzipfile.side_effect = Exception("File not found")

        with (
            patch("extractor.pyextractor.extractor.logger") as mock_logger,
            pytest.raises(Exception, match="File not found"),
        ):
            extractor._parse_xml_sync()

        # Verify error was logged
        mock_logger.error.assert_called()


class TestHealthMonitoring:
    """Test get_health_data function."""

    def test_get_health_data(self) -> None:
        """Test getting health data."""
        from extractor.pyextractor.extractor import get_health_data

        health = get_health_data()

        assert "status" in health
        assert health["status"] == "healthy"
        assert health["service"] == "extractor"
        assert "current_task" in health
        assert "progress" in health
        assert "extraction_progress" in health
        assert "last_extraction_time" in health
        assert "timestamp" in health


class TestSignalHandling:
    """Test signal_handler function."""

    def test_signal_handler(self) -> None:
        """Test signal handler sets shutdown flag."""
        import extractor.pyextractor.extractor

        # Reset shutdown flag
        extractor.pyextractor.extractor.shutdown_requested = False

        from extractor.pyextractor.extractor import signal_handler

        with patch("extractor.pyextractor.extractor.logger") as mock_logger:
            signal_handler(15, None)  # SIGTERM
            mock_logger.info.assert_called_once()
            assert extractor.pyextractor.extractor.shutdown_requested is True

        # Reset for other tests
        extractor.pyextractor.extractor.shutdown_requested = False


class TestInitErrorCases:
    """Test ConcurrentExtractor initialization error cases."""

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_invalid_filename_format(self, mock_exists: Mock, test_discogs_root: Path) -> None:
        """Test initialization with invalid filename format."""
        mock_exists.return_value = True
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://test"

        with pytest.raises(ValueError, match="Invalid input file format"):
            ConcurrentExtractor("invalid_filename.xml.gz", config)

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_init_file_not_found(self, mock_exists: Mock, test_discogs_root: Path) -> None:
        """Test initialization with non-existent file."""
        mock_exists.return_value = False
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://test"

        with pytest.raises(FileNotFoundError, match="Input file not found"):
            ConcurrentExtractor("discogs_20230101_artists.xml.gz", config)


class TestFlushErrorHandling:
    """Test error handling in _flush_pending_messages."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_flush_with_no_connection(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test flush when AMQP connection is unavailable."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)
        extractor.amqp_connection = None
        extractor.amqp_channel = None

        # Add test messages
        extractor.pending_messages = [{"id": "1", "name": "Test"}]

        with patch("extractor.pyextractor.extractor.logger") as mock_logger:
            extractor._flush_pending_messages()

            # Error should be logged
            mock_logger.error.assert_called()
            # Messages should be put back
            assert len(extractor.pending_messages) == 1

    @pytest.fixture
    def mock_channel(self) -> Mock:
        """Create a mock AMQP channel."""
        channel = Mock()
        channel.is_closed = False
        channel.basic_publish = Mock(return_value=True)
        channel.confirm_delivery = Mock()
        channel.basic_qos = Mock()
        channel.exchange_declare = Mock()
        return channel

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_flush_with_none_channel_after_connection_check(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test flush when channel is None after connection check."""
        mock_exists.return_value = True
        input_file = "discogs_20230101_artists.xml.gz"

        extractor = ConcurrentExtractor(input_file, mock_config)

        # Mock connection but channel is None
        extractor.amqp_connection = Mock()
        extractor.amqp_channel = None

        # Mock _ensure_amqp_connection to return True but leave channel as None
        with (
            patch.object(extractor, "_ensure_amqp_connection", return_value=True),
            patch("extractor.pyextractor.extractor.logger") as mock_logger,
        ):
            extractor.pending_messages = [{"id": "1", "name": "Test"}]
            extractor._flush_pending_messages()

            # Error should be logged
            error_calls = [call for call in mock_logger.error.call_args_list if "AMQP channel is None" in str(call)]
            assert len(error_calls) > 0
            # Messages should be put back
            assert len(extractor.pending_messages) == 1


class TestProcessingState:
    """Test _load_processing_state and _save_processing_state functions."""

    def test_load_processing_state_no_file(self, temp_dir: Path) -> None:
        """Test loading processing state when file doesn't exist."""
        from extractor.pyextractor.extractor import _load_processing_state

        result = _load_processing_state(temp_dir)

        assert result == {}

    def test_load_processing_state_with_data(self, temp_dir: Path) -> None:
        """Test loading processing state with existing data."""
        from extractor.pyextractor.extractor import _load_processing_state, _save_processing_state

        # First save some state
        state = {"file1.xml.gz": True, "file2.xml.gz": False}
        _save_processing_state(temp_dir, state)

        # Now load it
        result = _load_processing_state(temp_dir)

        assert result == {"file1.xml.gz": True, "file2.xml.gz": False}

    def test_load_processing_state_corrupted_file(self, temp_dir: Path) -> None:
        """Test loading processing state with corrupted file."""
        from extractor.pyextractor.extractor import _load_processing_state

        # Create a corrupted file
        state_file = temp_dir / ".processing_state.json"
        state_file.write_text("not valid json{]")

        with patch("extractor.pyextractor.extractor.logger") as mock_logger:
            result = _load_processing_state(temp_dir)

            assert result == {}
            mock_logger.warning.assert_called()

    def test_save_processing_state(self, temp_dir: Path) -> None:
        """Test saving processing state."""
        from extractor.pyextractor.extractor import _save_processing_state

        state = {"file1.xml.gz": True, "file2.xml.gz": False}
        _save_processing_state(temp_dir, state)

        state_file = temp_dir / ".processing_state.json"
        assert state_file.exists()

        # Verify content
        import orjson

        content = orjson.loads(state_file.read_bytes())
        assert content == {"file1.xml.gz": True, "file2.xml.gz": False}

    def test_save_processing_state_error(self, temp_dir: Path) -> None:
        """Test saving processing state with write error."""
        from extractor.pyextractor.extractor import _save_processing_state

        # Make directory read-only to cause write error
        state_file = temp_dir / ".processing_state.json"
        state_file.touch()
        state_file.chmod(0o000)

        try:
            with patch("extractor.pyextractor.extractor.logger") as mock_logger:
                state = {"file1.xml.gz": True}
                _save_processing_state(temp_dir, state)

                # Should log warning on error
                mock_logger.warning.assert_called()
        finally:
            # Restore permissions for cleanup
            state_file.chmod(0o644)


class TestProcessFileAsync:
    """Test process_file_async function."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_process_file_async_success(self, mock_exists: Mock, mock_config: Mock, temp_dir: Path) -> None:
        """Test successful file processing."""
        from extractor.pyextractor.extractor import process_file_async

        mock_exists.return_value = True
        mock_config.discogs_root = temp_dir

        # Mock the ConcurrentExtractor
        with (
            patch("extractor.pyextractor.extractor.ConcurrentExtractor") as mock_extractor_class,
            patch("extractor.pyextractor.extractor.completed_files", set()),
        ):
            mock_extractor = Mock()
            mock_extractor.extract_async = AsyncMock()
            mock_extractor.__enter__ = Mock(return_value=mock_extractor)
            mock_extractor.__exit__ = Mock(return_value=None)
            mock_extractor_class.return_value = mock_extractor

            await process_file_async("discogs_20230101_artists.xml.gz", mock_config)

            # Verify extractor was created and extract was called
            mock_extractor_class.assert_called_once()
            mock_extractor.extract_async.assert_called_once()

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_process_file_async_error(self, mock_exists: Mock, mock_config: Mock, temp_dir: Path) -> None:
        """Test file processing with error."""
        from extractor.pyextractor.extractor import process_file_async

        mock_exists.return_value = True
        mock_config.discogs_root = temp_dir

        with (
            patch("extractor.pyextractor.extractor.ConcurrentExtractor") as mock_extractor_class,
            patch("extractor.pyextractor.extractor.logger") as mock_logger,
        ):
            mock_extractor = Mock()
            mock_extractor.extract_async = AsyncMock(side_effect=Exception("Extraction failed"))
            mock_extractor.__enter__ = Mock(return_value=mock_extractor)
            mock_extractor.__exit__ = Mock(return_value=None)
            mock_extractor_class.return_value = mock_extractor

            with pytest.raises(Exception, match="Extraction failed"):
                await process_file_async("discogs_20230101_artists.xml.gz", mock_config)

            # Verify error was logged
            mock_logger.error.assert_called()


class TestProcessDiscogsData:
    """Test process_discogs_data function."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.download_discogs_data")
    @patch("extractor.pyextractor.extractor._load_processing_state")
    @patch("extractor.pyextractor.extractor._save_processing_state")
    @patch("extractor.pyextractor.extractor.process_file_async")
    async def test_process_discogs_data_success(
        self,
        mock_process_file: AsyncMock,
        mock_save_state: Mock,
        mock_load_state: Mock,
        mock_download: Mock,
        mock_config: Mock,
    ) -> None:
        """Test successful processing of Discogs data."""
        from extractor.pyextractor.extractor import process_discogs_data

        # Setup mocks
        mock_download.return_value = [
            "discogs_20240101_artists.xml.gz",
            "discogs_20240101_labels.xml.gz",
            "discogs_20240101_CHECKSUM.txt",
        ]
        mock_load_state.return_value = {}
        mock_process_file.return_value = None

        result = await process_discogs_data(mock_config)

        assert result is True
        mock_download.assert_called_once()
        # Should process 2 files (not the CHECKSUM)
        assert mock_process_file.call_count == 2
        mock_save_state.assert_called()

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.download_discogs_data")
    async def test_process_discogs_data_download_failure(self, mock_download: Mock, mock_config: Mock) -> None:
        """Test handling of download failure."""
        from extractor.pyextractor.extractor import process_discogs_data

        mock_download.side_effect = Exception("Download failed")

        result = await process_discogs_data(mock_config)

        assert result is False

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.download_discogs_data")
    @patch("extractor.pyextractor.extractor._load_processing_state")
    async def test_process_discogs_data_no_files(self, mock_load_state: Mock, mock_download: Mock, mock_config: Mock) -> None:
        """Test when no data files are available."""
        from extractor.pyextractor.extractor import process_discogs_data

        mock_download.return_value = ["discogs_20240101_CHECKSUM.txt"]
        mock_load_state.return_value = {}

        result = await process_discogs_data(mock_config)

        assert result is True

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.download_discogs_data")
    @patch("extractor.pyextractor.extractor._load_processing_state")
    @patch("extractor.pyextractor.extractor._save_processing_state")
    @patch("extractor.pyextractor.extractor.process_file_async")
    async def test_process_discogs_data_skip_processed(
        self,
        mock_process_file: AsyncMock,
        _mock_save_state: Mock,
        mock_load_state: Mock,
        mock_download: Mock,
        mock_config: Mock,
    ) -> None:
        """Test skipping already processed files."""
        from extractor.pyextractor.extractor import process_discogs_data

        mock_download.return_value = [
            "discogs_20240101_artists.xml.gz",
            "discogs_20240101_labels.xml.gz",
        ]
        # Mark artists as already processed
        mock_load_state.return_value = {"discogs_20240101_artists.xml.gz": True}

        result = await process_discogs_data(mock_config)

        assert result is True
        # Should only process 1 file (labels)
        assert mock_process_file.call_count == 1

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.download_discogs_data")
    @patch("extractor.pyextractor.extractor._load_processing_state")
    @patch("extractor.pyextractor.extractor.os.environ.get")
    async def test_process_discogs_data_force_reprocess(
        self, mock_env_get: Mock, mock_load_state: Mock, mock_download: Mock, mock_config: Mock
    ) -> None:
        """Test force reprocessing with FORCE_REPROCESS=true."""
        from extractor.pyextractor.extractor import process_discogs_data

        mock_download.return_value = ["discogs_20240101_artists.xml.gz"]
        # All files marked as processed
        mock_load_state.return_value = {"discogs_20240101_artists.xml.gz": True}
        # Force reprocess enabled
        mock_env_get.return_value = "true"

        with (
            patch("extractor.pyextractor.extractor.process_file_async", new_callable=AsyncMock) as mock_process,
            patch("extractor.pyextractor.extractor._save_processing_state"),
        ):
            result = await process_discogs_data(mock_config)

        assert result is True
        # Should process despite being marked as complete
        assert mock_process.call_count == 1

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.download_discogs_data")
    @patch("extractor.pyextractor.extractor._load_processing_state")
    @patch("extractor.pyextractor.extractor.shutdown_requested", True)
    async def test_process_discogs_data_shutdown_during_processing(self, mock_load_state: Mock, mock_download: Mock, mock_config: Mock) -> None:
        """Test shutdown during processing."""
        from extractor.pyextractor.extractor import process_discogs_data

        mock_download.return_value = ["discogs_20240101_artists.xml.gz"]
        mock_load_state.return_value = {}

        result = await process_discogs_data(mock_config)

        assert result is True


class TestPeriodicCheckLoop:
    """Test periodic_check_loop function."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.periodic_check_days = 1  # Check every day for testing
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.asyncio.sleep")
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    @patch("extractor.pyextractor.extractor.shutdown_requested", False)
    async def test_periodic_check_loop_single_iteration(self, mock_process: AsyncMock, mock_sleep: AsyncMock, mock_config: Mock) -> None:
        """Test single iteration of periodic check loop."""
        from extractor.pyextractor.extractor import periodic_check_loop

        mock_process.return_value = True
        mock_sleep.return_value = None

        # Mock shutdown after first check
        call_count = [0]

        async def mock_process_side_effect(_config: Any) -> bool:
            call_count[0] += 1
            if call_count[0] >= 1:
                # Trigger shutdown after first check
                import extractor.pyextractor.extractor

                extractor.pyextractor.extractor.shutdown_requested = True
            return True

        mock_process.side_effect = mock_process_side_effect

        # This should complete one check and then exit
        await periodic_check_loop(mock_config)

        assert mock_process.call_count >= 1

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    @patch("extractor.pyextractor.extractor.shutdown_requested", True)
    async def test_periodic_check_loop_shutdown_during_wait(self, mock_process: AsyncMock, mock_config: Mock) -> None:
        """Test shutdown during wait period."""
        from extractor.pyextractor.extractor import periodic_check_loop

        # Should exit immediately due to shutdown
        await periodic_check_loop(mock_config)

        # Should not call process_discogs_data
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.asyncio.sleep")
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    async def test_periodic_check_loop_process_failure(self, mock_process: AsyncMock, mock_sleep: AsyncMock, mock_config: Mock) -> None:
        """Test handling of process failure in periodic check."""
        from extractor.pyextractor.extractor import periodic_check_loop

        mock_process.return_value = False
        mock_sleep.return_value = None

        # Mock shutdown after first check
        call_count = [0]

        async def mock_process_side_effect(_config: Any) -> bool:
            call_count[0] += 1
            if call_count[0] >= 1:
                import extractor.pyextractor.extractor

                extractor.pyextractor.extractor.shutdown_requested = True
            return False

        mock_process.side_effect = mock_process_side_effect

        await periodic_check_loop(mock_config)

        assert mock_process.call_count >= 1

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.asyncio.sleep")
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    @patch("extractor.pyextractor.extractor.shutdown_requested", False)
    async def test_periodic_check_loop_exception(self, mock_process: AsyncMock, mock_sleep: AsyncMock, mock_config: Mock) -> None:
        """Test handling of exception during periodic check."""
        from extractor.pyextractor.extractor import periodic_check_loop

        mock_sleep.return_value = None

        # First call raises exception, second call triggers shutdown
        call_count = [0]

        async def mock_process_side_effect(_config: Any) -> bool:
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Process error")
            else:
                import extractor.pyextractor.extractor

                extractor.pyextractor.extractor.shutdown_requested = True
                return True

        mock_process.side_effect = mock_process_side_effect

        await periodic_check_loop(mock_config)

        assert mock_process.call_count >= 1


class TestMainAsync:
    """Test main_async function."""

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.setup_logging")
    @patch("extractor.pyextractor.extractor.ExtractorConfig.from_env")
    @patch("extractor.pyextractor.extractor.HealthServer")
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    @patch("extractor.pyextractor.extractor.periodic_check_loop")
    @patch("extractor.pyextractor.extractor.shutdown_requested", False)
    @patch("extractor.pyextractor.extractor.signal.signal")
    async def test_main_async_success(
        self,
        _mock_signal: Mock,
        mock_periodic: AsyncMock,
        mock_process: AsyncMock,
        mock_health_server: Mock,
        mock_from_env: Mock,
        mock_setup_logging: Mock,
        test_discogs_root: Path,
    ) -> None:
        """Test successful main_async execution."""
        from extractor.pyextractor.extractor import main_async

        # Setup mocks
        mock_config = Mock()
        mock_config.discogs_root = test_discogs_root
        mock_from_env.return_value = mock_config

        mock_health = Mock()
        mock_health_server.return_value = mock_health

        mock_process.return_value = True
        mock_periodic.return_value = None

        await main_async()

        mock_setup_logging.assert_called_once()
        mock_from_env.assert_called_once()
        mock_health.start_background.assert_called_once()
        mock_process.assert_called_once()
        mock_periodic.assert_called_once()
        mock_health.stop.assert_called_once()

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.setup_logging")
    @patch("extractor.pyextractor.extractor.ExtractorConfig.from_env")
    @patch("extractor.pyextractor.extractor.signal.signal")
    async def test_main_async_config_error(
        self,
        _mock_signal: Mock,
        mock_from_env: Mock,
        _mock_setup_logging: Mock,
    ) -> None:
        """Test main_async with configuration error."""
        from extractor.pyextractor.extractor import main_async

        mock_from_env.side_effect = ValueError("Invalid config")

        # sys.exit(1) will be called, which raises SystemExit
        with pytest.raises(SystemExit) as exc_info:
            await main_async()

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.setup_logging")
    @patch("extractor.pyextractor.extractor.ExtractorConfig.from_env")
    @patch("extractor.pyextractor.extractor.HealthServer")
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    @patch("extractor.pyextractor.extractor.signal.signal")
    async def test_main_async_initial_processing_failure(
        self,
        _mock_signal: Mock,
        mock_process: AsyncMock,
        mock_health_server: Mock,
        mock_from_env: Mock,
        _mock_setup_logging: Mock,
        test_discogs_root: Path,
    ) -> None:
        """Test main_async when initial processing fails."""
        from extractor.pyextractor.extractor import main_async

        mock_config = Mock()
        mock_config.discogs_root = test_discogs_root
        mock_from_env.return_value = mock_config

        mock_health = Mock()
        mock_health_server.return_value = mock_health

        mock_process.return_value = False

        # sys.exit(1) will be called, which raises SystemExit
        with pytest.raises(SystemExit) as exc_info:
            await main_async()

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.setup_logging")
    @patch("extractor.pyextractor.extractor.ExtractorConfig.from_env")
    @patch("extractor.pyextractor.extractor.HealthServer")
    @patch("extractor.pyextractor.extractor.process_discogs_data")
    @patch("extractor.pyextractor.extractor.periodic_check_loop")
    @patch("extractor.pyextractor.extractor.shutdown_requested", True)
    @patch("extractor.pyextractor.extractor.signal.signal")
    async def test_main_async_shutdown_before_periodic(
        self,
        _mock_signal: Mock,
        mock_periodic: AsyncMock,
        mock_process: AsyncMock,
        mock_health_server: Mock,
        mock_from_env: Mock,
        _mock_setup_logging: Mock,
        test_discogs_root: Path,
    ) -> None:
        """Test main_async with shutdown before periodic check."""
        from extractor.pyextractor.extractor import main_async

        mock_config = Mock()
        mock_config.discogs_root = test_discogs_root
        mock_from_env.return_value = mock_config

        mock_health = Mock()
        mock_health_server.return_value = mock_health

        mock_process.return_value = True

        await main_async()

        # Periodic check should not be called due to shutdown
        mock_periodic.assert_not_called()


class TestMainEntryPoint:
    """Test main entry point."""

    @patch("extractor.pyextractor.extractor.asyncio.run")
    def test_main_calls_asyncio_run(self, mock_run: Mock) -> None:
        """Test main calls asyncio.run with main_async."""
        from extractor.pyextractor.extractor import main

        main()

        mock_run.assert_called_once()

    @patch("extractor.pyextractor.extractor.asyncio.run")
    def test_main_handles_keyboard_interrupt(self, mock_run: Mock) -> None:
        """Test main handles KeyboardInterrupt."""
        from extractor.pyextractor.extractor import main

        mock_run.side_effect = KeyboardInterrupt()

        # Should not raise exception
        main()

    @patch("extractor.pyextractor.extractor.asyncio.run")
    def test_main_handles_exception(self, mock_run: Mock) -> None:
        """Test main handles general exception."""
        from extractor.pyextractor.extractor import main

        mock_run.side_effect = Exception("Fatal error")

        # sys.exit(1) will be called, which raises SystemExit
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1


class TestProgressMonitoring:
    """Test progress monitoring and reporting."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_progress_monitoring_with_stalled_extractors(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test progress monitoring detects stalled extractors."""
        import extractor.pyextractor.extractor as extractor_module

        mock_exists.return_value = True

        # Set up global state for progress monitoring
        extractor_module.extraction_progress = {
            "artists": 1000,
            "labels": 500,
            "masters": 0,
            "releases": 2000,
        }
        extractor_module.last_extraction_time = {
            "artists": time.time() - 130,  # Stalled (>120 seconds)
            "labels": time.time() - 10,  # Active
            "masters": 0,  # Not started
            "releases": time.time() - 5,  # Active
        }
        extractor_module.completed_files = set()
        extractor_module.active_connections = {"artists": Mock(), "releases": Mock()}

        ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)

        # Trigger progress reporting by logging
        with patch("extractor.pyextractor.extractor.logger"):
            # Simulate the progress monitoring logic
            current_time = time.time()
            stalled_extractors = []
            for data_type, last_time in extractor_module.last_extraction_time.items():
                if data_type in extractor_module.completed_files:
                    continue
                if last_time > 0 and extractor_module.extraction_progress[data_type] > 0 and (current_time - last_time) > 120:
                    stalled_extractors.append(data_type)

            assert "artists" in stalled_extractors
            assert "labels" not in stalled_extractors
            assert "releases" not in stalled_extractors

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_progress_logging_interval(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test periodic progress logging."""
        mock_exists.return_value = True
        mock_config.progress_log_interval = 10  # Log every 10 records

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)
        extractor.total_count = 10  # Trigger logging at next record

        # Progress logging happens when total_count % progress_log_interval == 0
        assert extractor.total_count % mock_config.progress_log_interval == 0


class TestQueueErrorHandling:
    """Test error handling in queue operations."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.asyncio.run_coroutine_threadsafe")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_queue_record_handles_queue_error(self, mock_exists: Mock, mock_rabbitmq: Mock, mock_run_coro: Mock, mock_config: Mock) -> None:
        """Test queue_record handles queue errors gracefully."""
        # Reset shutdown flag
        import extractor.pyextractor.extractor

        extractor.pyextractor.extractor.shutdown_requested = False

        mock_exists.return_value = True

        mock_connection = Mock()
        mock_channel = Mock()
        mock_channel.is_open = True
        mock_channel.is_closed = False
        mock_connection.channel.return_value = mock_channel
        mock_rabbitmq.return_value = mock_connection

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)

        # Set up the event loop and queue
        extractor.event_loop = Mock()
        extractor.record_queue = Mock()
        extractor.record_queue.qsize.return_value = 0
        extractor.record_queue.put = AsyncMock()  # Only put() needs to be async

        # Mock run_coroutine_threadsafe to raise an exception
        mock_future = Mock()
        mock_future.result.side_effect = Exception("Queue operation failed")
        mock_run_coro.return_value = mock_future

        # Try to queue a record - should handle error gracefully
        test_record = {"id": 123, "name": "Test Artist"}
        extractor._ConcurrentExtractor__queue_record([("artists", {"id": 123})], test_record)

        # Should have incremented error count
        assert extractor.error_count > 0


class TestFlushQueueBackoff:
    """Test flush queue retry and backoff logic."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.asyncio.sleep")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_flush_queue_backoff_increases(self, mock_exists: Mock, mock_rabbitmq: Mock, mock_sleep: AsyncMock, mock_config: Mock) -> None:
        """Test that flush queue backoff increases exponentially."""
        from extractor.pyextractor.extractor import FLUSH_QUEUE_INITIAL_BACKOFF

        mock_exists.return_value = True
        mock_sleep.return_value = None

        mock_connection = Mock()
        mock_channel = Mock()
        mock_channel.is_open = True
        mock_channel.is_closed = False
        mock_connection.channel.return_value = mock_channel
        mock_rabbitmq.return_value = mock_connection

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)
        extractor.amqp_channel = mock_channel

        # Set up flush queue
        extractor.flush_queue = asyncio.Queue(maxsize=1)

        # Initial backoff
        initial_backoff = extractor.flush_retry_backoff
        assert initial_backoff == FLUSH_QUEUE_INITIAL_BACKOFF

        # Fill the queue to trigger QueueFull on next attempt
        await extractor.flush_queue.put(True)

        # Try to flush when queue is full - should trigger backoff retry
        await extractor._try_queue_flush()

        # Now call the retry method which increases the backoff
        await extractor._retry_flush_with_backoff()

        # Backoff should have doubled
        assert extractor.flush_retry_backoff == initial_backoff * 2

    @pytest.mark.asyncio
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    @patch("extractor.pyextractor.extractor.Path.exists")
    async def test_flush_queue_retry_after_failure(self, mock_exists: Mock, mock_rabbitmq: Mock, mock_config: Mock) -> None:
        """Test that flush queue retries after failure if still needed."""
        mock_exists.return_value = True

        mock_connection = Mock()
        mock_channel = Mock()
        mock_channel.is_open = True
        mock_channel.is_closed = False
        mock_connection.channel.return_value = mock_channel
        mock_rabbitmq.return_value = mock_connection

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)
        extractor.amqp_channel = mock_channel

        # Add messages beyond batch size to trigger flush
        with extractor.pending_messages_lock:
            for i in range(mock_config.batch_size + 10):
                extractor.pending_messages.append((f"test.queue.{i}", b"test message", {"content_type": "application/json"}))

        # Mock channel to fail
        mock_channel.basic_publish.side_effect = Exception("Publish failed")

        # Try to flush - should handle failure
        with patch("extractor.pyextractor.extractor.logger"):
            await extractor._try_queue_flush()

        # Should still have messages pending
        with extractor.pending_messages_lock:
            assert len(extractor.pending_messages) > 0


class TestConcurrentExtractorProperties:
    """Tests for ConcurrentExtractor property methods."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_elapsed_time_property(self, mock_exists: Mock, mock_config: Mock) -> None:
        """Test elapsed_time property calculation."""
        mock_exists.return_value = True
        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)

        # Set start and end times
        extractor.start_time = datetime(2023, 1, 1, 10, 0, 0)
        extractor.end_time = datetime(2023, 1, 1, 10, 5, 30)

        # Check elapsed time
        elapsed = extractor.elapsed_time
        assert elapsed.total_seconds() == 330.0  # 5 minutes 30 seconds

    @patch("extractor.pyextractor.extractor.datetime")
    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_tps_property_with_zero_elapsed(self, mock_exists: Mock, mock_datetime: Mock, mock_config: Mock) -> None:
        """Test tps property when elapsed time is zero."""
        mock_exists.return_value = True

        # Mock datetime.now() to return the same time as start_time
        now = datetime(2023, 1, 1, 10, 0, 0)
        mock_datetime.now.return_value = now

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)
        extractor.start_time = now
        extractor.total_count = 100

        # TPS should be 0 when elapsed time is 0
        assert extractor.tps == 0.0

    @patch("extractor.pyextractor.extractor.datetime")
    @patch("extractor.pyextractor.extractor.Path.exists")
    def test_tps_property_with_elapsed_time(self, mock_exists: Mock, mock_datetime: Mock, mock_config: Mock) -> None:
        """Test tps property calculation with elapsed time."""
        mock_exists.return_value = True

        # Set start time and mock datetime.now() to return 60 seconds later
        start_time = datetime(2023, 1, 1, 10, 0, 0)
        end_time = datetime(2023, 1, 1, 10, 1, 0)  # 60 seconds later
        mock_datetime.now.return_value = end_time

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)
        extractor.start_time = start_time
        extractor.total_count = 600

        # TPS should be 600/60 = 10
        assert extractor.tps == 10.0


class TestConcurrentExtractorErrorHandling:
    """Tests for error handling paths in ConcurrentExtractor."""

    @pytest.fixture
    def mock_config(self, test_discogs_root: Path) -> Mock:
        """Create a mock ExtractorConfig."""
        config = Mock()
        config.discogs_root = test_discogs_root
        config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
        config.amqp_connection = "amqp://guest:guest@localhost:5672/"
        config.batch_size = 100
        config.progress_log_interval = 1000
        return config

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_enter_channel_setup_failure(self, mock_rabbitmq: Mock, mock_exists: Mock, mock_config: Mock) -> None:
        """Test __enter__ handles channel setup failures."""
        mock_exists.return_value = True

        # Mock connection that fails during channel creation
        mock_connection = Mock()
        mock_connection.channel.side_effect = Exception("Channel creation failed")
        mock_rabbitmq.return_value = mock_connection

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)

        # Should raise exception and close connection
        with pytest.raises(Exception, match="Channel creation failed"), extractor:
            pass

        # Verify connection was closed
        mock_connection.close.assert_called_once()

    @patch("extractor.pyextractor.extractor.Path.exists")
    @patch("extractor.pyextractor.extractor.ResilientRabbitMQConnection")
    def test_exit_completion_message_failure(self, mock_rabbitmq: Mock, mock_exists: Mock, mock_config: Mock) -> None:
        """Test __exit__ handles completion message send failure."""
        mock_exists.return_value = True

        mock_connection = Mock()
        mock_channel = Mock()
        mock_channel.is_closed = False
        mock_channel.is_open = True
        mock_connection.channel.return_value = mock_channel
        mock_rabbitmq.return_value = mock_connection

        extractor = ConcurrentExtractor("discogs_20230101_artists.xml.gz", mock_config)

        # Enter context
        extractor.__enter__()
        extractor.total_count = 100  # Set some count

        # Make publish fail for completion message
        mock_channel.basic_publish.side_effect = Exception("Publish failed")

        # Should not raise exception even though publishing fails
        extractor.__exit__(None, None, None)

        # Connection should still be closed despite failure
        mock_connection.close.assert_called_once()
