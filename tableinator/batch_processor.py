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
from psycopg import sql
from psycopg.errors import InterfaceError, OperationalError
from psycopg.types.json import Jsonb

from common import normalize_record

logger = structlog.get_logger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 100  # Number of records per batch
    flush_interval: float = 5.0  # Seconds before force flush
    max_pending: int = 1000  # Maximum pending records before blocking


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
    """

    def __init__(
        self, get_connection: Callable[[], Any], config: BatchConfig | None = None
    ):
        """Initialize the batch processor.

        Args:
            get_connection: Function that returns a database connection
            config: Batch processing configuration
        """
        self.get_connection = get_connection
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

        # Load batch size from environment
        env_batch_size = os.environ.get("POSTGRES_BATCH_SIZE")
        if env_batch_size:
            try:
                self.config.batch_size = int(env_batch_size)
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

        # Check if we should flush
        if len(queue) >= self.config.batch_size:
            await self._flush_queue(data_type)
        elif time.time() - self.last_flush[data_type] >= self.config.flush_interval:
            await self._flush_queue(data_type)

    async def _flush_queue(self, data_type: str) -> None:
        """Flush a queue by processing all pending messages.

        Args:
            data_type: The data type queue to flush
        """
        queue = self.queues[data_type]
        if not queue:
            return

        # Get all messages from queue up to batch size
        messages: list[PendingMessage] = []
        while queue and len(messages) < self.config.batch_size:
            messages.append(queue.popleft())

        if not messages:
            return

        batch_start = time.time()
        success = False

        try:
            await self._process_batch(data_type, messages)
            success = True

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
        except Exception as e:
            logger.error(
                "❌ Batch processing error",
                data_type=data_type,
                batch_size=len(messages),
                error=str(e),
            )

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
        else:
            # Nack all messages for retry
            for msg in messages:
                try:
                    await msg.nack_callback()
                except Exception as e:
                    logger.warning("⚠️ Failed to nack message", error=str(e))

    async def _process_batch(
        self, data_type: str, messages: list[PendingMessage]
    ) -> None:
        """Process a batch of records using efficient bulk operations.

        Uses a single transaction with:
        1. Bulk fetch existing hashes using ANY()
        2. Filter to only records that need updating
        3. Bulk upsert using executemany with ON CONFLICT
        """
        # Get connection from pool
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Step 1: Fetch all existing hashes in one query
                data_ids = [msg.data_id for msg in messages]
                cursor.execute(
                    sql.SQL(
                        "SELECT data_id, hash FROM {table} WHERE data_id = ANY(%s)"
                    ).format(table=sql.Identifier(data_type)),
                    (data_ids,),
                )
                existing_hashes = {row[0]: row[1] for row in cursor.fetchall()}

                # Step 2: Filter to only records that need updating
                records_to_upsert = []
                skipped_count = 0
                for msg in messages:
                    existing_hash = existing_hashes.get(msg.data_id)
                    if existing_hash == msg.sha256:
                        # Hash unchanged, skip this record
                        skipped_count += 1
                        continue
                    records_to_upsert.append((msg.sha256, msg.data_id, Jsonb(msg.data)))

                if skipped_count > 0:
                    logger.debug(
                        "⏩ Skipped unchanged records",
                        data_type=data_type,
                        skipped=skipped_count,
                    )

                if not records_to_upsert:
                    return

                # Step 3: Bulk upsert using executemany
                cursor.executemany(
                    sql.SQL(
                        "INSERT INTO {table} (hash, data_id, data) VALUES (%s, %s, %s) "
                        "ON CONFLICT (data_id) DO UPDATE SET hash = EXCLUDED.hash, data = EXCLUDED.data"
                    ).format(table=sql.Identifier(data_type)),
                    records_to_upsert,
                )

                logger.debug(
                    "🐘 Batch upserted records",
                    data_type=data_type,
                    upserted=len(records_to_upsert),
                    skipped=skipped_count,
                )

    async def flush_all(self) -> None:
        """Flush all pending queues."""
        for data_type in self.queues:
            await self._flush_queue(data_type)

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
        }
