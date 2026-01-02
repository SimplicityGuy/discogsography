import asyncio
import contextlib
import os
import signal
import time
from asyncio import run
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from aio_pika.abc import AbstractIncomingMessage
from common import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    DATA_TYPES,
    HealthServer,
    TableinatorConfig,
    setup_logging,
    ResilientPostgreSQLPool,
    AsyncResilientRabbitMQ,
)
from orjson import loads
from psycopg import sql
from psycopg.errors import DatabaseError, InterfaceError, OperationalError
from psycopg.types.json import Jsonb


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

# Periodic reconnection settings
RECONNECT_INTERVAL = int(
    os.environ.get("RECONNECT_INTERVAL", "86400")
)  # Default 24 hours (1 day)
EMPTY_QUEUE_TIMEOUT = int(
    os.environ.get("EMPTY_QUEUE_TIMEOUT", "1800")
)  # Default 30 minutes
QUEUE_CHECK_INTERVAL = int(
    os.environ.get("QUEUE_CHECK_INTERVAL", "3600")
)  # Default 1 hour - how often to check for new messages when connection is closed
reconnect_tasks: dict[
    str, asyncio.Task[None]
] = {}  # Tracks periodic reconnection tasks

# Connection parameters will be initialized in main
connection_params: dict[str, Any] = {}

# Connection state tracking
rabbitmq_manager: Any = None  # Will hold AsyncResilientRabbitMQ instance
active_connection: Any = None  # Current active connection
active_channel: Any = None  # Current active channel
connection_check_task: asyncio.Task[None] | None = (
    None  # Background task for periodic queue checks
)


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""

    return {
        "status": "healthy",
        "service": "tableinator",
        "current_task": current_task,
        "progress": current_progress,
        "message_counts": message_counts.copy(),
        "last_message_time": last_message_time.copy(),
        "timestamp": datetime.now().isoformat(),
    }


# Create connection pool for concurrent access
connection_pool: ResilientPostgreSQLPool | None = None

# Global shutdown flag
shutdown_requested = False


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(
        "🛑 Received signal signum, initiating graceful shutdown...", signum=signum
    )
    shutdown_requested = True


def get_connection() -> Any:
    """Get a database connection from the pool."""
    if connection_pool is None:
        raise RuntimeError("Connection pool not initialized")

    return connection_pool.connection()


def safe_execute_query(cursor: Any, query: Any, parameters: tuple[Any, ...]) -> bool:
    """Execute a PostgreSQL query with error handling."""
    try:
        cursor.execute(query, parameters)
        return True
    except DatabaseError as e:
        logger.error("❌ Database error executing query", error=str(e))
        return False
    except Exception as e:
        logger.error("❌ Unexpected error executing query", error=str(e))
        return False


async def schedule_consumer_cancellation(data_type: str, queue: Any) -> None:
    """Schedule cancellation of a consumer after a delay."""

    async def cancel_after_delay() -> None:
        try:
            await asyncio.sleep(CONSUMER_CANCEL_DELAY)

            if data_type in consumer_tags:
                consumer_tag = consumer_tags[data_type]
                logger.info(
                    "🔌 Canceling consumer for data_type after CONSUMER_CANCEL_DELAYs grace period",
                    data_type=data_type,
                    CONSUMER_CANCEL_DELAY=CONSUMER_CANCEL_DELAY,
                )

                # Cancel the consumer with nowait to avoid hanging
                await queue.cancel(consumer_tag, nowait=True)

                # Remove from tracking
                del consumer_tags[data_type]

                logger.info(
                    "✅ Consumer for data_type successfully canceled",
                    data_type=data_type,
                )

                # Check if all consumers are now idle
                if await check_all_consumers_idle():
                    logger.info("🔌 All consumers idle, closing RabbitMQ connection")
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
            "✅ RabbitMQ connection closed. Will check for new messages every QUEUE_CHECK_INTERVALs",
            QUEUE_CHECK_INTERVAL=QUEUE_CHECK_INTERVAL,
        )
    except Exception as e:
        logger.error("❌ Error closing RabbitMQ connection", error=str(e))


