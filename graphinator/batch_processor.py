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
from common.credit_roles import categorize_role
from common.data_normalizer import extract_format_names
from neo4j.exceptions import ServiceUnavailable, SessionExpired

logger = structlog.get_logger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 100  # Number of records per batch
    flush_interval: float = 5.0  # Seconds before force flush
    max_pending: int = 1000  # Maximum pending records before blocking
    max_concurrent_flushes: int = 2  # Max simultaneous Neo4j flush operations
    min_batch_size: int = 10  # Floor for adaptive batch sizing
    backoff_initial: float = 1.0  # Initial backoff delay on Neo4j errors (seconds)
    backoff_max: float = 30.0  # Maximum backoff delay (seconds)
    backoff_multiplier: float = 2.0  # Exponential backoff multiplier
    max_flush_retries: int = 5  # Max retries per data type during flush_queue drain


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

        # Concurrency limiter — prevents all 4 data types from flushing
        # simultaneously and exhausting the Neo4j connection pool
        self._flush_semaphore = asyncio.Semaphore(self.config.max_concurrent_flushes)

        # Adaptive batch sizing — reduces under Neo4j pressure, recovers on success
        # Per-data-type so pressure on one type doesn't affect others
        self._effective_batch_size: dict[str, int] = {
            "artists": self.config.batch_size,
            "labels": self.config.batch_size,
            "masters": self.config.batch_size,
            "releases": self.config.batch_size,
        }
        self._consecutive_failures: dict[str, int] = {
            "artists": 0,
            "labels": 0,
            "masters": 0,
            "releases": 0,
        }

        # Backoff state — delay between retries when Neo4j is struggling
        self._backoff_until: dict[str, float] = {
            "artists": 0.0,
            "labels": 0.0,
            "masters": 0.0,
            "releases": 0.0,
        }

        # Load batch size from environment
        env_batch_size = os.environ.get("NEO4J_BATCH_SIZE")
        if env_batch_size:
            try:
                self.config.batch_size = int(env_batch_size)
                for dt in self._effective_batch_size:
                    self._effective_batch_size[dt] = self.config.batch_size
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

        # Check if we should flush (use adaptive batch size)
        if len(queue) >= self._effective_batch_size[data_type]:
            await self._flush_queue(data_type)
        elif time.time() - self.last_flush[data_type] >= self.config.flush_interval:
            await self._flush_queue(data_type)

    async def _flush_queue(self, data_type: str) -> None:
        """Flush a queue by processing all pending messages.

        Uses a semaphore to limit concurrent Neo4j operations across data types,
        exponential backoff on Neo4j errors, and adaptive batch sizing.

        Args:
            data_type: The data type queue to flush
        """
        queue = self.queues[data_type]
        if not queue:
            return

        # Skip if in backoff period for this data type
        now = time.time()
        if now < self._backoff_until[data_type]:
            return

        # Mark flush start to prevent concurrent add_message() calls from
        # triggering redundant flushes while this one is in progress.
        # On failure this is overwritten by the backoff mechanism which sets
        # _backoff_until, preventing any flush during the delay window.
        self.last_flush[data_type] = now

        # Use effective (adaptive) batch size
        messages: list[PendingMessage] = []
        while queue and len(messages) < self._effective_batch_size[data_type]:
            messages.append(queue.popleft())

        if not messages:
            return

        batch_start = time.time()
        success = False

        # Limit concurrent Neo4j operations to prevent pool exhaustion
        async with self._flush_semaphore:
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

            except asyncio.CancelledError:
                # Re-enqueue messages before propagating cancellation (e.g. shutdown)
                for msg in reversed(messages):
                    queue.appendleft(msg)
                raise

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

                # Exponential backoff — prevent tight retry loop that worsens pool exhaustion
                self._consecutive_failures[data_type] += 1
                delay = min(
                    self.config.backoff_initial
                    * (
                        self.config.backoff_multiplier
                        ** (self._consecutive_failures[data_type] - 1)
                    ),
                    self.config.backoff_max,
                )
                self._backoff_until[data_type] = time.time() + delay

                # Adaptive batch sizing — halve on failure (floor at min_batch_size)
                old_size = self._effective_batch_size[data_type]
                self._effective_batch_size[data_type] = max(
                    self.config.min_batch_size,
                    self._effective_batch_size[data_type] // 2,
                )
                if self._effective_batch_size[data_type] != old_size:
                    logger.warning(
                        "📉 Reduced batch size due to Neo4j pressure",
                        old_size=old_size,
                        new_size=self._effective_batch_size[data_type],
                        backoff_seconds=round(delay, 1),
                        consecutive_failures=self._consecutive_failures[data_type],
                    )
                else:
                    logger.warning(
                        "⏳ Backing off before retry",
                        data_type=data_type,
                        backoff_seconds=round(delay, 1),
                        consecutive_failures=self._consecutive_failures[data_type],
                    )

                # Messages are back on deque for retry — do NOT nack them
                return

            except Exception as e:
                logger.error(
                    "❌ Batch processing error",
                    data_type=data_type,
                    batch_size=len(messages),
                    error=str(e),
                )
                # Re-enqueue messages for local retry before AMQP nack
                for msg in reversed(messages):
                    queue.appendleft(msg)
                # Track failures for non-transient errors too, to enable backoff
                self._consecutive_failures[data_type] = (
                    self._consecutive_failures.get(data_type, 0) + 1
                )
                # Apply backoff to prevent tight retry loop on persistent errors
                delay = min(
                    self.config.backoff_initial
                    * (
                        self.config.backoff_multiplier
                        ** (self._consecutive_failures[data_type] - 1)
                    ),
                    self.config.backoff_max,
                )
                self._backoff_until[data_type] = time.time() + delay
                # Messages are back on deque for retry — do NOT nack them
                return

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

            # Reset failure tracking on success
            self._consecutive_failures[data_type] = 0

            # Adaptive batch sizing — gradually recover toward configured size
            if self._effective_batch_size[data_type] < self.config.batch_size:
                old_size = self._effective_batch_size[data_type]
                self._effective_batch_size[data_type] = min(
                    self.config.batch_size,
                    self._effective_batch_size[data_type]
                    + max(10, self.config.batch_size // 10),
                )
                if self._effective_batch_size[data_type] != old_size:
                    logger.info(
                        "📈 Increased batch size after success",
                        old_size=old_size,
                        new_size=self._effective_batch_size[data_type],
                    )

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

    async def _process_artists_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of artist records.

        Uses a single session for hash check + write to ensure atomicity.
        """
        all_artists = []
        for msg in messages:
            artist_id = msg.data.get("id")
            if not artist_id:
                logger.warning(
                    "⚠️ Skipping message with missing 'id' field",
                    data_keys=list(msg.data.keys()),
                )
                continue
            all_artists.append(msg.data)

        if not all_artists:
            return

        # Single session for both hash check and write to avoid TOCTOU race
        async with self.driver.session(database="neo4j") as session:
            # Check which artists need updates (by hash)
            ids = [a.get("id") for a in all_artists]
            existing_hashes: dict[str, str] = {}
            if ids:
                result = await session.run(
                    "UNWIND $ids AS id "
                    "OPTIONAL MATCH (a:Artist {id: id}) "
                    "RETURN id, a.sha256 AS hash",
                    ids=ids,
                )
                async for record in result:
                    if record["hash"]:
                        existing_hashes[record["id"]] = record["hash"]

            artists_to_process = [
                a
                for a in all_artists
                if existing_hashes.get(str(a["id"])) != a.get("sha256")
            ]

            if not artists_to_process:
                logger.debug("🔄 All artists in batch already up to date")
                # Don't ack here — let _flush_queue handle acking uniformly
                return

            async def batch_write(tx: Any) -> None:
                # Create/update all artist nodes
                await tx.run(
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
                        """
                        UNWIND $aliases AS rel
                        MATCH (a:Artist {id: rel.artist_id})
                        MERGE (al:Artist {id: rel.alias_id})
                        MERGE (al)-[:ALIAS_OF]->(a)
                        """,
                        aliases=aliases_data,
                    )

            await session.execute_write(batch_write)

    async def _process_labels_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of label records.

        Uses a single session for hash check + write to ensure atomicity.
        """
        all_labels = []
        for msg in messages:
            label_id = msg.data.get("id")
            if not label_id:
                logger.warning(
                    "⚠️ Skipping message with missing 'id' field",
                    data_keys=list(msg.data.keys()),
                )
                continue
            all_labels.append(msg.data)

        if not all_labels:
            return

        # Single session for both hash check and write to avoid TOCTOU race
        async with self.driver.session(database="neo4j") as session:
            ids = [label.get("id") for label in all_labels]
            existing_hashes: dict[str, str] = {}
            if ids:
                result = await session.run(
                    "UNWIND $ids AS id "
                    "OPTIONAL MATCH (l:Label {id: id}) "
                    "RETURN id, l.sha256 AS hash",
                    ids=ids,
                )
                async for record in result:
                    if record["hash"]:
                        existing_hashes[record["id"]] = record["hash"]

            labels_to_process = [
                label
                for label in all_labels
                if existing_hashes.get(str(label["id"])) != label.get("sha256")
            ]

            if not labels_to_process:
                logger.debug("🔄 All labels in batch already up to date")
                # Don't ack here — let _flush_queue handle acking uniformly
                return

            async def batch_write(tx: Any) -> None:
                # Create/update all label nodes
                await tx.run(
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
                    await tx.run(
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
                    await tx.run(
                        """
                        UNWIND $sublabels AS rel
                        MATCH (l:Label {id: rel.label_id})
                        MERGE (s:Label {id: rel.sublabel_id})
                        MERGE (s)-[:SUBLABEL_OF]->(l)
                        """,
                        sublabels=sublabel_data,
                    )

            await session.execute_write(batch_write)

    async def _process_masters_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of master records.

        Uses a single session for hash check + write to ensure atomicity.
        """
        all_masters = []
        for msg in messages:
            master_id = msg.data.get("id")
            if not master_id:
                logger.warning(
                    "⚠️ Skipping message with missing 'id' field",
                    data_keys=list(msg.data.keys()),
                )
                continue
            all_masters.append(msg.data)

        if not all_masters:
            return

        # Single session for both hash check and write to avoid TOCTOU race
        async with self.driver.session(database="neo4j") as session:
            ids = [m.get("id") for m in all_masters]
            existing_hashes: dict[str, str] = {}
            if ids:
                result = await session.run(
                    "UNWIND $ids AS id "
                    "OPTIONAL MATCH (m:Master {id: id}) "
                    "RETURN id, m.sha256 AS hash",
                    ids=ids,
                )
                async for record in result:
                    if record["hash"]:
                        existing_hashes[record["id"]] = record["hash"]

            masters_to_process = [
                m
                for m in all_masters
                if existing_hashes.get(str(m["id"])) != m.get("sha256")
            ]

            if not masters_to_process:
                logger.debug("🔄 All masters in batch already up to date")
                # Don't ack here — let _flush_queue handle acking uniformly
                return

            async def batch_write(tx: Any) -> None:
                # Create/update all master nodes
                await tx.run(
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
                        """
                        UNWIND $pairs AS pair
                        MERGE (g:Genre {name: pair.genre})
                        MERGE (s:Style {name: pair.style})
                        MERGE (s)-[:PART_OF]->(g)
                        """,
                        pairs=genre_style_data,
                    )

            await session.execute_write(batch_write)

    async def _process_releases_batch(self, messages: list[PendingMessage]) -> None:
        """Process a batch of release records.

        Uses a single session for hash check + write to ensure atomicity.
        """
        all_releases = []
        for msg in messages:
            release_id = msg.data.get("id")
            if not release_id:
                logger.warning(
                    "⚠️ Skipping message with missing 'id' field",
                    data_keys=list(msg.data.keys()),
                )
                continue
            all_releases.append(msg)

        if not all_releases:
            return

        # Single session for both hash check and write to avoid TOCTOU race
        async with self.driver.session(database="neo4j") as session:
            ids = [m.data.get("id") for m in all_releases]
            existing_hashes: dict[str, str] = {}
            if ids:
                result = await session.run(
                    "UNWIND $ids AS id "
                    "OPTIONAL MATCH (r:Release {id: id}) "
                    "RETURN id, r.sha256 AS hash",
                    ids=ids,
                )
                async for record in result:
                    if record["hash"]:
                        existing_hashes[record["id"]] = record["hash"]

            releases_to_process = []
            for msg in all_releases:
                rid = str(msg.data["id"])
                release_hash = msg.data.get("sha256")
                if existing_hashes.get(rid) != release_hash:
                    msg.data["format_names"] = extract_format_names(
                        msg.data.get("formats")
                    )
                    releases_to_process.append(msg.data)

            if not releases_to_process:
                logger.debug("🔄 All releases in batch already up to date")
                # Don't ack here — let _flush_queue handle acking uniformly
                return

            async def batch_write(tx: Any) -> None:
                # Create/update all release nodes
                await tx.run(
                    """
                    UNWIND $releases AS release
                    MERGE (r:Release {id: release.id})
                    SET r.title = release.title,
                        r.year = release.year,
                        r.formats = release.format_names,
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
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
                    await tx.run(
                        """
                        UNWIND $pairs AS pair
                        MERGE (g:Genre {name: pair.genre})
                        MERGE (s:Style {name: pair.style})
                        MERGE (s)-[:PART_OF]->(g)
                        """,
                        pairs=genre_style_data,
                    )

                # Process credits (extraartists) — Person nodes and CREDITED_ON relationships
                credit_data = []
                artist_credit_data = []
                for release in releases_to_process:
                    if release.get("extraartists"):
                        for credit in release["extraartists"]:
                            name = credit.get("name")
                            role = credit.get("role", "")
                            if name and role:
                                category = categorize_role(role)
                                entry: dict[str, Any] = {
                                    "name": name,
                                    "role": role,
                                    "category": category,
                                    "release_id": release["id"],
                                }
                                credit_data.append(entry)
                                artist_id = credit.get("id")
                                if artist_id:
                                    artist_credit_data.append(
                                        {
                                            "name": name,
                                            "artist_id": artist_id,
                                        }
                                    )
                if credit_data:
                    await tx.run(
                        """
                        UNWIND $credits AS credit
                        MATCH (r:Release {id: credit.release_id})
                        MERGE (p:Person {name: credit.name})
                        MERGE (p)-[:CREDITED_ON {role: credit.role, category: credit.category}]->(r)
                        """,
                        credits=credit_data,
                    )
                if artist_credit_data:
                    await tx.run(
                        """
                        UNWIND $credits AS credit
                        MATCH (p:Person {name: credit.name})
                        MATCH (a:Artist {id: credit.artist_id})
                        MERGE (p)-[:SAME_AS]->(a)
                        """,
                        credits=artist_credit_data,
                    )

            await session.execute_write(batch_write)

    async def flush_all(self) -> None:
        """Flush all pending queues, draining each completely."""
        for data_type in self.queues:
            await self.flush_queue(data_type)

    async def flush_queue(self, data_type: str) -> None:
        """Fully drain a single data type queue.

        Unlike _flush_queue which processes up to one batch, this loops
        until the queue is completely empty. Yields to the event loop
        during backoff periods instead of busy-spinning.

        Enforces a retry limit to prevent infinite loops when persistent
        errors cause messages to be re-enqueued indefinitely.
        """
        retries = 0
        while self.queues.get(data_type):
            prev_len = len(self.queues[data_type])
            wait = self._backoff_until[data_type] - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
                # Don't count backoff waits as retries — only count actual flush failures
                await self._flush_queue(data_type)
                curr_len = len(self.queues.get(data_type, []))
                if curr_len < prev_len:
                    retries = 0
                continue
            await self._flush_queue(data_type)
            curr_len = len(self.queues.get(data_type, []))
            if curr_len >= prev_len:
                retries += 1
                if retries >= self.config.max_flush_retries:
                    remaining = len(self.queues.get(data_type, []))
                    logger.error(
                        "❌ Flush retry limit reached — nacking remaining messages",
                        data_type=data_type,
                        remaining=remaining,
                        max_retries=self.config.max_flush_retries,
                    )
                    queue = self.queues[data_type]
                    while queue:
                        msg = queue.popleft()
                        try:
                            await msg.nack_callback()
                        except Exception as e:
                            logger.warning("⚠️ Failed to nack message", error=str(e))
                    break
            else:
                retries = 0

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
            "effective_batch_size": self._effective_batch_size.copy(),
            "configured_batch_size": self.config.batch_size,
            "consecutive_failures": self._consecutive_failures.copy(),
        }
