import asyncio
import contextlib
import logging
import signal
import time
from asyncio import run
from pathlib import Path
from typing import Any

from aio_pika import connect
from aio_pika.abc import AbstractIncomingMessage
from aio_pika.exceptions import AMQPConnectionError
from common import (
    AMQP_EXCHANGE,
    AMQP_EXCHANGE_TYPE,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    DATA_TYPES,
    GraphinatorConfig,
    HealthServer,
    setup_logging,
)
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError
from orjson import loads


logger = logging.getLogger(__name__)

# Suppress Neo4j notifications for missing labels/properties during initial setup
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# Config will be initialized in main
config: GraphinatorConfig | None = None

# Progress tracking
message_counts = {"artists": 0, "labels": 0, "masters": 0, "releases": 0}
progress_interval = 100  # Log progress every 100 messages
last_message_time = {"artists": 0.0, "labels": 0.0, "masters": 0.0, "releases": 0.0}
current_task = None
current_progress = 0.0

# Driver will be initialized in main
graph: Any = None

# Global shutdown flag
shutdown_requested = False


def get_health_data() -> dict[str, Any]:
    """Get current health data for monitoring."""
    from datetime import datetime

    return {
        "status": "healthy" if graph else "unhealthy",
        "service": "graphinator",
        "current_task": current_task,
        "progress": current_progress,
        "message_counts": message_counts.copy(),
        "last_message_time": last_message_time.copy(),
        "timestamp": datetime.now().isoformat(),
    }


def signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


def get_existing_hash(session: Any, node_type: str, node_id: str) -> str | None:
    """Get existing hash for a node to check if update is needed."""
    try:
        result = session.run(
            f"MATCH (n:{node_type} {{id: $id}}) RETURN n.sha256 AS hash", id=node_id
        )
        record = result.single()
        return record["hash"] if record else None
    except Exception as e:
        logger.warning(f"⚠️ Error checking existing hash for {node_type} {node_id}: {e}")
        return None


def safe_execute_query(session: Any, query: str, parameters: dict[str, Any]) -> bool:
    """Execute a Neo4j query with error handling."""
    try:
        session.run(query, parameters)
        return True
    except Neo4jError as e:
        logger.error(f"❌ Neo4j error executing query: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error executing query: {e}")
        return False


