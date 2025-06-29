import asyncio
import logging
from asyncio import run
from pathlib import Path
from typing import Any

from aio_pika import connect
from aio_pika.abc import AbstractIncomingMessage
from neo4j import GraphDatabase
from orjson import loads

from config import GraphinatorConfig, setup_logging


logger = logging.getLogger(__name__)

config = GraphinatorConfig.from_env()
graph = GraphDatabase.driver(
    config.neo4j_address, auth=(config.neo4j_username, config.neo4j_password), encrypted=False
)


async def on_artist_message(message: AbstractIncomingMessage) -> None:
    try:
        artist: dict[str, Any] = loads(message.body)
        artist_id = artist.get("id", "unknown")
        artist_name = artist.get("name", "Unknown Artist")
        logger.info(f"Processing artist ID={artist_id}: {artist_name}")

        # If the old and new sha256 hashes match, no update/creation necessary.
        with graph.session() as session:

            def get_artist_hash(tx: Any) -> list[str]:
                result = tx.run("MATCH (a:Artist {id: $id}) return a.sha256", id=artist["id"])
                return [record["a.sha256"] for record in result]

            existing_artist_hashes = session.execute_read(get_artist_hash)
            for existing_artist_hash in existing_artist_hashes:
                if existing_artist_hash == artist["sha256"]:
                    return

        with graph.session() as session:
            resources: str = f"https://api.discogs.com/artists/{artist['id']}"
            releases: str = f"{resources}/releases"

            query = (
                "MERGE (a:Artist {id: $id}) "
                "ON CREATE SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256 "
                "ON MATCH SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256"
            )
            session.run(query, artist, resource_url=resources, releases_url=releases)

            members: dict[str, Any] | None = artist.get("members")
            if members is not None:
                query = "MATCH (a:Artist {id: $id}) MERGE (m_a:Artist {id: $m_id}) MERGE (m_a)-[:MEMBER_OF]->(a)"
                members_list = (
                    members["name"] if isinstance(members["name"], list) else [members["name"]]
                )
                for member in members_list:
                    session.run(query, artist, m_id=member["@id"])

            groups: dict[str, Any] | None = artist.get("groups")
            if groups is not None:
                query = "MATCH (a:Artist {id: $id}) MERGE (g_a:Artist {id: $g_id}) MERGE (a)-[:MEMBER_OF]->(g_a)"
                groups_list = (
                    groups["name"] if isinstance(groups["name"], list) else [groups["name"]]
                )
                for group in groups_list:
                    session.run(query, artist, g_id=group["@id"])

            aliases: dict[str, Any] | None = artist.get("aliases")
            if aliases is not None:
                query = "MATCH (a:Artist {id: $id}) MERGE (a_a:Artist {id: $a_id}) MERGE (a_a)-[:ALIAS_OF]->(a)"
                aliases_list = (
                    aliases["name"] if isinstance(aliases["name"], list) else [aliases["name"]]
                )
                for alias in aliases_list:
                    session.run(query, artist, a_id=alias["@id"])
        await message.ack()
        logger.debug(f"Stored artist ID={artist_id} in Neo4j")
    except Exception as e:
        logger.error(f"Failed to process artist message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"Failed to nack message: {nack_error}")


async def on_label_message(message: AbstractIncomingMessage) -> None:
    try:
        label: dict[str, Any] = loads(message.body)
        label_id = label.get("id", "unknown")
        label_name = label.get("name", "Unknown Label")
        logger.info(f"Processing label ID={label_id}: {label_name}")

        # If the old and new sha256 hashes match, no update/creation necessary.
        with graph.session() as session:

            def get_label_hash(tx: Any) -> list[str]:
                result = tx.run("MATCH (l:Label {id: $id}) return l.sha256", id=label["id"])
                return [record["l.sha256"] for record in result]

            existing_label_hashes = session.execute_read(get_label_hash)
            for existing_label_hash in existing_label_hashes:
                if existing_label_hash == label["sha256"]:
                    return

        with graph.session() as session:
            query = "MERGE (l:Label {id: $id}) ON CREATE SET l.name = $name, l.sha256 = $sha256 ON MATCH SET l.name = $name, l.sha256 = $sha256"
            session.run(query, label)

            parent: dict[str, Any] | None = label.get("parentLabel")
            if parent is not None:
                query = "MATCH (l:Label {id: $id}) MERGE (p_l:Label {id: $p_id}) MERGE (l)-[:SUBLABEL_OF]->(p_l)"
                session.run(query, label, p_id=parent["@id"])

            sublabels: dict[str, Any] | None = label.get("sublabels")
            if sublabels is not None:
                query = "MATCH (l:Label {id: $id}) MERGE (s_l:Label {id: $s_id}) MERGE (s_l)-[:SUBLABEL_OF]->(l)"
                sublabels_list = (
                    sublabels["label"]
                    if isinstance(sublabels["label"], list)
                    else [sublabels["label"]]
                )
                for sublabel in sublabels_list:
                    session.run(query, label, s_id=sublabel["@id"])

        await message.ack()
        logger.debug(f"Stored label ID={label_id} in Neo4j")
    except Exception as e:
        logger.error(f"Failed to process label message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"Failed to nack message: {nack_error}")


async def on_master_message(message: AbstractIncomingMessage) -> None:
    try:
        master: dict[str, Any] = loads(message.body)
        master_id = master.get("id", "unknown")
        master_title = master.get("title", "Unknown Master")
        logger.info(f"Processing master ID={master_id}: {master_title}")

        # If the old and new sha256 hashes match, no update/creation necessary.
        with graph.session() as session:

            def get_master_hash(tx: Any) -> list[str]:
                result = tx.run("MATCH (m:Master {id: $id}) return m.sha256", id=master["id"])
                return [record["m.sha256"] for record in result]

            existing_master_hashes = session.execute_read(get_master_hash)
            for existing_master_hash in existing_master_hashes:
                if existing_master_hash == master["sha256"]:
                    return

        with graph.session() as session:
            query = "MERGE (m:Master {id: $id}) ON CREATE SET m.title = $title, m.year = $year, m.sha256 = $sha256 ON MATCH SET m.title = $title, m.year = $year, m.sha256 = $sha256"
            session.run(query, master)

            artists: dict[str, Any] | None = master.get("artists")
            if artists is not None:
                query = "MATCH (m:Master {id: $id}),(a_m:Artist {id: $a_id}) MERGE (m)-[:BY]->(a_m)"
                artists_list = (
                    artists["artist"]
                    if isinstance(artists["artist"], list)
                    else [artists["artist"]]
                )
                for artist in artists_list:
                    session.run(query, master, a_id=artist["id"])

            genres: dict[str, Any] | None = master.get("genres")
            genres_list: list[str] = []
            if genres is not None:
                query = (
                    "MATCH (m:Master {id: $id}) MERGE (g:Genre {name: $name}) MERGE (m)-[:IS]->(g)"
                )
                genres_list = (
                    genres["genre"] if isinstance(genres["genre"], list) else [genres["genre"]]
                )
                for genre in genres_list:
                    session.run(query, master, name=genre)

            styles: dict[str, Any] | None = master.get("styles")
            styles_list: list[str] = []
            if styles is not None:
                query = (
                    "MATCH (m:Master {id: $id}) MERGE (s:Style {name: $name}) MERGE (m)-[:IS]->(s)"
                )
                styles_list = (
                    styles["style"] if isinstance(styles["style"], list) else [styles["style"]]
                )
                for style in styles_list:
                    session.run(query, master, name=style)

            if genres_list and styles_list:
                query = "MATCH (g:Genre {name: $g_name}),(s:Style {name: $s_name}) MERGE (s)-[:PART_OF]->(g)"
                for genre in genres_list:
                    for style in styles_list:
                        session.run(query, g_name=genre, s_name=style)

        await message.ack()
        logger.debug(f"Stored master ID={master_id} in Neo4j")
    except Exception as e:
        logger.error(f"Failed to process master message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"Failed to nack message: {nack_error}")


async def on_release_message(message: AbstractIncomingMessage) -> None:
    try:
        release: dict[str, Any] = loads(message.body)
        release_id = release.get("id", "unknown")
        release_title = release.get("title", "Unknown Release")
        logger.info(f"Processing release ID={release_id}: {release_title}")

        # If the old and new sha256 hashes match, no update/creation necessary.
        with graph.session() as session:

            def get_release_hash(tx: Any) -> list[str]:
                result = tx.run("MATCH (r:Release {id: $id}) return r.sha256", id=release["id"])
                return [record["r.sha256"] for record in result]

            existing_release_hashes = session.execute_read(get_release_hash)
            for existing_release_hash in existing_release_hashes:
                if existing_release_hash == release["sha256"]:
                    return

        with graph.session() as session:
            query = "MERGE (r:Release {id: $id}) ON CREATE SET r.title = $title, r.sha256 = $sha256 ON MATCH SET r.title = $title, r.sha256 = $sha256"
            session.run(query, release)

            artists: dict[str, Any] | None = release.get("artists")
            if artists is not None:
                query = "MATCH (r:Release {id: $id}),(a_r:Artist {id: $a_id}) MERGE (r)-[:BY]-(a_r)"
                artists_list = (
                    artists["artist"]
                    if isinstance(artists["artist"], list)
                    else [artists["artist"]]
                )
                for artist in artists_list:
                    session.run(query, release, a_id=artist["id"])

            labels: dict[str, Any] | None = release.get("labels")
            if labels is not None:
                query = "MATCH (r:Release {id: $id}),(l_r:Label {id: $l_id}) MERGE (r)-[:ON]->(l_r)"
                labels_list = (
                    labels["label"] if isinstance(labels["label"], list) else [labels["label"]]
                )
                for label in labels_list:
                    session.run(query, release, l_id=label["@id"])

            master_id: dict[str, Any] | None = release.get("master_id")
            if master_id is not None:
                query = "MATCH (r:Release {id: $id}),(m_r:Master {id: $m_id}) MERGE (r)-[:DERIVED_FROM]->(m_r)"
                session.run(query, release, m_id=master_id["#text"])

            genres: dict[str, Any] | None = release.get("genres")
            genres_list: list[str] = []
            if genres is not None:
                query = (
                    "MATCH (r:Release {id: $id}) MERGE (g:Genre {name: $name}) MERGE (r)-[:IS]->(g)"
                )
                genres_list = (
                    genres["genre"] if isinstance(genres["genre"], list) else [genres["genre"]]
                )
                for genre in genres_list:
                    session.run(query, release, name=genre)

            styles: dict[str, Any] | None = release.get("styles")
            styles_list: list[str] = []
            if styles is not None:
                query = (
                    "MATCH (r:Release {id: $id}) MERGE (s:Style {name: $name}) MERGE (r)-[:IS]->(s)"
                )
                styles_list = (
                    styles["style"] if isinstance(styles["style"], list) else [styles["style"]]
                )
                for style in styles_list:
                    session.run(query, release, name=style)

            if genres_list and styles_list:
                query = "MATCH (g:Genre {name: $g_name}),(s:Style {name: $s_name}) MERGE (s)-[:PART_OF]->(g)"
                for genre in genres_list:
                    for style in styles_list:
                        session.run(query, g_name=genre, s_name=style)

            tracklist: dict[str, Any] | None = release.get("tracklist")
            if tracklist is not None:
                query = (
                    "MATCH (r:Release {id: $id}) "
                    "MERGE (t:Track {id: $t_id, title: $t_title, position: $t_position}) "
                    "MERGE (r)-[:CONTAINS]->(t) "
                )
                tracklist_list = (
                    tracklist["track"]
                    if isinstance(tracklist["track"], list)
                    else [tracklist["track"]]
                )
                for n, track in enumerate(tracklist_list):
                    t_position: str | None = track.get("position")
                    if t_position is None:
                        t_position = f"<missing-{n}>"
                    t_title: str | None = track.get("title")
                    if t_title is None:
                        t_title = "<missing>"
                    t_id: str = f"{release['id']}:{t_position}:{t_title}"
                    session.run(query, release, t_id=t_id, t_title=t_title, t_position=t_position)

                    artist_types = ["artists", "extraartists"]
                    for artist_type in artist_types:
                        t_artists = track.get(artist_type)

                        # NOTE: Pattern change here (e.g. 'is None' instead of 'is not None') to limit indentation for the 'is not None' case.
                        if t_artists is None:
                            continue

                        t_artist_query = (
                            "MATCH (t:Track {id: $t_id}),(a_t:Artist {id: $a_id}) "
                            "MERGE (t)-[:BY {role: $a_role}]-(a_t)"
                        )
                        t_artists_list = (
                            t_artists["artist"]
                            if isinstance(t_artists["artist"], list)
                            else [t_artists["artist"]]
                        )
                        for t_artist in t_artists_list:
                            t_artist_role = t_artist.get("role")
                            if t_artist_role is not None:
                                t_artist_query = (
                                    "MATCH (t:Track {id: $t_id}),(a_t:Artist {id: $a_id}) "
                                    "MERGE (t)-[:BY {role: $a_role}]-(a_t)"
                                )
                                session.run(
                                    t_artist_query,
                                    t_id=t_id,
                                    a_id=t_artist["id"],
                                    a_role=t_artist_role,
                                )
                            else:
                                t_artist_query = (
                                    "MATCH (t:Track {id: $t_id}),(a_t:Artist {id: $a_id}) "
                                    "MERGE (t)-[:BY]-(a_t)"
                                )
                                session.run(t_artist_query, t_id=t_id, a_id=t_artist["id"])

        await message.ack()
        logger.debug(f"Stored release ID={release_id} in Neo4j")
    except Exception as e:
        logger.error(f"Failed to process release message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"Failed to nack message: {nack_error}")


async def main() -> None:
    setup_logging("graphinator", log_file=Path("graphinator.log"))
    logger.info("Starting Neo4j graphinator service")
    print("        ·▄▄▄▄  ▪  .▄▄ ·  ▄▄·        ▄▄ • .▄▄ ·           ")
    print("        ██▪ ██ ██ ▐█ ▀. ▐█ ▌▪▪     ▐█ ▀ ▪▐█ ▀.           ")
    print("        ▐█· ▐█▌▐█·▄▀▀▀█▄██ ▄▄ ▄█▀▄ ▄█ ▀█▄▄▀▀▀█▄          ")
    print("        ██. ██ ▐█▌▐█▄▪▐█▐███▌▐█▌.▐▌▐█▄▪▐█▐█▄▪▐█          ")
    print("        ▀▀▀▀▀• ▀▀▀ ▀▀▀▀ ·▀▀▀  ▀█▄▀▪·▀▀▀▀  ▀▀▀▀           ")
    print(" ▄▄ • ▄▄▄   ▄▄▄·  ▄▄▄· ▄ .▄▪   ▐ ▄  ▄▄▄· ▄▄▄▄▄      ▄▄▄  ")
    print("▐█ ▀ ▪▀▄ █·▐█ ▀█ ▐█ ▄███▪▐███ •█▌▐█▐█ ▀█ •██  ▪     ▀▄ █·")
    print("▄█ ▀█▄▐▀▀▄ ▄█▀▀█  ██▀·██▀▐█▐█·▐█▐▐▌▄█▀▀█  ▐█.▪ ▄█▀▄ ▐▀▀▄ ")
    print("▐█▄▪▐█▐█•█▌▐█ ▪▐▌▐█▪·•██▌▐▀▐█▌██▐█▌▐█ ▪▐▌ ▐█▌·▐█▌.▐▌▐█•█▌")
    print("·▀▀▀▀ .▀  ▀ ▀  ▀ .▀   ▀▀▀ ·▀▀▀▀▀ █▪ ▀  ▀  ▀▀▀  ▀█▄▀▪.▀  ▀")
    print()

    amqp_connection = await connect(config.amqp_connection)
    async with amqp_connection:
        channel = await amqp_connection.channel()
        prefix = "discogsography-graphinator"

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

        await artists_queue.consume(on_artist_message)
        await labels_queue.consume(on_label_message)
        await masters_queue.consume(on_master_message)
        await releases_queue.consume(on_release_message)

        logger.info("Waiting for messages. Press CTRL+C to exit")

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down gracefully")


if __name__ == "__main__":
    run(main())
