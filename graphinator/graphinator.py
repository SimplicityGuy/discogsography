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
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    DATA_TYPES,
    DISCOGS_EXCHANGE_PREFIX,
    AsyncResilientNeo4jDriver,
    AsyncResilientRabbitMQ,
    GraphinatorConfig,
    HealthServer,
    OutageBackoff,
    neo4j_security_kwargs,
    normalize_record,
    setup_logging,
)
from common.credit_roles import categorize_role
from common.db_resilience import DatabaseUnavailableError
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
from orjson import loads

from graphinator.batch_processor import BatchConfig, Neo4jBatchProcessor

logger = structlog.get_logger(__name__)

# Config will be initialized in main
config: GraphinatorConfig | None = None

# Progress tracking
message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
progress_interval = 100  # Log progress every 100 messages
last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}
completed_files: set[str] = set()  # Track which files have completed processing

# Non-batch mode only: throttles requeues while Neo4j is unavailable, so an
# outage cannot burn the quorum queue's x-delivery-limit budget and dead-letter
# valid records. Batch mode gets the same protection from _flush_queue's
# re-enqueue+backoff, which never nacks (discogsography-rb05).
outage_backoff = OutageBackoff("graphinator")
# Track which data types have delivered an extraction_complete signal. Stub
# cleanup and aggregate stats are deferred until EVERY type has signalled, so
# cross-type stub creation (release batches MERGE Artist/Label/Master stubs)
# has fully stopped before we DETACH DELETE.
#
# This set is only a CACHE of the durable latch stored in Neo4j (see
# _load_extraction_signals). Acking a signal destroys the only other copy — the
# queued message — so a restart between the first and last signal used to lose
# them all: the final signal then found 1-of-4, deferred forever, and post-import
# maintenance silently never ran. The latch is also keyed by extraction VERSION,
# so a long-lived process cannot carry a completed run's signals into the next
# dump and fire maintenance while other queues are still importing
# (discogsography-tk7v).
extraction_complete_signals: set[str] = set()
extraction_complete_version: str | None = None
EXTRACTION_LATCH_UNKNOWN_VERSION = "unknown"
# Post-import maintenance runs DETACHED from the AMQP delivery that triggers it
# (see check_file_completion). Strong references are held here so the loop cannot
# garbage-collect the task mid-flight.
post_import_maintenance_task: asyncio.Task[bool] | None = None
maintenance_tasks: set[asyncio.Task[bool]] = set()
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

# Driver will be initialized in main
graph: AsyncResilientNeo4jDriver | None = None

# Batch processor (optional, enabled via BATCH_MODE env var)
batch_processor: Neo4jBatchProcessor | None = None
BATCH_MODE = os.environ.get("NEO4J_BATCH_MODE", "true").lower() == "true"
BATCH_SIZE = int(os.environ.get("NEO4J_BATCH_SIZE", "100"))
BATCH_FLUSH_INTERVAL = float(os.environ.get("NEO4J_BATCH_FLUSH_INTERVAL", "5.0"))

# Connection state tracking
rabbitmq_manager: Any = None  # Will hold AsyncResilientRabbitMQ instance
active_connection: Any = None  # Current active connection
active_channel: Any = None  # Current active channel
connection_check_task: asyncio.Task[None] | None = (
    None  # Background task for periodic queue checks
)

