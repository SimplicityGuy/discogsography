import asyncio
import contextlib
import os
import signal
import time
from asyncio import run
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from aio_pika.abc import AbstractIncomingMessage
from common import (
    AMQP_EXCHANGE_PREFIX,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    DATA_TYPES,
    AsyncPostgreSQLPool,
    AsyncResilientRabbitMQ,
    HealthServer,
    TableinatorConfig,
    normalize_record,
    setup_logging,
)
from orjson import loads
from psycopg import sql
from psycopg.errors import InterfaceError, OperationalError
from psycopg.types.json import Jsonb

from tableinator.batch_processor import BatchConfig, PostgreSQLBatchProcessor

logger = structlog.get_logger(__name__)

# Config will be initialized in main
config: TableinatorConfig | None = None

# Progress tracking
message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
progress_interval = 100  # Log progress every 100 messages
last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}
completed_files: set[str] = set()  # Track which files have completed processing
current_task = None
current_progress = 0.0

# Consumer management
consumer_tags: dict[str, str] = {}  # {"artists": "consumer-tag-123", ...}
consumer_cancel_tasks: dict[
    str, asyncio.Task[None]
] = {}  # {"artists": asyncio.Task, ...}
queues: dict[str, Any] = {}  # {"artists": queue_object, ...}
CONSUMER_CANCEL_DELAY = int(
    os.environ.get("CONSUMER_CANCEL_DELAY", "300")
)  # Default 5 minutes

# Periodic queue checking settings
QUEUE_CHECK_INTERVAL = int(
    os.environ.get("QUEUE_CHECK_INTERVAL", "3600")
)  # Default 1 hour - how often to check for new messages when connection is closed

# Interval for checking stuck state (consumers died unexpectedly)
STUCK_CHECK_INTERVAL = int(
    os.environ.get("STUCK_CHECK_INTERVAL", "30")
)  # Default 30 seconds - how often to check for stuck state

# Idle mode settings - reduce log noise when no messages arrive after startup
STARTUP_IDLE_TIMEOUT = int(
    os.environ.get("STARTUP_IDLE_TIMEOUT", "30")
)  # Seconds after startup with no messages before entering idle mode
IDLE_LOG_INTERVAL = int(
    os.environ.get("IDLE_LOG_INTERVAL", "300")
)  # 5 min between idle status logs

# Idle mode state
idle_mode = False

# Connection parameters will be initialized in main
connection_params: dict[str, Any] = {}

# Connection state tracking
# Create async connection pool for concurrent access
connection_pool: AsyncPostgreSQLPool | None = None

