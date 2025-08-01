import asyncio
import contextlib
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from gzip import GzipFile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from common import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    ExtractorConfig,
    HealthServer,
    setup_logging,
    ResilientRabbitMQConnection,
)
from dict_hash import sha256
from orjson import OPT_INDENT_2, OPT_SORT_KEYS, dumps, loads
from pika import DeliveryMode
from pika.spec import BasicProperties
from xmltodict import parse

from extractor.discogs import download_discogs_data


if TYPE_CHECKING:
    from pika.adapters.blocking_connection import BlockingChannel

logger = logging.getLogger(__name__)
MAX_RETRIES = 3
RETRY_DELAY = 5

# Flush queue rate limiting
FLUSH_QUEUE_WARNING_INTERVAL = 60.0  # Only log warning once per minute
FLUSH_QUEUE_MAX_BACKOFF = 300.0  # Maximum backoff time in seconds (5 minutes)
FLUSH_QUEUE_INITIAL_BACKOFF = 30.0  # Initial backoff time in seconds

# Global shutdown flag
shutdown_requested = False

# Progress tracking for monitoring
extraction_progress = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
last_extraction_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}
current_task = None
current_progress = 0.0

# Periodic check configuration will be loaded from config


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    return {
        "status": "healthy",
        "service": "extractor",
        "current_task": current_task,
        "progress": current_progress,
        "extraction_progress": extraction_progress.copy(),
        "last_extraction_time": last_extraction_time.copy(),
        "timestamp": datetime.now().isoformat(),
    }


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


