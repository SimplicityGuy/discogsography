from asyncio import Future, run
from os import getenv

from aio_pika import connect
from aio_pika.abc import AbstractIncomingMessage
from psycopg2 import connect, sql
from psycopg2.extensions import register_adapter
from psycopg2.extras import Json

AMQP_CONNECTION = getenv("AMQP_CONNECTION")  # format: amqp://user:password@server:port
POSTGRES_ADDRESS = getenv("POSTGRES_ADDRESS")  # format: server
POSTGRES_USERNAME = getenv("POSTGRES_USERNAME")
POSTGRES_PASSWORD = getenv("POSTGRES_PASSWORD")
POSTGRES_DATABASE = getenv("POSTGRES_DATABASE")


database = connect(
    host=POSTGRES_ADDRESS,
    dbname=POSTGRES_DATABASE,
    user=POSTGRES_USERNAME,
    password=POSTGRES_PASSWORD,
)
register_adapter(dict, Json)


def on_data_message(message: AbstractIncomingMessage) -> None:
    data = message.body
    print(f" --: received message :-- ")
    data_type = message.routing_key
    data_id = data["id"]

    # If the old and new sha256 hashes match, no update/creation necessary.
    result = None
    with database.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT hash FROM {table} WHERE data_id = %s;").format(
                table=sql.Identifier(data_type)
            ),
            (data_id,),
        )
        result = cursor.fetchone()

    old_hash = -1 if result is None else result[0]
    new_hash = data["sha256"]

    if old_hash == new_hash:
        return

    with database.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "INSERT INTO {table} (hash, data_id, data) VALUES (%s, %s, %s) ON CONFLICT (data_id) DO UPDATE SET (hash, data_id, data) = (EXCLUDED.hash, EXCLUDED.data_id, EXCLUDED.data);"
            ).format(table=sql.Identifier(data_type)),
            (
                new_hash,
                data_id,
                data,
            ),
        )
    database.commit()


async def main():
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
    print(f" -=: Importing the most recent Discogs data into neo4j :=- ")

    amqp_connection = await connect(AMQP_CONNECTION)
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

        print(f" --: [⭐️] Waiting for messages. To exit press CTRL+C [⭐️] :-- ")

        await Future()


if __name__ == "__main__":
    run(main())
