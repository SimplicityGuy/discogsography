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
    AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR,
    MUSICBRAINZ_DATA_TYPES,
    MUSICBRAINZ_EXCHANGE_PREFIX,
    AsyncResilientNeo4jDriver,
    AsyncResilientRabbitMQ,
    BrainzgraphinatorConfig,
    HealthServer,
    setup_logging,
)
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from orjson import loads


logger = structlog.get_logger(__name__)

# Config will be initialized in main
config: BrainzgraphinatorConfig | None = None

# Progress tracking
message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
progress_interval = 100  # Log progress every 100 messages
last_message_time = {
    "artists": 0.0,
    "labels": 0.0,
    "release-groups": 0.0,
    "releases": 0.0,
}
completed_files: set[str] = set()  # Track which files have completed processing

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
)  # Default 1 hour

# Interval for checking stuck state (consumers died unexpectedly)
STUCK_CHECK_INTERVAL = int(
    os.environ.get("STUCK_CHECK_INTERVAL", "30")
)  # Default 30 seconds

# Idle mode settings
STARTUP_IDLE_TIMEOUT = int(os.environ.get("STARTUP_IDLE_TIMEOUT", "30"))
IDLE_LOG_INTERVAL = int(
    os.environ.get("IDLE_LOG_INTERVAL", "300")
)  # 5 min between idle status logs

# Idle mode state
idle_mode = False

# Driver will be initialized in main
graph: AsyncResilientNeo4jDriver | None = None

# Batch mode (disabled for brainzgraphinator — enrichment is simpler than ingestion)
BATCH_MODE = os.environ.get("NEO4J_BATCH_MODE", "true").lower() == "true"
BATCH_SIZE = int(os.environ.get("NEO4J_BATCH_SIZE", "100"))
BATCH_FLUSH_INTERVAL = float(os.environ.get("NEO4J_BATCH_FLUSH_INTERVAL", "5.0"))

# Connection state tracking
rabbitmq_manager: Any = None  # Will hold AsyncResilientRabbitMQ instance
active_connection: Any = None  # Current active connection
active_channel: Any = None  # Current active channel
connection_check_task: asyncio.Task[None] | None = None

# Global shutdown flag
shutdown_requested = False

# Enrichment stats
enrichment_stats = {
    "entities_enriched": 0,
    "entities_skipped_no_discogs_match": 0,
    "relationships_created": 0,
    "relationships_skipped_missing_side": 0,
}

# MusicBrainz relationship type mapping
MB_RELATIONSHIP_MAP: dict[str, str] = {
    "member of band": "MEMBER_OF",
    "collaboration": "COLLABORATED_WITH",
    "teacher": "TAUGHT",
    "tribute": "TRIBUTE_TO",
    "founder": "FOUNDED",
    "supporting musician": "SUPPORTED",
    "subgroup": "SUBGROUP_OF",
    "artist rename": "RENAMED_TO",
}


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    active_task = None
    current_time = time.time()

    # Check for recent message activity (within last 10 seconds)
    for data_type, last_time in last_message_time.items():
        if last_time > 0 and (current_time - last_time) < 10:
            active_task = f"Enriching {data_type}"
            break

    # If no recent activity but consumers exist, show as idle
    if active_task is None and len(consumer_tags) > 0:
        active_task = "Idle - waiting for messages"

    # Check for stuck state
    no_active_consumers = len(consumer_tags) == 0
    files_incomplete = len(completed_files) < len(MUSICBRAINZ_DATA_TYPES)
    has_processed_messages = any(count > 0 for count in message_counts.values())
    is_stuck = no_active_consumers and files_incomplete and has_processed_messages

    if is_stuck:
        active_task = "STUCK - consumers died, awaiting recovery"

    if graph is None:
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
        "service": "brainzgraphinator",
        "current_task": active_task,
        "message_counts": message_counts.copy(),
        "last_message_time": last_message_time.copy(),
        "active_consumers": list(consumer_tags.keys()),
        "completed_files": list(completed_files),
        "enrichment_stats": enrichment_stats.copy(),
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
                await queue.cancel(consumer_tag, nowait=True)
                del consumer_tags[data_type]

                logger.info(
                    "✅ Consumer successfully canceled",
                    data_type=data_type,
                )

                if await check_all_consumers_idle():
                    logger.info("🔧 All consumers idle, closing RabbitMQ connection")
                    await close_rabbitmq_connection()
        except Exception as e:
            logger.error(
                "❌ Failed to cancel consumer",
                data_type=data_type,
                error=str(e),
            )
        finally:
            if data_type in consumer_cancel_tasks:
                del consumer_cancel_tasks[data_type]

    # Cancel any existing scheduled cancellation
    if data_type in consumer_cancel_tasks:
        consumer_cancel_tasks[data_type].cancel()

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
            "✅ RabbitMQ connection closed", check_interval=f"{QUEUE_CHECK_INTERVAL}s"
        )
    except Exception as e:
        logger.error("❌ Error closing RabbitMQ connection", error=str(e))


