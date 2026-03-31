"""Batch processor for efficient PostgreSQL operations.

This module provides batch processing capabilities for PostgreSQL to improve
performance by reducing the number of database round trips.
"""

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import structlog
from common import normalize_record
from psycopg import sql
from psycopg.errors import InterfaceError, OperationalError
from psycopg.types.json import Jsonb

logger = structlog.get_logger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 100  # Number of records per batch
    flush_interval: float = 5.0  # Seconds before force flush
    max_pending: int = 1000  # Maximum pending records before blocking
    max_concurrent_flushes: int = 2  # Max simultaneous PostgreSQL flush operations
    min_batch_size: int = 10  # Floor for adaptive batch sizing
    backoff_initial: float = 1.0  # Initial backoff delay on PostgreSQL errors (seconds)
    backoff_max: float = 30.0  # Maximum backoff delay (seconds)
    backoff_multiplier: float = 2.0  # Exponential backoff multiplier
    max_flush_retries: int = 5  # Max retries per data type during flush_queue drain


@dataclass
class PendingMessage:
    """A message pending batch processing."""

    data_type: str
    data_id: str
    data: dict[str, Any]
    sha256: str
    ack_callback: Callable[[], Any]
    nack_callback: Callable[[], Any]
    received_at: float = field(default_factory=time.time)