class ConcurrentExtractor:
    def __init__(self, input_file: str, config: ExtractorConfig, max_workers: int = 4):
        # `input_file` is in the format of: discogs_YYYYMMDD_datatype.xml.gz
        try:
            self.data_type = input_file.split("_")[2].split(".")[0]
        except IndexError as e:
            raise ValueError(
                f"Invalid input file format: {input_file}. Expected: discogs_YYYYMMDD_datatype.xml.gz"
            ) from e

        self.input_file = input_file
        self.input_path = Path(config.discogs_root, self.input_file)

        if not self.input_path.exists():
            raise FileNotFoundError(f"Input file not found: {self.input_path}")

        self.config = config
        self.max_workers = max_workers
        self.total_count: int = 0
        self.error_count: int = 0
        self.start_time = datetime.now()
        self.end_time = datetime.now()
        self.last_progress_log = datetime.now()
        self.progress_log_interval = 1000  # Log progress every 1000 records
        self.batch_size = 100  # Batch AMQP messages for better performance
        self.pending_messages: list[dict[str, Any]] = []
        self.pending_messages_lock = (
            threading.Lock()
        )  # Thread safety for concurrent access
        self.last_flush_queue_warning = 0.0  # Track last warning time
        self.flush_retry_backoff = FLUSH_QUEUE_INITIAL_BACKOFF  # Current backoff time
        self.flush_retry_task: asyncio.Task[None] | None = None  # Retry task
        self.record_queue: asyncio.Queue[dict[str, Any] | None] | None = None
        self.flush_queue: asyncio.Queue[bool] | None = (
            None  # Queue to trigger AMQP flushes
        )
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.amqp_connection: ResilientRabbitMQConnection | None = None
        self.amqp_channel: BlockingChannel | None = None
        self.amqp_properties = BasicProperties(
            content_encoding="application/json",
            delivery_mode=DeliveryMode.Persistent,
            content_type="application/json",
        )

    def _get_elapsed_time(self) -> timedelta:
        return self.end_time - self.start_time

    elapsed_time = property(fget=_get_elapsed_time)

    def _get_tps(self) -> float:
        self.end_time = datetime.now()
        elapsed_seconds: float = self.elapsed_time.total_seconds()
        if elapsed_seconds == 0:
            return 0.0
        return float(self.total_count) / elapsed_seconds

    tps = property(fget=_get_tps)

    def __enter__(self) -> "ConcurrentExtractor":
        # Initialize resilient RabbitMQ connection
        self.amqp_connection = ResilientRabbitMQConnection(
            connection_url=self.config.amqp_connection,
            max_retries=MAX_RETRIES,
            heartbeat=600,
            blocked_connection_timeout=300,
        )

        try:
            self.amqp_channel = self.amqp_connection.channel()

            # Enable publisher confirmations for reliability
            self.amqp_channel.confirm_delivery()

            # Set QoS to prevent overwhelming consumers
            self.amqp_channel.basic_qos(prefetch_count=self.batch_size)

            # Create the shared exchange for all data types
            self.amqp_channel.exchange_declare(
                auto_delete=False,
                durable=True,
                exchange=AMQP_EXCHANGE,
                exchange_type=AMQP_EXCHANGE_TYPE,
            )

            # The topic exchange routes messages by data type to both graphinator and tableinator
            # This ensures the same data reaches both services for concurrent processing
            graphinator_queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{self.data_type}"
            tableinator_queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{self.data_type}"

            # Declare queues for this data type (other extractors may have already created them)
            self.amqp_channel.queue_declare(
                auto_delete=False, durable=True, queue=graphinator_queue_name
            )
            self.amqp_channel.queue_bind(
                exchange=AMQP_EXCHANGE,
                queue=graphinator_queue_name,
                routing_key=self.data_type,
            )

            self.amqp_channel.queue_declare(
                auto_delete=False, durable=True, queue=tableinator_queue_name
            )
            self.amqp_channel.queue_bind(
                exchange=AMQP_EXCHANGE,
                queue=tableinator_queue_name,
                routing_key=self.data_type,
            )

            logger.info(
                f"✅ Successfully connected to AMQP broker for {self.data_type} "
                f"(exchange: {AMQP_EXCHANGE}, type: {AMQP_EXCHANGE_TYPE})"
            )
            return self

        except Exception as e:
            logger.error(f"❌ Failed to set up AMQP channel: {e}")
            if self.amqp_connection:
                self.amqp_connection.close()
            raise

    def __exit__(self, exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        # Flush any pending messages
        try:
            self._flush_pending_messages()
        except Exception as e:
            logger.warning(f"⚠️ Failed to flush pending messages during cleanup: {e}")

        if self.amqp_connection is not None:
            try:
                self.amqp_connection.close()
                logger.info("✅ AMQP connection closed gracefully")
            except Exception as e:
                logger.warning(f"⚠️ Error closing AMQP connection: {e}")

    async def extract_async(self) -> None:
        """Async extraction with concurrent record processing."""
        logger.info(
            f"🚀 Starting extraction of {self.data_type} from {self.input_file}"
        )
        self.start_time = datetime.now()

        try:
            # Check if shutdown was requested before starting
            if shutdown_requested:
                logger.info("🛑 Shutdown requested before extraction started")
                return

            # Initialize the queue and event loop reference in async context
            # Larger queue to handle bursty XML parsing
            self.record_queue = asyncio.Queue(maxsize=5000)
            self.flush_queue = asyncio.Queue(maxsize=100)  # Queue for flush requests
            self.event_loop = asyncio.get_running_loop()

            # Start record processing tasks
            processing_tasks = [
                asyncio.create_task(self._process_records_async())
                for _ in range(self.max_workers)
            ]

            # Start dedicated AMQP flush worker
            flush_task = asyncio.create_task(self._amqp_flush_worker())

            # Give the async workers more time to start up before beginning XML parsing
            await asyncio.sleep(0.5)

            # Parse XML and queue records
            parse_task = asyncio.create_task(self._parse_xml_async())

            # Wait for parsing to complete
            await parse_task

            # Signal end of records to all workers
            for _ in range(self.max_workers):
                await self.record_queue.put(None)

            # Signal end to flush worker
            await self.flush_queue.put(False)  # False means shutdown

            # Wait for all processing to complete
            await asyncio.gather(*processing_tasks, flush_task, return_exceptions=True)

            # Flush any remaining messages
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.error(f"❌ Failed to flush final messages: {flush_error}")

        except KeyboardInterrupt:
            logger.info("⚠️ Extraction interrupted by user")
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.warning(
                    f"⚠️ Failed to flush messages during interrupt: {flush_error}"
                )
            raise
        except Exception as e:
            logger.error(f"❌ Error during extraction: {e}")
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.warning(
                    f"⚠️ Failed to flush messages during error handling: {flush_error}"
                )
            raise
        finally:
            self.end_time = datetime.now()

            # Log final extraction statistics
            elapsed = self.end_time - self.start_time
            final_tps = (
                self.total_count / elapsed.total_seconds()
                if elapsed.total_seconds() > 0
                else 0
            )
            logger.info(
                f"✅ Extractor Complete: {self.total_count:,} {self.data_type} processed "
                f"({self.error_count:,} errors) in {elapsed} (avg {final_tps:.1f} records/sec)"
            )

    def extract(self) -> None:
        """Synchronous wrapper for backward compatibility."""
        asyncio.run(self.extract_async())

    async def _parse_xml_async(self) -> None:
        """Parse XML file and queue records for processing."""
        loop = asyncio.get_event_loop()

        with ThreadPoolExecutor() as executor:
            await loop.run_in_executor(executor, self._parse_xml_sync)

    def _parse_xml_sync(self) -> None:
        """Synchronous XML parsing that queues records."""
        try:
            with GzipFile(self.input_path.resolve()) as gz_file:
                parse(gz_file, item_depth=2, item_callback=self.__queue_record)
        except Exception as e:
            logger.error(f"❌ Error parsing XML: {e}")
            raise

    async def _process_records_async(self) -> None:
        """Process records from the queue asynchronously."""
        if self.record_queue is None:
            return

        while True:
            try:
                # Get record from queue with timeout
                record = await asyncio.wait_for(self.record_queue.get(), timeout=1.0)

                if record is None:
                    # End of records signal
                    break

                # Process the record
                await self._process_record_async(record)

                # Mark task as done
                self.record_queue.task_done()

            except TimeoutError:
                # Check for shutdown
                if shutdown_requested:
                    break
                continue
            except Exception as e:
                logger.error(f"❌ Error processing record: {e}")
                self.error_count += 1

    async def _amqp_flush_worker(self) -> None:
        """Dedicated worker for AMQP flush operations."""
        if self.flush_queue is None:
            return

        while True:
            try:
                # Wait for flush requests
                flush_request = await self.flush_queue.get()

                if flush_request is False:
                    # Shutdown signal - flush any remaining messages and exit
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._flush_pending_messages
                    )
                    break

                # Process flush request
                await asyncio.get_event_loop().run_in_executor(
                    None, self._flush_pending_messages
                )

                # Mark flush request as done
                self.flush_queue.task_done()

            except Exception as e:
                logger.warning(f"⚠️ Error in AMQP flush worker: {e}")
                continue

    async def _process_record_async(self, data: dict[str, Any]) -> None:
        """Process a single record asynchronously."""
        try:
            # Normalize and compute hash
            normalized_data = loads(dumps(data, option=OPT_SORT_KEYS | OPT_INDENT_2))
            normalized_data["sha256"] = sha256(normalized_data)

            # Add to pending messages for batch processing (thread-safe)
            with self.pending_messages_lock:
                self.pending_messages.append(normalized_data)
                should_flush = len(self.pending_messages) >= self.batch_size

            # Process batch if it's full
            if should_flush:
                await self._try_queue_flush()

        except Exception as e:
            self.error_count += 1
            record_id = data.get("id", "unknown")
            logger.error(
                f"❌ Error processing {self.data_type[:-1]} ID={record_id}: {e}"
            )

    async def _try_queue_flush(self) -> None:
        """Try to queue a flush request with exponential backoff on failure."""
        if self.flush_queue is None:
            return

        try:
            # Try to queue the flush request
            self.flush_queue.put_nowait(True)
            # Reset backoff on success
            self.flush_retry_backoff = FLUSH_QUEUE_INITIAL_BACKOFF
        except asyncio.QueueFull:
            # Rate limit the warning messages
            current_time = time.time()
            if (
                current_time - self.last_flush_queue_warning
                >= FLUSH_QUEUE_WARNING_INTERVAL
            ):
                logger.warning(
                    f"⚠️ Flush queue is full, will retry with {self.flush_retry_backoff:.1f}s backoff"
                )
                self.last_flush_queue_warning = current_time

            # Schedule a retry with backoff if not already scheduled
            if self.flush_retry_task is None or self.flush_retry_task.done():
                self.flush_retry_task = asyncio.create_task(
                    self._retry_flush_with_backoff()
                )
        except Exception as flush_error:
            logger.warning(f"⚠️ Failed to queue flush request: {flush_error}")

    async def _retry_flush_with_backoff(self) -> None:
        """Retry flushing with exponential backoff."""
        await asyncio.sleep(self.flush_retry_backoff)

        # Increase backoff for next retry (exponential with cap)
        self.flush_retry_backoff = min(
            self.flush_retry_backoff * 2, FLUSH_QUEUE_MAX_BACKOFF
        )

        # Check if we still need to flush
        with self.pending_messages_lock:
            needs_flush = len(self.pending_messages) >= self.batch_size

        if needs_flush:
            # Try to flush again
            await self._try_queue_flush()

    def __queue_record(
        self, path: list[tuple[str, dict[str, Any] | None]], data: dict[str, Any]
    ) -> bool:
        # `path` is in the format of:
        #   [('masters', None), ('master', OrderedDict([('id', '2'), ('status', 'Accepted')]))]
        #   [('releases', None), ('release', OrderedDict([('id', '2'), ('status', 'Accepted')]))]

        data_type = path[0][0]
        if data_type != self.data_type:
            logger.warning(
                f"⚠️ Data type mismatch: expected {self.data_type}, got {data_type}"
            )
            return False

        self.total_count += 1

        # Update global progress tracking
        global current_task
        if self.data_type in extraction_progress:
            extraction_progress[self.data_type] += 1
            last_extraction_time[self.data_type] = time.time()
            current_task = f"Processing {self.data_type}"

        if (
            data_type in ["masters", "releases"]
            and len(path) > 1
            and path[1][1] is not None
        ):
            data["id"] = path[1][1]["id"]

        # Check for shutdown signal
        if shutdown_requested:
            logger.info("🛑 Shutdown requested, stopping extraction")
            return False

        # Extract record details for logging
        record_id = data.get("id", "unknown")
        record_name = None

        # Extract name/title based on data type
        if self.data_type == "artists":
            record_name = data.get("name", "Unknown Artist")
        elif self.data_type == "labels":
            record_name = data.get("name", "Unknown Label")
        elif self.data_type == "releases":
            record_name = data.get("title", "Unknown Release")
        elif self.data_type == "masters":
            record_name = data.get("title", "Unknown Master")

        # Log only at debug level for individual records to reduce noise
        if record_name:
            logger.debug(
                f"🔄 Processing {self.data_type[:-1]} ID={record_id}: {record_name}"
            )
        else:
            logger.debug(f"🔄 Processing {self.data_type[:-1]} ID={record_id}")

        try:
            # Queue the record for async processing
            if self.record_queue is not None and self.event_loop is not None:
                # Check queue size and implement adaptive backpressure
                queue_size = self.record_queue.qsize()

                # If queue is getting full, slow down the XML parsing
                if queue_size > 4000:  # 80% of max queue size
                    time.sleep(0.01)  # 10ms pause
                elif queue_size > 3000:  # 60% of max queue size
                    time.sleep(0.005)  # 5ms pause
                elif queue_size > 2000:  # 40% of max queue size
                    time.sleep(0.001)  # 1ms pause

                # Use put_nowait for non-blocking operation
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.record_queue.put(data), self.event_loop
                    )
                    # Use a longer timeout but only wait once
                    future.result(
                        timeout=30.0
                    )  # 30 second timeout, but should be much faster
                except TimeoutError:
                    # If we still get timeout after 30 seconds, there's a serious issue
                    logger.error(
                        f"⚠️ Severe queue timeout for {self.data_type[:-1]} ID={record_id}. "
                        f"Queue size: {queue_size}/5000. System may be deadlocked."
                    )
                    # Drop this record rather than hanging the entire process
                    self.error_count += 1
                except Exception as queue_error:
                    logger.error(
                        f"⚠️ Queue error for {self.data_type[:-1]} ID={record_id}: {queue_error}"
                    )
                    self.error_count += 1
        except Exception as e:
            self.error_count += 1
            logger.error(
                f"❌ Error queuing {self.data_type[:-1]} ID={record_id}: {e.__class__.__name__}: {str(e) if str(e) else 'Unknown error'}"
            )
            # Continue processing other records

        # Log progress statistics periodically
        if self.total_count % self.progress_log_interval == 0:
            current_time = datetime.now()
            elapsed = current_time - self.start_time
            current_tps = (
                self.total_count / elapsed.total_seconds()
                if elapsed.total_seconds() > 0
                else 0
            )

            logger.info(
                f"📊 Extractor Progress: {self.total_count:,} {self.data_type} processed "
                f"({self.error_count:,} errors, {current_tps:.1f} records/sec, elapsed: {elapsed})"
            )
            self.last_progress_log = current_time

        return True

    def _ensure_amqp_connection(self) -> bool:
        """Ensure AMQP connection and channel are open, reconnect if needed."""
        try:
            # Check if channel is still open
            if self.amqp_channel is None or self.amqp_channel.is_closed:
                logger.warning("⚠️ AMQP channel lost, attempting to get new channel...")

                # Get new channel from resilient connection
                if self.amqp_connection is None:
                    raise RuntimeError("AMQP connection is not initialized")
                self.amqp_channel = self.amqp_connection.channel()

                # Re-enable publisher confirmations
                self.amqp_channel.confirm_delivery()

                # Set QoS
                self.amqp_channel.basic_qos(prefetch_count=self.batch_size)

                # Re-declare exchange (idempotent)
                self.amqp_channel.exchange_declare(
                    auto_delete=False,
                    durable=True,
                    exchange=AMQP_EXCHANGE,
                    exchange_type=AMQP_EXCHANGE_TYPE,
                )

                logger.info("✅ AMQP channel re-established successfully")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to establish AMQP channel: {e}")
            return False

    def _flush_pending_messages(self) -> None:
        """Flush pending messages to AMQP in a batch with connection recovery."""
        # Thread-safe access to pending messages
        with self.pending_messages_lock:
            if not self.pending_messages:
                return
            # Create a copy of messages to send and clear the original list
            messages_to_send = self.pending_messages.copy()
            self.pending_messages.clear()

        # Ensure connection is available
        if not self._ensure_amqp_connection():
            logger.error("❌ Cannot flush messages - AMQP connection unavailable")
            # Put messages back if connection failed
            with self.pending_messages_lock:
                self.pending_messages.extend(messages_to_send)
            return

        # After _ensure_amqp_connection(), channel should be available
        if self.amqp_channel is None:
            logger.error("❌ AMQP channel is None after connection check")
            # Put messages back if channel is not available
            with self.pending_messages_lock:
                self.pending_messages.extend(messages_to_send)
            return

        try:
            # Publish all messages in batch
            for message_data in messages_to_send:
                try:
                    published = self.amqp_channel.basic_publish(
                        body=dumps(message_data, option=OPT_SORT_KEYS | OPT_INDENT_2),
                        exchange=AMQP_EXCHANGE,
                        properties=self.amqp_properties,
                        routing_key=self.data_type,
                        mandatory=True,  # Ensure message is routed
                    )
                    # basic_publish returns True if successful, None if confirmations are disabled
                    if published is False:
                        logger.warning("⚠️ Message was not routed properly")
                except Exception as publish_error:
                    logger.error(f"❌ Failed to publish message: {publish_error}")
                    raise

            logger.debug(
                f"✅ Flushed {len(messages_to_send)} messages to AMQP exchange"
            )

        except Exception as e:
            logger.error(f"❌ Error flushing messages to AMQP: {e}")
            # Put messages back for retry
            with self.pending_messages_lock:
                self.pending_messages.extend(messages_to_send)
            # Mark channel as needing reset for next attempt
            self.amqp_channel = None
            # Don't raise - let the process continue with other records
            logger.warning("⚠️ Messages will be retried on next flush")