# Global shutdown flag
shutdown_requested = False


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
    # - "starting" if graph driver not yet initialized (startup in progress)
    # - "unhealthy" if graph was initialized but is now None (connection lost)
    # - "unhealthy" if in stuck state (consumers died unexpectedly)
    # - "healthy" if graph is initialized and ready
    if graph is None:
        # Check if we're still in startup (no consumers registered yet)
        if len(consumer_tags) == 0 and all(c == 0 for c in message_counts.values()):
            status = "starting"
            active_task = "Initializing Neo4j connection"
        else:
            status = "unhealthy"
    elif is_stuck:
        status = "unhealthy"
    else:
        status = "healthy"

    return {
        "status": status,
        "service": "graphinator",
        "current_task": active_task,
        "progress": current_progress,
        "message_counts": message_counts.copy(),
        "last_message_time": last_message_time.copy(),
        "active_consumers": list(consumer_tags.keys()),
        "completed_files": list(completed_files),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info("🛑 Received signal, initiating graceful shutdown...", signum=signum)
    shutdown_requested = True


async def schedule_consumer_cancellation(data_type: str, queue: Any) -> None:
    """Schedule cancellation of a consumer after a delay."""

    async def cancel_after_delay() -> None:
        try:
            await asyncio.sleep(CONSUMER_CANCEL_DELAY)

            if data_type in consumer_tags:
                consumer_tag = consumer_tags[data_type]
                logger.info(
                    f"🔧 Canceling consumer for {data_type} after {CONSUMER_CANCEL_DELAY}s grace period"
                )

                # Cancel the consumer with nowait to avoid hanging
                await queue.cancel(consumer_tag, nowait=True)

                # Remove from tracking
                del consumer_tags[data_type]

                logger.info(
                    "✅ Consumer successfully canceled",
                    data_type=data_type,
                )

                # Check if all consumers are now idle
                if await check_all_consumers_idle():
                    logger.info("🔧 All consumers idle, closing RabbitMQ connection")
                    await close_rabbitmq_connection()
        except Exception as e:  # noqa: BLE001 - consumer cancellation is best-effort
            logger.error(
                "❌ Failed to cancel consumer",
                data_type=data_type,
                error=str(e),
            )
        finally:
            # Clean up the task reference
            consumer_cancel_tasks.pop(data_type, None)

    # Cancel any existing scheduled cancellation
    if data_type in consumer_cancel_tasks:
        consumer_cancel_tasks[data_type].cancel()

    # Schedule new cancellation
    consumer_cancel_tasks[data_type] = asyncio.create_task(cancel_after_delay())


async def cancel_all_consumers() -> None:
    """Stop new deliveries at shutdown by cancelling every consumer.

    Shutdown previously had no deregistration phase at all: the flag flipped, the
    consumers stayed subscribed, and the per-message guard nacked whatever the
    broker kept pushing. Cancelling here closes the delivery tap BEFORE the
    seconds-long flush/teardown sequence, so nothing is redelivered into a
    service that is on its way out. Best-effort: teardown continues regardless.
    """
    for data_type, consumer_tag in list(consumer_tags.items()):
        queue = queues.get(data_type)
        if queue is None:
            consumer_tags.pop(data_type, None)
            continue
        try:
            await queue.cancel(consumer_tag, nowait=True)
            consumer_tags.pop(data_type, None)
        except Exception as e:  # noqa: BLE001 - best-effort teardown; the connection is being discarded regardless
            logger.warning(
                "⚠️ Failed to cancel consumer during shutdown",
                data_type=data_type,
                error=str(e),
            )
    logger.info("✅ Consumers cancelled for shutdown")


async def close_rabbitmq_connection() -> None:
    """Close the RabbitMQ connection and channel when all consumers are idle."""
    global active_connection, active_channel

    try:
        if active_channel:
            try:
                await active_channel.close()
                logger.info("🔧 Closed RabbitMQ channel - all consumers idle")
            except Exception as e:  # noqa: BLE001 - best-effort teardown; the connection is being discarded regardless
                logger.warning("⚠️ Error closing channel", error=str(e))
            active_channel = None

        if active_connection:
            try:
                await active_connection.close()
                logger.info("🔧 Closed RabbitMQ connection - all consumers idle")
            except Exception as e:  # noqa: BLE001 - best-effort teardown; the connection is being discarded regardless
                logger.warning("⚠️ Error closing connection", error=str(e))
            active_connection = None

        logger.info(
            "✅ RabbitMQ connection closed", check_interval=f"{QUEUE_CHECK_INTERVAL}s"
        )
    except Exception as e:  # noqa: BLE001 - best-effort teardown; the connection is being discarded regardless
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
        except Exception as e:  # noqa: BLE001 - long-running loop must survive per-iteration faults
            logger.error("❌ Error in periodic queue checker", error=str(e))
            # Continue running despite errors


async def _recover_consumers() -> None:
    """Recover consumers by reconnecting to RabbitMQ and restarting consumption.

    This function handles the actual recovery logic for both:
    - Normal recovery after idle period
    - Emergency recovery after unexpected consumer death
    """
    global active_connection, active_channel, queues, idle_mode

    # Close any existing broken connection first
    if active_connection:
        try:
            await active_connection.close()
        except Exception as e:  # noqa: BLE001 - the connection is already broken; recovery must proceed regardless
            logger.warning(
                "⚠️ Error closing broken connection during recovery", error=str(e)
            )
        active_connection = None
        active_channel = None

    # Temporarily connect to check queue depths
    try:
        temp_connection = await rabbitmq_manager.connect()
        temp_channel = await temp_connection.channel()
    except Exception as e:  # noqa: BLE001 - recovery must not raise into its caller
        logger.error("❌ Failed to connect to RabbitMQ for recovery", error=str(e))
        return

    try:
        # Check each queue for pending messages
        queues_with_messages = []
        for data_type in DATA_TYPES:
            queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{data_type}"

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
                f"📬 Found messages in queues, restarting consumers: {queues_with_messages} "
                f"(total: {total_messages})"
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
                exchange_name = f"{DISCOGS_EXCHANGE_PREFIX}-{data_type}"
                queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{data_type}"
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

            # Start consumers for ALL data types lacking one — not just those
            # with a current backlog. A type whose queue was empty at the
            # passive-declare instant still needs a consumer; otherwise messages
            # that arrive later are never consumed, because once active_connection
            # is set and consumer_tags is non-empty both periodic recovery routes
            # are permanently gated off, silently starving that data type.
            pending_counts = dict(queues_with_messages)
            for data_type in DATA_TYPES:
                if data_type in queues and data_type not in consumer_tags:
                    handler = HANDLERS.get(data_type)
                    if handler:
                        consumer_tag = await queues[data_type].consume(
                            handler, consumer_tag=f"graphinator-{data_type}"
                        )
                        consumer_tags[data_type] = consumer_tag
                        # Only un-complete a type that actually has a backlog, so
                        # genuinely-finished types stay marked complete.
                        if data_type in pending_counts:
                            completed_files.discard(data_type)
                        last_message_time[data_type] = time.time()
                        logger.info(
                            f"✅ Started consumer for {data_type} "
                            f"(pending: {pending_counts.get(data_type, 0)})"
                        )

            logger.info(
                f"✅ Recovery complete - consumers restarted: {list(consumer_tags.keys())}"
            )
            # Clear idle mode since we have active consumers again
            idle_mode = False
            # Don't close temp_connection since we're using it as active_connection
        else:
            logger.info("⏳ No messages in any queue, connection remains closed")
            # Close the temporary connection
            await temp_channel.close()
            await temp_connection.close()

    except Exception as e:  # noqa: BLE001 - recovery must not raise into its caller
        logger.error("❌ Error during consumer recovery", error=str(e))
        # Make sure to close temporary connection on error
        try:
            await temp_channel.close()
            await temp_connection.close()
        except Exception as close_error:  # noqa: BLE001 - best-effort cleanup inside an error path
            logger.warning(
                "⚠️ Error closing temporary connection after recovery failure",
                error=str(close_error),
            )
        active_connection = None
        active_channel = None
        queues = {}
        # Clear stale consumer tags: any consumers registered before the error
        # died with the now-closed connection. Leaving them behind would keep
        # len(consumer_tags) > 0 forever, permanently gating off both recovery
        # routes (stuck-check requires 0 tags) while health still reads healthy.
        consumer_tags.clear()


async def _load_extraction_signals(version: str) -> set[str]:
    """Read the durable extraction_complete latch for this version from Neo4j.

    Returns the set of data types that have already signalled. Raises if Neo4j
    cannot answer — the caller must requeue rather than assume "none signalled",
    which would re-run maintenance state from scratch (discogsography-tk7v).
    """
    if graph is None:
        return set()

    async with graph.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (m:ExtractionCompletion {version: $version}) RETURN m.signals AS signals",
            version=version,
        )
        record = await result.single()

    if record is None or record["signals"] is None:
        return set()
    return {str(signal) for signal in record["signals"]}


async def _persist_extraction_signals(version: str, signals: set[str]) -> None:
    """Write the extraction_complete latch for this version to Neo4j.

    Called BEFORE the trigger message is acked, so the coordination state
    outlives the delivery that carried it.
    """
    if graph is None:
        return

    async with graph.session(database="neo4j") as session:
        await session.run(
            """
            MERGE (m:ExtractionCompletion {version: $version})
            ON CREATE SET m.created_at = datetime()
            SET m.signals = $signals, m.updated_at = datetime()
            """,
            version=version,
            signals=sorted(signals),
        )


async def _sync_extraction_signals(version: str) -> None:
    """Refresh the in-memory latch cache from Neo4j for this extraction version.

    On a version change the cache is rebuilt from that version's durable latch
    (usually empty), so signals from a previous dump can never satisfy the
    all-four check for the new one.
    """
    global extraction_complete_signals, extraction_complete_version

    if extraction_complete_version == version:
        return

    persisted = await _load_extraction_signals(version)
    if extraction_complete_version is not None:
        logger.info(
            "🔄 New extraction version — resetting the completion latch",
            previous_version=extraction_complete_version,
            version=version,
        )
    extraction_complete_signals = persisted
    extraction_complete_version = version
    if persisted:
        logger.info(
            "📥 Restored extraction_complete signals",
            version=version,
            received=sorted(persisted),
        )


