import asyncio
import contextlib
import logging
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from gzip import GzipFile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dict_hash import sha256
from orjson import OPT_INDENT_2, OPT_SORT_KEYS, dumps, loads
from pika import BlockingConnection, DeliveryMode, URLParameters
from pika.exceptions import AMQPChannelError, AMQPConnectionError
from pika.spec import BasicProperties
from xmltodict import parse

from config import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    ExtractorConfig,
    setup_logging,
)
from discogs import download_discogs_data


if TYPE_CHECKING:
    from pika.adapters.blocking_connection import BlockingChannel

logger = logging.getLogger(__name__)
MAX_RETRIES = 3
RETRY_DELAY = 5

# Global shutdown flag
shutdown_requested = False


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
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
        self.pending_messages_lock = threading.Lock()  # Thread safety for concurrent access
        self.record_queue: asyncio.Queue[dict[str, Any] | None] | None = None
        self.flush_queue: asyncio.Queue[bool] | None = None  # Queue to trigger AMQP flushes
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.amqp_connection: BlockingConnection | None = None
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
        retry_count = 0
        while retry_count < MAX_RETRIES:
            try:
                self.amqp_connection = BlockingConnection(
                    URLParameters(self.config.amqp_connection)
                )
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
                    exchange=AMQP_EXCHANGE, queue=graphinator_queue_name, routing_key=self.data_type
                )

                self.amqp_channel.queue_declare(
                    auto_delete=False, durable=True, queue=tableinator_queue_name
                )
                self.amqp_channel.queue_bind(
                    exchange=AMQP_EXCHANGE, queue=tableinator_queue_name, routing_key=self.data_type
                )

                logger.info(
                    f"Successfully connected to AMQP broker for {self.data_type} "
                    f"(exchange: {AMQP_EXCHANGE}, type: {AMQP_EXCHANGE_TYPE})"
                )
                return self

            except (AMQPConnectionError, AMQPChannelError) as e:
                retry_count += 1
                logger.warning(
                    f"⚠️ AMQP connection failed (attempt {retry_count}/{MAX_RETRIES}): {e}"
                )
                if retry_count < MAX_RETRIES:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    import time

                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("Max retries exceeded for AMQP connection")
                    raise

        return self

    def __exit__(self, exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        # Flush any pending messages
        try:
            self._flush_pending_messages()
        except Exception as e:
            logger.warning(f"⚠️ Failed to flush pending messages during cleanup: {e}")

        if self.amqp_connection is not None:
            try:
                if not self.amqp_connection.is_closed:
                    self.amqp_connection.close()
                logger.info("AMQP connection closed gracefully")
            except Exception as e:
                logger.warning(f"⚠️ Error closing AMQP connection: {e}")

    async def extract_async(self) -> None:
        """Async extraction with concurrent record processing."""
        logger.info(f"Starting extraction of {self.data_type} from {self.input_file}")
        self.start_time = datetime.now()

        try:
            # Check if shutdown was requested before starting
            if shutdown_requested:
                logger.info("Shutdown requested before extraction started")
                return

            # Initialize the queue and event loop reference in async context
            # Larger queue to handle bursty XML parsing
            self.record_queue = asyncio.Queue(maxsize=5000)
            self.flush_queue = asyncio.Queue(maxsize=100)  # Queue for flush requests
            self.event_loop = asyncio.get_running_loop()

            # Start record processing tasks
            processing_tasks = [
                asyncio.create_task(self._process_records_async()) for _ in range(self.max_workers)
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
                logger.error(f"Failed to flush final messages: {flush_error}")

        except KeyboardInterrupt:
            logger.info("Extraction interrupted by user")
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.warning(f"⚠️ Failed to flush messages during interrupt: {flush_error}")
            raise
        except Exception as e:
            logger.error(f"Error during extraction: {e}")
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.warning(f"⚠️ Failed to flush messages during error handling: {flush_error}")
            raise
        finally:
            self.end_time = datetime.now()

            # Log final extraction statistics
            elapsed = self.end_time - self.start_time
            final_tps = (
                self.total_count / elapsed.total_seconds() if elapsed.total_seconds() > 0 else 0
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
            logger.error(f"Error parsing XML: {e}")
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
                logger.error(f"Error processing record: {e}")
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
                await asyncio.get_event_loop().run_in_executor(None, self._flush_pending_messages)

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
                try:
                    # Signal flush worker to process batch (non-blocking)
                    if self.flush_queue is not None:
                        self.flush_queue.put_nowait(True)  # True means flush request
                except asyncio.QueueFull:
                    logger.warning("⚠️ Flush queue is full, will retry later")
                except Exception as flush_error:
                    logger.warning(f"⚠️ Failed to queue flush request: {flush_error}")

        except Exception as e:
            self.error_count += 1
            record_id = data.get("id", "unknown")
            logger.error(f"Error processing {self.data_type[:-1]} ID={record_id}: {e}")

    def __queue_record(
        self, path: list[tuple[str, dict[str, Any] | None]], data: dict[str, Any]
    ) -> bool:
        # `path` is in the format of:
        #   [('masters', None), ('master', OrderedDict([('id', '2'), ('status', 'Accepted')]))]
        #   [('releases', None), ('release', OrderedDict([('id', '2'), ('status', 'Accepted')]))]

        data_type = path[0][0]
        if data_type != self.data_type:
            logger.warning(f"⚠️ Data type mismatch: expected {self.data_type}, got {data_type}")
            return False

        self.total_count += 1

        if data_type in ["masters", "releases"] and len(path) > 1 and path[1][1] is not None:
            data["id"] = path[1][1]["id"]

        # Check for shutdown signal
        if shutdown_requested:
            logger.info("Shutdown requested, stopping extraction")
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
            logger.debug(f"Processing {self.data_type[:-1]} ID={record_id}: {record_name}")
        else:
            logger.debug(f"Processing {self.data_type[:-1]} ID={record_id}")

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
                    future.result(timeout=30.0)  # 30 second timeout, but should be much faster
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
                f"Error queuing {self.data_type[:-1]} ID={record_id}: {e.__class__.__name__}: {str(e) if str(e) else 'Unknown error'}"
            )
            # Continue processing other records

        # Log progress statistics periodically
        if self.total_count % self.progress_log_interval == 0:
            current_time = datetime.now()
            elapsed = current_time - self.start_time
            current_tps = (
                self.total_count / elapsed.total_seconds() if elapsed.total_seconds() > 0 else 0
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
            # Check if connection and channel are still open
            if (
                self.amqp_connection is None
                or self.amqp_connection.is_closed
                or self.amqp_channel is None
                or self.amqp_channel.is_closed
            ):
                logger.warning("⚠️ AMQP connection/channel closed, attempting to reconnect...")

                # Close existing connection if partially open
                if self.amqp_connection and not self.amqp_connection.is_closed:
                    with contextlib.suppress(Exception):
                        self.amqp_connection.close()

                # Reconnect
                self.amqp_connection = BlockingConnection(
                    URLParameters(self.config.amqp_connection)
                )
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

                logger.info("AMQP connection re-established successfully")

            return True

        except Exception as e:
            logger.error(f"Failed to establish AMQP connection: {e}")
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
            logger.error("Cannot flush messages - AMQP connection unavailable")
            # Put messages back if connection failed
            with self.pending_messages_lock:
                self.pending_messages.extend(messages_to_send)
            return

        # After _ensure_amqp_connection(), channel should be available
        if self.amqp_channel is None:
            logger.error("AMQP channel is None after connection check")
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
                    logger.error(f"Failed to publish message: {publish_error}")
                    raise

            logger.debug(f"Flushed {len(messages_to_send)} messages to AMQP exchange")

        except Exception as e:
            logger.error(f"Error flushing messages to AMQP: {e}")
            # Put messages back for retry
            with self.pending_messages_lock:
                self.pending_messages.extend(messages_to_send)
            # Mark connection as needing reset for next attempt
            if self.amqp_connection:
                with contextlib.suppress(Exception):
                    self.amqp_connection.close()
                self.amqp_connection = None
                self.amqp_channel = None
            # Don't raise - let the process continue with other records
            logger.warning("⚠️ Messages will be retried on next flush")


async def process_file_async(discogs_data_file: str, config: ExtractorConfig) -> None:
    """Process a single file asynchronously."""
    try:
        extractor = ConcurrentExtractor(discogs_data_file, config)
        with extractor:
            await extractor.extract_async()
    except Exception as e:
        logger.error(f"Failed to process {discogs_data_file}: {e}")
        raise


async def main_async() -> None:
    """Main async function with concurrent file processing."""
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        config = ExtractorConfig.from_env()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging("extractor", log_file=Path("extractor.log"))

    print("    ·▄▄▄▄  ▪  .▄▄ ·  ▄▄·        ▄▄ • .▄▄ ·      ")
    print("    ██▪ ██ ██ ▐█ ▀. ▐█ ▌▪▪     ▐█ ▀ ▪▐█ ▀.      ")
    print("    ▐█· ▐█▌▐█·▄▀▀▀█▄██ ▄▄ ▄█▀▄ ▄█ ▀█▄▄▀▀▀█▄     ")
    print("    ██. ██ ▐█▌▐█▄▪▐█▐███▌▐█▌.▐▌▐█▄▪▐█▐█▄▪▐█     ")
    print("    ▀▀▀▀▀• ▀▀▀ ▀▀▀▀ ·▀▀▀  ▀█▄▀▪·▀▀▀▀  ▀▀▀▀      ")
    print("▄▄▄ .▐▄• ▄ ▄▄▄▄▄▄▄▄   ▄▄▄·  ▄▄· ▄▄▄▄▄      ▄▄▄  ")
    print("▀▄.▀· █▌█▌▪•██  ▀▄ █·▐█ ▀█ ▐█ ▌▪•██  ▪     ▀▄ █·")
    print("▐▀▀▪▄ ·██·  ▐█.▪▐▀▀▄ ▄█▀▀█ ██ ▄▄ ▐█.▪ ▄█▀▄ ▐▀▀▄ ")
    print("▐█▄▄▌▪▐█·█▌ ▐█▌·▐█•█▌▐█ ▪▐▌▐███▌ ▐█▌·▐█▌.▐▌▐█•█▌")
    print(" ▀▀▀ •▀▀ ▀▀ ▀▀▀ .▀  ▀ ▀  ▀ ·▀▀▀  ▀▀▀  ▀█▄▀▪.▀  ▀")
    print()

    logger.info("Starting Discogs data extractor with concurrent processing")

    try:
        discogs_data = download_discogs_data(str(config.discogs_root))
    except Exception as e:
        logger.error(f"Failed to download Discogs data: {e}")
        sys.exit(1)

    # Filter out checksum files
    data_files = [file for file in discogs_data if "CHECKSUM" not in file]

    if not data_files:
        logger.warning("⚠️ No data files to process")
        return

    # Process files concurrently with a semaphore to limit concurrent files
    semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent files
    tasks = []

    async def process_with_semaphore(file: str) -> None:
        async with semaphore:
            if shutdown_requested:
                return
            await process_file_async(file, config)

    for data_file in data_files:
        if shutdown_requested:
            break
        tasks.append(asyncio.create_task(process_with_semaphore(data_file)))

    if tasks:
        logger.info(f"Processing {len(tasks)} files concurrently (max 3 at once)")

        # Wait for all tasks to complete, handling exceptions gracefully
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"File {data_files[i]} failed: {result}")

    logger.info("Extractor service shutdown complete")


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Extractor interrupted by user")
    except Exception as e:
        logger.error(f"Extractor failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
