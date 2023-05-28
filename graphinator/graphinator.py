from asyncio import Future, run
from os import getenv

from aio_pika import connect
from aio_pika.abc import AbstractIncomingMessage
from neo4j import GraphDatabase, basic_auth

AMQP_CONNECTION = getenv("AMQP_CONNECTION")  # format: amqp://user:password@server:port
NEO4J_ADDRESS = getenv("NEO4J_ADDRESS")  # format: bolt://server:port
NEO4J_USERNAME = getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = getenv("NEO4J_PASSWORD")

graph = GraphDatabase.driver(
    NEO4J_ADDRESS, auth=basic_auth(NEO4J_USERNAME, NEO4J_PASSWORD), encrypted=False
)


def on_artist_message(message: AbstractIncomingMessage) -> None:
    artist = message.body
    print(f" --: received message {artist} :-- ")

    # If the old and new sha256 hashes match, no update/creation necessary.
    with graph.session() as session:
        existing_artist_hashes = session.execute_read(
            "MATCH (a:Artist {id: $id}) return a['sha256']", artist
        )
        for existing_artist_hash in existing_artist_hashes:
            if existing_artist_hash == artist["sha256"]:
                return

    with graph.session() as session:
        resources = f"https://api.discogs.com/artists/{artist['id']}"
        releases = f"{resources}/releases"

        query = (
            "MERGE (a:Artist {id: $id}) "
            "ON CREATE SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url "
            "ON MATCH SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url"
        )
        session.run(query, artist, resource_url=resources, releases_url=releases)

        members = artist.get("members")
        if members is not None:
            query = "MATCH (a:Artist {id: $id}) MERGE (m_a:Artist {id: $m_id}) MERGE (m_a)-[:MEMBER_OF]->(a)"
            members = members["name"] if isinstance(members["name"], list) else [members["name"]]
            for member in members:
                session.run(query, artist, m_id=member["@id"])

        groups = artist.get("groups")
        if groups is not None:
            query = "MATCH (a:Artist {id: $id}) MERGE (g_a:Artist {id: $g_id}) MERGE (a)-[:MEMBER_OF]->(g_a)"
            groups = groups["name"] if isinstance(groups["name"], list) else [groups["name"]]
            for group in groups:
                session.run(query, artist, g_id=group["@id"])

        aliases = artist.get("aliases")
        if aliases is not None:
            query = "MATCH (a:Artist {id: $id}) MERGE (a_a:Artist {id: $a_id}) MERGE (a_a)-[:ALIAS_OF]->(a)"
            aliases = aliases["name"] if isinstance(aliases["name"], list) else [aliases["name"]]
            for alias in aliases:
                session.run(query, artist, a_id=alias["@id"])


def on_label_message(message: AbstractIncomingMessage) -> None:
    label = message.body
    print(f" --: received message {label} :-- ")

    # If the old and new sha256 hashes match, no update/creation necessary.
    with graph.session() as session:
        existing_label_hashes = session.execute_read(
            "MATCH (l:Label {id: $id}) return l['sha256']", label
        )
        for existing_label_hash in existing_label_hashes:
            if existing_label_hash == label["sha256"]:
                return

    with graph.session() as session:
        query = "MERGE (l:Label {id: $id}) ON CREATE SET l.name = $name ON MATCH SET l.name = $name"
        session.run(query, label)

        parent = label.get("parentLabel")
        if parent is not None:
            query = "MATCH (l:Label {id: $id}) MERGE (p_l:Label {id: $p_id}) MERGE (l)-[:SUBLABEL_OF]->(p_l)"
            session.run(query, label, p_id=parent["@id"])

        sublabels = label.get("sublabels")
        if sublabels is not None:
            query = "MATCH (l:Label {id: $id}) MERGE (s_l:Label {id: $s_id}) MERGE (s_l)-[:SUBLABEL_OF]->(l)"
            sublabels = (
                sublabels["label"] if isinstance(sublabels["label"], list) else [sublabels["label"]]
            )
            for sublabel in sublabels:
                session.run(query, label, s_id=sublabel["@id"])


def on_master_message(message: AbstractIncomingMessage) -> None:
    master = message.body
    print(f" --: received message {master} :-- ")

    # If the old and new sha256 hashes match, no update/creation necessary.
    with graph.session() as session:
        existing_master_hashes = session.execute_read(
            "MATCH (m:Master {id: $id}) return m['sha256']", master
        )
        for existing_master_hash in existing_master_hashes:
            if existing_master_hash == master["sha256"]:
                return

    with graph.session() as session:
        query = "MERGE (m:Master {id: $id}) ON CREATE SET m.title = $title, m.year = $year ON MATCH SET m.title = $title, m.year = $year"
        session.run(query, master)

        artists = master.get("artists")
        if artists is not None:
            query = "MATCH (m:Master {id: $id}),(a_m:Artist {id: $a_id}) MERGE (m)-[:BY]->(a_m)"
            artists = (
                artists["artist"] if isinstance(artists["artist"], list) else [artists["artist"]]
            )
            for artist in artists:
                session.run(query, master, a_id=artist["id"])

        genres = master.get("genres")
        if genres is not None:
            query = "MATCH (m:Master {id: $id}) MERGE (g:Genre {name: $name}) MERGE (m)-[:IS]->(g)"
            genres = genres["genre"] if isinstance(genres["genre"], list) else [genres["genre"]]
            for genre in genres:
                session.run(query, master, name=genre)

        styles = master.get("styles")
        if styles is not None:
            query = "MATCH (m:Master {id: $id}) MERGE (s:Style {name: $name}) MERGE (m)-[:IS]->(s)"
            styles = styles["style"] if isinstance(styles["style"], list) else [styles["style"]]
            for style in styles:
                session.run(query, master, name=style)

        if genres is not None and styles is not None:
            query = "MATCH (g:Genre {name: $g_name}),(s:Style {name: $s_name}) MERGE (s)-[:PART_OF]->(g)"
            for genre in genres:
                for style in styles:
                    session.run(query, g_name=genre, s_name=style)