rabbitmq_manager: Any = None  # Will hold AsyncResilientRabbitMQ instance
active_connection: Any = None  # Current active connection
active_channel: Any = None  # Current active channel
connection_check_task: asyncio.Task[None] | None = (
    None  # Background task for periodic queue checks
)


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    # Determine current task based on active consumers and recent activity
    active_task = None
    current_time = time.time()

    # Check for recent message activity (within last 10 seconds)
    for data_type, last_time in last_message_time.items():
        if last_time > 0 and (current_time - last_time) < 10:
            active_task = f"Processing {data_type}"
            break

    # If no recent activity but consumers exist, show as idle
    if active_task is None and len(consumer_tags) > 0:
        active_task = "Idle - waiting for messages"

    # Check for stuck state: no consumers but work remains (files not completed)
    no_active_consumers = len(consumer_tags) == 0
    files_incomplete = len(completed_files) < len(DATA_TYPES)
    has_processed_messages = any(count > 0 for count in message_counts.values())
    is_stuck = no_active_consumers and files_incomplete and has_processed_messages

    if is_stuck:
        active_task = "STUCK - consumers died, awaiting recovery"

    # Determine health status:
    # - "starting" if connection pool not yet initialized (startup in progress)
    # - "unhealthy" if connection pool was initialized but is now None (connection lost)
    # - "unhealthy" if in stuck state (consumers died unexpectedly)
    # - "healthy" if connection pool is initialized and ready
    if connection_pool is None:
        # Check if we're still in startup (no consumers registered yet)
        if len(consumer_tags) == 0 and all(c == 0 for c in message_counts.values()):
            status = "starting"
            active_task = "Initializing PostgreSQL connection"
        else:
            status = "unhealthy"
    elif is_stuck:
        status = "unhealthy"
    else:
        status = "healthy"

    return {
        "status": status,
        "service": "tableinator",
        "current_task": active_task,
        "progress": current_progress,
        "message_counts": message_counts.copy(),
        "last_message_time": last_message_time.copy(),
        "active_consumers": list(consumer_tags.keys()),
        "completed_files": list(completed_files),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# Batch processor (optional, enabled via BATCH_MODE env var)
batch_processor: PostgreSQLBatchProcessor | None = None
BATCH_MODE = os.environ.get("POSTGRES_BATCH_MODE", "true").lower() == "true"
BATCH_SIZE = int(os.environ.get("POSTGRES_BATCH_SIZE", "100"))
BATCH_FLUSH_INTERVAL = float(os.environ.get("POSTGRES_BATCH_FLUSH_INTERVAL", "5.0"))

# Global shutdown flag
shutdown_requested = False


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info("🛑 Received signal, initiating graceful shutdown...", signum=signum)
    shutdown_requested = True


def get_connection() -> Any:
    """Get a database connection from the pool."""
    if connection_pool is None:
        raise RuntimeError("Connection pool not initialized")

    return connection_pool.connection()


async def schedule_consumer_cancellation(data_type: str, queue: Any) -> None:
    """Schedule cancellation of a consumer after a delay."""

    async def cancel_after_delay() -> None:
        try:
            await asyncio.sleep(CONSUMER_CANCEL_DELAY)

            if data_type in consumer_tags:
                consumer_tag = consumer_tags[data_type]
                logger.info(
                    f"🔧 Canceling consumer for {data_type} after {CONSUMER_CANCEL_DELAY}s grace period",
                    data_type=data_type,
                    CONSUMER_CANCEL_DELAY=CONSUMER_CANCEL_DELAY,
                )

                # Cancel the consumer with nowait to avoid hanging
                await queue.cancel(consumer_tag, nowait=True)

                # Remove from tracking
                del consumer_tags[data_type]

                logger.info(
                    f"✅ Consumer for {data_type} successfully canceled",
                    data_type=data_type,
                )

                # Check if all consumers are now idle
                if await check_all_consumers_idle():
                    logger.info("🔧 All consumers idle, closing RabbitMQ connection")
                    await close_rabbitmq_connection()
        except Exception as e:
            logger.error(
                "❌ Failed to cancel consumer", data_type=data_type, error=str(e)
            )
        finally:
            # Clean up the task reference
            if data_type in consumer_cancel_tasks:
                del consumer_cancel_tasks[data_type]

    # Cancel any existing scheduled cancellation
    if data_type in consumer_cancel_tasks:
        consumer_cancel_tasks[data_type].cancel()

    # Schedule new cancellation
    consumer_cancel_tasks[data_type] = asyncio.create_task(cancel_after_delay())


async def close_rabbitmq_connection() -> None:
    """Close the RabbitMQ connection and channel when all consumers are idle."""
    global active_connection, active_channel

    try:
        if active_channel:
            try:
                await active_channel.close()
                logger.info("🔧 Closed RabbitMQ channel - all consumers idle")
            except Exception as e:
                logger.warning("⚠️ Error closing channel", error=str(e))
            active_channel = None

        if active_connection:
            try:
                await active_connection.close()
                logger.info("🔧 Closed RabbitMQ connection - all consumers idle")
            except Exception as e:
                logger.warning("⚠️ Error closing connection", error=str(e))
            active_connection = None

        logger.info(
            f"✅ RabbitMQ connection closed. Will check for new messages every {QUEUE_CHECK_INTERVAL}s",
            QUEUE_CHECK_INTERVAL=QUEUE_CHECK_INTERVAL,
        )
    except Exception as e:
        logger.error("❌ Error closing RabbitMQ connection", error=str(e))


async def check_all_consumers_idle() -> bool:
    """Check if all consumers are cancelled (idle) AND all files completed."""
    return len(consumer_tags) == 0 and len(DATA_TYPES) == len(completed_files)


async def check_consumers_unexpectedly_dead() -> bool:
    """Check if consumers have died unexpectedly (no consumers but files not completed).

    This detects the stuck state where:
    - No consumers are active (consumer_tags is empty)
    - Not all files are completed (some work remains)
    - We've processed at least some messages (not just starting up)

    Returns:
        True if consumers appear to have died unexpectedly
    """
    no_active_consumers = len(consumer_tags) == 0
    files_incomplete = len(completed_files) < len(DATA_TYPES)
    has_processed_messages = any(count > 0 for count in message_counts.values())

    return no_active_consumers and files_incomplete and has_processed_messages


async def periodic_queue_checker() -> None:
    """Periodically check queue health and recover from stuck states.

    This task handles two scenarios:
    1. Normal idle state: All files completed, check for new messages periodically
    2. Stuck state: Consumers died unexpectedly, need immediate recovery

    The stuck state check runs frequently (every STUCK_CHECK_INTERVAL seconds) to
    detect and recover quickly. The normal idle check runs at QUEUE_CHECK_INTERVAL.
    """
    global active_connection, active_channel, queues, consumer_tags

    last_full_check = 0.0  # Track when we last did a full queue check

    while not shutdown_requested:
        try:
            await asyncio.sleep(STUCK_CHECK_INTERVAL)

            current_time = time.time()

            # Check for stuck state (consumers died but work remains)
            if await check_consumers_unexpectedly_dead():
                logger.warning(
                    "⚠️ Detected stuck state: consumers died but files not completed. "
                    "Attempting recovery...",
                    active_consumers=len(consumer_tags),
                    completed_files=list(completed_files),
                    message_counts=message_counts,
                )
                await _recover_consumers()
                continue

            # Normal idle check: only run at QUEUE_CHECK_INTERVAL
            time_since_last_check = current_time - last_full_check
            if time_since_last_check < QUEUE_CHECK_INTERVAL:
                continue

            # Only do full queue check if no active consumers and connection is closed
            if active_connection or len(consumer_tags) > 0:
                continue

            last_full_check = current_time
            logger.info("🔄 Checking all queues for new messages...")
            await _recover_consumers()

        except asyncio.CancelledError:
            logger.info("🛑 Queue checker task cancelled")
            break
        except Exception as e:
            logger.error("❌ Error in periodic queue checker", error=str(e))
            # Continue running despite errors


async def _recover_consumers() -> None:
    """Recover consumers by reconnecting to RabbitMQ and restarting consumption.

    This function handles the actual recovery logic for both:
    - Normal recovery after idle period
    - Emergency recovery after unexpected consumer death
    """
    global active_connection, active_channel, queues, consumer_tags, idle_mode

    # Close any existing broken connection first
    if active_connection:
        try:
            await active_connection.close()
        except Exception:  # nosec: B110
            pass
        active_connection = None
        active_channel = None

    # Temporarily connect to check queue depths
    try:
        temp_connection = await rabbitmq_manager.connect()
        temp_channel = await temp_connection.channel()
    except Exception as e:
        logger.error("❌ Failed to connect to RabbitMQ for recovery", error=str(e))
        return

    try:
        # Check each queue for pending messages
        queues_with_messages = []
        for data_type in DATA_TYPES:
            queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{data_type}"

            # Use queue.declare with passive=True to get message count without affecting the queue
            declared_queue = await temp_channel.declare_queue(
                name=queue_name, passive=True
            )

            if declared_queue.declaration_result.message_count > 0:
                queues_with_messages.append(
                    (data_type, declared_queue.declaration_result.message_count)
                )

        if queues_with_messages:
            total_messages = sum(count for _, count in queues_with_messages)
            logger.info(
                "📬 Found messages in queues, restarting consumers",
                queues=queues_with_messages,
                total_messages=total_messages,
            )

            # Re-establish full connection and start consuming
            active_connection = temp_connection
            active_channel = temp_channel

            # Set QoS - scale with batch_size for efficient batch processing
            prefetch_count = max(200, BATCH_SIZE * 2) if BATCH_MODE else 200
            await active_channel.set_qos(prefetch_count=prefetch_count)

            # Declare per-data-type fanout exchanges and consumer-owned queues
            queues = {}
            for data_type in DATA_TYPES:
                exchange_name = f"{AMQP_EXCHANGE_PREFIX}-{data_type}"
                queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{data_type}"
                dlx_name = f"{queue_name}.dlx"
                dlq_name = f"{queue_name}.dlq"

                # Declare fanout exchange (must match extractor)
                exchange = await active_channel.declare_exchange(
                    exchange_name,
                    AMQP_EXCHANGE_TYPE,
                    durable=True,
                    auto_delete=False,
                )

                # Declare consumer-owned dead-letter exchange
                dlx_exchange = await active_channel.declare_exchange(
                    dlx_name,
                    AMQP_EXCHANGE_TYPE,
                    durable=True,
                    auto_delete=False,
                )

                # Declare DLQ (classic queue for dead letters)
                dlq = await active_channel.declare_queue(
                    auto_delete=False,
                    durable=True,
                    name=dlq_name,
                    arguments={"x-queue-type": "classic"},
                )
                await dlq.bind(dlx_exchange)

                # Declare main quorum queue with consumer-owned DLX
                queue_args = {
                    "x-queue-type": "quorum",
                    "x-dead-letter-exchange": dlx_name,
                    "x-delivery-limit": 20,
                }
                queue = await active_channel.declare_queue(
                    auto_delete=False,
                    durable=True,
                    name=queue_name,
                    arguments=queue_args,
                )
                await queue.bind(exchange)
                queues[data_type] = queue

            # Start consumers for queues with messages
            for data_type, msg_count in queues_with_messages:
                if data_type in queues and data_type not in consumer_tags:
                    handler = make_data_handler(data_type)
                    consumer_tag = await queues[data_type].consume(handler)
                    consumer_tags[data_type] = consumer_tag
                    # Remove from completed files so it will be processed
                    completed_files.discard(data_type)
                    last_message_time[data_type] = time.time()
                    logger.info(
                        f"✅ Started consumer for {data_type}",
                        data_type=data_type,
                        pending_messages=msg_count,
                    )

            logger.info(
                "✅ Recovery complete - consumers restarted",
                active_consumers=list(consumer_tags.keys()),
            )
            # Clear idle mode since we have active consumers again
            idle_mode = False
            # Don't close temp_connection since we're using it as active_connection
        else:
            logger.info("⏳ No messages in any queue, connection remains closed")
            # Close the temporary connection
            await temp_channel.close()
            await temp_connection.close()

    except Exception as e:
        logger.error("❌ Error during consumer recovery", error=str(e))
        # Make sure to close temporary connection on error
        try:
            await temp_channel.close()
            await temp_connection.close()
        except Exception:  # nosec: B110
            pass


async def purge_stale_rows(data_type: str, started_at: str) -> None:
    """Delete rows from prior extractions that were not updated in the current run.

    The extraction_complete message includes started_at — the time the extraction
    began. Any row with updated_at < started_at was not touched by the current
    extraction and is stale (removed from the Discogs dump or from a prior run).
    """
    if connection_pool is None:
        return

    if not started_at:
        logger.warning(
            "⚠️ No started_at in extraction_complete, skipping stale row purge",
            data_type=data_type,
        )
        return

    # Parse started_at as a timezone-aware UTC datetime to ensure correct comparison
    started_at_dt = datetime.fromisoformat(started_at)
    if started_at_dt.tzinfo is None:
        started_at_dt = started_at_dt.replace(tzinfo=UTC)

    try:
        async with connection_pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cursor:
                    await cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # safe: psycopg2 sql.Identifier parameterizes the identifier, not user input
                        sql.SQL(
                            "DELETE FROM {table} WHERE updated_at < %s RETURNING data_id"
                        ).format(table=sql.Identifier(data_type)),
                        (started_at_dt,),
                    )
                    deleted_rows = await cursor.fetchall()
                    deleted_count = len(deleted_rows)

                    if deleted_count > 0:
                        logger.info(
                            f"🧹 Purged {deleted_count} stale {data_type} rows "
                            f"(not updated since extraction started)",
                            data_type=data_type,
                            deleted=deleted_count,
                        )
                    else:
                        logger.info(
                            f"✅ No stale {data_type} rows to purge",
                            data_type=data_type,
                        )
    except Exception as e:
        logger.error(
            f"❌ Failed to purge stale {data_type} rows",
            data_type=data_type,
            error=str(e),
        )
        raise


