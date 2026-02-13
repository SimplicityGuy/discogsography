import asyncio
import contextlib
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

import structlog
from common import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    ExtractorConfig,
    HealthServer,
    PhaseStatus,
    ProcessingDecision,
    ResilientRabbitMQConnection,
    StateMarker,
    setup_logging,
)
from dict_hash import sha256
from extractor.pyextractor.discogs import download_discogs_data, get_latest_version
from orjson import OPT_INDENT_2, OPT_SORT_KEYS, dumps, loads
from pika import DeliveryMode
from pika.spec import BasicProperties
from xmltodict import parse

if TYPE_CHECKING:
    from pika.adapters.blocking_connection import BlockingChannel

logger = structlog.get_logger(__name__)
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
completed_files = set()  # Track which files have been completed
current_task = None
current_progress = 0.0
active_connections: dict[
    str, ResilientRabbitMQConnection
] = {}  # Track active AMQP connections by data type

# Periodic check configuration will be loaded from config


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    # Determine status based on current state
    # - "extracting" when actively processing files (has active AMQP connections)
    # - "healthy" when idle and ready for next scheduled run
    if active_connections:
        status = "extracting"
    else:
        status = "healthy"

    return {
        "status": status,
        "service": "extractor",
        "current_task": current_task,
        "progress": current_progress,
        "extraction_progress": extraction_progress.copy(),
        "last_extraction_time": last_extraction_time.copy(),
        "active_extractions": list(active_connections.keys()),
        "timestamp": datetime.now().isoformat(),
    }


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info("🛑 Received signal, initiating graceful shutdown...", signal=signum)
    shutdown_requested = True