def _load_processing_state(discogs_root: Path) -> dict[str, bool]:
    """Load processing state from file."""
    state_file = Path(discogs_root) / ".processing_state.json"
    if not state_file.exists():
        return {}

    try:
        with state_file.open("rb") as f:
            data = loads(f.read())
            # Ensure we return the correct type
            return {k: bool(v) for k, v in data.items()}
    except Exception as e:
        logger.warning(f"⚠️ Failed to load processing state: {e}")
        return {}


def _save_processing_state(discogs_root: Path, state: dict[str, bool]) -> None:
    """Save processing state to file."""
    state_file = Path(discogs_root) / ".processing_state.json"

    try:
        with state_file.open("wb") as f:
            f.write(dumps(state, option=OPT_INDENT_2))
    except Exception as e:
        logger.warning(f"⚠️ Failed to save processing state: {e}")


async def process_file_async(discogs_data_file: str, config: ExtractorConfig) -> None:
    """Process a single file asynchronously."""
    try:
        extractor = ConcurrentExtractor(discogs_data_file, config)
        with extractor:
            await extractor.extract_async()
    except Exception as e:
        logger.error(f"❌ Failed to process {discogs_data_file}: {e}")
        raise


async def process_discogs_data(config: ExtractorConfig) -> bool:
    """Process Discogs data files. Returns True if successful."""
    global extraction_progress, last_extraction_time

    # Reset progress counters for new processing run
    extraction_progress = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
    last_extraction_time = {
        "artists": 0.0,
        "labels": 0.0,
        "masters": 0.0,
        "releases": 0.0,
    }

    try:
        discogs_data = download_discogs_data(str(config.discogs_root))
    except Exception as e:
        logger.error(f"❌ Failed to download Discogs data: {e}")
        return False

    # Filter out checksum files
    data_files = [file for file in discogs_data if "CHECKSUM" not in file]

    if not data_files:
        logger.warning("⚠️ No data files to process")
        return True

    # Check processing state to handle restarts
    processing_state = _load_processing_state(config.discogs_root)
    files_to_process = []

    for data_file in data_files:
        if data_file not in processing_state or not processing_state[data_file]:
            files_to_process.append(data_file)
            logger.info(f"📋 Will process: {data_file}")
        else:
            logger.info(f"✅ Already processed: {data_file}")

    if not files_to_process:
        logger.info("✅ All files have been processed previously")
        # Force reprocessing if explicitly requested via environment variable
        if os.environ.get("FORCE_REPROCESS", "").lower() == "true":
            logger.info("🔄 FORCE_REPROCESS=true, will reprocess all files")
            files_to_process = data_files
            processing_state = {}  # Clear processing state
        else:
            return True

    # Process files concurrently with a semaphore to limit concurrent files
    semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent files
    tasks = []

    async def process_with_semaphore(file: str) -> None:
        async with semaphore:
            if shutdown_requested:
                return
            await process_file_async(file, config)
            # Mark file as processed
            processing_state[file] = True
            _save_processing_state(config.discogs_root, processing_state)
            logger.info(f"✅ Marked {file} as processed")

    for data_file in files_to_process:
        if shutdown_requested:
            break
        tasks.append(asyncio.create_task(process_with_semaphore(data_file)))

    # Start periodic progress reporting and monitoring
    async def progress_reporter() -> None:
        report_count = 0
        while not shutdown_requested:
            # More frequent reports initially, then every 30 seconds
            if report_count < 3:
                await asyncio.sleep(10)  # First 3 reports every 10 seconds
            else:
                await asyncio.sleep(30)  # Then every 30 seconds
            report_count += 1
            total = sum(extraction_progress.values())
            current_time = time.time()

            # Check for stalled extractors
            stalled_extractors = []
            for data_type, last_time in last_extraction_time.items():
                if (
                    last_time > 0
                    and extraction_progress[data_type] > 0
                    and (current_time - last_time) > 120
                ):  # No extraction for 2 minutes
                    stalled_extractors.append(data_type)

            if stalled_extractors:
                logger.error(
                    f"⚠️ Stalled extractors detected: {stalled_extractors}. "
                    f"No data extracted for >2 minutes."
                )

            # Always show progress
            logger.info(
                f"📊 Extraction Progress: {total} total records extracted "
                f"(Artists: {extraction_progress['artists']}, Labels: {extraction_progress['labels']}, "
                f"Masters: {extraction_progress['masters']}, Releases: {extraction_progress['releases']})"
            )

            # Log current extraction state
            if total == 0:
                logger.info("⏳ Starting extraction process...")
            else:
                # Check which files are actively being extracted
                active_extractors = []
                slow_extractors = []
                for data_type, last_time in last_extraction_time.items():
                    if last_time > 0:
                        time_since_last = current_time - last_time
                        if time_since_last < 5:
                            active_extractors.append(data_type)
                        elif 5 < time_since_last < 120:
                            slow_extractors.append(data_type)

                if active_extractors:
                    logger.info(f"✅ Active extractors: {active_extractors}")
                if slow_extractors:
                    logger.warning(f"⚠️ Slow extractors detected: {slow_extractors}")

    progress_task = asyncio.create_task(progress_reporter())

    if tasks:
        logger.info(f"🔄 Processing {len(tasks)} files concurrently (max 3 at once)")

        try:
            # Wait for all tasks to complete, handling exceptions gracefully
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any exceptions
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"❌ File {data_files[i]} failed: {result}")
                    # Don't return False here - continue with periodic checks even if some files failed
        finally:
            # Cancel progress reporting
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task

    return True