class PostgreSQLBatchProcessor:
    """Batches PostgreSQL operations for improved performance.

    Instead of processing each message individually, this class accumulates
    messages and processes them in batches using executemany, significantly
    reducing the overhead of database transactions.

    Uses async PostgreSQL operations to prevent event loop blocking.
    """

    def __init__(self, connection_pool: Any, config: BatchConfig | None = None):
        """Initialize the batch processor.

        Args:
            connection_pool: Async PostgreSQL connection pool
            config: Batch processing configuration
        """
        self.connection_pool = connection_pool
        self.config = config or BatchConfig()

        # Separate queues for each data type
        self.queues: dict[str, deque[PendingMessage]] = {
            "artists": deque(),
            "labels": deque(),
            "masters": deque(),
            "releases": deque(),
        }

        # Processing stats
        self.processed_counts: dict[str, int] = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        self.batch_counts: dict[str, int] = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        self.last_flush: dict[str, float] = {
            "artists": time.time(),
            "labels": time.time(),
            "masters": time.time(),
            "releases": time.time(),
        }

        # Shutdown flag
        self._shutdown = False

        # Concurrency limiter — prevents all 4 data types from flushing
        # simultaneously and exhausting the PostgreSQL connection pool
        self._flush_semaphore = asyncio.Semaphore(self.config.max_concurrent_flushes)

        # Adaptive batch sizing — reduces under PostgreSQL pressure, recovers on success
        # Per-data-type so pressure on one type doesn't affect others
        self._effective_batch_size: dict[str, int] = {
            "artists": self.config.batch_size,
            "labels": self.config.batch_size,
            "masters": self.config.batch_size,
            "releases": self.config.batch_size,
        }
        self._consecutive_failures: dict[str, int] = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }

        # Backoff state — delay between retries when PostgreSQL is struggling
        self._backoff_until: dict[str, float] = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }

        # Load batch size from environment
        env_batch_size = os.environ.get("POSTGRES_BATCH_SIZE")
        if env_batch_size:
            try:
                self.config.batch_size = int(env_batch_size)
                for dt in self._effective_batch_size:
                    self._effective_batch_size[dt] = self.config.batch_size
                logger.info(
                    "🔧 Using batch size from environment",
                    batch_size=self.config.batch_size,
                )
            except ValueError:
                logger.warning(
                    "⚠️ Invalid POSTGRES_BATCH_SIZE, using default",
                    value=env_batch_size,
                    default=self.config.batch_size,
                )

    async def add_message(
        self,
        data_type: str,
        data: dict[str, Any],
        ack_callback: Callable[[], Any],
        nack_callback: Callable[[], Any],
    ) -> None:
        """Add a message to the batch queue.

        Args:
            data_type: Type of data (artists, labels, masters, releases)
            data: The parsed message data
            ack_callback: Callback to acknowledge the message
            nack_callback: Callback to negative-acknowledge the message
        """
        queue = self.queues.get(data_type)
        if queue is None:
            logger.error("❌ Unknown data type", data_type=data_type)
            await nack_callback()
            return

        # Extract id and hash before normalization
        data_id = data.get("id")
        if not data_id:
            logger.error("❌ Message missing 'id' field", data_type=data_type)
            await nack_callback()
            return

        sha256 = data.get("sha256", "")

        # Normalize the data
        try:
            normalized_data = normalize_record(data_type, data)
        except Exception as e:
            logger.error(
                "❌ Failed to normalize data",
                data_type=data_type,
                error=str(e),
            )
            await nack_callback()
            return

        # Add to queue
        queue.append(
            PendingMessage(
                data_type=data_type,
                data_id=data_id,
                data=normalized_data,
                sha256=sha256,
                ack_callback=ack_callback,
                nack_callback=nack_callback,
            )
        )

        # Check if we should flush (use adaptive batch size)
        if len(queue) >= self._effective_batch_size[data_type]:
            await self._flush_queue(data_type)
        elif time.time() - self.last_flush[data_type] >= self.config.flush_interval:
            await self._flush_queue(data_type)

    async def _flush_queue(self, data_type: str) -> None:
        """Flush a queue by processing all pending messages.

        Uses a semaphore to limit concurrent PostgreSQL operations across data types,
        exponential backoff on PostgreSQL errors, and adaptive batch sizing.

        Args:
            data_type: The data type queue to flush
        """
        queue = self.queues[data_type]
        if not queue:
            return

        # Skip if in backoff period for this data type
        now = time.time()
        if now < self._backoff_until[data_type]:
            return

        # Use effective (adaptive) batch size
        messages: list[PendingMessage] = []
        while queue and len(messages) < self._effective_batch_size[data_type]:
            messages.append(queue.popleft())

        if not messages:
            return

        batch_start = time.time()
        success = False

        # Limit concurrent PostgreSQL operations to prevent pool exhaustion
        async with self._flush_semaphore:
            try:
                await self._process_batch(data_type, messages)
                success = True

            except asyncio.CancelledError:
                # Re-enqueue messages on cancellation (e.g., during graceful shutdown)
                for msg in reversed(messages):
                    queue.appendleft(msg)
                raise

            except (InterfaceError, OperationalError) as e:
                logger.error(
                    "❌ PostgreSQL connection error during batch",
                    data_type=data_type,
                    batch_size=len(messages),
                    error=str(e),
                )
                # Put messages back for retry
                for msg in reversed(messages):
                    queue.appendleft(msg)

                # Exponential backoff — prevent tight retry loop that worsens pool exhaustion
                self._consecutive_failures[data_type] += 1
                delay = min(
                    self.config.backoff_initial
                    * (
                        self.config.backoff_multiplier
                        ** (self._consecutive_failures[data_type] - 1)
                    ),
                    self.config.backoff_max,
                )
                self._backoff_until[data_type] = time.time() + delay

                # Adaptive batch sizing — halve on failure (floor at min_batch_size)
                old_size = self._effective_batch_size[data_type]
                self._effective_batch_size[data_type] = max(
                    self.config.min_batch_size,
                    self._effective_batch_size[data_type] // 2,
                )
                if self._effective_batch_size[data_type] != old_size:
                    logger.warning(
                        "📉 Reduced batch size due to PostgreSQL pressure",
                        old_size=old_size,
                        new_size=self._effective_batch_size[data_type],
                        backoff_seconds=round(delay, 1),
                        consecutive_failures=self._consecutive_failures[data_type],
                    )
                else:
                    logger.warning(
                        "⏳ Backing off before retry",
                        data_type=data_type,
                        backoff_seconds=round(delay, 1),
                        consecutive_failures=self._consecutive_failures[data_type],
                    )

                # Messages are back on deque for retry — do NOT nack them
                return

            except Exception as e:
                logger.error(
                    "❌ Batch processing error",
                    data_type=data_type,
                    batch_size=len(messages),
                    error=str(e),
                )
                # Re-enqueue messages for local retry before AMQP nack
                for msg in reversed(messages):
                    queue.appendleft(msg)
                # Track failures for non-transient errors too, to enable backoff
                self._consecutive_failures[data_type] = (
                    self._consecutive_failures.get(data_type, 0) + 1
                )
                # Apply backoff to prevent tight retry loop on persistent errors
                delay = min(
                    self.config.backoff_initial
                    * (
                        self.config.backoff_multiplier
                        ** (self._consecutive_failures[data_type] - 1)
                    ),
                    self.config.backoff_max,
                )
                self._backoff_until[data_type] = time.time() + delay
                # Messages are back on deque for retry — do NOT nack them
                return

        batch_duration = time.time() - batch_start

        if success:
            # Acknowledge all messages
            for msg in messages:
                try:
                    await msg.ack_callback()
                except Exception as e:
                    logger.warning("⚠️ Failed to ack message", error=str(e))

            self.processed_counts[data_type] += len(messages)
            self.batch_counts[data_type] += 1
            self.last_flush[data_type] = time.time()

            # Reset failure tracking on success
            self._consecutive_failures[data_type] = 0

            # Adaptive batch sizing — gradually recover toward configured size
            if self._effective_batch_size[data_type] < self.config.batch_size:
                old_size = self._effective_batch_size[data_type]
                self._effective_batch_size[data_type] = min(
                    self.config.batch_size,
                    self._effective_batch_size[data_type]
                    + max(10, self.config.batch_size // 10),
                )
                if self._effective_batch_size[data_type] != old_size:
                    logger.info(
                        "📈 Increased batch size after success",
                        old_size=old_size,
                        new_size=self._effective_batch_size[data_type],
                    )

            logger.info(
                "✅ Batch processed",
                data_type=data_type,
                batch_size=len(messages),
                duration_ms=round(batch_duration * 1000),
                records_per_sec=round(len(messages) / batch_duration)
                if batch_duration > 0
                else 0,
                total_processed=self.processed_counts[data_type],
            )

    async def _process_batch(
        self, data_type: str, messages: list[PendingMessage]
    ) -> None:
        """Process a batch of records using efficient bulk operations.

        Uses async PostgreSQL operations with a single transaction:
        1. Bulk fetch existing hashes using ANY()
        2. Filter to only records that need updating
        3. Bulk upsert using executemany with ON CONFLICT
        """
        # Get async connection from pool
        async with self.connection_pool.connection() as conn:
            async with conn.cursor() as cursor:
                # Step 1: Fetch all existing hashes in one query
                data_ids = [msg.data_id for msg in messages]
                await cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # safe: psycopg2 sql.Identifier parameterizes the identifier, not user input
                    sql.SQL(
                        "SELECT data_id, hash FROM {table} WHERE data_id = ANY(%s)"
                    ).format(table=sql.Identifier(data_type)),
                    (data_ids,),
                )
                existing_hashes = {row[0]: row[1] for row in await cursor.fetchall()}

                # Step 2: Filter to only records that need updating
                records_to_upsert = []
                unchanged_ids = []
                for msg in messages:
                    existing_hash = existing_hashes.get(msg.data_id)
                    if existing_hash == msg.sha256:
                        # Hash unchanged — skip data write but track for updated_at refresh
                        unchanged_ids.append(msg.data_id)
                        continue
                    records_to_upsert.append((msg.sha256, msg.data_id, Jsonb(msg.data)))

                if unchanged_ids:
                    logger.debug(
                        "🔄 Skipped unchanged records",
                        data_type=data_type,
                        skipped=len(unchanged_ids),
                    )
                    # Refresh updated_at so post-extraction stale row purge
                    # does not delete unchanged-but-still-present records
                    await cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # safe: psycopg2 sql.Identifier parameterizes the identifier, not user input
                        sql.SQL(
                            "UPDATE {table} SET updated_at = NOW() "
                            "WHERE data_id = ANY(%s)"
                        ).format(table=sql.Identifier(data_type)),
                        (unchanged_ids,),
                    )

                if not records_to_upsert:
                    return

                # Step 3: Bulk upsert using executemany
                await cursor.executemany(
                    sql.SQL(
                        "INSERT INTO {table} (hash, data_id, data, updated_at) "
                        "VALUES (%s, %s, %s, NOW()) "
                        "ON CONFLICT (data_id) DO UPDATE "
                        "SET hash = EXCLUDED.hash, data = EXCLUDED.data, updated_at = NOW()"
                    ).format(table=sql.Identifier(data_type)),
                    records_to_upsert,
                )

                logger.debug(
                    "🐘 Batch upserted records",
                    data_type=data_type,
                    upserted=len(records_to_upsert),
                    skipped=len(unchanged_ids),
                )

    async def flush_all(self) -> None:
        """Flush all pending queues, draining each completely."""
        for data_type in self.queues:
            await self.flush_queue(data_type)

    async def flush_queue(self, data_type: str) -> None:
        """Fully drain a single data type queue.

        Unlike _flush_queue which processes up to one batch, this loops
        until the queue is completely empty. Yields to the event loop
        during backoff periods instead of busy-spinning.

        Enforces a retry limit to prevent infinite loops when persistent
        errors cause messages to be re-enqueued indefinitely.
        """
        retries = 0
        while self.queues.get(data_type):
            prev_len = len(self.queues[data_type])
            wait = self._backoff_until[data_type] - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
                # Don't count backoff waits as retries — only count actual flush failures
                await self._flush_queue(data_type)
                curr_len = len(self.queues.get(data_type, []))
                if curr_len < prev_len:
                    retries = 0
                continue
            await self._flush_queue(data_type)
            curr_len = len(self.queues.get(data_type, []))
            if curr_len >= prev_len:
                retries += 1
                if retries >= self.config.max_flush_retries:
                    remaining = len(self.queues.get(data_type, []))
                    logger.error(
                        "❌ Flush retry limit reached — nacking remaining messages",
                        data_type=data_type,
                        remaining=remaining,
                        max_retries=self.config.max_flush_retries,
                    )
                    queue = self.queues[data_type]
                    while queue:
                        msg = queue.popleft()
                        try:
                            await msg.nack_callback()
                        except Exception as e:
                            logger.warning("⚠️ Failed to nack message", error=str(e))
                    break
            else:
                retries = 0

    async def periodic_flush(self) -> None:
        """Background task that periodically flushes queues.

        This ensures messages don't sit in the queue too long
        when message rate is low.
        """
        while not self._shutdown:
            await asyncio.sleep(self.config.flush_interval)

            for data_type, queue in self.queues.items():
                if (
                    queue
                    and time.time() - self.last_flush[data_type]
                    >= self.config.flush_interval
                ):
                    await self._flush_queue(data_type)

    def shutdown(self) -> None:
        """Signal shutdown to stop periodic tasks."""
        self._shutdown = True

    def get_stats(self) -> dict[str, Any]:
        """Get processing statistics."""
        return {
            "processed": self.processed_counts.copy(),
            "batches": self.batch_counts.copy(),
            "pending": {k: len(v) for k, v in self.queues.items()},
            "effective_batch_size": self._effective_batch_size.copy(),
            "configured_batch_size": self.config.batch_size,
            "consecutive_failures": self._consecutive_failures.copy(),
        }