def make_data_handler(
    data_type: str,
) -> Any:
    """Create a per-data-type message handler that injects data_type context."""

    async def handler(message: AbstractIncomingMessage) -> None:
        await on_data_message(message, data_type)

    return handler


async def on_data_message(message: AbstractIncomingMessage, data_type: str) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        data: dict[str, Any] = loads(message.body)

        # Check if this is a file completion message
        if data.get("type") == "file_complete":
            total_processed = data.get("total_processed", 0)
            logger.info(
                f"✅ File processing complete for {data_type}! "
                f"Total records processed: {total_processed}"
            )

            # Flush remaining batches for this data type before cancellation
            if batch_processor is not None:
                await batch_processor.flush_queue(data_type)

            # Mark complete only after flush to prevent premature idle detection
            completed_files.add(data_type)

            # Schedule consumer cancellation if enabled
            if CONSUMER_CANCEL_DELAY > 0 and data_type in queues:
                await schedule_consumer_cancellation(data_type, queues[data_type])

            await message.ack()
            return

        # Check if this is an extraction completion message
        if data.get("type") == "extraction_complete":
            logger.info(
                "🏁 Received extraction_complete signal",
                data_type=data_type,
                version=data.get("version"),
            )

            # Flush remaining batches for this data type before cleanup
            if batch_processor is not None:
                await batch_processor.flush_queue(data_type)

            # Purge stale rows from prior extractions
            purge_ok = True
            if connection_pool is not None:
                try:
                    await purge_stale_rows(data_type, data.get("started_at", ""))
                except Exception as purge_exc:
                    logger.error(
                        "❌ Purge failed, nacking extraction_complete for retry",
                        data_type=data_type,
                        error=str(purge_exc),
                    )
                    purge_ok = False

            if purge_ok:
                await message.ack()
            else:
                await message.nack(requeue=True)
            return

        # Normal message processing - require 'id' field
        if "id" not in data:
            logger.error("❌ Message missing 'id' field: data", data=data)
            await message.nack(requeue=False)
            return

        # If batch mode is enabled, delegate to batch processor
        if BATCH_MODE and batch_processor is not None:
            # Update progress tracking
            if data_type in message_counts:
                message_counts[data_type] += 1
                last_message_time[data_type] = time.time()

            await batch_processor.add_message(
                data_type=data_type,
                data=data,
                ack_callback=message.ack,
                nack_callback=lambda: message.nack(requeue=True),
            )
            return

        # Non-batch mode: process individual messages
        data_id: str = data["id"]

        # Normalize data to ensure consistent format (handles @id -> id, #text -> name, etc.)
        # This matches the normalization done in graphinator for consistency
        data = normalize_record(data_type, data)

        # Extract record details for logging
        record_name = None
        if data_type == "artists":
            record_name = data.get("name", "Unknown Artist")
        elif data_type == "labels":
            record_name = data.get("name", "Unknown Label")
        elif data_type == "releases":
            record_name = data.get("title", "Unknown Release")
        elif data_type == "masters":
            record_name = data.get("title", "Unknown Master")

        # Log at debug level to reduce noise
        if record_name:
            logger.debug(
                "🔄 Processing record",
                data_type=data_type[:-1],
                data_id=data_id,
                record_name=record_name,
            )
        else:
            logger.debug(
                "🔄 Processing record", data_type=data_type[:-1], data_id=data_id
            )

    except Exception as e:
        logger.error("❌ Failed to parse message", error=str(e))
        await message.nack(requeue=False)
        return

    # Process record using async connection pool for concurrent access
    try:
        if connection_pool is None:
            raise RuntimeError("Connection pool not initialized")

        async with connection_pool.connection() as conn:
            async with conn.cursor() as cursor:
                # Conditional upsert: only rewrites hash and data when hash differs,
                # but always refreshes updated_at so post-extraction stale row
                # purge does not delete unchanged-but-still-present records.
                await cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # safe: psycopg2 sql.Identifier parameterizes the identifier, not user input
                    sql.SQL(
                        "INSERT INTO {table} (hash, data_id, data, updated_at) "
                        "VALUES (%s, %s, %s, NOW()) "
                        "ON CONFLICT (data_id) DO UPDATE "
                        "SET hash = CASE WHEN {table}.hash != EXCLUDED.hash "
                        "THEN EXCLUDED.hash ELSE {table}.hash END, "
                        "data = CASE WHEN {table}.hash != EXCLUDED.hash "
                        "THEN EXCLUDED.data ELSE {table}.data END, "
                        "updated_at = NOW();"
                    ).format(table=sql.Identifier(data_type)),
                    (
                        data.get("sha256", ""),
                        data_id,
                        Jsonb(data),
                    ),
                )

                # Commit is automatic when exiting the connection context
                logger.debug(
                    "🐘 Updated record in PostgreSQL",
                    data_type=data_type[:-1],
                    data_id=data_id,
                )

        await message.ack()

        # Increment counter and log progress only after successful DB write and ack
        if data_type in message_counts:
            message_counts[data_type] += 1
            last_message_time[data_type] = time.time()
            if message_counts[data_type] % progress_interval == 0:
                logger.info(
                    "📊 Processed records in PostgreSQL",
                    count=message_counts[data_type],
                    data_type=data_type,
                )

    except (InterfaceError, OperationalError) as e:
        logger.warning("⚠️ Database connection issue, will retry", error=str(e))
        await message.nack(requeue=True)
    except Exception as e:
        logger.error("❌ Failed to process message", data_type=data_type, error=str(e))
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning("⚠️ Failed to nack message", error=str(nack_error))