async def check_all_consumers_idle() -> bool:
    """Check if all consumers are cancelled (idle)."""
    return len(consumer_tags) == 0 and len(DATA_TYPES) == len(completed_files)


async def periodic_queue_checker() -> None:
    """Periodically check all queues for pending messages when connection is closed."""
    global active_connection, active_channel, queues, consumer_tags

    while not shutdown_requested:
        try:
            await asyncio.sleep(QUEUE_CHECK_INTERVAL)

            # Only check if all consumers are idle and connection is closed
            if not await check_all_consumers_idle() or active_connection:
                continue

            logger.info("🔄 Checking all queues for new messages...")

            # Temporarily connect to check queue depths
            temp_connection = await rabbitmq_manager.connect()
            temp_channel = await temp_connection.channel()

            try:
                # Check each queue for pending messages
                queues_with_messages = []
                for data_type in DATA_TYPES:
                    queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{data_type}"
                    queue = await temp_channel.get_queue(queue_name)

                    # Use queue.declare with passive=True to get message count without affecting the queue
                    declared_queue = await temp_channel.declare_queue(
                        name=queue_name, passive=True
                    )

                    if declared_queue.declaration_result.message_count > 0:
                        queues_with_messages.append(
                            (data_type, declared_queue.declaration_result.message_count)
                        )

                if queues_with_messages:
                    logger.info(
                        "📬 Found messages in queues, restarting consumers",
                        queues=queues_with_messages,
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

                    # Set QoS
                    await active_channel.set_qos(prefetch_count=50)

                    # Declare and bind all queues
                    queues = {}
                    for data_type in DATA_TYPES:
                        queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{data_type}"
                        queue = await active_channel.declare_queue(
                            auto_delete=False, durable=True, name=queue_name
                        )
                        await queue.bind(exchange, routing_key=data_type)
                        queues[data_type] = queue

                    # Start consumers for queues with messages
                    for data_type, _ in queues_with_messages:
                        if data_type in queues and data_type not in consumer_tags:
                            consumer_tag = await queues[data_type].consume(
                                on_data_message
                            )
                            consumer_tags[data_type] = consumer_tag
                            # Remove from completed files so it will be processed
                            completed_files.discard(data_type)
                            last_message_time[data_type] = time.time()
                            logger.info(
                                "✅ Started consumer for data_type",
                                data_type=data_type,
                            )

                    # Don't close temp_connection since we're using it as active_connection
                else:
                    logger.info(
                        "📭 No messages in any queue, connection remains closed"
                    )
                    # Close the temporary connection
                    await temp_channel.close()
                    await temp_connection.close()

            except Exception as e:
                logger.error("❌ Error checking queues", error=str(e))
                # Make sure to close temporary connection on error
                try:
                    await temp_channel.close()
                    await temp_connection.close()
                except Exception:  # nosec: B110
                    pass

        except asyncio.CancelledError:
            logger.info("🛑 Queue checker task cancelled")
            break
        except Exception as e:
            logger.error("❌ Error in periodic queue checker", error=str(e))
            # Continue running despite errors


async def on_data_message(message: AbstractIncomingMessage) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        data: dict[str, Any] = loads(message.body)
        data_type: str = message.routing_key or "unknown"

        # Check if this is a file completion message
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
            return

        # Normal message processing - require 'id' field
        if "id" not in data:
            logger.error("❌ Message missing 'id' field: data", data=data)
            await message.nack(requeue=False)
            return

        data_id: str = data["id"]

        # Increment counter and log progress
        if data_type in message_counts:
            message_counts[data_type] += 1
            last_message_time[data_type] = time.time()
            global current_task
            current_task = f"Processing {data_type}"
            if message_counts[data_type] % progress_interval == 0:
                logger.info(
                    "📊 Processed records in PostgreSQL",
                    count=message_counts[data_type],
                    data_type=data_type,
                )

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

    # Process record using connection pool for concurrent access
    try:
        with (
            get_connection() as conn,
            conn.cursor() as cursor,
        ):
            # Check existing hash and update in a single transaction
            cursor.execute(
                sql.SQL("SELECT hash FROM {table} WHERE data_id = %s;").format(
                    table=sql.Identifier(data_type)
                ),
                (data_id,),
            )

            result = cursor.fetchone()
            old_hash: str = "-1" if result is None else result[0]
            new_hash: str = data["sha256"]

            if old_hash == new_hash:
                await message.ack()
                return

            # Insert or update record in same transaction
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {table} (hash, data_id, data) VALUES (%s, %s, %s) "
                    "ON CONFLICT (data_id) DO UPDATE SET (hash, data_id, data) = (EXCLUDED.hash, EXCLUDED.data_id, EXCLUDED.data);"
                ).format(table=sql.Identifier(data_type)),
                (
                    new_hash,
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

    except (InterfaceError, OperationalError) as e:
        logger.warning("⚠️ Database connection issue, will retry", error=str(e))
        await message.nack(requeue=True)
    except Exception as e:
        logger.error("❌ Failed to process message", data_type=data_type, error=str(e))
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning("⚠️ Failed to nack message", error=str(nack_error))


async def main() -> None:
    global \
        connection_pool, \
        config, \
        connection_params, \
        queues, \
        rabbitmq_manager, \
        active_connection, \
        active_channel, \
        connection_check_task

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("tableinator", log_file=Path("/logs/tableinator.log"))
    logger.info("🚀 Starting PostgreSQL tableinator service with connection pooling")

    # Add startup delay for dependent services
    startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
    if startup_delay > 0:
        logger.info(
            "⏳ Waiting startup_delay seconds for dependent services to start...",
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
    if ":" in config.postgres_address:
        host, port_str = config.postgres_address.split(":", 1)
        port = int(port_str)
    else:
        host = config.postgres_address
        port = 5432

    # Set connection parameters
    connection_params = {
        "host": str(host),
        "port": int(port),
        "dbname": str(config.postgres_database),
        "user": str(config.postgres_username),
        "password": str(config.postgres_password),
    }

    # First, ensure the database exists
    try:
        # Connect to default 'postgres' database to create our database if needed
        admin_params = connection_params.copy()
        admin_params["dbname"] = "postgres"

        with psycopg.connect(**admin_params) as admin_conn:
            admin_conn.autocommit = True
            with admin_conn.cursor() as cursor:
                # Check if database exists
                cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (config.postgres_database,),
                )
                if not cursor.fetchone():
                    logger.info(
                        "🔧 Creating database 'postgres_database'...",
                        postgres_database=config.postgres_database,
                    )
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(config.postgres_database)
                        )
                    )
                    logger.info(
                        "✅ Database 'postgres_database' created",
                        postgres_database=config.postgres_database,
                    )
                else:
                    logger.info(
                        "✅ Database 'postgres_database' already exists",
                        postgres_database=config.postgres_database,
                    )
    except Exception as e:
        logger.error("❌ Failed to ensure database exists", error=str(e))
        return

    # Initialize resilient connection pool for concurrent access
    try:
        connection_pool = ResilientPostgreSQLPool(
            connection_params=connection_params,
            max_connections=20,
            min_connections=2,
            max_retries=5,
            health_check_interval=30,
        )
        logger.info("🐘 Connected to PostgreSQL with resilient connection pool")
        logger.info("✅ Connection pool initialized (min: 2, max: 20 connections)")
    except Exception as e:
        logger.error("❌ Failed to initialize connection pool", error=str(e))
        return

    # Initialize database tables
    try:
        with (
            get_connection() as conn,
            conn.cursor() as cursor,
        ):
            for table_name in ["artists", "labels", "masters", "releases"]:
                cursor.execute(
                    sql.SQL(
                        """
                            CREATE TABLE IF NOT EXISTS {table} (
                                data_id VARCHAR PRIMARY KEY,
                                hash VARCHAR NOT NULL,
                                data JSONB NOT NULL
                            )
                        """
                    ).format(table=sql.Identifier(table_name))
                )
            # Autocommit is enabled, so tables are created immediately
        logger.info("✅ Database tables created/verified")
    except Exception as e:
        logger.error("❌ Failed to initialize database", error=str(e))
        if connection_pool:
            connection_pool.close()
        return
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

        # Set QoS to allow more concurrent message processing with connection pooling
        await channel.set_qos(prefetch_count=50)

        # Declare the shared exchange (must match extractor)
        exchange = await channel.declare_exchange(
            AMQP_EXCHANGE, AMQP_EXCHANGE_TYPE, durable=True, auto_delete=False
        )

        # Declare queues for all data types and bind them to exchange
        queues = {}
        for data_type in DATA_TYPES:
            queue_name = f"{AMQP_QUEUE_PREFIX_TABLEINATOR}-{data_type}"
            queue = await channel.declare_queue(
                auto_delete=False, durable=True, name=queue_name
            )
            await queue.bind(exchange, routing_key=data_type)
            queues[data_type] = queue

        # Map queues to their respective message handlers (all use same handler)
        artists_queue = queues["artists"]
        labels_queue = queues["labels"]
        masters_queue = queues["masters"]
        releases_queue = queues["releases"]

        # Start consumers and store their tags
        consumer_tags["artists"] = await artists_queue.consume(on_data_message)
        consumer_tags["labels"] = await labels_queue.consume(on_data_message)
        consumer_tags["masters"] = await masters_queue.consume(on_data_message)
        consumer_tags["releases"] = await releases_queue.consume(on_data_message)

        logger.info(
            f"🚀 Tableinator started! Connected to AMQP broker (exchange: {AMQP_EXCHANGE}, type: {AMQP_EXCHANGE_TYPE}). "
            f"Consuming from {len(DATA_TYPES)} queues with connection pool (max 20 connections). "
            "Ready to process messages into PostgreSQL. Press CTRL+C to exit"
        )

        # Start periodic progress reporting and consumer health monitoring
        async def progress_reporter() -> None:
            report_count = 0
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
                        "⚠️ Slow consumers detected: slow_consumers",
                        slow_consumers=slow_consumers,
                    )

                # Log consumer status
                active_consumers = list(consumer_tags.keys())
                canceled_consumers = [
                    dt
                    for dt in DATA_TYPES
                    if dt not in consumer_tags and dt in completed_files
                ]

                if canceled_consumers:
                    logger.info(
                        "🔌 Canceled consumers: canceled_consumers",
                        canceled_consumers=canceled_consumers,
                    )
                if active_consumers:
                    logger.info(
                        "✅ Active consumers: active_consumers",
                        active_consumers=active_consumers,
                    )

        progress_task = asyncio.create_task(progress_reporter())

        # Start periodic queue checker task
        connection_check_task = asyncio.create_task(periodic_queue_checker())
        logger.info(
            "🔄 Started periodic queue checker (interval: QUEUE_CHECK_INTERVALs)",
            QUEUE_CHECK_INTERVAL=QUEUE_CHECK_INTERVAL,
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

            # Cancel any pending consumer cancellation tasks
            for task in consumer_cancel_tasks.values():
                task.cancel()

            # Cancel any pending reconnection tasks
            for task in reconnect_tasks.values():
                task.cancel()

            # Close RabbitMQ connection if still active
            await close_rabbitmq_connection()

            # Close connection pool
            try:
                if connection_pool:
                    connection_pool.close()
                    logger.info("✅ Connection pool closed")
            except Exception as e:
                logger.warning("⚠️ Error closing connection pool", error=str(e))

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
        logger.info("✅ Tableinator service shutdown complete")