class ConcurrentExtractor:
    def __init__(
        self,
        input_file: str,
        config: ExtractorConfig,
        state_marker: StateMarker,
        max_workers: int = 4,
    ):
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
        self.state_marker = state_marker
        self.max_workers = max_workers
        self.total_count: int = 0
        self.error_count: int = 0
        self.batches_sent: int = 0
        self.start_time = datetime.now()
        self.end_time = datetime.now()
        self.last_progress_log = datetime.now()
        self.last_state_save = datetime.now()
        self.progress_log_interval = 1000  # Log progress every 1000 records
        self.state_save_interval = 5000  # Save state every 5000 records
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

            # Create dead-letter exchange for poison messages
            dlx_exchange = f"{AMQP_EXCHANGE}.dlx"
            self.amqp_channel.exchange_declare(
                auto_delete=False,
                durable=True,
                exchange=dlx_exchange,
                exchange_type="topic",
            )

            # The topic exchange routes messages by data type to both graphinator and tableinator
            # This ensures the same data reaches both services for concurrent processing
            graphinator_queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{self.data_type}"
            tableinator_queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{self.data_type}"

            # Queue arguments for quorum queues with DLX
            # x-queue-type: quorum - Use quorum queues for HA and data safety
            # x-dead-letter-exchange: Route poison messages (20+ retries) to DLX
            # x-delivery-limit: Default is 20, explicitly set for clarity
            queue_args = {
                "x-queue-type": "quorum",
                "x-dead-letter-exchange": dlx_exchange,
                "x-delivery-limit": 20,
            }

            # Create dead-letter queues for poison messages
            graphinator_dlq_name = f"{graphinator_queue_name}.dlq"
            tableinator_dlq_name = f"{tableinator_queue_name}.dlq"

            # Declare DLQs (using classic queues for DLQs is fine)
            self.amqp_channel.queue_declare(
                auto_delete=False,
                durable=True,
                queue=graphinator_dlq_name,
                arguments={"x-queue-type": "classic"},
            )
            self.amqp_channel.queue_bind(
                exchange=dlx_exchange,
                queue=graphinator_dlq_name,
                routing_key=self.data_type,
            )

            self.amqp_channel.queue_declare(
                auto_delete=False,
                durable=True,
                queue=tableinator_dlq_name,
                arguments={"x-queue-type": "classic"},
            )
            self.amqp_channel.queue_bind(
                exchange=dlx_exchange,
                queue=tableinator_dlq_name,
                routing_key=self.data_type,
            )

            # Declare main quorum queues for this data type (other extractors may have already created them)
            self.amqp_channel.queue_declare(
                auto_delete=False,
                durable=True,
                queue=graphinator_queue_name,
                arguments=queue_args,
            )
            self.amqp_channel.queue_bind(
                exchange=AMQP_EXCHANGE,
                queue=graphinator_queue_name,
                routing_key=self.data_type,
            )

            self.amqp_channel.queue_declare(
                auto_delete=False,
                durable=True,
                queue=tableinator_queue_name,
                arguments=queue_args,
            )
            self.amqp_channel.queue_bind(
                exchange=AMQP_EXCHANGE,
                queue=tableinator_queue_name,
                routing_key=self.data_type,
            )

            logger.info(
                "✅ Successfully connected to AMQP broker",
                data_type=self.data_type,
                exchange=AMQP_EXCHANGE,
                exchange_type=AMQP_EXCHANGE_TYPE,
            )

            # Track active connection
            global active_connections
            active_connections[self.data_type] = self.amqp_connection

            # Mark file processing as started in state marker
            self.state_marker.start_file_processing(self.input_file)
            marker_path = StateMarker.file_path(
                Path(self.config.discogs_root), self.state_marker.current_version
            )
            self.state_marker.save(marker_path)
            logger.info(
                "📋 Started file processing in state marker", file=self.input_file
            )

            return self

        except Exception as e:
            logger.error("❌ Failed to set up AMQP channel", error=str(e))
            if self.amqp_connection:
                self.amqp_connection.close()
            raise

    def __exit__(self, exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        global active_connections

        # Flush any pending messages
        try:
            self._flush_pending_messages()
        except Exception as e:
            logger.warning(
                "⚠️ Failed to flush pending messages during cleanup", error=str(e)
            )

        # Mark file as completed in state marker
        try:
            self.state_marker.complete_file_processing(
                self.input_file, self.total_count
            )
            marker_path = StateMarker.file_path(
                Path(self.config.discogs_root), self.state_marker.current_version
            )
            self.state_marker.save(marker_path)
            logger.info(
                "✅ Completed file processing in state marker",
                file=self.input_file,
                records=self.total_count,
            )
        except Exception as e:
            logger.warning(
                "⚠️ Failed to update state marker on file completion", error=str(e)
            )

        # Send file completion message before closing connection
        if self.amqp_channel is not None and not self.amqp_channel.is_closed:
            try:
                completion_message = {
                    "type": "file_complete",
                    "data_type": self.data_type,
                    "timestamp": datetime.now().isoformat(),
                    "total_processed": self.total_count,
                    "file": self.input_file,
                }

                self.amqp_channel.basic_publish(
                    body=dumps(completion_message, option=OPT_SORT_KEYS | OPT_INDENT_2),
                    exchange=AMQP_EXCHANGE,
                    properties=self.amqp_properties,
                    routing_key=self.data_type,
                    mandatory=True,
                )
                logger.info(
                    "🎉 File processing complete!",
                    data_type=self.data_type,
                    total_records=self.total_count,
                )
                # Mark this data type as completed to avoid stalled warnings
                completed_files.add(self.data_type)
            except Exception as e:
                logger.warning("⚠️ Failed to send file completion message", error=str(e))

        if self.amqp_connection is not None:
            try:
                self.amqp_connection.close()
                logger.info(
                    "🔌 Closing AMQP connection after file completion",
                    data_type=self.data_type,
                )

                # Remove from active connections tracking
                if self.data_type in active_connections:
                    del active_connections[self.data_type]

            except Exception as e:
                logger.warning("⚠️ Error closing AMQP connection", error=str(e))

    async def extract_async(self) -> None:
        """Async extraction with concurrent record processing."""
        logger.info(
            "🚀 Starting extraction", data_type=self.data_type, file=self.input_file
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
                logger.error(
                    "❌ Failed to flush final messages", error=str(flush_error)
                )

        except KeyboardInterrupt:
            logger.info("⚠️ Extraction interrupted by user")
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.warning(
                    "⚠️ Failed to flush messages during interrupt",
                    error=str(flush_error),
                )
            raise
        except Exception as e:
            logger.error("❌ Error during extraction", error=str(e))
            try:
                self._flush_pending_messages()
            except Exception as flush_error:
                logger.warning(
                    "⚠️ Failed to flush messages during error handling",
                    error=str(flush_error),
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
                "✅ Extractor Complete",
                data_type=self.data_type,
                total_records=self.total_count,
                error_count=self.error_count,
                elapsed=str(elapsed),
                records_per_sec=final_tps,
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
                parse(gz_file, item_depth=2, item_callback=self.__queue_record)  # type: ignore[arg-type]
        except Exception as e:
            logger.error("❌ Error parsing XML", error=str(e))
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
                logger.error("❌ Error processing record", error=str(e))
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
                logger.warning("⚠️ Error in AMQP flush worker", error=str(e))
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
                "❌ Error processing record",
                data_type=self.data_type[:-1],
                record_id=record_id,
                error=str(e),
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
                    "⚠️ Flush queue is full, will retry with backoff",
                    backoff_seconds=self.flush_retry_backoff,
                )
                self.last_flush_queue_warning = current_time

            # Schedule a retry with backoff if not already scheduled
            if self.flush_retry_task is None or self.flush_retry_task.done():
                self.flush_retry_task = asyncio.create_task(
                    self._retry_flush_with_backoff()
                )
        except Exception as flush_error:
            logger.warning("⚠️ Failed to queue flush request", error=str(flush_error))

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
                "⚠️ Data type mismatch", expected=self.data_type, got=data_type
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
                "🔄 Processing record",
                data_type=self.data_type[:-1],
                record_id=record_id,
                name=record_name,
            )
        else:
            logger.debug(
                "🔄 Processing record",
                data_type=self.data_type[:-1],
                record_id=record_id,
            )

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
                        "⚠️ Severe queue timeout",
                        data_type=self.data_type[:-1],
                        record_id=record_id,
                        queue_size=queue_size,
                        max_size=5000,
                    )
                    # Drop this record rather than hanging the entire process
                    self.error_count += 1
                except Exception as queue_error:
                    logger.error(
                        "⚠️ Queue error",
                        data_type=self.data_type[:-1],
                        record_id=record_id,
                        error=str(queue_error),
                    )
                    self.error_count += 1
        except Exception as e:
            self.error_count += 1
            logger.error(
                "❌ Error queuing record",
                data_type=self.data_type[:-1],
                record_id=record_id,
                error_type=e.__class__.__name__,
                error_msg=str(e) if str(e) else "Unknown error",
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
                "📊 Extractor Progress",
                data_type=self.data_type,
                total_processed=self.total_count,
                error_count=self.error_count,
                records_per_sec=current_tps,
                elapsed=str(elapsed),
            )
            self.last_progress_log = current_time

        # Save state marker periodically
        if self.total_count % self.state_save_interval == 0:
            try:
                # Update progress in state marker
                self.state_marker.update_file_progress(
                    self.input_file,
                    self.total_count,
                    self.total_count,  # Messages published (one per record)
                    self.batches_sent,  # Actual batches sent
                )
                marker_path = StateMarker.file_path(
                    Path(self.config.discogs_root), self.state_marker.current_version
                )
                self.state_marker.save(marker_path)
                logger.debug(
                    "💾 Saved state marker progress",
                    file=self.input_file,
                    records=self.total_count,
                )
                self.last_state_save = datetime.now()
            except Exception as e:
                logger.warning("⚠️ Failed to save state marker progress", error=str(e))

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
            logger.error("❌ Failed to establish AMQP channel", error=str(e))
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
                    logger.error(
                        "❌ Failed to publish message", error=str(publish_error)
                    )
                    raise

            # Increment batches sent counter
            self.batches_sent += 1

            logger.debug(
                "✅ Flushed messages to AMQP exchange",
                count=len(messages_to_send),
                batches_sent=self.batches_sent,
            )

        except Exception as e:
            logger.error("❌ Error flushing messages to AMQP", error=str(e))
            # Put messages back for retry
            with self.pending_messages_lock:
                self.pending_messages.extend(messages_to_send)
            # Mark channel as needing reset for next attempt
            self.amqp_channel = None
            # Don't raise - let the process continue with other records
            logger.warning("⚠️ Messages will be retried on next flush")