async def on_artist_message(message: AbstractIncomingMessage) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        logger.debug("📥 Received artist message")
        artist: dict[str, Any] = loads(message.body)
        artist_id = artist.get("id", "unknown")
        artist_name = artist.get("name", "Unknown Artist")

        # Increment counter and log progress
        message_counts["artists"] += 1
        last_message_time["artists"] = time.time()
        global current_task
        current_task = "Processing artists"
        if message_counts["artists"] % progress_interval == 0:
            logger.info(f"📊 Processed {message_counts['artists']} artists in Neo4j")

        logger.debug(f"🔄 Received artist message ID={artist_id}: {artist_name}")

        # Process entire artist in a single session with proper transaction handling
        try:
            logger.debug(f"🔄 Starting transaction for artist ID={artist_id}")
            # Add timeout to prevent hanging transactions
            with graph.session(database="neo4j") as session:

                def process_artist_tx(tx: Any) -> bool:
                    """Process artist within a single transaction for atomicity."""
                    # Check if update is needed by comparing hashes
                    existing_result = tx.run(
                        "MATCH (a:Artist {id: $id}) RETURN a.sha256 AS hash",
                        id=artist["id"],
                    )
                    existing_record = existing_result.single()
                    if existing_record and existing_record["hash"] == artist["sha256"]:
                        return False  # No update needed

                    # Create/update the main artist node
                    resources: str = f"https://api.discogs.com/artists/{artist['id']}"
                    releases: str = f"{resources}/releases"

                    tx.run(
                        "MERGE (a:Artist {id: $id}) "
                        "ON CREATE SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256 "
                        "ON MATCH SET a.name = $name, a.resource_url = $resource_url, a.releases_url = $releases_url, a.sha256 = $sha256",
                        id=artist["id"],
                        name=artist.get("name", "Unknown Artist"),
                        resource_url=resources,
                        releases_url=releases,
                        sha256=artist["sha256"],
                    )

                    # Process relationships in batches for better performance
                    # Handle members
                    members: dict[str, Any] | None = artist.get("members")
                    if members is not None:
                        members_list = (
                            members["name"]
                            if isinstance(members["name"], list)
                            else [members["name"]]
                        )
                        if members_list:
                            # Filter and log members without IDs
                            valid_members = []
                            for member in members_list:
                                member_id = member.get("@id") or member.get("id")
                                if member_id:
                                    valid_members.append({"id": member_id})
                                else:
                                    logger.warning(
                                        f"⚠️ Skipping member without ID in artist {artist['id']}: {member}"
                                    )

                            # Batch create member relationships
                            if valid_members:
                                tx.run(
                                    "UNWIND $members AS member "
                                    "MATCH (a:Artist {id: $artist_id}) "
                                    "MERGE (m_a:Artist {id: member.id}) "
                                    "MERGE (m_a)-[:MEMBER_OF]->(a)",
                                    members=valid_members,
                                    artist_id=artist["id"],
                                )

                    # Handle groups
                    groups: dict[str, Any] | None = artist.get("groups")
                    if groups is not None:
                        groups_list = (
                            groups["name"]
                            if isinstance(groups["name"], list)
                            else [groups["name"]]
                        )
                        if groups_list:
                            # Filter and log groups without IDs
                            valid_groups = []
                            for group in groups_list:
                                group_id = group.get("@id") or group.get("id")
                                if group_id:
                                    valid_groups.append({"id": group_id})
                                else:
                                    logger.warning(
                                        f"⚠️ Skipping group without ID in artist {artist['id']}: {group}"
                                    )

                            # Batch create group relationships
                            if valid_groups:
                                tx.run(
                                    "UNWIND $groups AS group "
                                    "MATCH (a:Artist {id: $artist_id}) "
                                    "MERGE (g_a:Artist {id: group.id}) "
                                    "MERGE (a)-[:MEMBER_OF]->(g_a)",
                                    groups=valid_groups,
                                    artist_id=artist["id"],
                                )

                    # Handle aliases
                    aliases: dict[str, Any] | None = artist.get("aliases")
                    if aliases is not None:
                        aliases_list = (
                            aliases["name"]
                            if isinstance(aliases["name"], list)
                            else [aliases["name"]]
                        )
                        if aliases_list:
                            # Filter and log aliases without IDs
                            valid_aliases = []
                            for alias in aliases_list:
                                alias_id = alias.get("@id") or alias.get("id")
                                if alias_id:
                                    valid_aliases.append({"id": alias_id})
                                else:
                                    logger.warning(
                                        f"⚠️ Skipping alias without ID in artist {artist['id']}: {alias}"
                                    )

                            # Batch create alias relationships
                            if valid_aliases:
                                tx.run(
                                    "UNWIND $aliases AS alias "
                                    "MATCH (a:Artist {id: $artist_id}) "
                                    "MERGE (a_a:Artist {id: alias.id}) "
                                    "MERGE (a_a)-[:ALIAS_OF]->(a)",
                                    aliases=valid_aliases,
                                    artist_id=artist["id"],
                                )

                    return True  # Updated successfully

                # Execute the transaction with explicit timeout
                logger.debug(f"🔄 Executing transaction for artist ID={artist_id}")
                # Session configuration is done at creation time
                updated = session.execute_write(process_artist_tx)
                logger.debug(f"✅ Transaction completed for artist ID={artist_id}")

                if updated:
                    logger.debug(f"💾 Updated artist ID={artist_id} in Neo4j")
                else:
                    logger.debug(
                        f"⏩ Skipped artist ID={artist_id} (no changes needed)"
                    )
        except Exception as neo4j_error:
            logger.error(
                f"❌ Neo4j error processing artist ID={artist_id}: {neo4j_error}"
            )
            raise

        logger.debug(f"✅ Acknowledging artist message ID={artist_id}")
        await message.ack()
        logger.debug(f"✅ Completed artist message ID={artist_id}")
    except Exception as e:
        logger.error(f"❌ Failed to process artist message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"⚠️ Failed to nack message: {nack_error}")


async def on_label_message(message: AbstractIncomingMessage) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        logger.debug("📥 Received label message")
        label: dict[str, Any] = loads(message.body)
        label_id = label.get("id", "unknown")
        label_name = label.get("name", "Unknown Label")

        # Increment counter and log progress
        message_counts["labels"] += 1
        last_message_time["labels"] = time.time()
        global current_task
        current_task = "Processing labels"
        if message_counts["labels"] % progress_interval == 0:
            logger.info(f"📊 Processed {message_counts['labels']} labels in Neo4j")

        logger.debug(f"🔄 Processing label ID={label_id}: {label_name}")

        # Process entire label in a single session with proper transaction handling
        with graph.session(database="neo4j") as session:

            def process_label_tx(tx: Any) -> bool:
                """Process label within a single transaction for atomicity."""
                # Check if update is needed by comparing hashes
                existing_result = tx.run(
                    "MATCH (l:Label {id: $id}) RETURN l.sha256 AS hash", id=label["id"]
                )
                existing_record = existing_result.single()
                if existing_record and existing_record["hash"] == label["sha256"]:
                    return False  # No update needed

                # Create/update the main label node
                tx.run(
                    "MERGE (l:Label {id: $id}) "
                    "ON CREATE SET l.name = $name, l.sha256 = $sha256 "
                    "ON MATCH SET l.name = $name, l.sha256 = $sha256",
                    id=label["id"],
                    name=label.get("name", "Unknown Label"),
                    sha256=label["sha256"],
                )

                # Handle parent label relationship
                parent: dict[str, Any] | None = label.get("parentLabel")
                if parent is not None:
                    parent_id = parent.get("@id") or parent.get("id")
                    if parent_id:
                        tx.run(
                            "MATCH (l:Label {id: $id}) "
                            "MERGE (p_l:Label {id: $p_id}) "
                            "MERGE (l)-[:SUBLABEL_OF]->(p_l)",
                            id=label["id"],
                            p_id=parent_id,
                        )
                    else:
                        logger.warning(
                            f"⚠️ Skipping parent label without ID in label {label['id']}: {parent}"
                        )

                # Handle sublabels in batch
                sublabels: dict[str, Any] | None = label.get("sublabels")
                if sublabels is not None:
                    sublabels_list = (
                        sublabels["label"]
                        if isinstance(sublabels["label"], list)
                        else [sublabels["label"]]
                    )
                    if sublabels_list:
                        # Filter and log sublabels without IDs
                        valid_sublabels = []
                        for sublabel in sublabels_list:
                            sublabel_id = sublabel.get("@id") or sublabel.get("id")
                            if sublabel_id:
                                valid_sublabels.append({"id": sublabel_id})
                            else:
                                logger.warning(
                                    f"⚠️ Skipping sublabel without ID in label {label['id']}: {sublabel}"
                                )

                        # Batch create sublabel relationships
                        if valid_sublabels:
                            tx.run(
                                "UNWIND $sublabels AS sublabel "
                                "MATCH (l:Label {id: $label_id}) "
                                "MERGE (s_l:Label {id: sublabel.id}) "
                                "MERGE (s_l)-[:SUBLABEL_OF]->(l)",
                                sublabels=valid_sublabels,
                                label_id=label["id"],
                            )

                return True  # Updated successfully

            # Execute the transaction with timeout
            # Session configuration is done at creation time
            updated = session.execute_write(process_label_tx)

            if updated:
                logger.debug(f"💾 Updated label ID={label_id} in Neo4j")
            else:
                logger.debug(f"⏩ Skipped label ID={label_id} (no changes needed)")

        await message.ack()
    except Exception as e:
        logger.error(f"❌ Failed to process label message: {e}")
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"⚠️ Failed to nack message: {nack_error}")