def on_release_message(message: AbstractIncomingMessage) -> None:
    release = message.body
    print(f" --: received message {release} :-- ")

    # If the old and new sha256 hashes match, no update/creation necessary.
    with graph.session() as session:
        existing_release_hashes = session.execute_read(
            "MATCH (r:Release {id: $id}) return m['sha256']", release
        )
        for existing_release_hash in existing_release_hashes:
            if existing_release_hash == release["sha256"]:
                return

    with graph.session() as session:
        query = "MERGE (r:Release {id: $id}) ON CREATE SET r.title = $title ON MATCH SET r.title = $title"
        session.run(query, release)

        artists = release.get("artists")
        if artists is not None:
            query = "MATCH (r:Release {id: $id}),(a_r:Artist {id: $a_id}) MERGE (r)-[:BY]-(a_r)"
            artists = (
                artists["artist"] if isinstance(artists["artist"], list) else [artists["artist"]]
            )
            for artist in artists:
                session.run(query, release, a_id=artist["id"])

        labels = release.get("labels")
        if labels is not None:
            query = "MATCH (r:Release {id: $id}),(l_r:Label {id: $l_id}) MERGE (r)-[:ON]->(l_r)"
            labels = labels["label"] if isinstance(labels["label"], list) else [labels["label"]]
            for label in labels:
                session.run(query, release, l_id=label["@id"])

        master_id = release.get("master_id")
        if master_id is not None:
            query = "MATCH (r:Release {id: $id}),(m_r:Master {id: $m_id}) MERGE (r)-[:DERIVED_FROM]->(m_r)"
            session.run(query, release, m_id=master_id["#text"])

        genres = release.get("genres")
        if genres is not None:
            query = "MATCH (r:Release {id: $id}) MERGE (g:Genre {name: $name}) MERGE (r)-[:IS]->(g)"
            genres = genres["genre"] if isinstance(genres["genre"], list) else [genres["genre"]]
            for genre in genres:
                session.run(query, release, name=genre)

        styles = release.get("styles")
        if styles is not None:
            query = "MATCH (r:Release {id: $id}) MERGE (s:Style {name: $name}) MERGE (r)-[:IS]->(s)"
            styles = styles["style"] if isinstance(styles["style"], list) else [styles["style"]]
            for style in styles:
                session.run(query, release, name=style)

        if genres is not None and styles is not None:
            query = "MATCH (g:Genre {name: $g_name}),(s:Style {name: $s_name}) MERGE (s)-[:PART_OF]->(g)"
            for genre in genres:
                for style in styles:
                    session.run(query, g_name=genre, s_name=style)

        tracklist = release.get("tracklist")
        if tracklist is not None:
            query = (
                "MATCH (r:Release {id: $id}) "
                "MERGE (t:Track {id: $t_id, title: $t_title, position: $t_position}) "
                "MERGE (r)-[:CONTAINS]->(t) "
            )
            tracklist = (
                tracklist["track"] if isinstance(tracklist["track"], list) else [tracklist["track"]]
            )
            for n, track in enumerate(tracklist):
                t_position = track.get("position")
                if t_position is None:
                    t_position = f"<missing-{n}>"
                t_title = track.get("title")
                if t_title is None:
                    t_title = "<missing>"
                t_id = f"{release['id']}:{t_position}:{t_title}"
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
                    t_artists = (
                        t_artists["artist"]
                        if isinstance(t_artists["artist"], list)
                        else [t_artists["artist"]]
                    )
                    for t_artist in t_artists:
                        t_artist_role = t_artist.get("role")
                        if t_artist_role is not None:
                            t_artist_query = (
                                "MATCH (t:Track {id: $t_id}),(a_t:Artist {id: $a_id}) "
                                "MERGE (t)-[:BY {role: $a_role}]-(a_t)"
                            )
                            session.run(
                                t_artist_query, t_id=t_id, a_id=t_artist["id"], a_role=t_artist_role
                            )
                        else:
                            t_artist_query = (
                                "MATCH (t:Track {id: $t_id}),(a_t:Artist {id: $a_id}) "
                                "MERGE (t)-[:BY]-(a_t)"
                            )
                            session.run(t_artist_query, t_id=t_id, a_id=t_artist["id"])


async def main():
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
    print(f" -=: Importing the most recent Discogs data into neo4j :=- ")

    amqp_connection = await connect(AMQP_CONNECTION)
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

        print(f" --: [⭐️] Waiting for messages. To exit press CTRL+C [⭐️] :-- ")

        await Future()


if __name__ == "__main__":
    run(main())
