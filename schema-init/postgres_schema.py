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


# User-facing tables for auth and personal data
_USER_TABLES: list[tuple[str, str]] = [
    (
        "users table",
        """
        CREATE TABLE IF NOT EXISTS users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           VARCHAR(255) UNIQUE NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_users_email",
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)",
    ),
    (
        "oauth_tokens table",
        """
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider          VARCHAR(50) NOT NULL,
            access_token      TEXT NOT NULL,
            access_secret     TEXT NOT NULL,
            provider_username VARCHAR(255),
            provider_user_id  VARCHAR(255),
            created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, provider)
        )
        """,
    ),
    (
        "idx_oauth_tokens_user_provider",
        "CREATE INDEX IF NOT EXISTS idx_oauth_tokens_user_provider ON oauth_tokens (user_id, provider)",
    ),
    (
        "app_config table",
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key        VARCHAR(255) PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "user_collections table",
        """
        CREATE TABLE IF NOT EXISTS user_collections (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            release_id   BIGINT NOT NULL,
            instance_id  BIGINT,
            folder_id    INTEGER,
            title        VARCHAR(500),
            artist       VARCHAR(500),
            year         INTEGER,
            format       VARCHAR(255),
            label        VARCHAR(255),
            condition    VARCHAR(100),
            rating       SMALLINT,
            notes        TEXT,
            date_added   TIMESTAMP WITH TIME ZONE,
            metadata     JSONB,
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, release_id, instance_id)
        )
        """,
    ),
    (
        "idx_user_collections_user_id",
        "CREATE INDEX IF NOT EXISTS idx_user_collections_user_id ON user_collections (user_id)",
    ),
    (
        "idx_user_collections_release_id",
        "CREATE INDEX IF NOT EXISTS idx_user_collections_release_id ON user_collections (release_id)",
    ),
    (
        "user_wantlists table",
        """
        CREATE TABLE IF NOT EXISTS user_wantlists (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            release_id BIGINT NOT NULL,
            title      VARCHAR(500),
            artist     VARCHAR(500),
            year       INTEGER,
            format     VARCHAR(255),
            rating     SMALLINT,
            notes      TEXT,
            date_added TIMESTAMP WITH TIME ZONE,
            metadata   JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, release_id)
        )
        """,
    ),
    (
        "idx_user_wantlists_user_id",
        "CREATE INDEX IF NOT EXISTS idx_user_wantlists_user_id ON user_wantlists (user_id)",
    ),
    (
        "idx_user_wantlists_release_id",
        "CREATE INDEX IF NOT EXISTS idx_user_wantlists_release_id ON user_wantlists (release_id)",
    ),
    (
        "sync_history table",
        """
        CREATE TABLE IF NOT EXISTS sync_history (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            sync_type     VARCHAR(50) NOT NULL,
            status        VARCHAR(50) NOT NULL DEFAULT 'pending',
            items_synced  INTEGER,
            pages_fetched INTEGER,
            error_message TEXT,
            started_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at  TIMESTAMP WITH TIME ZONE
        )
        """,
    ),
    (
        "idx_sync_history_user_id",
        "CREATE INDEX IF NOT EXISTS idx_sync_history_user_id ON sync_history (user_id)",
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

            # ── User-facing tables ────────────────────────────────────────────
            for name, stmt in _USER_TABLES:
                try:
                    await cursor.execute(stmt)
                    logger.info(f"✅ Schema: {name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to create schema object '{name}': {e}")
                    failure_count += 1

    total = len(_ENTITY_TABLES) * 3 + len(_SPECIFIC_INDEXES) + len(_USER_TABLES)
    logger.info(
        f"✅ PostgreSQL schema creation complete: "
        f"{success_count} succeeded, {failure_count} failed (total: {total})"
    )