async def on_master_message(message: AbstractIncomingMessage) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        logger.debug("📥 Received master message")
        master: dict[str, Any] = loads(message.body)
        master_id = master.get("id", "unknown")
        master_title = master.get("title", "Unknown Master")

        # Increment counter and log progress
        message_counts["masters"] += 1
        last_message_time["masters"] = time.time()
        global current_task
        current_task = "Processing masters"
        if message_counts["masters"] % progress_interval == 0:
            logger.info(f"📊 Processed {message_counts['masters']} masters in Neo4j")

        logger.debug(f"🔄 Processing master ID={master_id}: {master_title}")

        # Process entire master in a single session with proper transaction handling
        with graph.session(database="neo4j") as session:

            def process_master_tx(tx: Any) -> bool:
                """Process master within a single transaction for atomicity."""
                # Check if update is needed by comparing hashes
                existing_result = tx.run(
                    "MATCH (m:Master {id: $id}) RETURN m.sha256 AS hash",
                    id=master["id"],
                )
                existing_record = existing_result.single()
                if existing_record and existing_record["hash"] == master["sha256"]:
                    return False  # No update needed

                # Create/update the main master node
                tx.run(
                    "MERGE (m:Master {id: $id}) "
                    "ON CREATE SET m.title = $title, m.year = $year, m.sha256 = $sha256 "
                    "ON MATCH SET m.title = $title, m.year = $year, m.sha256 = $sha256",
                    id=master["id"],
                    title=master.get("title", "Unknown Master"),
                    year=master.get("year", 0),
                    sha256=master["sha256"],
                )

                # Handle artist relationships in batch
                artists: dict[str, Any] | None = master.get("artists")
                if artists is not None:
                    artists_list = (
                        artists["artist"]
                        if isinstance(artists["artist"], list)
                        else [artists["artist"]]
                    )
                    if artists_list:
                        # Filter and log artists without IDs
                        valid_artists = []
                        for artist in artists_list:
                            artist_id = artist.get("id") or artist.get("@id")
                            if artist_id:
                                valid_artists.append({"id": artist_id})
                            else:
                                logger.warning(
                                    f"⚠️ Skipping artist without ID in master {master['id']}: {artist}"
                                )

                        if valid_artists:
                            tx.run(
                                "UNWIND $artists AS artist "
                                "MATCH (m:Master {id: $master_id}) "
                                "MERGE (a_m:Artist {id: artist.id}) "
                                "MERGE (m)-[:BY]->(a_m)",
                                artists=valid_artists,
                                master_id=master["id"],
                            )

                # Handle genres and styles
                genres: dict[str, Any] | None = master.get("genres")
                genres_list: list[str] = []
                if genres is not None:
                    genres_list = (
                        genres["genre"]
                        if isinstance(genres["genre"], list)
                        else [genres["genre"]]
                    )
                    if genres_list:
                        tx.run(
                            "UNWIND $genres AS genre "
                            "MATCH (m:Master {id: $master_id}) "
                            "MERGE (g:Genre {name: genre.name}) "
                            "MERGE (m)-[:IS]->(g)",
                            genres=[{"name": genre} for genre in genres_list],
                            master_id=master["id"],
                        )

                styles: dict[str, Any] | None = master.get("styles")
                styles_list: list[str] = []
                if styles is not None:
                    styles_list = (
                        styles["style"]
                        if isinstance(styles["style"], list)
                        else [styles["style"]]
                    )
                    if styles_list:
                        tx.run(
                            "UNWIND $styles AS style "
                            "MATCH (m:Master {id: $master_id}) "
                            "MERGE (s:Style {name: style.name}) "
                            "MERGE (m)-[:IS]->(s)",
                            styles=[{"name": style} for style in styles_list],
                            master_id=master["id"],
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

            # Execute the transaction with timeout
            # Session configuration is done at creation time
            updated = session.execute_write(process_master_tx)

            if updated:
                logger.debug(f"💾 Updated master ID={master_id} in Neo4j")
            else:
                logger.debug(f"⏩ Skipped master ID={master_id} (no changes needed)")

        await message.ack()
    except Exception as e:
        # Include more context in error message
        error_context = (
            f"master_id={master_id if 'master_id' in locals() else 'unknown'}"
        )
        error_type = type(e).__name__
        if error_type == "KeyError" and str(e) == "'id'":
            logger.error(
                f"❌ Failed to process master message ({error_context}): "
                f"Missing 'id' field in nested object. This typically occurs when artist objects "
                f"within the master don't have an 'id' field. Error: {error_type}: {e}"
            )
        else:
            logger.error(
                f"❌ Failed to process master message ({error_context}): {error_type}: {e}"
            )
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"⚠️ Failed to nack message: {nack_error}")