async def check_file_completion(
    data: dict[str, Any], data_type: str, message: AbstractIncomingMessage
) -> bool:
    """Check if message is a file completion or extraction completion message."""
    if data.get("type") == "file_complete":
        total_processed = data.get("total_processed", 0)
        logger.info(
            f"✅ File processing complete for {data_type}! "
            f"Total records processed: {total_processed}"
        )

        # Flush remaining batches for this data type before cancellation
        if batch_processor is not None and not await batch_processor.flush_queue(
            data_type
        ):
            # The drain gave up with records still pending (typically a database
            # outage). Marking the file complete here would cancel the consumer
            # and let post-import maintenance run over an incomplete graph while
            # the service reports success. Requeue the marker instead — the
            # pending records stay queued and periodic_flush retries them.
            # See discogsography-hh7r.
            logger.error(
                "❌ Flush incomplete — requeueing file_complete instead of marking the file done",
                data_type=data_type,
            )
            await message.nack(requeue=True)
            return True

        # Mark complete only after flush succeeds
        completed_files.add(data_type)

        # Schedule consumer cancellation if enabled
        if CONSUMER_CANCEL_DELAY > 0 and data_type in queues:
            await schedule_consumer_cancellation(data_type, queues[data_type])

        await message.ack()
        return True

    if data.get("type") == "extraction_complete":
        logger.info(
            "🏁 Received extraction_complete signal",
            data_type=data_type,
            version=data.get("version"),
        )

        # Flush remaining batches for this data type before cleanup
        if batch_processor is not None and not await batch_processor.flush_queue(
            data_type
        ):
            # Records are still pending, so this type is NOT complete. Recording
            # the signal would let stub cleanup and stats run over a graph that is
            # still missing rows. Requeue and retry (discogsography-hh7r).
            logger.error(
                "❌ Flush incomplete — requeueing extraction_complete instead of recording the signal",
                data_type=data_type,
            )
            await message.nack(requeue=True)
            return True

        # Record this type's completion signal (idempotent — safe under
        # nack/requeue redelivery) in Neo4j BEFORE acking. The ack destroys the
        # queued message, which was otherwise the only durable copy of this
        # coordination state (discogsography-tk7v).
        version = str(data.get("version") or EXTRACTION_LATCH_UNKNOWN_VERSION)
        try:
            await _sync_extraction_signals(version)
            extraction_complete_signals.add(data_type)
            await _persist_extraction_signals(version, extraction_complete_signals)
        except Exception as e:  # noqa: BLE001 - a lost latch write must requeue, never ack
            logger.error(
                "❌ Failed to persist extraction_complete latch — requeueing the signal",
                data_type=data_type,
                version=version,
                error=str(e),
            )
            extraction_complete_signals.discard(data_type)
            await message.nack(requeue=True)
            return True

        # Defer stub cleanup and stats until EVERY data type has signalled
        # extraction_complete. The four fanout queues drain at very different
        # rates (releases is by far the largest and finishes last), and every
        # release batch MERGEs sha256-less Artist/Label/Master stubs for
        # dangling references. Cleaning per-type as each queue completes would
        # race those still-running release writers: stubs re-created after an
        # early cleanup persist forever, and DETACH DELETE can interleave with
        # freshly written release edges. Running once — after all four signals
        # — guarantees no consumer is still creating stubs.
        if not extraction_complete_signals.issuperset(DATA_TYPES):
            logger.info(
                "⏳ Deferring stub cleanup until all data types complete",
                data_type=data_type,
                received=sorted(extraction_complete_signals),
                pending=sorted(set(DATA_TYPES) - extraction_complete_signals),
            )
            await message.ack()
            return True

        logger.info(
            "🏁 All data types complete — running post-import maintenance",
            received=sorted(extraction_complete_signals),
        )

        # Ack the trigger BEFORE maintenance starts, never after. Post-import
        # maintenance is unbounded work — genre/style stats alone run ~10-30s per
        # node over 16 genres + ~757 styles, label stats cover ~2.3M labels, and
        # stub cleanup DETACH DELETEs millions of nodes — routinely hours. Holding
        # the delivery unacked across it trips RabbitMQ's 30-minute consumer ack
        # timeout, which closes the SHARED channel with PRECONDITION_FAILED: all
        # four consumers die, the signal is redelivered, maintenance restarts from
        # scratch, and after x-delivery-limit=20 redeliveries the trigger is
        # dead-lettered and maintenance never completes at all. See
        # discogsography-zjja.
        await message.ack()

        # Maintenance now runs detached with its own retry, because the AMQP
        # delivery is no longer available as a retry token.
        start_post_import_maintenance()
        return True

    return False


def start_post_import_maintenance() -> None:
    """Launch post-import maintenance as a detached, single-flight task.

    Single-flight matters: extraction_complete can be redelivered (consumer
    restart, recovery loop) and every step is a heavy Neo4j sweep — two
    concurrent runs would contend for the same transaction pool the retry logic
    is trying to relieve.
    """
    global post_import_maintenance_task

    if (
        post_import_maintenance_task is not None
        and not post_import_maintenance_task.done()
    ):
        logger.info(
            "⏳ Post-import maintenance already running — ignoring duplicate trigger"
        )
        return

    task = asyncio.create_task(run_post_import_maintenance())
    post_import_maintenance_task = task
    maintenance_tasks.add(task)
    task.add_done_callback(maintenance_tasks.discard)


async def run_post_import_maintenance() -> bool:
    """Run stub cleanup and aggregate stats, retrying on failure.

    Detached from the extraction_complete delivery (which is acked immediately),
    so this owns the retry the nack/requeue used to provide. Every step is
    idempotent, so a retry re-runs the whole sweep safely.

    Returns:
        True if a full pass succeeded, False if every attempt failed.
    """
    for attempt in range(1, POST_IMPORT_MAINTENANCE_MAX_ATTEMPTS + 1):
        if shutdown_requested:
            logger.warning(
                "🛑 Shutdown requested — abandoning post-import maintenance",
                attempt=attempt,
            )
            return False

        try:
            maintenance_ok = True

            # Clean up stub nodes created by cross-type MERGE operations, across
            # EVERY entity label — not just one type's — because release batches
            # create Artist/Label/Master stubs regardless of which signal arrived
            # last.
            if graph is not None and not await cleanup_all_stub_nodes():
                maintenance_ok = False

            # All releases are now imported — compute aggregate stats on
            # Genre/Style/Label nodes.
            if graph is not None and not await compute_genre_style_stats():
                maintenance_ok = False
        except Exception as e:  # noqa: BLE001 - detached task: log and retry instead of dying silently
            logger.error(
                "❌ Post-import maintenance raised", attempt=attempt, error=str(e)
            )
            maintenance_ok = False

        if maintenance_ok:
            logger.info("✅ Post-import maintenance complete", attempt=attempt)
            return True

        if attempt == POST_IMPORT_MAINTENANCE_MAX_ATTEMPTS:
            logger.error(
                "❌ Post-import maintenance failed after every attempt — stub nodes and "
                "aggregate stats are stale until it is re-run",
                attempts=attempt,
            )
            return False

        delay = POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
        logger.warning(
            "⚠️ Post-import maintenance failed — retrying",
            attempt=attempt,
            retry_in_seconds=delay,
        )
        await asyncio.sleep(delay)

    return False


