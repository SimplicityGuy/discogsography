import asyncio
import contextlib
import logging
import os
import signal
import time
from asyncio import run
from pathlib import Path
from typing import Any

import psycopg
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


logger = logging.getLogger(__name__)

# Config will be initialized in main
config: TableinatorConfig | None = None

# Progress tracking
message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
progress_interval = 100  # Log progress every 100 messages
last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}
completed_files = set()  # Track which files have completed processing
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
reconnect_tasks: dict[
    str, asyncio.Task[None]
] = {}  # Tracks periodic reconnection tasks

# Connection parameters will be initialized in main
connection_params: dict[str, Any] = {}


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    from datetime import datetime

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
    logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
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
        logger.error(f"❌ Database error executing query: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error executing query: {e}")
        return False


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

                logger.info(f"✅ Consumer for {data_type} successfully canceled")

                # Schedule periodic reconnection if enabled
                if RECONNECT_INTERVAL > 0:
                    await schedule_periodic_reconnection(data_type)
        except Exception as e:
            logger.error(f"❌ Failed to cancel consumer for {data_type}: {e}")
        finally:
            # Clean up the task reference
            if data_type in consumer_cancel_tasks:
                del consumer_cancel_tasks[data_type]

    # Cancel any existing scheduled cancellation
    if data_type in consumer_cancel_tasks:
        consumer_cancel_tasks[data_type].cancel()

    # Schedule new cancellation
    consumer_cancel_tasks[data_type] = asyncio.create_task(cancel_after_delay())


