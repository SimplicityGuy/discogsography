"""Batch processor for efficient Neo4j operations.

This module provides batch processing capabilities for Neo4j to improve
performance by reducing the number of database round trips.
"""

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import structlog
from common import normalize_record
from neo4j.exceptions import ServiceUnavailable, SessionExpired

logger = structlog.get_logger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 100  # Number of records per batch
    flush_interval: float = 5.0  # Seconds before force flush
    max_pending: int = 1000  # Maximum pending records before blocking


@dataclass
class PendingMessage:
    """A message pending batch processing."""

    data_type: str
    data: dict[str, Any]
    ack_callback: Callable[[], Any]
    nack_callback: Callable[[], Any]
    received_at: float = field(default_factory=time.time)


class Neo4jBatchProcessor:
    """Batches Neo4j operations for improved performance.

    Instead of processing each message individually, this class accumulates
    messages and processes them in batches, significantly reducing the
    overhead of Neo4j transactions.
    """

    def __init__(self, driver: Any, config: BatchConfig | None = None):
        """Initialize the batch processor.

        Args:
            driver: Neo4j driver instance
            config: Batch processing configuration
        """
        self.driver = driver  # AsyncResilientNeo4jDriver
        self.config = config or BatchConfig()

        # Separate queues for each data type
        self.queues: dict[str, deque[PendingMessage]] = {
            "artists": deque(),
            "labels": deque(),
            "masters": deque(),
            "releases": deque(),
        }

        # Processing stats
        self.processed_counts: dict[str, int] = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        self.batch_counts: dict[str, int] = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }
        self.last_flush: dict[str, float] = {
            "artists": time.time(),
            "labels": time.time(),
            "masters": time.time(),
            "releases": time.time(),
        }

        # Shutdown flag
        self._shutdown = False

        # Load batch size from environment
        env_batch_size = os.environ.get("NEO4J_BATCH_SIZE")
        if env_batch_size:
            try:
                self.config.batch_size = int(env_batch_size)
                logger.info(
                    "🔧 Using batch size from environment",
                    batch_size=self.config.batch_size,
                )
            except ValueError:
                logger.warning(
                    "⚠️ Invalid NEO4J_BATCH_SIZE, using default",
                    value=env_batch_size,
                    default=self.config.batch_size,
                )

    async def add_message(
        self,
        data_type: str,
        data: dict[str, Any],
        ack_callback: Callable[[], Any],
        nack_callback: Callable[[], Any],
    ) -> None:
        """Add a message to the batch queue.

        Args:
            data_type: Type of data (artists, labels, masters, releases)
            data: The parsed message data
            ack_callback: Callback to acknowledge the message
            nack_callback: Callback to negative-acknowledge the message
        """
        queue = self.queues.get(data_type)
        if queue is None:
            logger.error("❌ Unknown data type", data_type=data_type)
            await nack_callback()
            return

        # Normalize the data
        try:
            normalized_data = normalize_record(data_type, data)
        except Exception as e:
            logger.error(
                "❌ Failed to normalize data",
                data_type=data_type,
                error=str(e),
            )
            await nack_callback()
            return

        # Add to queue
        queue.append(
            PendingMessage(
                data_type=data_type,
                data=normalized_data,
                ack_callback=ack_callback,
                nack_callback=nack_callback,
            )
        )

        # Check if we should flush
        if len(queue) >= self.config.batch_size:
            await self._flush_queue(data_type)
        elif time.time() - self.last_flush[data_type] >= self.config.flush_interval:
            await self._flush_queue(data_type)

    async def _flush_queue(self, data_type: str) -> None:
        """Flush a queue by processing all pending messages.

        Args:
            data_type: The data type queue to flush
        """
        queue = self.queues[data_type]
        if not queue:
            return

        # Get all messages from queue
        messages: list[PendingMessage] = []
        while queue and len(messages) < self.config.batch_size:
            messages.append(queue.popleft())

        if not messages:
            return

        batch_start = time.time()
        success = False

        try:
            # Process batch based on data type
            if data_type == "artists":
                await self._process_artists_batch(messages)
            elif data_type == "labels":
                await self._process_labels_batch(messages)
            elif data_type == "masters":
                await self._process_masters_batch(messages)
            elif data_type == "releases":
                await self._process_releases_batch(messages)

            success = True

        except (ServiceUnavailable, SessionExpired) as e:
            logger.error(
                "❌ Neo4j connection error during batch",
                data_type=data_type,
                batch_size=len(messages),
                error=str(e),
            )
            # Put messages back for retry
            for msg in reversed(messages):
                queue.appendleft(msg)
        except Exception as e:
            logger.error(
                "❌ Batch processing error",
                data_type=data_type,
                batch_size=len(messages),
                error=str(e),
            )

        batch_duration = time.time() - batch_start

        if success:
            # Acknowledge all messages
            for msg in messages:
                try:
                    await msg.ack_callback()
                except Exception as e:
                    logger.warning("⚠️ Failed to ack message", error=str(e))

            self.processed_counts[data_type] += len(messages)
            self.batch_counts[data_type] += 1
            self.last_flush[data_type] = time.time()

            logger.info(
                "✅ Batch processed",
                data_type=data_type,
                batch_size=len(messages),
                duration_ms=round(batch_duration * 1000),
                records_per_sec=round(len(messages) / batch_duration)
                if batch_duration > 0
                else 0,
                total_processed=self.processed_counts[data_type],
            )
        else:
            # Nack all messages for retry
            for msg in messages:
                try:
                    await msg.nack_callback()
                except Exception as e:
                    logger.warning("⚠️ Failed to nack message", error=str(e))

    async def _process_artists_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of artist records.

        Uses a single transaction for all artists in the batch.
        """

        def _process_sync() -> None:
            """Synchronous processing logic to run in thread pool."""
            # Separate artists that need updates from those that don't
            artists_to_process = []
            existing_hashes: dict[str, str] = {}

            # First, check which artists need updates (by hash)
            with self.driver.session(database="neo4j") as session:
                # Get all IDs and their hashes
                ids = [msg.data.get("id") for msg in messages if msg.data.get("id")]
                if ids:
                    result = session.run(
                        "UNWIND $ids AS id "
                        "OPTIONAL MATCH (a:Artist {id: id}) "
                        "RETURN id, a.sha256 AS hash",
                        ids=ids,
                    )
                    for record in result:
                        if record["hash"]:
                            existing_hashes[record["id"]] = record["hash"]

            # Filter artists that need processing
            for msg in messages:
                artist_id = msg.data.get("id")
                artist_hash = msg.data.get("sha256")
                if artist_id and existing_hashes.get(artist_id) != artist_hash:
                    artists_to_process.append(msg.data)

            if not artists_to_process:
                logger.debug("⏩ All artists in batch already up to date")
                return

            # Process artists in a single transaction
            with self.driver.session(database="neo4j") as session:

                def batch_write(tx: Any) -> None:
                    # Create/update all artist nodes
                    tx.run(
                        """
                        UNWIND $artists AS artist
                        MERGE (a:Artist {id: artist.id})
                        SET a.name = artist.name,
                            a.sha256 = artist.sha256,
                            a.resource_url = 'https://api.discogs.com/artists/' + artist.id,
                            a.releases_url = 'https://api.discogs.com/artists/' + artist.id + '/releases'
                        """,
                        artists=artists_to_process,
                    )

                    # Process all member relationships
                    members_data = []
                    for artist in artists_to_process:
                        if artist.get("members"):
                            for member in artist["members"]:
                                if member.get("id"):
                                    members_data.append(
                                        {
                                            "artist_id": artist["id"],
                                            "member_id": member["id"],
                                        }
                                    )
                    if members_data:
                        tx.run(
                            """
                            UNWIND $members AS rel
                            MATCH (a:Artist {id: rel.artist_id})
                            MERGE (m:Artist {id: rel.member_id})
                            MERGE (m)-[:MEMBER_OF]->(a)
                            """,
                            members=members_data,
                        )

                    # Process all group relationships
                    groups_data = []
                    for artist in artists_to_process:
                        if artist.get("groups"):
                            for group in artist["groups"]:
                                if group.get("id"):
                                    groups_data.append(
                                        {
                                            "artist_id": artist["id"],
                                            "group_id": group["id"],
                                        }
                                    )
                    if groups_data:
                        tx.run(
                            """
                            UNWIND $groups AS rel
                            MATCH (a:Artist {id: rel.artist_id})
                            MERGE (g:Artist {id: rel.group_id})
                            MERGE (a)-[:MEMBER_OF]->(g)
                            """,
                            groups=groups_data,
                        )

                    # Process all alias relationships
                    aliases_data = []
                    for artist in artists_to_process:
                        if artist.get("aliases"):
                            for alias in artist["aliases"]:
                                if alias.get("id"):
                                    aliases_data.append(
                                        {
                                            "artist_id": artist["id"],
                                            "alias_id": alias["id"],
                                        }
                                    )
                    if aliases_data:
                        tx.run(
                            """
                            UNWIND $aliases AS rel
                            MATCH (a:Artist {id: rel.artist_id})
                            MERGE (al:Artist {id: rel.alias_id})
                            MERGE (al)-[:ALIAS_OF]->(a)
                            """,
                            aliases=aliases_data,
                        )

                session.execute_write(batch_write)

        # Run the synchronous processing in a thread pool
        await asyncio.to_thread(_process_sync)

    async def _process_labels_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of label records."""

        def _process_sync() -> None:
            """Synchronous processing logic to run in thread pool."""
            labels_to_process = []
            existing_hashes: dict[str, str] = {}

            with self.driver.session(database="neo4j") as session:
                ids = [msg.data.get("id") for msg in messages if msg.data.get("id")]
                if ids:
                    result = session.run(
                        "UNWIND $ids AS id "
                        "OPTIONAL MATCH (l:Label {id: id}) "
                        "RETURN id, l.sha256 AS hash",
                        ids=ids,
                    )
                    for record in result:
                        if record["hash"]:
                            existing_hashes[record["id"]] = record["hash"]

            for msg in messages:
                label_id = msg.data.get("id")
                label_hash = msg.data.get("sha256")
                if label_id and existing_hashes.get(label_id) != label_hash:
                    labels_to_process.append(msg.data)

            if not labels_to_process:
                logger.debug("⏩ All labels in batch already up to date")
                return

            with self.driver.session(database="neo4j") as session:

                def batch_write(tx: Any) -> None:
                    # Create/update all label nodes
                    tx.run(
                        """
                        UNWIND $labels AS label
                        MERGE (l:Label {id: label.id})
                        SET l.name = label.name,
                            l.sha256 = label.sha256
                        """,
                        labels=labels_to_process,
                    )

                    # Process parent label relationships
                    parent_data = []
                    for label in labels_to_process:
                        parent = label.get("parentLabel")
                        if parent and parent.get("id"):
                            parent_data.append(
                                {
                                    "label_id": label["id"],
                                    "parent_id": parent["id"],
                                }
                            )
                    if parent_data:
                        tx.run(
                            """
                            UNWIND $parents AS rel
                            MATCH (l:Label {id: rel.label_id})
                            MERGE (p:Label {id: rel.parent_id})
                            MERGE (l)-[:SUBLABEL_OF]->(p)
                            """,
                            parents=parent_data,
                        )

                    # Process sublabel relationships
                    sublabel_data = []
                    for label in labels_to_process:
                        if label.get("sublabels"):
                            for sublabel in label["sublabels"]:
                                if sublabel.get("id"):
                                    sublabel_data.append(
                                        {
                                            "label_id": label["id"],
                                            "sublabel_id": sublabel["id"],
                                        }
                                    )
                    if sublabel_data:
                        tx.run(
                            """
                            UNWIND $sublabels AS rel
                            MATCH (l:Label {id: rel.label_id})
                            MERGE (s:Label {id: rel.sublabel_id})
                            MERGE (s)-[:SUBLABEL_OF]->(l)
                            """,
                            sublabels=sublabel_data,
                        )

                session.execute_write(batch_write)

        # Run the synchronous processing in a thread pool
        await asyncio.to_thread(_process_sync)

    async def _process_masters_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of master records."""

        def _process_sync() -> None:
            """Synchronous processing logic to run in thread pool."""
            masters_to_process = []
            existing_hashes: dict[str, str] = {}

            with self.driver.session(database="neo4j") as session:
                ids = [msg.data.get("id") for msg in messages if msg.data.get("id")]
                if ids:
                    result = session.run(
                        "UNWIND $ids AS id "
                        "OPTIONAL MATCH (m:Master {id: id}) "
                        "RETURN id, m.sha256 AS hash",
                        ids=ids,
                    )
                    for record in result:
                        if record["hash"]:
                            existing_hashes[record["id"]] = record["hash"]

            for msg in messages:
                master_id = msg.data.get("id")
                master_hash = msg.data.get("sha256")
                if master_id and existing_hashes.get(master_id) != master_hash:
                    masters_to_process.append(msg.data)

            if not masters_to_process:
                logger.debug("⏩ All masters in batch already up to date")
                return

            with self.driver.session(database="neo4j") as session:

                def batch_write(tx: Any) -> None:
                    # Create/update all master nodes
                    tx.run(
                        """
                        UNWIND $masters AS master
                        MERGE (m:Master {id: master.id})
                        SET m.title = master.title,
                            m.year = master.year,
                            m.sha256 = master.sha256
                        """,
                        masters=masters_to_process,
                    )

                    # Process artist relationships
                    artist_data = []
                    for master in masters_to_process:
                        if master.get("artists"):
                            for artist in master["artists"]:
                                if artist.get("id"):
                                    artist_data.append(
                                        {
                                            "master_id": master["id"],
                                            "artist_id": artist["id"],
                                        }
                                    )
                    if artist_data:
                        tx.run(
                            """
                            UNWIND $artists AS rel
                            MATCH (m:Master {id: rel.master_id})
                            MERGE (a:Artist {id: rel.artist_id})
                            MERGE (m)-[:BY]->(a)
                            """,
                            artists=artist_data,
                        )

                    # Process genre relationships
                    genre_data = []
                    for master in masters_to_process:
                        if master.get("genres"):
                            for genre in master["genres"]:
                                if genre:
                                    genre_data.append(
                                        {
                                            "master_id": master["id"],
                                            "genre": genre,
                                        }
                                    )
                    if genre_data:
                        tx.run(
                            """
                            UNWIND $genres AS rel
                            MATCH (m:Master {id: rel.master_id})
                            MERGE (g:Genre {name: rel.genre})
                            MERGE (m)-[:IS]->(g)
                            """,
                            genres=genre_data,
                        )

                    # Process style relationships
                    style_data = []
                    for master in masters_to_process:
                        if master.get("styles"):
                            for style in master["styles"]:
                                if style:
                                    style_data.append(
                                        {
                                            "master_id": master["id"],
                                            "style": style,
                                        }
                                    )
                    if style_data:
                        tx.run(
                            """
                            UNWIND $styles AS rel
                            MATCH (m:Master {id: rel.master_id})
                            MERGE (s:Style {name: rel.style})
                            MERGE (m)-[:IS]->(s)
                            """,
                            styles=style_data,
                        )

                    # Connect styles to genres
                    genre_style_data = []
                    for master in masters_to_process:
                        genres = master.get("genres", [])
                        styles = master.get("styles", [])
                        for genre in genres:
                            for style in styles:
                                if genre and style:
                                    genre_style_data.append(
                                        {
                                            "genre": genre,
                                            "style": style,
                                        }
                                    )
                    if genre_style_data:
                        tx.run(
                            """
                            UNWIND $pairs AS pair
                            MERGE (g:Genre {name: pair.genre})
                            MERGE (s:Style {name: pair.style})
                            MERGE (s)-[:PART_OF]->(g)
                            """,
                            pairs=genre_style_data,
                        )

                session.execute_write(batch_write)

        # Run the synchronous processing in a thread pool
        await asyncio.to_thread(_process_sync)

    async def _process_releases_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of release records."""

        def _process_sync() -> None:
            """Synchronous processing logic to run in thread pool."""
            releases_to_process = []
            existing_hashes: dict[str, str] = {}

            with self.driver.session(database="neo4j") as session:
                ids = [msg.data.get("id") for msg in messages if msg.data.get("id")]
                if ids:
                    result = session.run(
                        "UNWIND $ids AS id "
                        "OPTIONAL MATCH (r:Release {id: id}) "
                        "RETURN id, r.sha256 AS hash",
                        ids=ids,
                    )
                    for record in result:
                        if record["hash"]:
                            existing_hashes[record["id"]] = record["hash"]

            for msg in messages:
                release_id = msg.data.get("id")
                release_hash = msg.data.get("sha256")
                if release_id and existing_hashes.get(release_id) != release_hash:
                    releases_to_process.append(msg.data)

            if not releases_to_process:
                logger.debug("⏩ All releases in batch already up to date")
                return

            with self.driver.session(database="neo4j") as session:

                def batch_write(tx: Any) -> None:
                    # Create/update all release nodes
                    tx.run(
                        """
                        UNWIND $releases AS release
                        MERGE (r:Release {id: release.id})
                        SET r.title = release.title,
                            r.sha256 = release.sha256
                        """,
                        releases=releases_to_process,
                    )

                    # Process artist relationships (Release)-[:BY]->(Artist)
                    artist_data = []
                    for release in releases_to_process:
                        if release.get("artists"):
                            for artist in release["artists"]:
                                if artist.get("id"):
                                    artist_data.append(
                                        {
                                            "release_id": release["id"],
                                            "artist_id": artist["id"],
                                        }
                                    )
                    if artist_data:
                        tx.run(
                            """
                            UNWIND $artists AS rel
                            MATCH (r:Release {id: rel.release_id})
                            MERGE (a:Artist {id: rel.artist_id})
                            MERGE (r)-[:BY]->(a)
                            """,
                            artists=artist_data,
                        )

                    # Process label relationships (Release)-[:ON]->(Label)
                    label_data = []
                    for release in releases_to_process:
                        if release.get("labels"):
                            for label in release["labels"]:
                                if label.get("id"):
                                    label_data.append(
                                        {
                                            "release_id": release["id"],
                                            "label_id": label["id"],
                                        }
                                    )
                    if label_data:
                        tx.run(
                            """
                            UNWIND $labels AS rel
                            MATCH (r:Release {id: rel.release_id})
                            MERGE (l:Label {id: rel.label_id})
                            MERGE (r)-[:ON]->(l)
                            """,
                            labels=label_data,
                        )

                    # Process master relationships (Release)-[:DERIVED_FROM]->(Master)
                    master_data = []
                    for release in releases_to_process:
                        master_id = release.get("master_id")
                        if master_id:
                            master_data.append(
                                {
                                    "release_id": release["id"],
                                    "master_id": str(master_id),
                                }
                            )
                    if master_data:
                        tx.run(
                            """
                            UNWIND $masters AS rel
                            MATCH (r:Release {id: rel.release_id})
                            MERGE (m:Master {id: rel.master_id})
                            MERGE (r)-[:DERIVED_FROM]->(m)
                            """,
                            masters=master_data,
                        )

                    # Process genre relationships
                    genre_data = []
                    for release in releases_to_process:
                        if release.get("genres"):
                            for genre in release["genres"]:
                                if genre:
                                    genre_data.append(
                                        {
                                            "release_id": release["id"],
                                            "genre": genre,
                                        }
                                    )
                    if genre_data:
                        tx.run(
                            """
                            UNWIND $genres AS rel
                            MATCH (r:Release {id: rel.release_id})
                            MERGE (g:Genre {name: rel.genre})
                            MERGE (r)-[:IS]->(g)
                            """,
                            genres=genre_data,
                        )

                    # Process style relationships
                    style_data = []
                    for release in releases_to_process:
                        if release.get("styles"):
                            for style in release["styles"]:
                                if style:
                                    style_data.append(
                                        {
                                            "release_id": release["id"],
                                            "style": style,
                                        }
                                    )
                    if style_data:
                        tx.run(
                            """
                            UNWIND $styles AS rel
                            MATCH (r:Release {id: rel.release_id})
                            MERGE (s:Style {name: rel.style})
                            MERGE (r)-[:IS]->(s)
                            """,
                            styles=style_data,
                        )

                    # Connect styles to genres
                    genre_style_data = []
                    for release in releases_to_process:
                        genres = release.get("genres", [])
                        styles = release.get("styles", [])
                        for genre in genres:
                            for style in styles:
                                if genre and style:
                                    genre_style_data.append(
                                        {
                                            "genre": genre,
                                            "style": style,
                                        }
                                    )
                    if genre_style_data:
                        tx.run(
                            """
                            UNWIND $pairs AS pair
                            MERGE (g:Genre {name: pair.genre})
                            MERGE (s:Style {name: pair.style})
                            MERGE (s)-[:PART_OF]->(g)
                            """,
                            pairs=genre_style_data,
                        )

                session.execute_write(batch_write)

        # Run the synchronous processing in a thread pool
        await asyncio.to_thread(_process_sync)

    async def flush_all(self) -> None:
        """Flush all pending queues."""
        for data_type in self.queues:
            await self._flush_queue(data_type)

    async def periodic_flush(self) -> None:
        """Background task that periodically flushes queues.

        This ensures messages don't sit in the queue too long
        when message rate is low.
        """
        while not self._shutdown:
            await asyncio.sleep(self.config.flush_interval)

            for data_type, queue in self.queues.items():
                if (
                    queue
                    and time.time() - self.last_flush[data_type]
                    >= self.config.flush_interval
                ):
                    await self._flush_queue(data_type)

    def shutdown(self) -> None:
        """Signal shutdown to stop periodic tasks."""
        self._shutdown = True

    def get_stats(self) -> dict[str, Any]:
        """Get processing statistics."""
        return {
            "processed": self.processed_counts.copy(),
            "batches": self.batch_counts.copy(),
            "pending": {k: len(v) for k, v in self.queues.items()},
        }