async def compute_genre_style_stats() -> bool:
    """Pre-compute aggregate counts and first_year on Genre, Style, and Label nodes.

    Sets release_count, artist_count, label_count, style_count/genre_count,
    and first_year properties on each Genre and Style node.  Also sets
    release_count, artist_count, genre_count on Label nodes.

    - Genre/Style counts are read by explore/genre and explore/style endpoints,
      replacing 4 expensive traversal queries (~200M DB hits for Rock)
      with a single property read (~3 DB hits).
    - first_year is read by genre-emergence, replacing a full IS edge scan
      (~184M DB hits) with an index seek (~100 DB hits).
    - Label counts are read by explore/label, replacing a 1.2M DB-hit
      traversal (for Reprise Records with 55K releases) with ~3 DB hits.

    Should be called after all releases have been imported.

    Returns:
        True if all stats were computed (or there is no driver / no work),
        False if the computation failed — so the caller can nack and retry.
    """
    if graph is None:
        return True

    # Drive the batching with an outer MATCH so CALL {} IN TRANSACTIONS actually
    # commits one inner transaction per node (OF 1 ROWS = one genre/style per
    # transaction).  The driving MATCH MUST sit OUTSIDE the transactional
    # subquery, with the node re-imported via WITH; otherwise nothing precedes
    # the CALL, exactly one implicit input row drives it, and the entire update
    # runs in a SINGLE transaction — defeating the batching and hitting the
    # default 120s transaction timeout (each node takes ~10-30s).
    genre_cypher = """
    MATCH (g:Genre)
    CALL {
        WITH g
        CALL {
            WITH g
            MATCH (g)<-[:IS]-(r:Release)
            RETURN count(DISTINCT r) AS rc
        }
        CALL {
            WITH g
            MATCH (g)<-[:IS]-(r:Release)-[:BY]->(a:Artist)
            RETURN count(DISTINCT a) AS ac
        }
        CALL {
            WITH g
            MATCH (g)<-[:IS]-(r:Release)-[:ON]->(l:Label)
            RETURN count(DISTINCT l) AS lc
        }
        CALL {
            WITH g
            MATCH (g)<-[:IS]-(r:Release)-[:IS]->(s:Style)
            RETURN count(DISTINCT s) AS sc
        }
        CALL {
            WITH g
            MATCH (g)<-[:IS]-(r:Release)
            WHERE r.year > 0
            RETURN min(r.year) AS fy
        }
        SET g.release_count = rc, g.artist_count = ac,
            g.label_count = lc, g.style_count = sc,
            g.first_year = fy
    } IN TRANSACTIONS OF 1 ROWS
    """

    style_cypher = """
    MATCH (s:Style)
    CALL {
        WITH s
        CALL {
            WITH s
            MATCH (s)<-[:IS]-(r:Release)
            RETURN count(DISTINCT r) AS rc
        }
        CALL {
            WITH s
            MATCH (s)<-[:IS]-(r:Release)-[:BY]->(a:Artist)
            RETURN count(DISTINCT a) AS ac
        }
        CALL {
            WITH s
            MATCH (s)<-[:IS]-(r:Release)-[:ON]->(l:Label)
            RETURN count(DISTINCT l) AS lc
        }
        CALL {
            WITH s
            MATCH (s)<-[:IS]-(r:Release)-[:IS]->(g:Genre)
            RETURN count(DISTINCT g) AS gc
        }
        CALL {
            WITH s
            MATCH (s)<-[:IS]-(r:Release)
            WHERE r.year > 0
            RETURN min(r.year) AS fy
        }
        SET s.release_count = rc, s.artist_count = ac,
            s.label_count = lc, s.genre_count = gc,
            s.first_year = fy
    } IN TRANSACTIONS OF 1 ROWS
    """

    # Label stats: release_count, artist_count, genre_count.
    # Labels have higher cardinality (~2.3M) than genres (16) or styles (757),
    # but most labels have <100 releases so each batch computes quickly.
    # Use IN TRANSACTIONS OF 100 ROWS for throughput.
    label_cypher = """
    MATCH (l:Label)
    CALL {
        WITH l
        CALL {
            WITH l
            MATCH (l)<-[:ON]-(r:Release)
            RETURN count(DISTINCT r) AS rc
        }
        CALL {
            WITH l
            MATCH (l)<-[:ON]-(r:Release)-[:BY]->(a:Artist)
            RETURN count(DISTINCT a) AS ac
        }
        CALL {
            WITH l
            MATCH (l)<-[:ON]-(r:Release)-[:IS]->(g:Genre)
            RETURN count(DISTINCT g) AS gc
        }
        SET l.release_count = rc, l.artist_count = ac,
            l.genre_count = gc
    } IN TRANSACTIONS OF 100 ROWS
    """

    # These share the transaction-memory pool with stub cleanup and the insights
    # background scans, so they get the same retry-under-pressure treatment and
    # are staggered rather than run back to back.
    stats_queries = [
        ("Genre", genre_cypher),
        ("Style", style_cypher),
        ("Label", label_cypher),
    ]

    try:
        for index, (node_label, cypher) in enumerate(stats_queries):
            if index:
                await asyncio.sleep(MAINTENANCE_SETTLE_SECONDS)
            logger.info(f"📊 Computing aggregate stats on {node_label} nodes...")
            summary = await _run_maintenance_query(
                lambda _batch_size, _cypher=cypher: _cypher,
                f"{node_label} stats computation",
                node_label=node_label,
            )
            if summary is None:
                # Retries exhausted — already logged. Fail so the caller nacks
                # and the whole maintenance step is retried on the next cycle.
                return False
            logger.info(
                f"✅ {node_label} stats computed",
                counters=str(summary.counters),
            )
    except Exception as e:  # noqa: BLE001 - aggregate stats are advisory; failure must not stop ingestion
        logger.error(
            "❌ Failed to compute genre/style/label stats",
            error=str(e),
        )
        return False

    return True


# ── Post-import maintenance under transaction-memory pressure ──────────────
#
# Post-import maintenance shares Neo4j's single transaction-memory pool
# (dbms.memory.transaction.total.max, 16 GiB in production) with ingestion and
# the insights background scans. Jul 5-9 that pool was exhausted repeatedly
# (Neo.TransientError.General.MemoryPoolOutOfMemoryError), which killed
# stub-Master cleanup twice — silently skipping the maintenance — and broke
# seven dashboard health checks.
#
# Two defences, applied to EVERY batched maintenance query in this module:
#
#  1. Bound the working set. Smaller `IN TRANSACTIONS OF n ROWS` chunks keep a
#     single inner transaction cheap even when the chunk contains high-degree
#     nodes whose DETACH DELETE touches many relationships.
#  2. Retry with backoff AND a halved chunk size. Pool exhaustion is transient
#     and contention-driven, so waiting and then asking for less is the correct
#     response. Every query here is idempotent and `IN TRANSACTIONS` commits per
#     chunk, so a retry resumes from where the failed attempt stopped instead of
#     redoing its work.
#
# Reduced from 10000: a chunk of 10000 DETACH DELETEs over high-degree stubs was
# still large enough to contend for the shared pool.
STUB_CLEANUP_BATCH_SIZE = 1000

# Floor for the halving backoff — below this the round-trip overhead dominates.
MAINTENANCE_MIN_BATCH_SIZE = 50

MAINTENANCE_MAX_ATTEMPTS = 4
MAINTENANCE_RETRY_BASE_DELAY_SECONDS = 30.0

# Whole-sweep retries for the detached post-import maintenance task. The AMQP
# delivery is acked before maintenance starts (discogsography-zjja), so this — not
# nack/requeue — is what retries a failed sweep. Kept small: each pass is hours of
# Neo4j work, and every step is idempotent so a later manual re-run is always safe.
POST_IMPORT_MAINTENANCE_MAX_ATTEMPTS = 3
POST_IMPORT_MAINTENANCE_RETRY_DELAY_SECONDS = 60.0

# Pause between consecutive heavy maintenance queries so the transaction pool
# can drain before the next one claims it, rather than running them back to back.
MAINTENANCE_SETTLE_SECONDS = 5.0


