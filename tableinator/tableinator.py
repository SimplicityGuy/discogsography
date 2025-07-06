import asyncio
import contextlib
import logging
import signal
import threading
import time
from asyncio import run
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from typing import Any

import psycopg
from aio_pika import connect
from aio_pika.abc import AbstractIncomingMessage
from aio_pika.exceptions import AMQPConnectionError
from common import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
    DATA_TYPES,
    HealthServer,
    TableinatorConfig,
    setup_logging,
)
from orjson import loads
from psycopg import sql
from psycopg.errors import DatabaseError, InterfaceError
from psycopg.types.json import Jsonb


logger = logging.getLogger(__name__)

# Config will be initialized in main
config: TableinatorConfig | None = None

# Progress tracking
message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
progress_interval = 100  # Log progress every 100 messages
last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}
current_task = None
current_progress = 0.0

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


# Simple connection pool implementation
class SimpleConnectionPool:
    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.connections: Queue[psycopg.Connection[Any]] = Queue(
            maxsize=max_connections
        )
        self.lock = threading.Lock()
        self._closed = False

    def _create_connection(self) -> psycopg.Connection[Any]:
        conn = psycopg.connect(**connection_params)
        conn.autocommit = True  # Enable autocommit for all operations
        return conn

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection[Any]]:
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        conn = None
        try:
            # Try to get existing connection
            try:
                conn = self.connections.get_nowait()
            except Exception:
                # Create new connection if none available
                conn = self._create_connection()

            # Test connection
            if conn.closed:
                conn = self._create_connection()

            yield conn

        except Exception:
            # Don't return broken connections to pool
            if conn and not conn.closed:
                with contextlib.suppress(Exception):
                    conn.rollback()
            raise
        finally:
            # Return connection to pool if it's still good
            if conn and not conn.closed and not self._closed:
                try:
                    self.connections.put_nowait(conn)
                except Exception:
                    # Pool is full, close connection
                    with contextlib.suppress(Exception):
                        conn.close()

    def close(self) -> None:
        self._closed = True
        while not self.connections.empty():
            try:
                conn = self.connections.get_nowait()
                conn.close()
            except Exception:
                break


# Create connection pool for concurrent access
connection_pool: SimpleConnectionPool | None = None

# Global shutdown flag
shutdown_requested = False


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


def get_db_connection() -> Any:
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


async def on_data_message(message: AbstractIncomingMessage) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        data: dict[str, Any] = loads(message.body)
        data_type: str = message.routing_key or "unknown"
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
            get_db_connection() as conn,
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
            logger.debug(f"💾 Updated {data_type[:-1]} ID={data_id} in PostgreSQL")

        await message.ack()

    except InterfaceError as e:
        logger.warning(f"⚠️ Database connection issue, will retry: {e}")
        await message.nack(requeue=True)
    except Exception as e:
        logger.error(f"❌ Failed to process {data_type} message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"⚠️ Failed to nack message: {nack_error}")


async def main() -> None:
    global connection_pool, config, connection_params

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("tableinator", log_file=Path("/logs/tableinator.log"))
    logger.info("🚀 Starting PostgreSQL tableinator service with connection pooling")

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

    # Initialize connection pool for concurrent access
    try:
        connection_pool = SimpleConnectionPool(max_connections=20)
        logger.info("✅ Connection pool initialized (max 20 connections)")
    except Exception as e:
        logger.error(f"❌ Failed to initialize connection pool: {e}")
        return

    # Initialize database tables
    try:
        with (
            get_db_connection() as conn,
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
    print("        ·▄▄▄▄  ▪  .▄▄ ·  ▄▄·        ▄▄ • .▄▄ ·           ")
    print("        ██▪ ██ ██ ▐█ ▀. ▐█ ▌▪▪     ▐█ ▀ ▪▐█ ▀.           ")
    print("        ▐█· ▐█▌▐█·▄▀▀▀█▄██ ▄▄ ▄█▀▄ ▄█ ▀█▄▄▀▀▀█▄          ")
    print("        ██. ██ ▐█▌▐█▄▪▐█▐███▌▐█▌.▐▌▐█▄▪▐█▐█▄▪▐█          ")
    print("        ▀▀▀▀▀• ▀▀▀ ▀▀▀▀ ·▀▀▀  ▀█▄▀▪·▀▀▀▀  ▀▀▀▀           ")
    print("▄▄▄▄▄ ▄▄▄· ▄▄▄▄· ▄▄▌  ▄▄▄ .▪   ▐ ▄  ▄▄▄· ▄▄▄▄▄      ▄▄▄  ")
    print("•██  ▐█ ▀█ ▐█ ▀█▪██•  ▀▄.▀·██ •█▌▐█▐█ ▀█ •██  ▪     ▀▄ █·")
    print(" ▐█.▪▄█▀▀█ ▐█▀▀█▄██▪  ▐▀▀▪▄▐█·▐█▐▐▌▄█▀▀█  ▐█.▪ ▄█▀▄ ▐▀▀▄ ")
    print(" ▐█▌·▐█ ▪▐▌██▄▪▐█▐█▌▐▌▐█▄▄▌▐█▌██▐█▌▐█ ▪▐▌ ▐█▌·▐█▌.▐▌▐█•█▌")
    print(" ▀▀▀  ▀  ▀ ·▀▀▀▀ .▀▀▀  ▀▀▀ ▀▀▀▀▀ █▪ ▀  ▀  ▀▀▀  ▀█▄▀▪.▀  ▀")
    print()

    try:
        amqp_connection = await connect(config.amqp_connection)
    except AMQPConnectionError as e:
        logger.error(f"❌ Failed to connect to AMQP broker: {e}")
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

        await artists_queue.consume(on_data_message)
        await labels_queue.consume(on_data_message)
        await masters_queue.consume(on_data_message)
        await releases_queue.consume(on_data_message)

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

                # Check for stalled consumers
                stalled_consumers = []
                for data_type, last_time in last_message_time.items():
                    if (
                        last_time > 0 and (current_time - last_time) > 120
                    ):  # No messages for 2 minutes
                        stalled_consumers.append(data_type)

                if stalled_consumers:
                    logger.error(
                        f"⚠️ Stalled consumers detected: {stalled_consumers}. "
                        f"No messages processed for >2 minutes."
                    )

                # Always show progress, even if no messages processed yet
                logger.info(
                    f"📊 PostgreSQL Progress: {total} total messages processed "
                    f"(Artists: {message_counts['artists']}, Labels: {message_counts['labels']}, "
                    f"Masters: {message_counts['masters']}, Releases: {message_counts['releases']})"
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