def _extract_version_from_filename(filename: str) -> str | None:
    """Extract version from Discogs filename (e.g., 'discogs_20260101_artists.xml.gz' -> '20260101')."""
    try:
        parts = filename.split("_")
        if len(parts) >= 2:
            return parts[1]
    except (IndexError, AttributeError):
        pass
    return None


async def process_file_async(
    discogs_data_file: str, config: ExtractorConfig, state_marker: StateMarker
) -> None:
    """Process a single file asynchronously."""
    try:
        extractor = ConcurrentExtractor(discogs_data_file, config, state_marker)
        with extractor:
            await extractor.extract_async()
            # Note: File completion is handled in __exit__ method where:
            # - File completion message is sent to consumers
            # - AMQP connection is closed
            # - completed_files set is updated
    except Exception as e:
        logger.error("❌ Failed to process file", file=discogs_data_file, error=str(e))
        raise


async def process_discogs_data(
    config: ExtractorConfig, force_reprocess: bool = False
) -> bool:
    """Process Discogs data files with state marker support. Returns True if successful."""
    global \
        extraction_progress, \
        last_extraction_time, \
        completed_files, \
        active_connections

    # Reset progress counters for new processing run
    extraction_progress = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
    last_extraction_time = {
        "artists": 0.0,
        "labels": 0.0,
        "masters": 0.0,
        "releases": 0.0,
    }
    completed_files.clear()  # Clear completed files for new run
    active_connections.clear()  # Clear active connections tracking

    # First, determine the latest available version (fast, no download)
    version = get_latest_version()
    if not version:
        logger.error("❌ Could not determine latest Discogs data version")
        return False

    logger.info("📋 Latest available Discogs data version", version=version)

    # Load or create state marker
    marker_path = StateMarker.file_path(Path(config.discogs_root), version)
    state_marker = StateMarker.load(marker_path) or StateMarker(current_version=version)

    # Check if we should force reprocess
    if force_reprocess or os.environ.get("FORCE_REPROCESS", "").lower() == "true":
        logger.info("🔄 Force reprocess requested, creating new state marker")
        state_marker = StateMarker(current_version=version)

    # Check what to do based on state marker
    decision = state_marker.should_process()

    if decision == ProcessingDecision.SKIP:
        logger.info("✅ Version already processed, skipping", version=version)
        return True
    elif decision == ProcessingDecision.REPROCESS:
        logger.warning("⚠️ Will re-download and re-process", version=version)
        state_marker = StateMarker(current_version=version)

    # Download with state marker tracking (always required now)
    try:
        discogs_data = download_discogs_data(
            str(config.discogs_root), state_marker, marker_path
        )
    except Exception as e:
        logger.error("❌ Failed to download Discogs data", error=str(e))
        return False

    # Filter out checksum files
    data_files = [file for file in discogs_data if "CHECKSUM" not in file]

    if not data_files:
        logger.warning("⚠️ No data files to process")
        return True

    # Start processing phase
    if state_marker.processing_phase.status != PhaseStatus.COMPLETED:
        state_marker.start_processing(len(data_files))
        state_marker.save(marker_path)
        logger.info("🚀 Starting processing phase", total_files=len(data_files))

    # Get list of files that still need processing
    pending_files = state_marker.pending_files(data_files)

    if not pending_files:
        logger.info("✅ All files already processed")
        state_marker.complete_processing()
        state_marker.complete_extraction()
        state_marker.save(marker_path)
        return True

    logger.info(
        "📋 Files to process",
        total=len(data_files),
        pending=len(pending_files),
        completed=len(data_files) - len(pending_files),
    )

    # Process files concurrently with a semaphore to limit concurrent files
    semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent files
    tasks = []

    async def process_with_semaphore(file: str) -> None:
        async with semaphore:
            if shutdown_requested:
                return
            await process_file_async(file, config, state_marker)
            logger.info("✅ Completed processing", file=file)

    for data_file in pending_files:
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
                # Skip if this file type has been completed
                if data_type in completed_files:
                    continue

                if (
                    last_time > 0
                    and extraction_progress[data_type] > 0
                    and (current_time - last_time) > 120
                ):  # No extraction for 2 minutes
                    stalled_extractors.append(data_type)

            if stalled_extractors:
                logger.error(
                    "⚠️ Stalled extractors detected",
                    stalled=stalled_extractors,
                    message="No data extracted for >2 minutes",
                )

            # Always show progress with completion emojis similar to other services
            progress_parts = []
            for data_type in ["artists", "labels", "masters", "releases"]:
                emoji = "🎉 " if data_type in completed_files else ""
                progress_parts.append(
                    f"{emoji}{data_type.capitalize()}: {extraction_progress[data_type]}"
                )

            logger.info(
                "📊 Extraction Progress",
                total_records=total,
                progress=", ".join(progress_parts),
            )

            # Show completed files clearly
            if completed_files:
                logger.info("🎉 Completed files", files=sorted(completed_files))

            # Show connection status
            if active_connections:
                logger.info(
                    "🔗 Active AMQP connections",
                    connections=list(active_connections.keys()),
                )
            elif completed_files:
                logger.info(
                    "🔌 Connections closed for completed files",
                    files=sorted(completed_files),
                )

            # Log current extraction state
            if total == 0:
                logger.info("⏳ Starting extraction process...")
            else:
                # Check which files are actively being extracted
                active_extractors = []
                slow_extractors = []
                for data_type, last_time in last_extraction_time.items():
                    # Skip if this file type has been completed
                    if data_type in completed_files:
                        continue

                    if last_time > 0:
                        time_since_last = current_time - last_time
                        if time_since_last < 5:
                            active_extractors.append(data_type)
                        elif 5 < time_since_last < 120:
                            slow_extractors.append(data_type)

                if active_extractors:
                    logger.info("✅ Active extractors", extractors=active_extractors)
                if slow_extractors:
                    logger.warning(
                        "⚠️ Slow extractors detected", extractors=slow_extractors
                    )

    progress_task = asyncio.create_task(progress_reporter())

    if tasks:
        logger.info(
            "🔄 Processing files concurrently", count=len(tasks), max_concurrent=3
        )

        try:
            # Wait for all tasks to complete, handling exceptions gracefully
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any exceptions
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        "❌ File failed", file=data_files[i], error=str(result)
                    )
                    # Don't return False here - continue with periodic checks even if some files failed
        finally:
            # Cancel progress reporting
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task

    # Mark processing as complete
    state_marker.complete_processing()
    state_marker.complete_extraction()
    state_marker.save(marker_path)
    logger.info("✅ Processing phase completed", version=version)

    # Log final completion status
    if completed_files:
        logger.info(
            "🎉 All processing complete! Finished files", files=sorted(completed_files)
        )

        # Log final statistics
        total_extracted = sum(extraction_progress.values())
        logger.info(
            "📊 Final statistics",
            total_records=total_extracted,
            message="Total records extracted across all files",
        )

        # Confirm all connections are closed
        if not active_connections:
            logger.info("🔌 All AMQP connections closed after file completion")
        else:
            logger.warning(
                "⚠️ Unexpected active connections remaining",
                connections=list(active_connections.keys()),
            )

    return True