async def on_release_message(message: AbstractIncomingMessage) -> None:
    if shutdown_requested:
        logger.info("🛑 Shutdown requested, rejecting new messages")
        await message.nack(requeue=True)
        return

    try:
        logger.debug("📥 Received release message")
        release: dict[str, Any] = loads(message.body)
        release_id = release.get("id", "unknown")
        release_title = release.get("title", "Unknown Release")

        # Increment counter and log progress
        message_counts["releases"] += 1
        last_message_time["releases"] = time.time()
        global current_task
        current_task = "Processing releases"
        if message_counts["releases"] % progress_interval == 0:
            logger.info(f"📊 Processed {message_counts['releases']} releases in Neo4j")

        logger.debug(f"🔄 Processing release ID={release_id}: {release_title}")

        # Process entire release in a single session with proper transaction handling
        with graph.session(database="neo4j") as session:

            def process_release_tx(tx: Any) -> bool:
                """Process release within a single transaction for atomicity."""
                # Check if update is needed by comparing hashes
                existing_result = tx.run(
                    "MATCH (r:Release {id: $id}) RETURN r.sha256 AS hash",
                    id=release["id"],
                )
                existing_record = existing_result.single()
                if existing_record and existing_record["hash"] == release["sha256"]:
                    return False  # No update needed

                # Create/update the main release node
                tx.run(
                    "MERGE (r:Release {id: $id}) "
                    "ON CREATE SET r.title = $title, r.sha256 = $sha256 "
                    "ON MATCH SET r.title = $title, r.sha256 = $sha256",
                    id=release["id"],
                    title=release.get("title", "Unknown Release"),
                    sha256=release["sha256"],
                )

                # Handle artist relationships
                artists: dict[str, Any] | None = release.get("artists")
                if artists is not None:
                    artists_list = (
                        artists["artist"]
                        if isinstance(artists["artist"], list)
                        else [artists["artist"]]
                    )
                    if artists_list:
                        # Filter and log artists without IDs
                        valid_artists = []
                        for artist in artists_list:
                            artist_id = artist.get("id") or artist.get("@id")
                            if artist_id:
                                valid_artists.append({"id": artist_id})
                            else:
                                logger.warning(
                                    f"⚠️ Skipping artist without ID in release {release['id']}: {artist}"
                                )

                        # Use batch processing for better performance
                        if valid_artists:
                            tx.run(
                                "UNWIND $artists AS artist "
                                "MATCH (r:Release {id: $release_id}) "
                                "MERGE (a_r:Artist {id: artist.id}) "
                                "MERGE (r)-[:BY]-(a_r)",
                                artists=valid_artists,
                                release_id=release["id"],
                            )

                # Handle label relationships
                labels: dict[str, Any] | None = release.get("labels")
                if labels is not None:
                    labels_list = (
                        labels["label"]
                        if isinstance(labels["label"], list)
                        else [labels["label"]]
                    )
                    if labels_list:
                        # Filter and log labels without IDs
                        valid_labels = []
                        for label in labels_list:
                            label_id = label.get("@id") or label.get("id")
                            if label_id:
                                valid_labels.append({"id": label_id})
                            else:
                                logger.warning(
                                    f"⚠️ Skipping label without ID in release {release['id']}: {label}"
                                )

                        if valid_labels:
                            tx.run(
                                "UNWIND $labels AS label "
                                "MATCH (r:Release {id: $release_id}) "
                                "MERGE (l_r:Label {id: label.id}) "
                                "MERGE (r)-[:ON]->(l_r)",
                                labels=valid_labels,
                                release_id=release["id"],
                            )

                # Handle master relationship
                master_id: dict[str, Any] | None = release.get("master_id")
                if master_id is not None:
                    # master_id is typically a dict with "#text" containing the actual ID
                    m_id = (
                        master_id.get("#text")
                        if isinstance(master_id, dict)
                        else master_id
                    )
                    if m_id:
                        tx.run(
                            "MATCH (r:Release {id: $id}),(m_r:Master {id: $m_id}) "
                            "MERGE (r)-[:DERIVED_FROM]->(m_r)",
                            id=release["id"],
                            m_id=m_id,
                        )
                    else:
                        logger.warning(
                            f"⚠️ Skipping master relationship without valid ID in release {release['id']}: {master_id}"
                        )

                # Handle genres and styles in batch
                genres: dict[str, Any] | None = release.get("genres")
                genres_list: list[str] = []
                if genres is not None:
                    genres_list = (
                        genres["genre"]
                        if isinstance(genres["genre"], list)
                        else [genres["genre"]]
                    )
                    if genres_list:
                        tx.run(
                            "UNWIND $genres AS genre "
                            "MATCH (r:Release {id: $release_id}) "
                            "MERGE (g:Genre {name: genre.name}) "
                            "MERGE (r)-[:IS]->(g)",
                            genres=[{"name": genre} for genre in genres_list],
                            release_id=release["id"],
                        )

                styles: dict[str, Any] | None = release.get("styles")
                styles_list: list[str] = []
                if styles is not None:
                    styles_list = (
                        styles["style"]
                        if isinstance(styles["style"], list)
                        else [styles["style"]]
                    )
                    if styles_list:
                        tx.run(
                            "UNWIND $styles AS style "
                            "MATCH (r:Release {id: $release_id}) "
                            "MERGE (s:Style {name: style.name}) "
                            "MERGE (r)-[:IS]->(s)",
                            styles=[{"name": style} for style in styles_list],
                            release_id=release["id"],
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

                # Handle tracklist (simplified to avoid complex nested transactions)
                # Note: Skipping detailed track processing to avoid deadlocks
                # This can be re-added later if needed

                return True  # Updated successfully

            # Execute the transaction with timeout
            # Session configuration is done at creation time
            updated = session.execute_write(process_release_tx)

            if updated:
                logger.debug(f"💾 Updated release ID={release_id} in Neo4j")
            else:
                logger.debug(f"⏩ Skipped release ID={release_id} (no changes needed)")

        await message.ack()
        logger.debug(f"💾 Stored release ID={release_id} in Neo4j")
    except Exception as e:
        # Include more context in error message
        error_context = (
            f"release_id={release_id if 'release_id' in locals() else 'unknown'}"
        )
        error_type = type(e).__name__
        if error_type == "KeyError" and str(e) == "'id'":
            logger.error(
                f"❌ Failed to process release message ({error_context}): "
                f"Missing 'id' field in nested object. This typically occurs when artist/label objects "
                f"within the release don't have an 'id' field. Error: {error_type}: {e}"
            )
        else:
            logger.error(
                f"❌ Failed to process release message ({error_context}): {error_type}: {e}"
            )
        try:
            await message.nack(requeue=True)
        except Exception as nack_error:
            logger.warning(f"⚠️ Failed to nack message: {nack_error}")


async def main() -> None:
    global config, graph

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    setup_logging("graphinator", log_file=Path("/logs/graphinator.log"))
    logger.info("🚀 Starting Neo4j graphinator service")

    # Start health server
    health_server = HealthServer(8001, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8001")

    # Initialize configuration
    try:
        config = GraphinatorConfig.from_env()
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        return

    # Initialize Neo4j driver
    graph = GraphDatabase.driver(
        config.neo4j_address,
        auth=(config.neo4j_username, config.neo4j_password),
        encrypted=False,
        max_connection_lifetime=30 * 60,  # 30 minutes
        max_connection_pool_size=50,
        connection_acquisition_timeout=60.0,
    )

    # Test Neo4j connectivity
    try:
        with graph.session(database="neo4j") as session:
            result = session.run("RETURN 1 as test")
            result.single()
            logger.info("✅ Neo4j connectivity verified")

            # Create indexes for better performance
            logger.info("🔧 Creating Neo4j indexes...")
            constraints_to_create = [
                "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Artist) REQUIRE a.id IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Label) REQUIRE l.id IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Master) REQUIRE m.id IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Release) REQUIRE r.id IS UNIQUE",
            ]

            for constraint in constraints_to_create:
                try:
                    session.run(constraint)
                    logger.info(
                        f"✅ Created/verified constraint: {constraint.split('FOR')[1].split('REQUIRE')[0].strip()}"
                    )
                except Exception as constraint_error:
                    logger.warning(f"⚠️ Constraint creation note: {constraint_error}")

            logger.info("✅ Neo4j indexes setup complete")

    except Exception as e:
        logger.error(f"❌ Failed to connect to Neo4j: {e}")
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

    try:
        amqp_connection = await connect(config.amqp_connection)
    except AMQPConnectionError as e:
        logger.error(f"❌ Failed to connect to AMQP broker: {e}")
        return

    async with amqp_connection:
        channel = await amqp_connection.channel()

        # Set QoS to prevent overwhelming Neo4j with too many concurrent transactions
        # Reduce to minimal prefetch to force sequential processing and avoid deadlocks
        await channel.set_qos(prefetch_count=1, global_=True)

        # Declare the shared exchange (must match extractor)
        exchange = await channel.declare_exchange(
            AMQP_EXCHANGE, AMQP_EXCHANGE_TYPE, durable=True, auto_delete=False
        )

        # Declare queues for all data types and bind them to exchange
        queues = {}
        for data_type in DATA_TYPES:
            queue_name = f"{AMQP_QUEUE_PREFIX_GRAPHINATOR}-{data_type}"
            queue = await channel.declare_queue(
                auto_delete=False, durable=True, name=queue_name
            )
            await queue.bind(exchange, routing_key=data_type)
            queues[data_type] = queue

        # Map queues to their respective message handlers
        artists_queue = queues["artists"]
        labels_queue = queues["labels"]
        masters_queue = queues["masters"]
        releases_queue = queues["releases"]

        # Start consumers with consumer tags for better debugging
        await artists_queue.consume(
            on_artist_message, consumer_tag="graphinator-artists"
        )
        await labels_queue.consume(on_label_message, consumer_tag="graphinator-labels")
        await masters_queue.consume(
            on_master_message, consumer_tag="graphinator-masters"
        )
        await releases_queue.consume(
            on_release_message, consumer_tag="graphinator-releases"
        )

        logger.info(
            f"🚀 Graphinator started! Connected to AMQP broker (exchange: {AMQP_EXCHANGE}, type: {AMQP_EXCHANGE_TYPE}). "
            f"Consuming from {len(DATA_TYPES)} queues. "
            "Ready to process messages into Neo4j. Press CTRL+C to exit"
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

                # Check for stalled consumers and force reconnection if needed
                stalled_consumers = []
                for data_type, last_time in last_message_time.items():
                    if (
                        last_time > 0 and (current_time - last_time) > 120
                    ):  # No messages for 2 minutes
                        stalled_consumers.append(data_type)

                if stalled_consumers:
                    logger.error(
                        f"⚠️ Stalled consumers detected: {stalled_consumers}. "
                        f"No messages processed for >2 minutes. Forcing graph database reconnection."
                    )
                    # Close and recreate driver to force reconnection
                    try:
                        global graph
                        graph.close()
                        from neo4j import GraphDatabase

                        graph = GraphDatabase.driver(
                            config.neo4j_address,
                            auth=(config.neo4j_username, config.neo4j_password),
                            encrypted=False,
                            max_connection_lifetime=30 * 60,
                            max_connection_pool_size=50,
                            connection_acquisition_timeout=60.0,
                        )
                        logger.info("✅ Graph database driver reconnected")
                    except Exception as reconnect_error:
                        logger.error(
                            f"❌ Failed to reconnect graph database: {reconnect_error}"
                        )

                # Always show progress, even if no messages processed yet
                logger.info(
                    f"📊 Neo4j Progress: {total} total messages processed "
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

            # Close Neo4j driver
            try:
                graph.close()
                logger.info("✅ Neo4j driver closed")
            except Exception as e:
                logger.warning(f"⚠️ Error closing Neo4j driver: {e}")

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
        logger.info("✅ Graphinator service shutdown complete")