async def progress_reporter() -> None:
    global idle_mode

    report_count = 0
    startup_time = time.time()
    last_idle_log = 0.0

    while not shutdown_requested:
        # More frequent reports initially, then every 30 seconds
        if report_count < 3:
            await asyncio.sleep(10)  # First 3 reports every 10 seconds
        else:
            await asyncio.sleep(30)  # Then every 30 seconds
        report_count += 1

        # Skip all logging if all files are complete
        if len(completed_files) == len(DATA_TYPES):
            continue

        total = sum(message_counts.values())
        current_time = time.time()

        # Idle mode detection: no messages received after STARTUP_IDLE_TIMEOUT
        # Idle mode only suppresses reporting - consumers stay connected
        if (
            not idle_mode
            and total == 0
            and (current_time - startup_time) >= STARTUP_IDLE_TIMEOUT
        ):
            idle_mode = True
            last_idle_log = current_time
            logger.info(
                f"😴 No messages received after {STARTUP_IDLE_TIMEOUT}s, entering idle mode. "
                "Consumers remain connected, reporting paused.",
                startup_idle_timeout=STARTUP_IDLE_TIMEOUT,
            )
            continue

        # While in idle mode, only log briefly every IDLE_LOG_INTERVAL
        if idle_mode:
            if total > 0:
                # Messages started flowing, exit idle mode
                idle_mode = False
                logger.info("🔄 Messages detected, resuming normal operation")
            elif (current_time - last_idle_log) >= IDLE_LOG_INTERVAL:
                last_idle_log = current_time
                logger.info(
                    "😴 Idle mode - waiting for messages. Consumers connected.",
                )
            continue

        # Check for stalled consumers (skip completed files)
        stalled_consumers = []
        for data_type, last_time in last_message_time.items():
            if (
                data_type not in completed_files
                and last_time > 0
                and (current_time - last_time) > 120
            ):  # No messages for 2 minutes
                stalled_consumers.append(data_type)

        if stalled_consumers:
            logger.error(
                f"⚠️ Stalled consumers detected: {stalled_consumers}. "
                f"No messages processed for >2 minutes."
            )

        # Always show progress, even if no messages processed yet
        # Build progress string with completion emojis
        progress_parts = []
        for data_type in ["artists", "labels", "masters", "releases"]:
            emoji = "✅ " if data_type in completed_files else ""
            progress_parts.append(
                f"{emoji}{data_type.capitalize()}: {message_counts[data_type]}"
            )

        logger.info(
            f"📊 PostgreSQL Progress: {total} total messages processed "
            f"({', '.join(progress_parts)})"
        )

        # Log current processing state
        if total == 0:
            logger.info("⏳ Waiting for messages to process...")
        elif all(
            current_time - last_time < 5
            for last_time in last_message_time.values()
            if last_time > 0
        ):
            logger.info("✅ All consumers actively processing")
        elif any(
            last_time > 0 and 5 < current_time - last_time < 120
            for last_time in last_message_time.values()
        ):
            slow_consumers = [
                dt
                for dt, lt in last_message_time.items()
                if lt > 0 and 5 < current_time - lt < 120
            ]
            logger.warning(
                f"⚠️ Slow consumers detected: {slow_consumers}",
                slow_consumers=slow_consumers,
            )

        # Log consumer status
        active_consumers = list(consumer_tags.keys())
        canceled_consumers = [
            dt for dt in DATA_TYPES if dt not in consumer_tags and dt in completed_files
        ]

        if canceled_consumers:
            logger.info(
                f"🔧 Canceled consumers: {canceled_consumers}",
                canceled_consumers=canceled_consumers,
            )
        if active_consumers:
            logger.info(
                f"✅ Active consumers: {active_consumers}",
                active_consumers=active_consumers,
            )


