"""PostgreSQL schema definitions for the discogsography platform.

Single source of truth for all PostgreSQL tables and indexes.
All statements use IF NOT EXISTS — safe to run on every startup; subsequent
runs are no-ops for already-created schema objects. Schema is never dropped.
"""

import logging
from typing import Any, cast

from psycopg import sql


logger = logging.getLogger(__name__)


# The four Discogs entity tables.  Each has the same base structure:
#   data_id VARCHAR PRIMARY KEY  — Discogs numeric ID as a string
#   hash    VARCHAR NOT NULL     — SHA-256 of the record, used for change detection
#   data    JSONB   NOT NULL     — full Discogs record document
_ENTITY_TABLES = ["artists", "labels", "masters", "releases"]

# Table-specific JSONB field indexes, as (name, sql_string) pairs.
# Plain string literals are safe here because all table/column names are
# hardcoded constants, not user-supplied values.
_SPECIFIC_INDEXES: list[tuple[str, str]] = [
    # Artists
    (
        "idx_artists_name",
        "CREATE INDEX IF NOT EXISTS idx_artists_name ON artists ((data->>'name'))",
    ),
    # Labels
    (
        "idx_labels_name",
        "CREATE INDEX IF NOT EXISTS idx_labels_name ON labels ((data->>'name'))",
    ),
    # Masters
    (
        "idx_masters_title",
        "CREATE INDEX IF NOT EXISTS idx_masters_title ON masters ((data->>'title'))",
    ),
    (
        "idx_masters_year",
        "CREATE INDEX IF NOT EXISTS idx_masters_year ON masters ((data->>'year'))",
    ),
    # Releases
    (
        "idx_releases_title",
        "CREATE INDEX IF NOT EXISTS idx_releases_title ON releases ((data->>'title'))",
    ),
    (
        "idx_releases_year",
        "CREATE INDEX IF NOT EXISTS idx_releases_year ON releases ((data->>'year'))",
    ),
    (
        "idx_releases_country",
        "CREATE INDEX IF NOT EXISTS idx_releases_country ON releases ((data->>'country'))",
    ),
    (
        "idx_releases_genres",
        "CREATE INDEX IF NOT EXISTS idx_releases_genres ON releases USING GIN ((data->'genres'))",
    ),
    (
        "idx_releases_labels",
        "CREATE INDEX IF NOT EXISTS idx_releases_labels ON releases USING GIN ((data->'labels'))",
    ),
]


async def create_postgres_schema(pool: Any) -> None:
    """Create all PostgreSQL tables and indexes.

    Safe to call on every startup; all statements use IF NOT EXISTS so
    subsequent calls are no-ops for already-created schema objects.

    Args:
        pool: An AsyncPostgreSQLPool instance (from common.postgres_resilient).
    """
    logger.info("🔧 Creating PostgreSQL schema (tables and indexes)...")

    success_count = 0
    failure_count = 0

    async with pool.connection() as conn:
        # psycopg async cursor types are not fully inferred by mypy
        async with conn.cursor() as cursor_cm:
            cursor = cast(Any, cursor_cm)

            # ── Per-entity tables and shared indexes ──────────────────────────
            for table_name in _ENTITY_TABLES:
                per_table: list[tuple[str, Any]] = [
                    (
                        f"{table_name} table",
                        sql.SQL(
                            """
                            CREATE TABLE IF NOT EXISTS {table} (
                                data_id VARCHAR PRIMARY KEY,
                                hash    VARCHAR NOT NULL,
                                data    JSONB   NOT NULL
                            )
                            """
                        ).format(table=sql.Identifier(table_name)),
                    ),
                    (
                        f"idx_{table_name}_hash",
                        sql.SQL(
                            "CREATE INDEX IF NOT EXISTS {index} ON {table} (hash)"
                        ).format(
                            index=sql.Identifier(f"idx_{table_name}_hash"),
                            table=sql.Identifier(table_name),
                        ),
                    ),
                    (
                        f"idx_{table_name}_gin",
                        sql.SQL(
                            "CREATE INDEX IF NOT EXISTS {index} ON {table} USING GIN (data)"
                        ).format(
                            index=sql.Identifier(f"idx_{table_name}_gin"),
                            table=sql.Identifier(table_name),
                        ),
                    ),
                ]
                for name, stmt in per_table:
                    try:
                        await cursor.execute(stmt)
                        logger.info(f"✅ Schema: {name}")
                        success_count += 1
                    except Exception as e:
                        logger.error(f"❌ Failed to create schema object '{name}': {e}")
                        failure_count += 1

            # ── Table-specific JSONB field indexes ────────────────────────────
            for name, stmt in _SPECIFIC_INDEXES:
                try:
                    await cursor.execute(stmt)
                    logger.info(f"✅ Schema: {name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to create schema object '{name}': {e}")
                    failure_count += 1

    total = len(_ENTITY_TABLES) * 3 + len(_SPECIFIC_INDEXES)
    logger.info(
        f"✅ PostgreSQL schema creation complete: "
        f"{success_count} succeeded, {failure_count} failed (total: {total})"
    )