async def periodic_check_loop(config: ExtractorConfig) -> None:
    """Run periodic checks for new or updated files at configured interval."""
    global active_connections
    periodic_check_days = config.periodic_check_days
    periodic_check_seconds = periodic_check_days * 24 * 60 * 60

    logger.info("🔄 Starting periodic check loop", interval_days=periodic_check_days)

    while True:
        # Wait for the specified interval
        logger.info("⏰ Waiting before next check", days=periodic_check_days)

        # Verify all connections are closed during wait
        if not active_connections:
            logger.info("✅ No active connections during wait period")
        else:
            logger.warning(
                "⚠️ Unexpected active connections",
                connections=list(active_connections.keys()),
            )

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
                    "⏰ Periodic check timer",
                    hours_elapsed=hours_elapsed,
                    hours_remaining=hours_remaining,
                )

        if shutdown_requested:
            logger.info("🛑 Shutdown requested before periodic check")
            return

        # Perform the periodic check
        logger.info("🔄 Starting periodic check for new or updated Discogs files...")
        logger.info("🔄 Re-establishing connections for data check...")
        check_start_time = datetime.now()

        try:
            success = await process_discogs_data(config)
            check_duration = datetime.now() - check_start_time

            if success:
                logger.info(
                    "✅ Periodic check completed successfully",
                    duration=str(check_duration),
                    next_check_days=periodic_check_days,
                )

                # Log what was processed in this check
                if completed_files:
                    logger.info(
                        "🎉 Files processed in this check",
                        files=sorted(completed_files),
                    )
                else:
                    logger.info("ℹ️ No new files found in this check")

                # Verify connections are closed
                if not active_connections:
                    logger.info("🔌 All connections closed after periodic check")
                else:
                    logger.warning(
                        "⚠️ Active connections remaining",
                        connections=list(active_connections.keys()),
                    )
            else:
                logger.error(
                    "❌ Periodic check failed",
                    duration=str(check_duration),
                    retry_days=periodic_check_days,
                )
        except Exception as e:
            logger.error("❌ Error during periodic check", error=str(e))
            logger.info("⏳ Will retry", days=periodic_check_days)


async def main_async() -> None:
    """Main async function with concurrent file processing and periodic checks."""
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("extractor", log_file=Path("/logs/extractor.log"))

    try:
        config = ExtractorConfig.from_env()
    except ValueError as e:
        logger.error("❌ Configuration error", error=str(e))
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
    logger.info("🏥 Health server started", port=8000)

    # Process initial data
    logger.info("📥 Starting initial data processing...")
    initial_success = await process_discogs_data(config)

    if not initial_success:
        logger.error("❌ Initial data processing failed")
        sys.exit(1)

    logger.info("✅ Initial data processing completed successfully")

    # Log summary of what was processed
    if completed_files:
        logger.info("🎉 Initial processing complete", files=sorted(completed_files))
    if not active_connections:
        logger.info("🔌 All connections properly closed after initial processing")

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
        logger.error("❌ Extractor failed", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