async def main() -> None:
    global \
        connection_pool, \
        config, \
        connection_params, \
        queues, \
        rabbitmq_manager, \
        active_connection, \
        active_channel, \
        connection_check_task, \
        batch_processor

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("tableinator", log_file=Path("/logs/tableinator.log"))
    logger.info("🚀 Starting PostgreSQL tableinator service with connection pooling")

    # Add startup delay for dependent services
    startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
    if startup_delay > 0:
        logger.info(
            f"⏳ Waiting {startup_delay} seconds for dependent services to start...",
            startup_delay=startup_delay,
        )
        await asyncio.sleep(startup_delay)

    # Start health server
    health_server = HealthServer(8002, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8002")

    # Initialize configuration
    try:
        config = TableinatorConfig.from_env()
    except ValueError as e:
        logger.error("❌ Configuration error", error=str(e))
        return

    # Parse host and port from address
    if ":" in config.postgres_host:
        host, port_str = config.postgres_host.split(":", 1)
        port = int(port_str)
    else:
        host = config.postgres_host
        port = 5432

    # Set connection parameters
    connection_params = {
        "host": str(host),
        "port": int(port),
        "dbname": str(config.postgres_database),
        "user": str(config.postgres_username),
        "password": str(config.postgres_password),
    }

    # Initialize async resilient connection pool for concurrent access
    # Increased from max=20 to max=50 to match prefetch_count for better throughput
    try:
        connection_pool = AsyncPostgreSQLPool(
            connection_params=connection_params,
            max_connections=50,
            min_connections=5,
            max_retries=5,
            health_check_interval=30,
        )
        await connection_pool.initialize()
        logger.info("🐘 Connected to PostgreSQL with async resilient connection pool")
        logger.info(
            "✅ Async connection pool initialized (min: 5, max: 50 connections)"
        )
    except Exception as e:
        logger.error("❌ Failed to initialize connection pool", error=str(e))
        return

    # Initialize async batch processor if enabled
    if BATCH_MODE:
        batch_config = BatchConfig(
            batch_size=BATCH_SIZE,
            flush_interval=BATCH_FLUSH_INTERVAL,
        )
        batch_processor = PostgreSQLBatchProcessor(connection_pool, batch_config)
        logger.info(
            "🚀 Async batch processing enabled",
            batch_size=BATCH_SIZE,
            flush_interval=BATCH_FLUSH_INTERVAL,
        )
    else:
        logger.info("📝 Using per-message processing (batch mode disabled)")
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗                                   ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝                                   ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗                                   ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║                                   ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║                                   ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝                                   ")
    print("                                                                                        ")
    print("████████╗ █████╗ ██████╗ ██╗     ███████╗██╗███╗   ██╗ █████╗ ████████╗ ██████╗ ██████╗ ")
    print("╚══██╔══╝██╔══██╗██╔══██╗██║     ██╔════╝██║████╗  ██║██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗")
    print("   ██║   ███████║██████╔╝██║     █████╗  ██║██╔██╗ ██║███████║   ██║   ██║   ██║██████╔╝")
    print("   ██║   ██╔══██║██╔══██╗██║     ██╔══╝  ██║██║╚██╗██║██╔══██║   ██║   ██║   ██║██╔══██╗")
    print("   ██║   ██║  ██║██████╔╝███████╗███████╗██║██║ ╚████║██║  ██║   ██║   ╚██████╔╝██║  ██║")
    print("   ╚═╝   ╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝")
    print()
    # fmt: on

    # Initialize resilient RabbitMQ connection manager (not connecting yet)
    rabbitmq_manager = AsyncResilientRabbitMQ(
        connection_url=config.amqp_connection,
        max_retries=10,  # More retries for startup
        heartbeat=600,
        connection_attempts=10,
        retry_delay=5.0,
    )

    # Try to connect with additional retry logic for startup
    max_startup_retries = 5
    startup_retry = 0
    amqp_connection = None

    while startup_retry < max_startup_retries and not shutdown_requested:
        try:
            logger.info(
                "🐰 Attempting to connect to RabbitMQ",
                attempt=startup_retry + 1,
                max_attempts=max_startup_retries,
            )
            amqp_connection = await rabbitmq_manager.connect()
            active_connection = amqp_connection
            break
        except Exception as e:
            startup_retry += 1
            if startup_retry < max_startup_retries:
                wait_time = min(30, 5 * startup_retry)  # Exponential backoff up to 30s
                logger.warning(
                    "⚠️ RabbitMQ connection failed. Retrying...",
                    error=str(e),
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "❌ Failed to connect to AMQP broker",
                    max_attempts=max_startup_retries,
                    error=str(e),
                )
                return

    if amqp_connection is None:
        logger.error("❌ No AMQP connection available")
        return

    async with amqp_connection:
        channel = await amqp_connection.channel()
        active_channel = channel

        # Set QoS to allow concurrent batch processing for better throughput
        # prefetch_count must be >= batch_size to allow batches to fill before flushing
        prefetch_count = max(200, BATCH_SIZE * 2) if BATCH_MODE else 200
        await channel.set_qos(prefetch_count=prefetch_count)
        logger.info(
            "🔧 QoS prefetch configured",
            prefetch_count=prefetch_count,
            batch_size=BATCH_SIZE if BATCH_MODE else "N/A",
        )

        # Declare per-data-type fanout exchanges and consumer-owned queues
        queues = {}
        for data_type in DATA_TYPES:
            exchange_name = f"{AMQP_EXCHANGE_PREFIX}-{data_type}"
            queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{data_type}"
            dlx_name = f"{queue_name}.dlx"
            dlq_name = f"{queue_name}.dlq"

            # Declare fanout exchange (must match extractor)
            exchange = await channel.declare_exchange(
                exchange_name, AMQP_EXCHANGE_TYPE, durable=True, auto_delete=False
            )

            # Declare consumer-owned dead-letter exchange
            dlx_exchange = await channel.declare_exchange(
                dlx_name, AMQP_EXCHANGE_TYPE, durable=True, auto_delete=False
            )

            # Declare DLQ (classic queue for dead letters)
            dlq = await channel.declare_queue(
                auto_delete=False,
                durable=True,
                name=dlq_name,
                arguments={"x-queue-type": "classic"},
            )
            await dlq.bind(dlx_exchange)

            # Declare main quorum queue with consumer-owned DLX
            queue_args = {
                "x-queue-type": "quorum",
                "x-dead-letter-exchange": dlx_name,
                "x-delivery-limit": 20,
            }
            queue = await channel.declare_queue(
                auto_delete=False,
                durable=True,
                name=queue_name,
                arguments=queue_args,
            )
            await queue.bind(exchange)
            queues[data_type] = queue

        # Start consumers for all data types
        for data_type in DATA_TYPES:
            handler = make_data_handler(data_type)
            consumer_tags[data_type] = await queues[data_type].consume(handler)

        logger.info(
            f"🚀 Tableinator started! Connected to AMQP broker ({len(DATA_TYPES)} fanout exchanges). "
            f"Consuming from {len(DATA_TYPES)} queues with connection pool (max 50 connections). "
            "Ready to process messages into PostgreSQL. Press CTRL+C to exit"
        )

        progress_task = asyncio.create_task(progress_reporter())

        # Start periodic queue checker task
        connection_check_task = asyncio.create_task(periodic_queue_checker())
        logger.info(
            f"🔄 Started periodic queue checker (interval: {QUEUE_CHECK_INTERVAL}s)",
            QUEUE_CHECK_INTERVAL=QUEUE_CHECK_INTERVAL,
        )

        # Start batch processor periodic flush task if enabled
        batch_flush_task = None
        if BATCH_MODE and batch_processor is not None:
            batch_flush_task = asyncio.create_task(batch_processor.periodic_flush())
            logger.info("🔄 Started batch processor periodic flush task")

        try:
            # Create a shutdown event that can be triggered by signal handler
            shutdown_event = asyncio.Event()

            # Check for shutdown periodically
            while not shutdown_requested:
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
                    break
                except TimeoutError:
                    continue

        except KeyboardInterrupt:
            logger.info("🛑 Received interrupt signal, shutting down gracefully")
        finally:
            # Cancel progress reporting
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task

            # Cancel connection check task
            if connection_check_task:
                connection_check_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await connection_check_task
                logger.info("✅ Queue checker task stopped")

            # Cancel batch flush task and flush remaining messages
            if batch_flush_task:
                batch_flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await batch_flush_task
            if batch_processor:
                batch_processor.shutdown()
                try:
                    await batch_processor.flush_all()
                    logger.info("✅ Batch processor flushed and stopped")
                except Exception as e:
                    logger.warning("⚠️ Error flushing batch processor", error=str(e))

            # Cancel any pending consumer cancellation tasks
            for task in list(consumer_cancel_tasks.values()):
                task.cancel()

            # Close RabbitMQ connection if still active
            await close_rabbitmq_connection()

            # Close async connection pool
            try:
                if connection_pool:
                    await connection_pool.close()
                    logger.info("✅ Async connection pool closed")
            except Exception as e:
                logger.warning("⚠️ Error closing connection pool", error=str(e))

        # Stop health server
        health_server.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        logger.warning("⚠️ Application interrupted")
    except Exception as e:
        logger.error("❌ Application error", error=str(e))
    finally:
        logger.info("✅ Tableinator service shutdown complete")
