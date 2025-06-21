import asyncio
import logging
from asyncio import run
from pathlib import Path
from typing import Any

import psycopg
from aio_pika import connect
from aio_pika.abc import AbstractIncomingMessage
from orjson import loads
from psycopg import sql
from psycopg.types.json import Jsonb

from config import TableinatorConfig, setup_logging

logger = logging.getLogger(__name__)

config = TableinatorConfig.from_env()
database: psycopg.Connection[Any] = psycopg.connect(
    host=config.postgres_address,
    dbname=config.postgres_database,
    user=config.postgres_username,
    password=config.postgres_password,
)


async def on_data_message(message: AbstractIncomingMessage) -> None:
    try:
        logger.debug(f"Processing {message.routing_key} message")
        data: dict[str, Any] = loads(message.body)
        data_type: str = message.routing_key
        data_id: str = data["id"]
    except Exception as e:
        logger.error(f"Failed to parse message: {e}")
        await message.nack(requeue=False)
        return

    # If the old and new sha256 hashes match, no update/creation necessary.
    try:
        result: tuple[str] | None = None
        with database.cursor() as cursor:
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

        with database.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {table} (hash, data_id, data) VALUES (%s, %s, %s) ON CONFLICT (data_id) DO UPDATE SET (hash, data_id, data) = (EXCLUDED.hash, EXCLUDED.data_id, EXCLUDED.data);"
                ).format(table=sql.Identifier(data_type)),
                (
                    new_hash,
                    data_id,
                    Jsonb(data),
                ),
            )
            database.commit()
        await message.ack()
    except Exception as e:
        logger.error(f"Failed to process {data_type} message: {e}")
        try:
            database.rollback()
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"Failed to rollback/nack message: {nack_error}")


async def main() -> None:
    setup_logging("tableinator", log_file=Path("tableinator.log"))
    logger.info("Starting PostgreSQL tableinator service")
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

    amqp_connection = await connect(config.amqp_connection)
    async with amqp_connection:
        channel = await amqp_connection.channel()
        prefix = "discogsography-tableinator"

        artists_queue = await channel.declare_queue(
            auto_delete=True, durable=True, name=f"{prefix}-artists"
        )
        labels_queue = await channel.declare_queue(
            auto_delete=True, durable=True, name=f"{prefix}-labels"
        )
        masters_queue = await channel.declare_queue(
            auto_delete=True, durable=True, name=f"{prefix}-masters"
        )
        releases_queue = await channel.declare_queue(
            auto_delete=True, durable=True, name=f"{prefix}-releases"
        )

        await artists_queue.consume(on_data_message)
        await labels_queue.consume(on_data_message)
        await masters_queue.consume(on_data_message)
        await releases_queue.consume(on_data_message)

        logger.info("Waiting for messages. Press CTRL+C to exit")

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down gracefully")


if __name__ == "__main__":
    run(main())