async def periodic_check_loop(config: ExtractorConfig) -> None:
    """Run periodic checks for new or updated files at configured interval."""
    periodic_check_days = config.periodic_check_days
    periodic_check_seconds = periodic_check_days * 24 * 60 * 60

    logger.info(
        f"🔄 Starting periodic check loop (interval: {periodic_check_days} days)"
    )

    while True:
        # Wait for the specified interval
        logger.info(f"⏰ Waiting {periodic_check_days} days before next check...")

        # Use shorter sleep intervals to check for shutdown more frequently
        elapsed_seconds = 0
        check_interval = 60  # Check every minute for shutdown

        while elapsed_seconds < periodic_check_seconds:
            if shutdown_requested:
                logger.info("🛑 Shutdown requested during wait period")
                return

            await asyncio.sleep(
                min(check_interval, periodic_check_seconds - elapsed_seconds)
            )
            elapsed_seconds += check_interval

            # Log progress every hour
            if elapsed_seconds % 3600 == 0 and not shutdown_requested:
                hours_elapsed = elapsed_seconds // 3600
                hours_remaining = (periodic_check_seconds - elapsed_seconds) // 3600
                logger.info(
                    f"⏰ Periodic check timer: {hours_elapsed} hours elapsed, "
                    f"{hours_remaining} hours remaining"
                )

        if shutdown_requested:
            logger.info("🛑 Shutdown requested before periodic check")
            return

        # Perform the periodic check
        logger.info("🔄 Starting periodic check for new or updated Discogs files...")
        check_start_time = datetime.now()

        try:
            success = await process_discogs_data(config)
            check_duration = datetime.now() - check_start_time

            if success:
                logger.info(
                    f"✅ Periodic check completed successfully in {check_duration}. "
                    f"Next check in {periodic_check_days} days."
                )
            else:
                logger.error(
                    f"❌ Periodic check failed after {check_duration}. "
                    f"Will retry in {periodic_check_days} days."
                )
        except Exception as e:
            logger.error(f"❌ Error during periodic check: {e}")
            logger.info(f"⏳ Will retry in {periodic_check_days} days.")