async def schedule_periodic_reconnection(data_type: str) -> None:
    """Schedule periodic reconnection to check for new messages after file completion."""

    async def periodic_reconnect() -> None:
        """Periodically reconnect to check for new messages."""
        while data_type in completed_files:
            try:
                # Wait for the reconnect interval
                logger.info(
                    f"⏰ Scheduled reconnection for {data_type} in {RECONNECT_INTERVAL}s ({RECONNECT_INTERVAL / 3600:.1f} hours)"
                )
                await asyncio.sleep(RECONNECT_INTERVAL)

                # Check if we're still marked as complete and not already consuming
                if data_type not in completed_files or data_type in consumer_tags:
                    logger.info(
                        f"🔄 Skipping reconnection for {data_type} - state changed"
                    )
                    break

                # Get the queue for this data type
                if data_type not in queues:
                    logger.warning(
                        f"⚠️ Queue not found for {data_type}, skipping reconnection"
                    )
                    break

                queue = queues[data_type]

                logger.info(f"🔄 Attempting periodic reconnection for {data_type}...")

                # Start consuming messages again (all data types use the same handler)
                consumer_tag = await queue.consume(
                    on_data_message, consumer_tag=f"tableinator-{data_type}-reconnect"
                )
                consumer_tags[data_type] = consumer_tag

                logger.info(f"✅ Reconnected consumer for {data_type}")

                # Track that we've reconnected
                last_message_time[data_type] = time.time()
                empty_queue_start = time.time()

                # Monitor for empty queue timeout
                while data_type in consumer_tags:
                    await asyncio.sleep(60)  # Check every minute

                    # Check if we've received any messages recently
                    if time.time() - last_message_time[data_type] < 60:
                        # Reset empty queue timer if we received messages
                        empty_queue_start = time.time()
                    elif time.time() - empty_queue_start > EMPTY_QUEUE_TIMEOUT:
                        # No messages for timeout period, disconnect
                        logger.info(
                            f"⏱️ No messages for {data_type} in {EMPTY_QUEUE_TIMEOUT}s, disconnecting..."
                        )

                        if data_type in consumer_tags:
                            await queue.cancel(consumer_tags[data_type], nowait=True)
                            del consumer_tags[data_type]
                            logger.info(
                                f"🔌 Disconnected idle consumer for {data_type}"
                            )

                        # File is still considered complete, will reconnect again later
                        break

            except Exception as e:
                logger.error(f"❌ Error in periodic reconnection for {data_type}: {e}")
                # Clean up consumer if it exists
                if data_type in consumer_tags:
                    try:
                        queue = queues.get(data_type)
                        if queue:
                            await queue.cancel(consumer_tags[data_type], nowait=True)
                    except Exception:  # nosec: B110 - Ignore cancellation errors during cleanup
                        pass
                    del consumer_tags[data_type]
            finally:
                # Clean up task reference
                if data_type in reconnect_tasks:
                    del reconnect_tasks[data_type]

    # Cancel any existing reconnection task
    if data_type in reconnect_tasks:
        reconnect_tasks[data_type].cancel()

    # Schedule new reconnection task
    reconnect_tasks[data_type] = asyncio.create_task(periodic_reconnect())


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
            logger.error(f"❌ Message missing 'id' field: {data}")
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
                    f"📊 Processed {message_counts[data_type]} {data_type} in PostgreSQL"
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
            logger.debug(f"🔄 Processing {data_type[:-1]} ID={data_id}: {record_name}")
        else:
            logger.debug(f"🔄 Processing {data_type[:-1]} ID={data_id}")

    except Exception as e:
        logger.error(f"❌ Failed to parse message: {e}")
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
            logger.debug(f"🐘 Updated {data_type[:-1]} ID={data_id} in PostgreSQL")

        await message.ack()

    except (InterfaceError, OperationalError) as e:
        logger.warning(f"⚠️ Database connection issue, will retry: {e}")
        await message.nack(requeue=True)
    except Exception as e:
        logger.error(f"❌ Failed to process {data_type} message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"⚠️ Failed to nack message: {nack_error}")


async def main() -> None:
    global connection_pool, config, connection_params, queues

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("tableinator", log_file=Path("/logs/tableinator.log"))
    logger.info("🚀 Starting PostgreSQL tableinator service with connection pooling")

    # Add startup delay for dependent services
    startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
    if startup_delay > 0:
        logger.info(
            f"⏳ Waiting {startup_delay} seconds for dependent services to start..."
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
        logger.error(f"❌ Configuration error: {e}")
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
                    logger.info(f"🔧 Creating database '{config.postgres_database}'...")
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(config.postgres_database)
                        )
                    )
                    logger.info(f"✅ Database '{config.postgres_database}' created")
                else:
                    logger.info(
                        f"✅ Database '{config.postgres_database}' already exists"
                    )
    except Exception as e:
        logger.error(f"❌ Failed to ensure database exists: {e}")
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
        logger.error(f"❌ Failed to initialize connection pool: {e}")
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
        logger.error(f"❌ Failed to initialize database: {e}")
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

    # Initialize resilient RabbitMQ connection
    rabbitmq = AsyncResilientRabbitMQ(
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
            amqp_connection = await rabbitmq.connect()
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
                    logger.warning(f"⚠️ Slow consumers detected: {slow_consumers}")

                # Log consumer status
                active_consumers = list(consumer_tags.keys())
                canceled_consumers = [
                    dt
                    for dt in DATA_TYPES
                    if dt not in consumer_tags and dt in completed_files
                ]

                if canceled_consumers:
                    logger.info(f"🔌 Canceled consumers: {canceled_consumers}")
                if active_consumers:
                    logger.info(f"✅ Active consumers: {active_consumers}")

        progress_task = asyncio.create_task(progress_reporter())

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

            # Cancel any pending consumer cancellation tasks
            for task in consumer_cancel_tasks.values():
                task.cancel()

            # Cancel any pending reconnection tasks
            for task in reconnect_tasks.values():
                task.cancel()

            # Close connection pool
            try:
                if connection_pool:
                    connection_pool.close()
                    logger.info("✅ Connection pool closed")
            except Exception as e:
                logger.warning(f"⚠️ Error closing connection pool: {e}")

        # Stop health server
        health_server.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Application interrupted")
    except Exception as e:
        logger.error(f"❌ Application error: {e}")
    finally:
        logger.info("✅ Tableinator service shutdown complete")