async def _run_maintenance_query(
    build_cypher: Any,
    description: str,
    batch_size: int | None = None,
    **log_fields: Any,
) -> Any | None:
    """Run a batched maintenance query, retrying on transaction-memory exhaustion.

    Args:
        build_cypher: Callable taking the current batch size and returning the
            Cypher to run. Called again with a smaller size on each retry.
        description: Human-readable name used in log messages.
        batch_size: Starting `IN TRANSACTIONS OF n ROWS` size, or ``None`` for
            queries that are not batch-size parameterised.
        **log_fields: Extra structured log fields.

    Returns:
        The query summary on success, or ``None`` if every attempt failed.
    """
    if graph is None:
        return None

    current_batch = batch_size
    for attempt in range(1, MAINTENANCE_MAX_ATTEMPTS + 1):
        try:
            async with graph.session(database="neo4j") as session:
                result = await session.run(build_cypher(current_batch))
                return await result.consume()
        except TransientError as e:
            # Pool exhaustion / contention — retryable. Anything else is a real
            # error and propagates to the caller's handler.
            if attempt == MAINTENANCE_MAX_ATTEMPTS:
                logger.error(
                    f"❌ {description} exhausted retries under transaction-memory pressure",
                    attempts=attempt,
                    batch_size=current_batch,
                    error=str(e),
                    **log_fields,
                )
                return None
            delay = MAINTENANCE_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            if current_batch is not None:
                current_batch = max(MAINTENANCE_MIN_BATCH_SIZE, current_batch // 2)
            logger.warning(
                f"⚠️ {description} hit transaction-memory pressure — retrying with a smaller batch",
                attempt=attempt,
                next_batch_size=current_batch,
                retry_in_seconds=delay,
                error=str(e),
                **log_fields,
            )
            await asyncio.sleep(delay)
    return None


async def cleanup_all_stub_nodes() -> bool:
    """Clean up stub nodes for every entity label once all data is imported.

    Called only after every data type has delivered extraction_complete, so no
    consumer is still MERGEing cross-type stubs. Runs cleanup for all labels
    (Artist, Label, Master, Release) rather than a single type, because release
    batches create stubs of every other type.

    Returns:
        True if all label cleanups succeeded, False if any failed — so the
        caller can nack and retry (each cleanup is idempotent).
    """
    ok = True
    for index, data_type in enumerate(DATA_TYPES):
        if index:
            # Stagger: let the shared transaction pool drain between labels
            # instead of firing four DETACH DELETE sweeps back to back.
            await asyncio.sleep(MAINTENANCE_SETTLE_SECONDS)
        if not await cleanup_stub_nodes(data_type):
            ok = False
    return ok


async def cleanup_stub_nodes(data_type: str) -> bool:
    """Delete stub nodes that have no sha256 property.

    During extraction, MERGE operations in relationship queries create
    skeleton nodes for cross-referenced entities (e.g., a release referencing
    an artist that hasn't been processed yet). Primary records always set
    sha256, so nodes without it are stubs that were never filled.

    Returns:
        True if cleanup succeeded (or there is nothing to do), False if the
        DETACH DELETE failed — so the caller can nack and retry (idempotent).
    """
    if graph is None:
        return True

    # Map data types to their Neo4j labels
    label_map = {
        "artists": "Artist",
        "labels": "Label",
        "masters": "Master",
        "releases": "Release",
    }

    label = label_map.get(data_type)
    if not label:
        return True

    # Batch the deletion with CALL {} IN TRANSACTIONS so a large stub-node set
    # (cross-type MERGEs can leave hundreds of thousands to millions of
    # property-less stubs after a full import) does not run in one implicit
    # transaction — a single unbatched DETACH DELETE blows the Neo4j
    # transaction memory limit (dbms.memory.transaction.total.max) or the
    # default 120s timeout, and the swallowed error would leave the stubs
    # forever. Mirrors the compute_genre_style_stats batching in this file: the
    # driving MATCH sits OUTSIDE the transactional subquery and the node is
    # re-imported via WITH, so each inner transaction deletes at most one chunk.
    #
    # The chunk size is a parameter of the retry loop, not a constant in the
    # query: under transaction-memory pressure _run_maintenance_query re-runs
    # this with progressively smaller chunks. IN TRANSACTIONS commits per chunk,
    # so a retry only has to delete what the failed attempt did not.
    def _build_cleanup_cypher(batch_size: int | None) -> str:
        return f"""
    MATCH (n:{label})
    WHERE n.sha256 IS NULL
    CALL {{
        WITH n
        DETACH DELETE n
    }} IN TRANSACTIONS OF {batch_size} ROWS
    """

    try:
        summary = await _run_maintenance_query(
            _build_cleanup_cypher,
            f"Stub {label} cleanup",
            batch_size=STUB_CLEANUP_BATCH_SIZE,
            data_type=data_type,
        )
        if summary is None:
            # Retries exhausted — already logged. Report failure so the caller
            # nacks and the cleanup is retried on the next cycle rather than
            # being silently skipped.
            return False

        deleted = summary.counters.nodes_deleted
        if deleted > 0:
            logger.info(
                f"🧹 Cleaned up {deleted} stub {label} nodes (no sha256 property)",
                data_type=data_type,
                deleted=deleted,
            )
        else:
            logger.info(
                f"✅ No stub {label} nodes to clean up",
                data_type=data_type,
            )
    except Exception as e:  # noqa: BLE001 - stub cleanup is advisory; failure must not stop ingestion
        logger.error(
            f"❌ Failed to clean up stub {label} nodes",
            data_type=data_type,
            error=str(e),
        )
        return False

    return True


async def process_artist(tx: Any, record: dict[str, Any]) -> bool:
    """Process artist within a single transaction for atomicity."""
    existing_result = await tx.run(
        "MATCH (a:Artist {id: $id}) RETURN a.sha256 AS hash",
        id=record["id"],
    )
    existing_record = await existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    resources: str = f"https://api.discogs.com/artists/{record['id']}"
    releases: str = f"{resources}/releases"

    await tx.run(
        "MERGE (a:Artist {id: $id}) "
        "ON CREATE SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256 "
        "ON MATCH SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256",
        id=record["id"],
        name=record.get("name", "Unknown Artist"),
        resource_url=resources,
        releases_url=releases,
        sha256=record["sha256"],
    )

    # Handle members (normalized to list of {"id": ...} dicts)
    members: list[dict[str, Any]] | None = record.get("members")
    if members:
        valid_members = [m for m in members if m.get("id")]
        if valid_members:
            await tx.run(
                "UNWIND $members AS member "
                "MATCH (a:Artist {id: $artist_id}) "
                "MERGE (m_a:Artist {id: member.id}) "
                "MERGE (m_a)-[:MEMBER_OF]->(a)",
                members=valid_members,
                artist_id=record["id"],
            )

    # Handle groups (normalized to list of {"id": ...} dicts)
    groups: list[dict[str, Any]] | None = record.get("groups")
    if groups:
        valid_groups = [g for g in groups if g.get("id")]
        if valid_groups:
            await tx.run(
                "UNWIND $groups AS group "
                "MATCH (a:Artist {id: $artist_id}) "
                "MERGE (g_a:Artist {id: group.id}) "
                "MERGE (a)-[:MEMBER_OF]->(g_a)",
                groups=valid_groups,
                artist_id=record["id"],
            )

    # Handle aliases (normalized to list of {"id": ...} dicts)
    aliases: list[dict[str, Any]] | None = record.get("aliases")
    if aliases:
        valid_aliases = [a for a in aliases if a.get("id")]
        if valid_aliases:
            await tx.run(
                "UNWIND $aliases AS alias "
                "MATCH (a:Artist {id: $artist_id}) "
                "MERGE (a_a:Artist {id: alias.id}) "
                "MERGE (a_a)-[:ALIAS_OF]->(a)",
                aliases=valid_aliases,
                artist_id=record["id"],
            )

    return True  # Updated successfully


async def process_label(tx: Any, record: dict[str, Any]) -> bool:
    """Process label within a single transaction for atomicity."""
    existing_result = await tx.run(
        "MATCH (l:Label {id: $id}) RETURN l.sha256 AS hash", id=record["id"]
    )
    existing_record = await existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    await tx.run(
        "MERGE (l:Label {id: $id}) "
        "ON CREATE SET l.name = $name, l.sha256 = $sha256 "
        "ON MATCH SET l.name = $name, l.sha256 = $sha256",
        id=record["id"],
        name=record.get("name", "Unknown Label"),
        sha256=record["sha256"],
    )

    # Handle parent label relationship (normalized to {"id": ...} dict)
    parent: dict[str, Any] | None = record.get("parentLabel")
    if parent and parent.get("id"):
        await tx.run(
            "MATCH (l:Label {id: $id}) "
            "MERGE (p_l:Label {id: $p_id}) "
            "MERGE (l)-[:SUBLABEL_OF]->(p_l)",
            id=record["id"],
            p_id=parent["id"],
        )

    # Handle sublabels (normalized to list of {"id": ...} dicts)
    sublabels: list[dict[str, Any]] | None = record.get("sublabels")
    if sublabels:
        valid_sublabels = [s for s in sublabels if s.get("id")]
        if valid_sublabels:
            await tx.run(
                "UNWIND $sublabels AS sublabel "
                "MATCH (l:Label {id: $label_id}) "
                "MERGE (s_l:Label {id: sublabel.id}) "
                "MERGE (s_l)-[:SUBLABEL_OF]->(l)",
                sublabels=valid_sublabels,
                label_id=record["id"],
            )

    return True  # Updated successfully


async def process_master(tx: Any, record: dict[str, Any]) -> bool:
    """Process master within a single transaction for atomicity."""
    existing_result = await tx.run(
        "MATCH (m:Master {id: $id}) RETURN m.sha256 AS hash",
        id=record["id"],
    )
    existing_record = await existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    await tx.run(
        "MERGE (m:Master {id: $id}) "
        "ON CREATE SET m.title = $title, m.year = $year, m.sha256 = $sha256 "
        "ON MATCH SET m.title = $title, m.year = $year, m.sha256 = $sha256",
        id=record["id"],
        title=record.get("title", "Unknown Master"),
        year=record.get("year"),
        sha256=record["sha256"],
    )

    # Handle artist relationships (normalized to list of {"id": ...} dicts)
    artists: list[dict[str, Any]] | None = record.get("artists")
    if artists:
        valid_artists = [a for a in artists if a.get("id")]
        if valid_artists:
            await tx.run(
                "UNWIND $artists AS artist "
                "MATCH (m:Master {id: $master_id}) "
                "MERGE (a_m:Artist {id: artist.id}) "
                "MERGE (m)-[:BY]->(a_m)",
                artists=valid_artists,
                master_id=record["id"],
            )

    # Handle genres and styles (normalized to string lists)
    genres_list: list[str] = record.get("genres", [])
    if genres_list:
        await tx.run(
            "UNWIND $genres AS genre "
            "MATCH (m:Master {id: $master_id}) "
            "MERGE (g:Genre {name: genre.name}) "
            "MERGE (m)-[:IS]->(g)",
            genres=[{"name": genre} for genre in genres_list],
            master_id=record["id"],
        )

    styles_list: list[str] = record.get("styles", [])
    if styles_list:
        await tx.run(
            "UNWIND $styles AS style "
            "MATCH (m:Master {id: $master_id}) "
            "MERGE (s:Style {name: style.name}) "
            "MERGE (m)-[:IS]->(s)",
            styles=[{"name": style} for style in styles_list],
            master_id=record["id"],
        )

    # Connect styles to genres. PART_OF asserts a style belongs to a genre, which is
    # only unambiguous when the record carries a single genre — cartesian-linking
    # every style to every genre on a multi-genre record would create false
    # Style-[:PART_OF]->Genre edges (discogsography-sy5k).
    if len(genres_list) == 1 and styles_list:
        await tx.run(
            "UNWIND $genre_style_pairs AS pair "
            "MERGE (g:Genre {name: pair.genre}) "
            "MERGE (s:Style {name: pair.style}) "
            "MERGE (s)-[:PART_OF]->(g)",
            genre_style_pairs=[
                {"genre": genres_list[0], "style": style} for style in styles_list
            ],
        )

    return True  # Updated successfully


async def process_release(tx: Any, record: dict[str, Any]) -> bool:
    """Process release within a single transaction for atomicity."""
    existing_result = await tx.run(
        "MATCH (r:Release {id: $id}) RETURN r.sha256 AS hash",
        id=record["id"],
    )
    existing_record = await existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    formats = [
        f["name"]
        for f in record.get("formats", [])
        if isinstance(f, dict) and "name" in f
    ]
    await tx.run(
        "MERGE (r:Release {id: $id}) "
        "ON CREATE SET r.title = $title, r.year = $year, r.formats = $formats, r.sha256 = $sha256 "
        "ON MATCH SET r.title = $title, r.year = $year, r.formats = $formats, r.sha256 = $sha256",
        id=record["id"],
        title=record.get("title", "Unknown Release"),
        year=record.get("year"),
        formats=formats,
        sha256=record["sha256"],
    )

    # Handle artist relationships (normalized to list of {"id": ...} dicts)
    artists: list[dict[str, Any]] | None = record.get("artists")
    if artists:
        valid_artists = [a for a in artists if a.get("id")]
        if valid_artists:
            await tx.run(
                "UNWIND $artists AS artist "
                "MATCH (r:Release {id: $release_id}) "
                "MERGE (a_r:Artist {id: artist.id}) "
                "MERGE (r)-[:BY]->(a_r)",
                artists=valid_artists,
                release_id=record["id"],
            )

    # Handle label relationships (normalized to list of {"id": ...} dicts)
    labels: list[dict[str, Any]] | None = record.get("labels")
    if labels:
        valid_labels = [lbl for lbl in labels if lbl.get("id")]
        if valid_labels:
            await tx.run(
                "UNWIND $labels AS label "
                "MATCH (r:Release {id: $release_id}) "
                "MERGE (l_r:Label {id: label.id}) "
                "MERGE (r)-[:ON]->(l_r)",
                labels=valid_labels,
                release_id=record["id"],
            )

    # Handle master relationship (normalized to string)
    master_id = record.get("master_id")
    if master_id:
        await tx.run(
            "MATCH (r:Release {id: $id}) "
            "MERGE (m_r:Master {id: $m_id}) "
            "MERGE (r)-[:DERIVED_FROM]->(m_r)",
            id=record["id"],
            m_id=master_id,
        )

    # Handle genres and styles (normalized to string lists)
    genres_list: list[str] = record.get("genres", [])
    if genres_list:
        await tx.run(
            "UNWIND $genres AS genre "
            "MATCH (r:Release {id: $release_id}) "
            "MERGE (g:Genre {name: genre.name}) "
            "MERGE (r)-[:IS]->(g)",
            genres=[{"name": genre} for genre in genres_list],
            release_id=record["id"],
        )

    styles_list: list[str] = record.get("styles", [])
    if styles_list:
        await tx.run(
            "UNWIND $styles AS style "
            "MATCH (r:Release {id: $release_id}) "
            "MERGE (s:Style {name: style.name}) "
            "MERGE (r)-[:IS]->(s)",
            styles=[{"name": style} for style in styles_list],
            release_id=record["id"],
        )

    # Connect styles to genres. PART_OF asserts a style belongs to a genre, which is
    # only unambiguous when the record carries a single genre — cartesian-linking
    # every style to every genre on a multi-genre record would create false
    # Style-[:PART_OF]->Genre edges (discogsography-sy5k).
    if len(genres_list) == 1 and styles_list:
        await tx.run(
            "UNWIND $genre_style_pairs AS pair "
            "MERGE (g:Genre {name: pair.genre}) "
            "MERGE (s:Style {name: pair.style}) "
            "MERGE (s)-[:PART_OF]->(g)",
            genre_style_pairs=[
                {"genre": genres_list[0], "style": style} for style in styles_list
            ],
        )

    # Handle credits (extraartists) — create Person nodes and CREDITED_ON relationships
    extraartists: list[dict[str, Any]] | None = record.get("extraartists")
    if extraartists:
        credit_data = []
        for credit in extraartists:
            name = credit.get("name")
            role = credit.get("role", "")
            if name and role:
                category = categorize_role(role)
                artist_id = credit.get("id")
                entry: dict[str, Any] = {
                    "name": name,
                    "role": role,
                    "category": category,
                    "release_id": record["id"],
                }
                if artist_id:
                    entry["artist_id"] = artist_id
                credit_data.append(entry)
        if credit_data:
            # Create Person nodes and CREDITED_ON relationships
            await tx.run(
                "UNWIND $credits AS credit "
                "MATCH (r:Release {id: credit.release_id}) "
                "MERGE (p:Person {name: credit.name}) "
                "MERGE (p)-[:CREDITED_ON {role: credit.role, category: credit.category}]->(r)",
                credits=credit_data,
            )
            # Create SAME_AS relationships for credited people who are also performing artists
            artist_credits = [c for c in credit_data if c.get("artist_id")]
            if artist_credits:
                await tx.run(
                    "UNWIND $credits AS credit "
                    "MATCH (p:Person {name: credit.name}) "
                    "MATCH (a:Artist {id: credit.artist_id}) "
                    "MERGE (p)-[:SAME_AS]->(a)",
                    credits=artist_credits,
                )

    return True  # Updated successfully


def make_message_handler(
    data_type: str,
    name_field: str,
    default_name: str,
    process_fn: Any,
) -> Any:
    """Create a RabbitMQ message handler for the given data type."""

    async def handler(message: AbstractIncomingMessage) -> None:
        if shutdown_requested:
            # Leave the delivery UNACKED — never nack(requeue=True) here. The
            # consumer is still subscribed at this point, so a requeue is
            # redelivered within milliseconds and nacked again, burning a quorum
            # x-delivery-count per cycle; at x-delivery-limit=20 valid records
            # are dead-lettered within a second of a routine restart. Returning
            # without settling lets the connection close requeue them exactly
            # once. See discogsography-lnn4.
            logger.debug(
                "🛑 Shutdown requested, leaving message unacked for redelivery"
            )
            return

        record_id = "unknown"
        try:
            logger.debug("🔄 Received message", data_type=data_type[:-1])
            record: dict[str, Any] = loads(message.body)

            if await check_file_completion(record, data_type, message):
                return

            if BATCH_MODE and batch_processor is not None:
                accepted = await batch_processor.add_message(
                    data_type,
                    record,
                    message.ack,
                    # requeue=False: this callback nacks permanently-invalid
                    # input (unknown data_type, missing 'id', normalize failure,
                    # poison batch) — send it straight to the DLQ instead of
                    # cycling x-delivery-limit (20) futile redeliveries. Transient
                    # failures are handled by _flush_queue's re-enqueue+backoff,
                    # which never nacks.
                    lambda: message.nack(requeue=False),
                )
                if accepted:
                    # Note: message_counts tracks received (not processed) messages in
                    # batch mode. Actual processed count is in batch_processor.processed_counts.
                    # Messages nacked later by _process_*_batch (e.g. missing 'id') are included.
                    message_counts[data_type] += 1
                    last_message_time[data_type] = time.time()
                return

            record = normalize_record(data_type, record)

            # Validate required 'id' field — nack with requeue=False to avoid
            # infinite requeue loop for malformed messages (matches tableinator).
            # Check both missing key and None value since normalize_record
            # sets id=None when the raw message lacks an id field.
            if not record.get("id"):
                logger.error("❌ Message missing 'id' field", data_type=data_type)
                await message.nack(requeue=False)
                return

            record_id = record.get("id", "unknown")
            record_name = record.get(name_field, default_name)

            logger.debug(
                f"🔄 Processing {data_type[:-1]}",
                record_id=record_id,
                record_name=record_name,
            )

            if graph is None:
                raise RuntimeError("Neo4j driver not initialized")

            async with graph.session(database="neo4j") as session:

                async def tx_fn(tx: Any) -> bool:
                    return bool(await process_fn(tx, record))

                updated = await session.execute_write(tx_fn)

            # Ack first, then increment counters — avoids double-ack-then-nack
            # if ack raises (exception handler would attempt nack on already-acked msg)
            await message.ack()

            # Neo4j answered — clear the outage backoff.
            outage_backoff.reset()

            message_counts[data_type] += 1
            last_message_time[data_type] = time.time()
            if message_counts[data_type] % progress_interval == 0:
                logger.info(
                    f"📊 Processed {data_type} in Neo4j",
                    message_counts=message_counts[data_type],
                )

            if updated:
                logger.debug(
                    f"💾 Updated {data_type[:-1]} in Neo4j",
                    record_id=record_id,
                )
            else:
                logger.debug(
                    f"🔄 Skipped {data_type[:-1]} (no changes needed)",
                    record_id=record_id,
                )
        except (ServiceUnavailable, SessionExpired, DatabaseUnavailableError) as e:
            logger.warning(
                f"⚠️ Neo4j unavailable, will retry {data_type[:-1]} message",
                error=str(e),
            )
            # Pause before requeueing — x-delivery-limit=20 is a budget with no
            # time dimension, so unthrottled requeues dead-letter valid records
            # within minutes of a Neo4j outage (discogsography-rb05).
            await outage_backoff.wait()
            try:
                await message.nack(requeue=True)
            except Exception as nack_error:  # noqa: BLE001 - the nack path itself is best-effort; the broker will redeliver
                logger.warning("⚠️ Failed to nack message", error=str(nack_error))
        except Exception as e:  # noqa: BLE001 - per-message fault must nack rather than kill the consumer
            logger.error(
                f"❌ Failed to process {data_type[:-1]} message",
                record_id=record_id,
                error=str(e),
            )
            try:
                await message.nack(requeue=True)
            except Exception as nack_error:  # noqa: BLE001 - the nack path itself is best-effort; the broker will redeliver
                logger.warning("⚠️ Failed to nack message", error=str(nack_error))

    return handler


on_artist_message = make_message_handler(
    "artists", "name", "Unknown Artist", process_artist
)
on_label_message = make_message_handler(
    "labels", "name", "Unknown Label", process_label
)
on_master_message = make_message_handler(
    "masters", "title", "Unknown Master", process_master
)
on_release_message = make_message_handler(
    "releases", "title", "Unknown Release", process_release
)

# Handler lookup by data type for consumer registration and recovery
HANDLERS: dict[str, Any] = {
    "artists": on_artist_message,
    "labels": on_label_message,
    "masters": on_master_message,
    "releases": on_release_message,
}


async def progress_reporter() -> None:
    """Periodically report processing progress and manage idle mode."""
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
            f"📊 Neo4j Progress: {total} total messages processed "
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
        config, \
        graph, \
        queues, \
        rabbitmq_manager, \
        active_connection, \
        active_channel, \
        connection_check_task, \
        batch_processor

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("graphinator", log_file=Path("/logs/graphinator.log"))
    logger.info("🚀 Starting Neo4j graphinator service")

    # Add startup delay for dependent services
    startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
    if startup_delay > 0:
        logger.info(
            f"⏳ Waiting {startup_delay} seconds for dependent services to start..."
        )
        await asyncio.sleep(startup_delay)

    # Start health server
    health_server = HealthServer(8001, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8001")

    # Initialize configuration
    try:
        config = GraphinatorConfig.from_env()
    except ValueError as e:
        logger.error("❌ Configuration error", error=str(e))
        return

    # Initialize async resilient Neo4j driver
    graph = AsyncResilientNeo4jDriver(
        uri=config.neo4j_host,
        auth=(config.neo4j_username, config.neo4j_password),
        max_retries=5,
        **neo4j_security_kwargs(),
    )

    # Test Neo4j connectivity using async operations
    try:
        async with graph.session(database="neo4j") as session:
            result = await session.run("RETURN 1 as test")
            await result.single()
            logger.info("✅ Neo4j connectivity verified (async)")

        # Initialize batch processor if enabled
        if BATCH_MODE:
            batch_config = BatchConfig(
                batch_size=BATCH_SIZE,
                flush_interval=BATCH_FLUSH_INTERVAL,
            )
            batch_processor = Neo4jBatchProcessor(graph, batch_config)
            logger.info(
                "🚀 Batch processing enabled",
                batch_size=BATCH_SIZE,
                flush_interval=BATCH_FLUSH_INTERVAL,
            )
        else:
            logger.info("📝 Using per-message processing (batch mode disabled)")

    except Exception as e:  # noqa: BLE001 - top-level guard: log and exit cleanly instead of a traceback
        logger.error("❌ Failed to connect to Neo4j", error=str(e))
        return
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗                                   ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝                                   ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗                                   ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║                                   ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║                                   ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝                                   ")
    print("                                                                                        ")
    print(" ██████╗ ██████╗  █████╗ ██████╗ ██╗  ██╗██╗███╗   ██╗ █████╗ ████████╗ ██████╗ ██████╗ ")
    print("██╔════╝ ██╔══██╗██╔══██╗██╔══██╗██║  ██║██║████╗  ██║██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗")
    print("██║  ███╗██████╔╝███████║██████╔╝███████║██║██╔██╗ ██║███████║   ██║   ██║   ██║██████╔╝")
    print("██║   ██║██╔══██╗██╔══██║██╔═══╝ ██╔══██║██║██║╚██╗██║██╔══██║   ██║   ██║   ██║██╔══██╗")
    print("╚██████╔╝██║  ██║██║  ██║██║     ██║  ██║██║██║ ╚████║██║  ██║   ██║   ╚██████╔╝██║  ██║")
    print(" ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝")
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
                f"🐰 Attempting to connect to RabbitMQ (attempt {startup_retry + 1}/{max_startup_retries})"
            )
            amqp_connection = await rabbitmq_manager.connect()
            active_connection = amqp_connection
            break
        except Exception as e:  # noqa: BLE001 - top-level guard: log and exit cleanly instead of a traceback
            startup_retry += 1
            if startup_retry < max_startup_retries:
                wait_time = min(30, 5 * startup_retry)  # Exponential backoff up to 30s
                logger.warning(
                    f"⚠️ RabbitMQ connection failed: {e}. Retrying in {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    f"❌ Failed to connect to AMQP broker after {max_startup_retries} attempts: {e}"
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
            exchange_name = f"{DISCOGS_EXCHANGE_PREFIX}-{data_type}"
            queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{data_type}"
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
        for data_type, handler in HANDLERS.items():
            consumer_tags[data_type] = await queues[data_type].consume(
                handler, consumer_tag=f"graphinator-{data_type}"
            )

        logger.info(
            f"🚀 Graphinator started! Connected to AMQP broker ({len(DATA_TYPES)} fanout exchanges). "
            f"Consuming from {len(DATA_TYPES)} queues. "
            "Ready to process messages into Neo4j. Press CTRL+C to exit"
        )

        progress_task = asyncio.create_task(progress_reporter())

        # Start batch flush task if using batch mode
        batch_flush_task = None
        if BATCH_MODE and batch_processor is not None:
            batch_flush_task = asyncio.create_task(batch_processor.periodic_flush())
            logger.info("🔄 Started batch periodic flush task")

        # Start periodic queue checker task
        connection_check_task = asyncio.create_task(periodic_queue_checker())
        logger.info(
            f"🔄 Started periodic queue checker (interval: {QUEUE_CHECK_INTERVAL}s)"
        )

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
            # Stop new deliveries FIRST, before the multi-second flush/teardown
            # below: a still-subscribed consumer keeps being handed messages it
            # can only leave unacked (discogsography-lnn4).
            await cancel_all_consumers()

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
                except Exception as e:  # noqa: BLE001 - top-level guard: log and exit cleanly instead of a traceback
                    logger.error("❌ Error flushing batch processor", error=str(e))

            # Cancel any pending consumer cancellation tasks
            for task in list(consumer_cancel_tasks.values()):
                task.cancel()

            # Cancel detached post-import maintenance. Its trigger was already
            # acked, and every step is idempotent — an interrupted sweep is
            # re-run by the next extraction_complete or manually.
            for maintenance_task in list(maintenance_tasks):
                maintenance_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maintenance_task
            if maintenance_tasks:
                logger.info("✅ Post-import maintenance task stopped")

            # Close RabbitMQ connection if still active
            await close_rabbitmq_connection()

            # Close async Neo4j driver
            try:
                if graph is not None:
                    await graph.close()
                logger.info("✅ Async Neo4j driver closed")
            except Exception as e:  # noqa: BLE001 - top-level guard: log and exit cleanly instead of a traceback
                logger.warning("⚠️ Error closing Neo4j driver", error=str(e))

        # Stop health server
        health_server.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        logger.warning("⚠️ Application interrupted")
    except Exception as e:  # noqa: BLE001 - top-level guard: log and exit cleanly instead of a traceback
        logger.error("❌ Application error", error=str(e))
    finally:
        logger.info("✅ Graphinator service shutdown complete")
