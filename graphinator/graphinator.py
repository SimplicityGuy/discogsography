import asyncio
import contextlib
import logging
import os
import signal
import time
from asyncio import run
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from aio_pika.abc import AbstractIncomingMessage
from common import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    DATA_TYPES,
    AsyncResilientNeo4jDriver,
    AsyncResilientRabbitMQ,
    GraphinatorConfig,
    HealthServer,
    setup_logging,
)
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from orjson import loads

from graphinator.batch_processor import BatchConfig, Neo4jBatchProcessor

logger = structlog.get_logger(__name__)

# Suppress Neo4j notifications for missing labels/properties during initial setup
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# Config will be initialized in main
config: GraphinatorConfig | None = None

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
    os.environ.get("STARTUP_IDLE_TIMEOUT", "60")
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
        "timestamp": datetime.now().isoformat(),
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
                    f"🔌 Canceling consumer for {data_type} after {CONSUMER_CANCEL_DELAY}s grace period"
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
                    logger.info("🔌 All consumers idle, closing RabbitMQ connection")
                    await close_rabbitmq_connection()
        except Exception as e:
            logger.error(
                "❌ Failed to cancel consumer",
                data_type=data_type,
                error=str(e),
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
                logger.info("🔌 Closed RabbitMQ channel - all consumers idle")
            except Exception as e:
                logger.warning("⚠️ Error closing channel", error=str(e))
            active_channel = None

        if active_connection:
            try:
                await active_connection.close()
                logger.info("🔌 Closed RabbitMQ connection - all consumers idle")
            except Exception as e:
                logger.warning("⚠️ Error closing connection", error=str(e))
            active_connection = None

        logger.info(
            f"✅ RabbitMQ connection closed. Will check for new messages every {QUEUE_CHECK_INTERVAL}s"
        )
    except Exception as e:
        logger.error(f"❌ Error closing RabbitMQ connection: {e}")


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
            logger.error(f"❌ Error in periodic queue checker: {e}")
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
        logger.error(f"❌ Failed to connect to RabbitMQ for recovery: {e}")
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

            # Declare exchange and queues
            exchange = await active_channel.declare_exchange(
                AMQP_EXCHANGE,
                AMQP_EXCHANGE_TYPE,
                durable=True,
                auto_delete=False,
            )

            # Declare dead-letter exchange for poison messages
            dlx_exchange_name = f"{AMQP_EXCHANGE}.dlx"
            dlx_exchange = await active_channel.declare_exchange(
                dlx_exchange_name,
                "topic",
                durable=True,
                auto_delete=False,
            )

            # Set QoS - must match batch_size for efficient batch processing
            await active_channel.set_qos(prefetch_count=200)

            # Queue arguments for quorum queues with DLX
            queue_args = {
                "x-queue-type": "quorum",
                "x-dead-letter-exchange": dlx_exchange_name,
                "x-delivery-limit": 20,
            }

            # Declare and bind all queues
            queues = {}
            for data_type in DATA_TYPES:
                queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{data_type}"
                dlq_name = f"{queue_name}.dlq"

                # Declare DLQ (classic queue for dead letters)
                dlq = await active_channel.declare_queue(
                    auto_delete=False,
                    durable=True,
                    name=dlq_name,
                    arguments={"x-queue-type": "classic"},
                )
                await dlq.bind(dlx_exchange, routing_key=data_type)

                # Declare main quorum queue
                queue = await active_channel.declare_queue(
                    auto_delete=False,
                    durable=True,
                    name=queue_name,
                    arguments=queue_args,
                )
                await queue.bind(exchange, routing_key=data_type)
                queues[data_type] = queue

            # Start consumers for queues with messages
            for data_type, msg_count in queues_with_messages:
                if data_type in queues and data_type not in consumer_tags:
                    handler = HANDLERS.get(data_type)
                    if handler:
                        consumer_tag = await queues[data_type].consume(
                            handler, consumer_tag=f"graphinator-{data_type}"
                        )
                        consumer_tags[data_type] = consumer_tag
                        # Remove from completed files so it will be processed
                        completed_files.discard(data_type)
                        last_message_time[data_type] = time.time()
                        logger.info(
                            f"✅ Started consumer for {data_type} "
                            f"(pending: {msg_count})"
                        )

            logger.info(
                f"✅ Recovery complete - consumers restarted: {list(consumer_tags.keys())}"
            )
            # Clear idle mode since we have active consumers again
            idle_mode = False
            # Don't close temp_connection since we're using it as active_connection
        else:
            logger.info("📭 No messages in any queue, connection remains closed")
            # Close the temporary connection
            await temp_channel.close()
            await temp_connection.close()

    except Exception as e:
        logger.error(f"❌ Error during consumer recovery: {e}")
        # Make sure to close temporary connection on error
        try:
            await temp_channel.close()
            await temp_connection.close()
        except Exception:  # nosec: B110
            pass


async def check_file_completion(
    data: dict[str, Any], data_type: str, message: AbstractIncomingMessage
) -> bool:
    """Check if message is a file completion message and handle it."""
    if data.get("type") == "file_complete":
        completed_files.add(data_type)
        total_processed = data.get("total_processed", 0)
        logger.info(
            f"🎉 File processing complete for {data_type}! "
            f"Total records processed: {total_processed}"
        )

        # Schedule consumer cancellation if enabled
        if CONSUMER_CANCEL_DELAY > 0 and data_type in queues:
            await schedule_consumer_cancellation(data_type, queues[data_type])

        await message.ack()
        return True
    return False


def process_artist(tx: Any, record: dict[str, Any]) -> bool:
    """Process artist within a single transaction for atomicity."""
    existing_result = tx.run(
        "MATCH (a:Artist {id: $id}) RETURN a.sha256 AS hash",
        id=record["id"],
    )
    existing_record = existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    resources: str = f"https://api.discogs.com/artists/{record['id']}"
    releases: str = f"{resources}/releases"

    tx.run(
        "MERGE (a:Artist {id: $id}) "
        "ON CREATE SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256 "
        "ON MATCH SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256",
        id=record["id"],
        name=record.get("name", "Unknown Artist"),
        resource_url=resources,
        releases_url=releases,
        sha256=record["sha256"],
    )

    # Handle members
    members: dict[str, Any] | None = record.get("members")
    if members is not None:
        members_list = (
            members["name"] if isinstance(members["name"], list) else [members["name"]]
        )
        if members_list:
            valid_members = []
            for member in members_list:
                if isinstance(member, str):
                    member_id = member
                else:
                    member_id = member.get("@id") or member.get("id")
                if member_id:
                    valid_members.append({"id": member_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping member without ID in artist {record['id']}: {member}"
                    )
            if valid_members:
                tx.run(
                    "UNWIND $members AS member "
                    "MATCH (a:Artist {id: $artist_id}) "
                    "MERGE (m_a:Artist {id: member.id}) "
                    "MERGE (m_a)-[:MEMBER_OF]->(a)",
                    members=valid_members,
                    artist_id=record["id"],
                )

    # Handle groups
    groups: dict[str, Any] | None = record.get("groups")
    if groups is not None:
        groups_list = (
            groups["name"] if isinstance(groups["name"], list) else [groups["name"]]
        )
        if groups_list:
            valid_groups = []
            for group in groups_list:
                if isinstance(group, str):
                    group_id = group
                else:
                    group_id = group.get("@id") or group.get("id")
                if group_id:
                    valid_groups.append({"id": group_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping group without ID in artist {record['id']}: {group}"
                    )
            if valid_groups:
                tx.run(
                    "UNWIND $groups AS group "
                    "MATCH (a:Artist {id: $artist_id}) "
                    "MERGE (g_a:Artist {id: group.id}) "
                    "MERGE (a)-[:MEMBER_OF]->(g_a)",
                    groups=valid_groups,
                    artist_id=record["id"],
                )

    # Handle aliases
    aliases: dict[str, Any] | None = record.get("aliases")
    if aliases is not None:
        aliases_list = (
            aliases["name"] if isinstance(aliases["name"], list) else [aliases["name"]]
        )
        if aliases_list:
            valid_aliases = []
            for alias in aliases_list:
                if isinstance(alias, str):
                    alias_id = alias
                else:
                    alias_id = alias.get("@id") or alias.get("id")
                if alias_id:
                    valid_aliases.append({"id": alias_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping alias without ID in artist {record['id']}: {alias}"
                    )
            if valid_aliases:
                tx.run(
                    "UNWIND $aliases AS alias "
                    "MATCH (a:Artist {id: $artist_id}) "
                    "MERGE (a_a:Artist {id: alias.id}) "
                    "MERGE (a_a)-[:ALIAS_OF]->(a)",
                    aliases=valid_aliases,
                    artist_id=record["id"],
                )

    return True  # Updated successfully


def process_label(tx: Any, record: dict[str, Any]) -> bool:
    """Process label within a single transaction for atomicity."""
    existing_result = tx.run(
        "MATCH (l:Label {id: $id}) RETURN l.sha256 AS hash", id=record["id"]
    )
    existing_record = existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    tx.run(
        "MERGE (l:Label {id: $id}) "
        "ON CREATE SET l.name = $name, l.sha256 = $sha256 "
        "ON MATCH SET l.name = $name, l.sha256 = $sha256",
        id=record["id"],
        name=record.get("name", "Unknown Label"),
        sha256=record["sha256"],
    )

    # Handle parent label relationship
    parent: dict[str, Any] | str | None = record.get("parentLabel")
    if parent is not None:
        parent_id: str | None
        if isinstance(parent, str):
            parent_id = parent
        else:
            parent_id = parent.get("@id") or parent.get("id")

        if parent_id:
            tx.run(
                "MATCH (l:Label {id: $id}) "
                "MERGE (p_l:Label {id: $p_id}) "
                "MERGE (l)-[:SUBLABEL_OF]->(p_l)",
                id=record["id"],
                p_id=parent_id,
            )
        else:
            logger.warning(
                f"⚠️ Skipping parent label without ID in label {record['id']}: {parent}"
            )

    # Handle sublabels in batch
    sublabels: dict[str, Any] | list[Any] | str | None = record.get("sublabels")
    if sublabels is not None:
        sublabels_list: list[Any] = []
        if isinstance(sublabels, str):
            sublabels_list = [sublabels]
        elif isinstance(sublabels, list):
            sublabels_list = sublabels
        elif isinstance(sublabels, dict) and "label" in sublabels:
            sublabels_list = (
                sublabels["label"]
                if isinstance(sublabels["label"], list)
                else [sublabels["label"]]
            )

        if sublabels_list:
            valid_sublabels = []
            for sublabel in sublabels_list:
                if isinstance(sublabel, str):
                    sublabel_id = sublabel
                else:
                    sublabel_id = sublabel.get("@id") or sublabel.get("id")
                if sublabel_id:
                    valid_sublabels.append({"id": sublabel_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping sublabel without ID in label {record['id']}: {sublabel}"
                    )
            if valid_sublabels:
                tx.run(
                    "UNWIND $sublabels AS sublabel "
                    "MATCH (l:Label {id: $label_id}) "
                    "MERGE (s_l:Label {id: sublabel.id}) "
                    "MERGE (s_l)-[:SUBLABEL_OF]->(l)",
                    sublabels=valid_sublabels,
                    label_id=record["id"],
                )

    return True  # Updated successfully


def process_master(tx: Any, record: dict[str, Any]) -> bool:
    """Process master within a single transaction for atomicity."""
    existing_result = tx.run(
        "MATCH (m:Master {id: $id}) RETURN m.sha256 AS hash",
        id=record["id"],
    )
    existing_record = existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    tx.run(
        "MERGE (m:Master {id: $id}) "
        "ON CREATE SET m.title = $title, m.year = $year, m.sha256 = $sha256 "
        "ON MATCH SET m.title = $title, m.year = $year, m.sha256 = $sha256",
        id=record["id"],
        title=record.get("title", "Unknown Master"),
        year=record.get("year", 0),
        sha256=record["sha256"],
    )

    # Handle artist relationships in batch
    artists: dict[str, Any] | None = record.get("artists")
    if artists is not None:
        artists_list = (
            artists["artist"]
            if isinstance(artists["artist"], list)
            else [artists["artist"]]
        )
        if artists_list:
            valid_artists = []
            for artist in artists_list:
                if isinstance(artist, str):
                    artist_id = artist
                else:
                    artist_id = artist.get("id") or artist.get("@id")
                if artist_id:
                    valid_artists.append({"id": artist_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping artist without ID in master {record['id']}: {artist}"
                    )
            if valid_artists:
                tx.run(
                    "UNWIND $artists AS artist "
                    "MATCH (m:Master {id: $master_id}) "
                    "MERGE (a_m:Artist {id: artist.id}) "
                    "MERGE (m)-[:BY]->(a_m)",
                    artists=valid_artists,
                    master_id=record["id"],
                )

    # Handle genres and styles
    genres: dict[str, Any] | None = record.get("genres")
    genres_list: list[str] = []
    if genres is not None:
        genres_list = (
            genres["genre"] if isinstance(genres["genre"], list) else [genres["genre"]]
        )
        if genres_list:
            tx.run(
                "UNWIND $genres AS genre "
                "MATCH (m:Master {id: $master_id}) "
                "MERGE (g:Genre {name: genre.name}) "
                "MERGE (m)-[:IS]->(g)",
                genres=[{"name": genre} for genre in genres_list],
                master_id=record["id"],
            )

    styles: dict[str, Any] | None = record.get("styles")
    styles_list: list[str] = []
    if styles is not None:
        styles_list = (
            styles["style"] if isinstance(styles["style"], list) else [styles["style"]]
        )
        if styles_list:
            tx.run(
                "UNWIND $styles AS style "
                "MATCH (m:Master {id: $master_id}) "
                "MERGE (s:Style {name: style.name}) "
                "MERGE (m)-[:IS]->(s)",
                styles=[{"name": style} for style in styles_list],
                master_id=record["id"],
            )

    # Connect styles to genres if both exist
    if genres_list and styles_list:
        tx.run(
            "UNWIND $genre_style_pairs AS pair "
            "MERGE (g:Genre {name: pair.genre}) "
            "MERGE (s:Style {name: pair.style}) "
            "MERGE (s)-[:PART_OF]->(g)",
            genre_style_pairs=[
                {"genre": genre, "style": style}
                for genre in genres_list
                for style in styles_list
            ],
        )

    return True  # Updated successfully


def process_release(tx: Any, record: dict[str, Any]) -> bool:
    """Process release within a single transaction for atomicity."""
    existing_result = tx.run(
        "MATCH (r:Release {id: $id}) RETURN r.sha256 AS hash",
        id=record["id"],
    )
    existing_record = existing_result.single()
    if existing_record and existing_record["hash"] == record["sha256"]:
        return False  # No update needed

    tx.run(
        "MERGE (r:Release {id: $id}) "
        "ON CREATE SET r.title = $title, r.sha256 = $sha256 "
        "ON MATCH SET r.title = $title, r.sha256 = $sha256",
        id=record["id"],
        title=record.get("title", "Unknown Release"),
        sha256=record["sha256"],
    )

    # Handle artist relationships
    artists: dict[str, Any] | None = record.get("artists")
    if artists is not None:
        artists_list = (
            artists["artist"]
            if isinstance(artists["artist"], list)
            else [artists["artist"]]
        )
        if artists_list:
            valid_artists = []
            for artist in artists_list:
                if isinstance(artist, str):
                    artist_id = artist
                else:
                    artist_id = artist.get("id") or artist.get("@id")
                if artist_id:
                    valid_artists.append({"id": artist_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping artist without ID in release {record['id']}: {artist}"
                    )
            if valid_artists:
                tx.run(
                    "UNWIND $artists AS artist "
                    "MATCH (r:Release {id: $release_id}) "
                    "MERGE (a_r:Artist {id: artist.id}) "
                    "MERGE (r)-[:BY]->(a_r)",
                    artists=valid_artists,
                    release_id=record["id"],
                )

    # Handle label relationships
    labels: dict[str, Any] | None = record.get("labels")
    if labels is not None:
        labels_list = (
            labels["label"] if isinstance(labels["label"], list) else [labels["label"]]
        )
        if labels_list:
            valid_labels = []
            for label in labels_list:
                if isinstance(label, str):
                    label_id = label
                else:
                    label_id = label.get("@id") or label.get("id")
                if label_id:
                    valid_labels.append({"id": label_id})
                else:
                    logger.warning(
                        f"⚠️ Skipping label without ID in release {record['id']}: {label}"
                    )
            if valid_labels:
                tx.run(
                    "UNWIND $labels AS label "
                    "MATCH (r:Release {id: $release_id}) "
                    "MERGE (l_r:Label {id: label.id}) "
                    "MERGE (r)-[:ON]->(l_r)",
                    labels=valid_labels,
                    release_id=record["id"],
                )

    # Handle master relationship
    master_id: dict[str, Any] | None = record.get("master_id")
    if master_id is not None:
        m_id = master_id.get("#text") if isinstance(master_id, dict) else master_id
        if m_id:
            tx.run(
                "MATCH (r:Release {id: $id}),(m_r:Master {id: $m_id}) "
                "MERGE (r)-[:DERIVED_FROM]->(m_r)",
                id=record["id"],
                m_id=m_id,
            )
        else:
            logger.warning(
                f"⚠️ Skipping master relationship without valid ID in release {record['id']}: {master_id}"
            )

    # Handle genres and styles in batch
    genres: dict[str, Any] | None = record.get("genres")
    genres_list: list[str] = []
    if genres is not None:
        genres_list = (
            genres["genre"] if isinstance(genres["genre"], list) else [genres["genre"]]
        )
        if genres_list:
            tx.run(
                "UNWIND $genres AS genre "
                "MATCH (r:Release {id: $release_id}) "
                "MERGE (g:Genre {name: genre.name}) "
                "MERGE (r)-[:IS]->(g)",
                genres=[{"name": genre} for genre in genres_list],
                release_id=record["id"],
            )

    styles: dict[str, Any] | None = record.get("styles")
    styles_list: list[str] = []
    if styles is not None:
        styles_list = (
            styles["style"] if isinstance(styles["style"], list) else [styles["style"]]
        )
        if styles_list:
            tx.run(
                "UNWIND $styles AS style "
                "MATCH (r:Release {id: $release_id}) "
                "MERGE (s:Style {name: style.name}) "
                "MERGE (r)-[:IS]->(s)",
                styles=[{"name": style} for style in styles_list],
                release_id=record["id"],
            )

    # Connect styles to genres if both exist
    if genres_list and styles_list:
        tx.run(
            "UNWIND $genre_style_pairs AS pair "
            "MERGE (g:Genre {name: pair.genre}) "
            "MERGE (s:Style {name: pair.style}) "
            "MERGE (s)-[:PART_OF]->(g)",
            genre_style_pairs=[
                {"genre": genre, "style": style}
                for genre in genres_list
                for style in styles_list
            ],
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
            logger.info("🛑 Shutdown requested, rejecting new messages")
            await message.nack(requeue=True)
            return

        record_id = "unknown"
        try:
            logger.debug(f"📥 Received {data_type[:-1]} message")
            record: dict[str, Any] = loads(message.body)

            if await check_file_completion(record, data_type, message):
                return

            if BATCH_MODE and batch_processor is not None:
                await batch_processor.add_message(
                    data_type,
                    record,
                    message.ack,
                    lambda: message.nack(requeue=True),
                )
                message_counts[data_type] += 1
                last_message_time[data_type] = time.time()
                return

            record_id = record.get("id", "unknown")
            record_name = record.get(name_field, default_name)

            message_counts[data_type] += 1
            last_message_time[data_type] = time.time()
            if message_counts[data_type] % progress_interval == 0:
                logger.info(
                    f"📊 Processed {data_type} in Neo4j",
                    message_counts=message_counts[data_type],
                )

            logger.debug(
                f"🔄 Processing {data_type[:-1]}",
                record_id=record_id,
                record_name=record_name,
            )

            if graph is None:
                raise RuntimeError("Neo4j driver not initialized")

            async with await graph.session(database="neo4j") as session:

                def tx_fn(tx: Any) -> bool:
                    return bool(process_fn(tx, record))

                updated = await session.execute_write(tx_fn)

            if updated:
                logger.debug(
                    f"💾 Updated {data_type[:-1]} in Neo4j",
                    record_id=record_id,
                )
            else:
                logger.debug(
                    f"⏩ Skipped {data_type[:-1]} (no changes needed)",
                    record_id=record_id,
                )

            await message.ack()
        except (ServiceUnavailable, SessionExpired) as e:
            logger.warning(
                f"⚠️ Neo4j unavailable, will retry {data_type[:-1]} message",
                error=str(e),
            )
            try:
                await message.nack(requeue=True)
            except Exception as nack_error:
                logger.warning("⚠️ Failed to nack message", error=str(nack_error))
        except Exception as e:
            logger.error(
                f"❌ Failed to process {data_type[:-1]} message",
                record_id=record_id,
                error=str(e),
            )
            try:
                await message.nack(requeue=True)
            except Exception as nack_error:
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
        if (
            not idle_mode
            and total == 0
            and (current_time - startup_time) >= STARTUP_IDLE_TIMEOUT
        ):
            idle_mode = True
            last_idle_log = current_time

            # Cancel all active consumers and close connection
            for dt in list(consumer_tags.keys()):
                if dt in queues:
                    try:
                        await queues[dt].cancel(consumer_tags[dt], nowait=True)
                    except Exception as e:
                        logger.warning(
                            "⚠️ Error canceling consumer during idle transition",
                            data_type=dt,
                            error=str(e),
                        )
                del consumer_tags[dt]

            await close_rabbitmq_connection()

            logger.info(
                f"😴 No messages received after {STARTUP_IDLE_TIMEOUT}s, entering idle mode. "
                f"Will check queues every {QUEUE_CHECK_INTERVAL}s",
                startup_idle_timeout=STARTUP_IDLE_TIMEOUT,
                queue_check_interval=QUEUE_CHECK_INTERVAL,
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
                    "😴 Idle mode - no messages received. "
                    f"Next queue check in ≤{QUEUE_CHECK_INTERVAL}s",
                    queue_check_interval=QUEUE_CHECK_INTERVAL,
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
            emoji = "🎉 " if data_type in completed_files else ""
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
                f"🔌 Canceled consumers: {canceled_consumers}",
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
        uri=config.neo4j_address,
        auth=(config.neo4j_username, config.neo4j_password),
        max_retries=5,
        encrypted=False,
    )

    # Test Neo4j connectivity using async operations
    try:
        async with await graph.session(database="neo4j") as session:
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

    except Exception as e:
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
        except Exception as e:
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
        # With batch_size=100 (default), we use 200 to allow 2 batches in parallel
        await channel.set_qos(prefetch_count=200)

        # Declare the shared exchange (must match extractor)
        exchange = await channel.declare_exchange(
            AMQP_EXCHANGE, AMQP_EXCHANGE_TYPE, durable=True, auto_delete=False
        )

        # Declare dead-letter exchange for poison messages
        dlx_exchange_name = f"{AMQP_EXCHANGE}.dlx"
        dlx_exchange = await channel.declare_exchange(
            dlx_exchange_name, "topic", durable=True, auto_delete=False
        )

        # Queue arguments for quorum queues with DLX
        queue_args = {
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": dlx_exchange_name,
            "x-delivery-limit": 20,
        }

        # Declare queues for all data types and bind them to exchange
        queues = {}
        for data_type in DATA_TYPES:
            queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{data_type}"
            dlq_name = f"{queue_name}.dlq"

            # Declare DLQ (classic queue for dead letters)
            dlq = await channel.declare_queue(
                auto_delete=False,
                durable=True,
                name=dlq_name,
                arguments={"x-queue-type": "classic"},
            )
            await dlq.bind(dlx_exchange, routing_key=data_type)

            # Declare main quorum queue
            queue = await channel.declare_queue(
                auto_delete=False,
                durable=True,
                name=queue_name,
                arguments=queue_args,
            )
            await queue.bind(exchange, routing_key=data_type)
            queues[data_type] = queue

        # Start consumers for all data types
        for data_type, handler in HANDLERS.items():
            consumer_tags[data_type] = await queues[data_type].consume(
                handler, consumer_tag=f"graphinator-{data_type}"
            )

        logger.info(
            f"🚀 Graphinator started! Connected to AMQP broker (exchange: {AMQP_EXCHANGE}, type: {AMQP_EXCHANGE_TYPE}). "
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
                    logger.error("❌ Error flushing batch processor", error=str(e))

            # Cancel any pending consumer cancellation tasks
            for task in consumer_cancel_tasks.values():
                task.cancel()

            # Close RabbitMQ connection if still active
            await close_rabbitmq_connection()

            # Close async Neo4j driver
            try:
                await graph.close()
                logger.info("✅ Async Neo4j driver closed")
            except Exception as e:
                logger.warning("⚠️ Error closing Neo4j driver", error=str(e))

        # Stop health server
        health_server.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Application interrupted")
    except Exception as e:
        logger.error("❌ Application error", error=str(e))
    finally:
        logger.info("✅ Graphinator service shutdown complete")
