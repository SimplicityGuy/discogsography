"""Neo4j schema definitions: constraints and indexes for the discogsography platform.

Single source of truth for all Neo4j constraints and indexes.
All statements use IF NOT EXISTS — safe to run on every startup; subsequent
runs are no-ops for already-created schema objects.

Ordering: constraints are listed first because each unique constraint implicitly
creates a backing range index on the constrained property. Standalone range/
fulltext indexes are listed after, so there is no property overlap and no risk
of conflicts between constraint-backed indexes and explicit range indexes.
"""

import logging
from typing import Any


logger = logging.getLogger(__name__)


# All schema statements in creation order.
# Constraints first (they implicitly create backing range indexes),
# then additional range indexes, then fulltext indexes.
SCHEMA_STATEMENTS: list[tuple[str, str]] = [
    # ── Unique constraints ────────────────────────────────────────────────────
    # Each constraint implicitly creates a backing range index on the property.
    # Do NOT add explicit range indexes for Artist.id, Label.id, Master.id,
    # Release.id, Genre.name, or Style.name — they would conflict.
    (
        "artist_id",
        "CREATE CONSTRAINT artist_id IF NOT EXISTS FOR (a:Artist) REQUIRE a.id IS UNIQUE",
    ),
    (
        "label_id",
        "CREATE CONSTRAINT label_id IF NOT EXISTS FOR (l:Label) REQUIRE l.id IS UNIQUE",
    ),
    (
        "master_id",
        "CREATE CONSTRAINT master_id IF NOT EXISTS FOR (m:Master) REQUIRE m.id IS UNIQUE",
    ),
    (
        "release_id",
        "CREATE CONSTRAINT release_id IF NOT EXISTS FOR (r:Release) REQUIRE r.id IS UNIQUE",
    ),
    (
        "genre_name",
        "CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE",
    ),
    (
        "style_name",
        "CREATE CONSTRAINT style_name IF NOT EXISTS FOR (s:Style) REQUIRE s.name IS UNIQUE",
    ),
    # ── Range indexes ─────────────────────────────────────────────────────────
    # sha256 indexes retained for efficient MERGE operations during ingestion.
    (
        "artist_sha256",
        "CREATE INDEX artist_sha256 IF NOT EXISTS FOR (a:Artist) ON (a.sha256)",
    ),
    (
        "label_sha256",
        "CREATE INDEX label_sha256 IF NOT EXISTS FOR (l:Label) ON (l.sha256)",
    ),
    (
        "master_sha256",
        "CREATE INDEX master_sha256 IF NOT EXISTS FOR (m:Master) ON (m.sha256)",
    ),
    (
        "release_sha256",
        "CREATE INDEX release_sha256 IF NOT EXISTS FOR (r:Release) ON (r.sha256)",
    ),
    # Year range index used by explore for temporal queries.
    (
        "release_year_index",
        "CREATE INDEX release_year_index IF NOT EXISTS FOR (r:Release) ON (r.year)",
    ),
    # ── Fulltext indexes ──────────────────────────────────────────────────────
    # Used by explore for autocomplete and full-text search.
    (
        "artist_name_fulltext",
        "CREATE FULLTEXT INDEX artist_name_fulltext IF NOT EXISTS FOR (n:Artist) ON EACH [n.name]",
    ),
    (
        "release_title_fulltext",
        "CREATE FULLTEXT INDEX release_title_fulltext IF NOT EXISTS FOR (n:Release) ON EACH [n.title]",
    ),
    (
        "label_name_fulltext",
        "CREATE FULLTEXT INDEX label_name_fulltext IF NOT EXISTS FOR (n:Label) ON EACH [n.name]",
    ),
]


async def create_neo4j_schema(driver: Any) -> None:
    """Create all Neo4j constraints and indexes.

    Safe to call on every startup. Every statement uses IF NOT EXISTS so
    subsequent calls are no-ops for already-created schema objects.

    Args:
        driver: An AsyncResilientNeo4jDriver instance (from common.neo4j_resilient).
    """
    logger.info("🔧 Creating Neo4j schema (constraints and indexes)...")

    success_count = 0
    failure_count = 0

    async with await driver.session(database="neo4j") as session:
        for name, cypher in SCHEMA_STATEMENTS:
            try:
                await session.run(cypher)
                logger.info(f"✅ Schema: {name}")
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to create schema object '{name}': {e}")
                failure_count += 1

    total = len(SCHEMA_STATEMENTS)
    logger.info(
        f"✅ Neo4j schema creation complete: "
        f"{success_count} succeeded, {failure_count} failed (total: {total})"
    )