async def main_async() -> None:
    """Main async function with concurrent file processing and periodic checks."""
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("extractor", log_file=Path("/logs/extractor.log"))

    try:
        config = ExtractorConfig.from_env()
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)

    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗                      ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝                      ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗                      ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║                      ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║                      ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝                      ")
    print("                                                                           ")
    print("███████╗██╗  ██╗████████╗██████╗  █████╗  ██████╗████████╗ ██████╗ ██████╗ ")
    print("██╔════╝╚██╗██╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗")
    print("█████╗   ╚███╔╝    ██║   ██████╔╝███████║██║        ██║   ██║   ██║██████╔╝")
    print("██╔══╝   ██╔██╗    ██║   ██╔══██╗██╔══██║██║        ██║   ██║   ██║██╔══██╗")
    print("███████╗██╔╝ ██╗   ██║   ██║  ██║██║  ██║╚██████╗   ██║   ╚██████╔╝██║  ██║")
    print("╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝")
    print()
    # fmt: on

    logger.info(
        "🚀 Starting Discogs data extractor with concurrent processing and periodic checks"
    )
    logger.info("📋 Will check for incomplete processing from previous runs")
    logger.info("💡 Tip: Set FORCE_REPROCESS=true to reprocess all files")

    # Start health server
    health_server = HealthServer(8000, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8000")

    # Process initial data
    logger.info("📥 Starting initial data processing...")
    initial_success = await process_discogs_data(config)

    if not initial_success:
        logger.error("❌ Initial data processing failed")
        sys.exit(1)

    logger.info("✅ Initial data processing completed successfully")

    # Start periodic check loop
    if not shutdown_requested:
        logger.info("🔄 Starting periodic check service...")
        await periodic_check_loop(config)

    # Stop health server
    health_server.stop()
    logger.info("✅ Extractor service shutdown complete")


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("⚠️ Extractor interrupted by user")
    except Exception as e:
        logger.error(f"❌ Extractor failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