async def check_all_consumers_idle() -> bool:
    """Check if all consumers are cancelled (idle) AND all files completed."""
    return len(consumer_tags) == 0 and len(MUSICBRAINZ_DATA_TYPES) == len(
        completed_files
    )


async def check_file_completion(
    data: dict[str, Any], data_type: str, message: AbstractIncomingMessage
) -> bool:
    """Check if message is a file completion or extraction completion message."""
    if data.get("type") == "file_complete":
        completed_files.add(data_type)
        total_processed = data.get("total_processed", 0)
        logger.info(
            f"✅ File processing complete for {data_type}! "
            f"Total records processed: {total_processed}"
        )

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
        await message.ack()
        return True

    return False


async def enrich_artist(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich an existing Artist node with MusicBrainz metadata.

    If discogs_artist_id is None, skip — entity has no Discogs match.
    """
    discogs_id = record.get("discogs_artist_id")
    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True  # Deliberately skipped, not an error

    result = await tx.run(
        "MATCH (a:Artist {id: $discogs_id}) "
        "SET a.mbid = $mbid, "
        "    a.mb_type = $mb_type, "
        "    a.mb_gender = $mb_gender, "
        "    a.mb_begin_date = $mb_begin_date, "
        "    a.mb_end_date = $mb_end_date, "
        "    a.mb_area = $mb_area, "
        "    a.mb_begin_area = $mb_begin_area, "
        "    a.mb_end_area = $mb_end_area, "
        "    a.mb_disambiguation = $mb_disambiguation, "
        "    a.mb_updated_at = $mb_updated_at "
        "RETURN a.id AS matched_id",
        discogs_id=discogs_id,
        mbid=record.get("mbid", record.get("id")),
        mb_type=record.get("mb_type", record.get("type")),
        mb_gender=record.get("gender"),
        mb_begin_date=record.get(
            "begin_date", (record.get("life_span") or {}).get("begin")
        ),
        mb_end_date=record.get("end_date", (record.get("life_span") or {}).get("end")),
        mb_area=record.get("area"),
        mb_begin_area=record.get("begin_area"),
        mb_end_area=record.get("end_area"),
        mb_disambiguation=record.get("disambiguation"),
        mb_updated_at=datetime.now(UTC).isoformat(),
    )
    matched = await result.single()
    if matched:
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    # Create relationship edges if relations are present
    relations = record.get("relations", [])
    if relations and matched:
        await create_relationship_edges(tx, discogs_id, relations)

    return True


async def enrich_label(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich an existing Label node with MusicBrainz metadata.

    If discogs_label_id is None, skip — entity has no Discogs match.
    """
    discogs_id = record.get("discogs_label_id")
    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True

    result = await tx.run(
        "MATCH (l:Label {id: $discogs_id}) "
        "SET l.mbid = $mbid, "
        "    l.mb_type = $mb_type, "
        "    l.mb_label_code = $mb_label_code, "
        "    l.mb_begin_date = $mb_begin_date, "
        "    l.mb_end_date = $mb_end_date, "
        "    l.mb_area = $mb_area, "
        "    l.mb_updated_at = $mb_updated_at "
        "RETURN l.id AS matched_id",
        discogs_id=discogs_id,
        mbid=record.get("mbid", record.get("id")),
        mb_type=record.get("mb_type", record.get("type")),
        mb_label_code=record.get("label_code"),
        mb_begin_date=record.get(
            "begin_date", (record.get("life_span") or {}).get("begin")
        ),
        mb_end_date=record.get("end_date", (record.get("life_span") or {}).get("end")),
        mb_area=record.get("area"),
        mb_updated_at=datetime.now(UTC).isoformat(),
    )
    matched = await result.single()
    if matched:
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True


async def enrich_release(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich an existing Release node with MusicBrainz metadata.

    If discogs_release_id is None, skip — entity has no Discogs match.
    """
    discogs_id = record.get("discogs_release_id")
    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True

    result = await tx.run(
        "MATCH (r:Release {id: $discogs_id}) "
        "SET r.mbid = $mbid, "
        "    r.mb_barcode = $mb_barcode, "
        "    r.mb_status = $mb_status, "
        "    r.mb_updated_at = $mb_updated_at "
        "RETURN r.id AS matched_id",
        discogs_id=discogs_id,
        mbid=record.get("mbid", record.get("id")),
        mb_barcode=record.get("barcode"),
        mb_status=record.get("status"),
        mb_updated_at=datetime.now(UTC).isoformat(),
    )
    matched = await result.single()
    if matched:
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True


async def create_relationship_edges(
    tx: Any,
    source_discogs_id: int,
    relations: list[dict[str, Any]],
) -> None:
    """Create MusicBrainz relationship edges between Artist nodes.

    For each relation:
    - Look up the Neo4j edge type in MB_RELATIONSHIP_MAP
    - Skip unknown relationship types
    - If target_discogs_artist_id is None, skip
    - MERGE the edge with source: 'musicbrainz' property

    Cypher can't parameterize relationship types, so we format the edge type
    into the query string. This is safe because values come from our map, not
    user input.
    """
    for relation in relations:
        mb_type = relation.get("type", "")
        edge_type = MB_RELATIONSHIP_MAP.get(mb_type)
        if edge_type is None:
            continue  # Unknown relationship type, skip

        target_discogs_id = relation.get("target_discogs_artist_id")
        if target_discogs_id is None:
            enrichment_stats["relationships_skipped_missing_side"] += 1
            continue

        # Safe: edge_type comes from MB_RELATIONSHIP_MAP, not user input
        result = await tx.run(
            f"MATCH (a:Artist {{id: $source_id}}) "  # noqa: S608
            f"MATCH (b:Artist {{id: $target_id}}) "
            f"MERGE (a)-[r:{edge_type}]->(b) "
            f"SET r.source = 'musicbrainz'",
            source_id=source_discogs_id,
            target_id=target_discogs_id,
        )
        await result.consume()
        enrichment_stats["relationships_created"] += 1


async def enrich_release_group(tx: Any, record: dict[str, Any]) -> bool:
    """Enrich an existing Master node with MusicBrainz release-group metadata.

    If discogs_master_id is None, skip — entity has no Discogs match.
    """
    discogs_id = record.get("discogs_master_id")
    if discogs_id is None:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1
        return True

    result = await tx.run(
        "MATCH (m:Master {id: $discogs_id}) "
        "SET m.mbid = $mbid, "
        "    m.mb_type = $mb_type, "
        "    m.mb_secondary_types = $mb_secondary_types, "
        "    m.mb_first_release_date = $mb_first_release_date, "
        "    m.mb_disambiguation = $mb_disambiguation, "
        "    m.mb_updated_at = $mb_updated_at "
        "RETURN m.id AS matched_id",
        discogs_id=discogs_id,
        mbid=record.get("mbid", record.get("id")),
        mb_type=record.get("mb_type", record.get("type")),
        mb_secondary_types=record.get("secondary_types", []),
        mb_first_release_date=record.get("first_release_date"),
        mb_disambiguation=record.get("disambiguation"),
        mb_updated_at=datetime.now(UTC).isoformat(),
    )
    matched = await result.single()
    if matched:
        enrichment_stats["entities_enriched"] += 1
    else:
        enrichment_stats["entities_skipped_no_discogs_match"] += 1

    return True


# Processor lookup by data type
PROCESSORS: dict[str, Any] = {
    "artists": enrich_artist,
    "labels": enrich_label,
    "release-groups": enrich_release_group,
    "releases": enrich_release,
}


def make_message_handler(data_type: str, enrich_fn: Any) -> Any:
    """Create a RabbitMQ message handler for the given data type."""

    async def handler(message: AbstractIncomingMessage) -> None:
        if shutdown_requested:
            logger.info("🛑 Shutdown requested, rejecting new messages")
            await message.nack(requeue=True)
            return

        try:
            logger.debug("🔄 Received MusicBrainz message", data_type=data_type)
            body: dict[str, Any] = loads(message.body)

            if await check_file_completion(body, data_type, message):
                return

            message_counts[data_type] += 1
            last_message_time[data_type] = time.time()
            if message_counts[data_type] % progress_interval == 0:
                logger.info(
                    f"📊 Enriched {data_type} in Neo4j",
                    message_counts=message_counts[data_type],
                )

            if graph is None:
                raise RuntimeError("Neo4j driver not initialized")

            # Use local counters inside the transaction to avoid race conditions
            # with concurrent messages mutating the global enrichment_stats dict.
            # Temporarily swap global enrichment_stats to local_stats so enrich
            # functions (which reference the global by name) write to local_stats.
            global enrichment_stats
            local_stats: dict[str, int] = {
                "entities_enriched": 0,
                "entities_skipped_no_discogs_match": 0,
                "relationships_created": 0,
                "relationships_skipped_missing_side": 0,
            }
            saved_stats = enrichment_stats
            enrichment_stats = local_stats

            try:
                async with graph.session(database="neo4j") as session:

                    async def tx_fn(tx: Any) -> bool:
                        # Reset local counters on each retry attempt
                        for key in local_stats:
                            local_stats[key] = 0
                        return bool(await enrich_fn(tx, body))

                    await session.execute_write(tx_fn)
            finally:
                # Always restore the global reference
                enrichment_stats = saved_stats

            # Merge local counters into global stats only after transaction succeeds
            for key in local_stats:
                enrichment_stats[key] += local_stats[key]

            await message.ack()
        except (ServiceUnavailable, SessionExpired) as e:
            logger.warning(
                f"⚠️ Neo4j unavailable, will retry {data_type} message",
                error=str(e),
            )
            try:
                await message.nack(requeue=True)
            except Exception as nack_error:
                logger.warning("⚠️ Failed to nack message", error=str(nack_error))
        except Exception as e:
            logger.error(
                f"❌ Failed to process {data_type} MusicBrainz message",
                error=str(e),
            )
            try:
                await message.nack(requeue=True)
            except Exception as nack_error:
                logger.warning("⚠️ Failed to nack message", error=str(nack_error))

    return handler


on_artist_message = make_message_handler("artists", enrich_artist)
on_label_message = make_message_handler("labels", enrich_label)
on_release_group_message = make_message_handler("release-groups", enrich_release_group)
on_release_message = make_message_handler("releases", enrich_release)

# Handler lookup by data type for consumer registration
HANDLERS: dict[str, Any] = {
    "artists": on_artist_message,
    "labels": on_label_message,
    "release-groups": on_release_group_message,
    "releases": on_release_message,
}


async def progress_reporter() -> None:
    """Periodically report processing progress and manage idle mode."""
    global idle_mode

    report_count = 0
    startup_time = time.time()
    last_idle_log = 0.0

    while not shutdown_requested:
        if report_count < 3:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(30)
        report_count += 1

        if len(completed_files) == len(MUSICBRAINZ_DATA_TYPES):
            continue

        total = sum(message_counts.values())
        current_time = time.time()

        if (
            not idle_mode
            and total == 0
            and (current_time - startup_time) >= STARTUP_IDLE_TIMEOUT
        ):
            idle_mode = True
            last_idle_log = current_time
            logger.info(
                "⏳ No MusicBrainz messages received — entering idle mode",
                startup_idle_timeout=STARTUP_IDLE_TIMEOUT,
            )

        if idle_mode:
            if total > 0:
                idle_mode = False
                logger.info("🔄 Messages detected, resuming normal operation")
            elif (current_time - last_idle_log) >= IDLE_LOG_INTERVAL:
                last_idle_log = current_time
                logger.info(
                    "⏳ Still idle, waiting for MusicBrainz messages",
                    active_consumers=list(consumer_tags.keys()),
                    enrichment_stats=enrichment_stats,
                )
            continue

        if total > 0:
            logger.info(
                "📊 MusicBrainz enrichment progress",
                message_counts=message_counts.copy(),
                enrichment_stats=enrichment_stats.copy(),
                active_consumers=list(consumer_tags.keys()),
                completed_files=list(completed_files),
            )


async def periodic_queue_checker() -> None:
    """Periodically check queue health and recover from stuck states."""
    global active_connection, active_channel, queues, consumer_tags, idle_mode

    last_full_check = 0.0

    while not shutdown_requested:
        try:
            await asyncio.sleep(STUCK_CHECK_INTERVAL)

            current_time = time.time()

            # Check for stuck state
            no_active_consumers = len(consumer_tags) == 0
            files_incomplete = len(completed_files) < len(MUSICBRAINZ_DATA_TYPES)
            has_processed_messages = any(count > 0 for count in message_counts.values())

            if no_active_consumers and files_incomplete and has_processed_messages:
                logger.warning(
                    "⚠️ Detected stuck state: consumers died but files not completed. "
                    "Attempting recovery...",
                    active_consumers=len(consumer_tags),
                    completed_files=list(completed_files),
                    message_counts=message_counts,
                )
                await _recover_consumers()
                continue

            # Normal idle check
            time_since_last_check = current_time - last_full_check
            if time_since_last_check < QUEUE_CHECK_INTERVAL:
                continue

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


async def _recover_consumers() -> None:
    """Recover consumers by reconnecting to RabbitMQ and restarting consumption."""
    global active_connection, active_channel, queues, consumer_tags, idle_mode

    if active_connection:
        try:
            await active_connection.close()
        except Exception:  # nosec: B110
            pass
        active_connection = None
        active_channel = None

    try:
        temp_connection = await rabbitmq_manager.connect()
        temp_channel = await temp_connection.channel()
    except Exception as e:
        logger.error("❌ Failed to connect to RabbitMQ for recovery", error=str(e))
        return

    try:
        queues_with_messages = []
        for data_type in MUSICBRAINZ_DATA_TYPES:
            queue_name = f"{AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR}-{data_type}"

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

            active_connection = temp_connection
            active_channel = temp_channel

            await active_channel.set_qos(prefetch_count=200)

            queues = {}
            for data_type in MUSICBRAINZ_DATA_TYPES:
                exchange_name = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-{data_type}"
                queue_name = f"{AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR}-{data_type}"
                dlx_name = f"{queue_name}.dlx"
                dlq_name = f"{queue_name}.dlq"

                exchange = await active_channel.declare_exchange(
                    exchange_name,
                    AMQP_EXCHANGE_TYPE,
                    durable=True,
                    auto_delete=False,
                )

                dlx_exchange = await active_channel.declare_exchange(
                    dlx_name,
                    AMQP_EXCHANGE_TYPE,
                    durable=True,
                    auto_delete=False,
                )

                dlq = await active_channel.declare_queue(
                    auto_delete=False,
                    durable=True,
                    name=dlq_name,
                    arguments={"x-queue-type": "classic"},
                )
                await dlq.bind(dlx_exchange)

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

            for data_type, msg_count in queues_with_messages:
                if data_type in queues and data_type not in consumer_tags:
                    handler = HANDLERS.get(data_type)
                    if handler:
                        consumer_tag = await queues[data_type].consume(
                            handler, consumer_tag=f"brainzgraphinator-{data_type}"
                        )
                        consumer_tags[data_type] = consumer_tag
                        completed_files.discard(data_type)
                        last_message_time[data_type] = time.time()
                        logger.info(
                            f"✅ Started consumer for {data_type} "
                            f"(pending: {msg_count})"
                        )

            logger.info(
                f"✅ Recovery complete - consumers restarted: {list(consumer_tags.keys())}"
            )
            idle_mode = False
        else:
            logger.info("⏳ No messages in any queue, connection remains closed")
            await temp_channel.close()
            await temp_connection.close()

    except Exception as e:
        logger.error("❌ Error during consumer recovery", error=str(e))
        try:
            await temp_channel.close()
            await temp_connection.close()
        except Exception:  # nosec: B110
            pass
        active_connection = None
        active_channel = None
        queues = {}


async def main() -> None:
    global \
        config, \
        graph, \
        queues, \
        rabbitmq_manager, \
        active_connection, \
        active_channel, \
        connection_check_task

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("brainzgraphinator", log_file=Path("/logs/brainzgraphinator.log"))
    logger.info("🚀 Starting MusicBrainz brainzgraphinator service")

    # Add startup delay for dependent services
    startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
    if startup_delay > 0:
        logger.info(
            f"⏳ Waiting {startup_delay} seconds for dependent services to start..."
        )
        await asyncio.sleep(startup_delay)

    # Start health server
    health_server = HealthServer(8011, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8011")

    # Initialize configuration
    try:
        config = BrainzgraphinatorConfig.from_env()
    except ValueError as e:
        logger.error("❌ Configuration error", error=str(e))
        return

    # Initialize async resilient Neo4j driver
    graph = AsyncResilientNeo4jDriver(
        uri=config.neo4j_host,
        auth=(config.neo4j_username, config.neo4j_password),
        max_retries=5,
        encrypted=False,
    )

    # Test Neo4j connectivity
    try:
        async with graph.session(database="neo4j") as session:
            result = await session.run("RETURN 1 as test")
            await result.single()
            logger.info("✅ Neo4j connectivity verified (async)")
    except Exception as e:
        logger.error("❌ Failed to connect to Neo4j", error=str(e))
        return

    # fmt: off
    print("██████╗ ██████╗  █████╗ ██╗███╗   ██╗███████╗                                        ")
    print("██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║╚══███╔╝                                        ")
    print("██████╔╝██████╔╝███████║██║██╔██╗ ██║  ███╔╝                                         ")
    print("██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║ ███╔╝                                          ")
    print("██████╔╝██║  ██║██║  ██║██║██║ ╚████║███████╗                                        ")
    print("╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝                                        ")
    print("                                                                                     ")
    print(" ██████╗ ██████╗  █████╗ ██████╗ ██╗  ██╗██╗███╗   ██╗ █████╗ ████████╗ ██████╗ ██████╗ ")
    print("██╔════╝ ██╔══██╗██╔══██╗██╔══██╗██║  ██║██║████╗  ██║██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗")
    print("██║  ███╗██████╔╝███████║██████╔╝███████║██║██╔██╗ ██║███████║   ██║   ██║   ██║██████╔╝")
    print("██║   ██║██╔══██╗██╔══██║██╔═══╝ ██╔══██║██║██║╚██╗██║██╔══██║   ██║   ██║   ██║██╔══██╗")
    print("╚██████╔╝██║  ██║██║  ██║██║     ██║  ██║██║██║ ╚████║██║  ██║   ██║   ╚██████╔╝██║  ██║")
    print(" ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝")
    print()
    # fmt: on

    # Initialize resilient RabbitMQ connection manager
    rabbitmq_manager = AsyncResilientRabbitMQ(
        connection_url=config.amqp_connection,
        max_retries=10,
        heartbeat=600,
        connection_attempts=10,
        retry_delay=5.0,
    )

    # Try to connect with retry logic
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
        except Exception as e:
            startup_retry += 1
            if startup_retry < max_startup_retries:
                wait_time = min(30, 5 * startup_retry)
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

        await channel.set_qos(prefetch_count=200)
        logger.info("🔧 QoS prefetch configured", prefetch_count=200)

        # Declare per-data-type fanout exchanges and consumer-owned queues
        queues = {}
        for data_type in MUSICBRAINZ_DATA_TYPES:
            exchange_name = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-{data_type}"
            queue_name = f"{AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR}-{data_type}"
            dlx_name = f"{queue_name}.dlx"
            dlq_name = f"{queue_name}.dlq"

            # Declare fanout exchange
            exchange = await channel.declare_exchange(
                exchange_name,
                AMQP_EXCHANGE_TYPE,
                durable=True,
                auto_delete=False,
            )

            # Declare consumer-owned dead-letter exchange
            dlx_exchange = await channel.declare_exchange(
                dlx_name,
                AMQP_EXCHANGE_TYPE,
                durable=True,
                auto_delete=False,
            )

            # Declare DLQ
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

        # Start consuming from each queue
        for data_type in MUSICBRAINZ_DATA_TYPES:
            handler = HANDLERS[data_type]
            consumer_tag = await queues[data_type].consume(
                handler, consumer_tag=f"brainzgraphinator-{data_type}"
            )
            consumer_tags[data_type] = consumer_tag
            logger.info(f"✅ Started consuming {data_type} MusicBrainz messages")

        logger.info(
            "🚀 Brainzgraphinator is ready and consuming MusicBrainz messages",
            data_types=MUSICBRAINZ_DATA_TYPES,
        )

        # Start background tasks
        progress_task = asyncio.create_task(progress_reporter())
        connection_check_task = asyncio.create_task(periodic_queue_checker())

        try:
            while not shutdown_requested:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("🛑 Main loop cancelled")
        finally:
            progress_task.cancel()
            if connection_check_task:
                connection_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task
            if connection_check_task:
                with contextlib.suppress(asyncio.CancelledError):
                    await connection_check_task

            logger.info(
                "✅ Brainzgraphinator shutdown complete",
                enrichment_stats=enrichment_stats,
            )


if __name__ == "__main__":
    run(main())
