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
    # Full-text search GIN indexes — used by /api/search
    (
        "idx_artists_fts",
        "CREATE INDEX IF NOT EXISTS idx_artists_fts ON artists USING GIN (to_tsvector('english', COALESCE(data->>'name', '')))",
    ),
    (
        "idx_labels_fts",
        "CREATE INDEX IF NOT EXISTS idx_labels_fts ON labels USING GIN (to_tsvector('english', COALESCE(data->>'name', '')))",
    ),
    (
        "idx_masters_fts",
        "CREATE INDEX IF NOT EXISTS idx_masters_fts ON masters USING GIN (to_tsvector('english', COALESCE(data->>'title', '')))",
    ),
    (
        "idx_releases_fts",
        "CREATE INDEX IF NOT EXISTS idx_releases_fts ON releases USING GIN (to_tsvector('english', COALESCE(data->>'title', '')))",
    ),
]


# User-facing tables for auth and personal data
_USER_TABLES: list[tuple[str, str]] = [
    (
        "users table",
        """
        CREATE TABLE IF NOT EXISTS users (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email                VARCHAR(255) UNIQUE NOT NULL,
            hashed_password      VARCHAR(255) NOT NULL,
            is_active            BOOLEAN NOT NULL DEFAULT TRUE,
            is_admin             BOOLEAN NOT NULL DEFAULT FALSE,
            password_changed_at  TIMESTAMP WITH TIME ZONE,
            totp_secret          VARCHAR,
            totp_enabled         BOOLEAN NOT NULL DEFAULT FALSE,
            totp_recovery_codes  JSONB,
            totp_failed_attempts INTEGER NOT NULL DEFAULT 0,
            totp_locked_until    TIMESTAMP WITH TIME ZONE,
            created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "users.password_changed_at column",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP WITH TIME ZONE",
    ),
    (
        "users.totp_secret column",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR",
    ),
    (
        "users.totp_enabled column",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    ),
    (
        "users.totp_recovery_codes column",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_recovery_codes JSONB",
    ),
    (
        "users.totp_failed_attempts column",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_failed_attempts INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "users.totp_locked_until column",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_locked_until TIMESTAMP WITH TIME ZONE",
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
            formats      JSONB,
            label        VARCHAR(255),
            condition    VARCHAR(100),
            rating       SMALLINT,
            notes        TEXT,
            date_added   TIMESTAMP WITH TIME ZONE,
            metadata     JSONB,
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            UNIQUE NULLS NOT DISTINCT(user_id, release_id, instance_id)
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
        "idx_sync_history_user_started",
        "CREATE INDEX IF NOT EXISTS idx_sync_history_user_started ON sync_history (user_id, started_at DESC)",
    ),
    (
        "idx_sync_history_running",
        "CREATE INDEX IF NOT EXISTS idx_sync_history_running ON sync_history (user_id) WHERE status = 'running'",
    ),
    (
        "extraction_history",
        """
        CREATE TABLE IF NOT EXISTS extraction_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            triggered_by UUID NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            record_counts JSONB,
            error_message TEXT,
            extractor_version VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_extraction_history_status",
        "CREATE INDEX IF NOT EXISTS idx_extraction_history_status ON extraction_history(status)",
    ),
    (
        "idx_extraction_history_created_at",
        "CREATE INDEX IF NOT EXISTS idx_extraction_history_created_at ON extraction_history(created_at DESC)",
    ),
    (
        "queue_metrics table",
        """
        CREATE TABLE IF NOT EXISTS queue_metrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL,
            queue_name VARCHAR(100) NOT NULL,
            messages_ready INTEGER,
            messages_unacknowledged INTEGER,
            consumers INTEGER,
            publish_rate REAL,
            ack_rate REAL
        )
        """,
    ),
    (
        "idx_queue_metrics_recorded_queue",
        "CREATE INDEX IF NOT EXISTS idx_queue_metrics_recorded_queue ON queue_metrics (recorded_at, queue_name)",
    ),
    (
        "service_health_metrics table",
        """
        CREATE TABLE IF NOT EXISTS service_health_metrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL,
            service_name VARCHAR(50) NOT NULL,
            status VARCHAR(20),
            response_time_ms REAL,
            endpoint_stats JSONB
        )
        """,
    ),
    (
        "idx_service_health_recorded_service",
        "CREATE INDEX IF NOT EXISTS idx_service_health_recorded_service ON service_health_metrics (recorded_at, service_name)",
    ),
    (
        "admin_audit_log table",
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_id   UUID NOT NULL REFERENCES users(id),
            action     VARCHAR(100) NOT NULL,
            target     VARCHAR(255),
            details    JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_admin_audit_log_created_at",
        "CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at ON admin_audit_log (created_at DESC)",
    ),
    (
        "idx_admin_audit_log_admin_id",
        "CREATE INDEX IF NOT EXISTS idx_admin_audit_log_admin_id ON admin_audit_log (admin_id)",
    ),
]


# Insights tables — precomputed analytics stored in a dedicated schema.
# All tables include computed_at for cache freshness checks.
_INSIGHTS_TABLES: list[tuple[str, str]] = [
    (
        "insights schema",
        "CREATE SCHEMA IF NOT EXISTS insights",
    ),
    (
        "insights.artist_centrality table",
        """
        CREATE TABLE IF NOT EXISTS insights.artist_centrality (
            rank            INT NOT NULL,
            artist_id       TEXT NOT NULL,
            artist_name     TEXT NOT NULL,
            edge_count      BIGINT NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (rank)
        )
        """,
    ),
    (
        "insights.genre_trends table",
        """
        CREATE TABLE IF NOT EXISTS insights.genre_trends (
            genre           TEXT NOT NULL,
            decade          INT NOT NULL,
            release_count   BIGINT NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (genre, decade)
        )
        """,
    ),
    (
        "insights.label_longevity table",
        """
        CREATE TABLE IF NOT EXISTS insights.label_longevity (
            rank            INT NOT NULL,
            label_id        TEXT NOT NULL,
            label_name      TEXT NOT NULL,
            first_year      INT NOT NULL,
            last_year       INT,
            years_active    INT NOT NULL,
            total_releases  BIGINT NOT NULL,
            peak_decade     INT,
            still_active    BOOLEAN NOT NULL DEFAULT FALSE,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (rank)
        )
        """,
    ),
    (
        "insights.monthly_anniversaries table",
        """
        CREATE TABLE IF NOT EXISTS insights.monthly_anniversaries (
            master_id       TEXT NOT NULL,
            title           TEXT NOT NULL,
            artist_name     TEXT,
            release_year    INT NOT NULL,
            anniversary     INT NOT NULL,
            computed_month  INT NOT NULL,
            computed_year   INT NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (master_id, computed_year, computed_month)
        )
        """,
    ),
    (
        "insights.data_completeness table",
        """
        CREATE TABLE IF NOT EXISTS insights.data_completeness (
            entity_type     TEXT NOT NULL,
            total_count     BIGINT NOT NULL,
            with_image      BIGINT NOT NULL DEFAULT 0,
            with_year       BIGINT NOT NULL DEFAULT 0,
            with_country    BIGINT NOT NULL DEFAULT 0,
            with_genre      BIGINT NOT NULL DEFAULT 0,
            completeness_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (entity_type)
        )
        """,
    ),
    (
        "insights.release_rarity table",
        """
        CREATE TABLE IF NOT EXISTS insights.release_rarity (
            release_id      BIGINT PRIMARY KEY,
            title           TEXT,
            artist_name     TEXT,
            year            INTEGER,
            rarity_score    REAL NOT NULL,
            tier            TEXT NOT NULL,
            hidden_gem_score REAL,
            pressing_scarcity REAL,
            label_catalog   REAL,
            format_rarity   REAL,
            temporal_scarcity REAL,
            graph_isolation REAL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_release_rarity_score",
        "CREATE INDEX IF NOT EXISTS idx_release_rarity_score ON insights.release_rarity (rarity_score DESC)",
    ),
    (
        "idx_release_rarity_tier",
        "CREATE INDEX IF NOT EXISTS idx_release_rarity_tier ON insights.release_rarity (tier)",
    ),
    (
        "idx_release_rarity_gem",
        "CREATE INDEX IF NOT EXISTS idx_release_rarity_gem ON insights.release_rarity (hidden_gem_score DESC NULLS LAST)",
    ),
    (
        "insights.computation_log table",
        """
        CREATE TABLE IF NOT EXISTS insights.computation_log (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            insight_type    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'running',
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at    TIMESTAMPTZ,
            rows_affected   BIGINT,
            error_message   TEXT,
            duration_ms     BIGINT
        )
        """,
    ),
    (
        "idx_computation_log_type_started",
        "CREATE INDEX IF NOT EXISTS idx_computation_log_type_started ON insights.computation_log (insight_type, started_at DESC)",
    ),
    (
        "idx_anniversaries_month_year",
        "CREATE INDEX IF NOT EXISTS idx_anniversaries_month_year ON insights.monthly_anniversaries (computed_year, computed_month)",
    ),
    (
        "idx_genre_trends_genre",
        "CREATE INDEX IF NOT EXISTS idx_genre_trends_genre ON insights.genre_trends (genre)",
    ),
]


# MusicBrainz tables — external music metadata and relationships
# Stores artist, label, and release data from MusicBrainz with cross-references to Discogs IDs.
_MUSICBRAINZ_TABLES: list[tuple[str, str]] = [
    (
        "musicbrainz schema",
        "CREATE SCHEMA IF NOT EXISTS musicbrainz",
    ),
    (
        "musicbrainz.artists table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.artists (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            sort_name TEXT,
            type TEXT,
            gender TEXT,
            begin_date TEXT,
            end_date TEXT,
            ended BOOLEAN DEFAULT FALSE,
            area TEXT,
            begin_area TEXT,
            end_area TEXT,
            disambiguation TEXT,
            discogs_artist_id INTEGER,
            aliases JSONB,
            tags JSONB,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz.labels table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.labels (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            label_code INTEGER,
            begin_date TEXT,
            end_date TEXT,
            ended BOOLEAN DEFAULT FALSE,
            area TEXT,
            disambiguation TEXT,
            discogs_label_id INTEGER,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz.releases table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.releases (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            barcode TEXT,
            status TEXT,
            release_group_mbid UUID,
            discogs_release_id INTEGER,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz.release_groups table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.release_groups (
            mbid UUID PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            secondary_types JSONB,
            first_release_date TEXT,
            disambiguation TEXT,
            discogs_master_id INTEGER,
            data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ),
    (
        "musicbrainz.relationships table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.relationships (
            id SERIAL PRIMARY KEY,
            source_mbid UUID NOT NULL,
            target_mbid UUID NOT NULL,
            source_entity_type TEXT NOT NULL,
            target_entity_type TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            begin_date TEXT,
            end_date TEXT,
            ended BOOLEAN DEFAULT FALSE,
            attributes JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (source_mbid, target_mbid, source_entity_type, target_entity_type, relationship_type)
        )""",
    ),
    (
        "musicbrainz.external_links table",
        """CREATE TABLE IF NOT EXISTS musicbrainz.external_links (
            id SERIAL PRIMARY KEY,
            mbid UUID NOT NULL,
            entity_type TEXT NOT NULL,
            service_name TEXT NOT NULL,
            url TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (mbid, entity_type, service_name)
        )""",
    ),
]


# MusicBrainz indexes — optimized queries for cross-database lookups
_MUSICBRAINZ_INDEXES: list[tuple[str, str]] = [
    (
        "idx_mb_artists_discogs_id",
        "CREATE INDEX IF NOT EXISTS idx_mb_artists_discogs_id ON musicbrainz.artists (discogs_artist_id) WHERE discogs_artist_id IS NOT NULL",
    ),
    (
        "idx_mb_labels_discogs_id",
        "CREATE INDEX IF NOT EXISTS idx_mb_labels_discogs_id ON musicbrainz.labels (discogs_label_id) WHERE discogs_label_id IS NOT NULL",
    ),
    (
        "idx_mb_releases_discogs_id",
        "CREATE INDEX IF NOT EXISTS idx_mb_releases_discogs_id ON musicbrainz.releases (discogs_release_id) WHERE discogs_release_id IS NOT NULL",
    ),
    (
        "idx_mb_release_groups_discogs_id",
        "CREATE INDEX IF NOT EXISTS idx_mb_release_groups_discogs_id ON musicbrainz.release_groups (discogs_master_id) WHERE discogs_master_id IS NOT NULL",
    ),
    (
        "idx_mb_artists_name",
        "CREATE INDEX IF NOT EXISTS idx_mb_artists_name ON musicbrainz.artists (name)",
    ),
    (
        "idx_mb_labels_name",
        "CREATE INDEX IF NOT EXISTS idx_mb_labels_name ON musicbrainz.labels (name)",
    ),
    (
        "idx_mb_rels_source",
        "CREATE INDEX IF NOT EXISTS idx_mb_rels_source ON musicbrainz.relationships (source_mbid)",
    ),
    (
        "idx_mb_rels_target",
        "CREATE INDEX IF NOT EXISTS idx_mb_rels_target ON musicbrainz.relationships (target_mbid)",
    ),
    (
        "idx_mb_rels_type",
        "CREATE INDEX IF NOT EXISTS idx_mb_rels_type ON musicbrainz.relationships (relationship_type)",
    ),
    (
        "idx_mb_links_mbid",
        "CREATE INDEX IF NOT EXISTS idx_mb_links_mbid ON musicbrainz.external_links (mbid)",
    ),
    (
        "idx_mb_links_service",
        "CREATE INDEX IF NOT EXISTS idx_mb_links_service ON musicbrainz.external_links (service_name)",
    ),
]


async def create_postgres_schema(pool: Any) -> int:
    """Create all PostgreSQL tables and indexes.

    Safe to call on every startup; all statements use IF NOT EXISTS so
    subsequent calls are no-ops for already-created schema objects.

    Args:
        pool: An AsyncPostgreSQLPool instance (from common.postgres_resilient).

    Returns:
        Number of failed schema statements (0 means all succeeded).
    """
    logger.info("🔧 Creating PostgreSQL schema (tables and indexes)...")

    success_count = 0
    failure_count = 0

    async with pool.connection() as conn:
        await conn.set_autocommit(True)
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
                                data_id    VARCHAR PRIMARY KEY,
                                hash       VARCHAR NOT NULL,
                                data       JSONB   NOT NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
                        f"idx_{table_name}_updated_at",
                        sql.SQL(
                            "CREATE INDEX IF NOT EXISTS {index} ON {table} (updated_at)"
                        ).format(
                            index=sql.Identifier(f"idx_{table_name}_updated_at"),
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

            # ── Insights tables ───────────────────────────────────────────
            for name, stmt in _INSIGHTS_TABLES:
                try:
                    await cursor.execute(stmt)
                    logger.info(f"✅ Schema: {name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to create schema object '{name}': {e}")
                    failure_count += 1

            # ── MusicBrainz tables ────────────────────────────────────────
            for name, stmt in _MUSICBRAINZ_TABLES + _MUSICBRAINZ_INDEXES:
                try:
                    await cursor.execute(stmt)
                    logger.info(f"✅ Schema: {name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to create schema object '{name}': {e}")
                    failure_count += 1

    total = (
        len(_ENTITY_TABLES) * 3
        + len(_SPECIFIC_INDEXES)
        + len(_USER_TABLES)
        + len(_INSIGHTS_TABLES)
        + len(_MUSICBRAINZ_TABLES)
        + len(_MUSICBRAINZ_INDEXES)
    )
    logger.info(
        f"✅ PostgreSQL schema creation complete: "
        f"{success_count} succeeded, {failure_count} failed (total: {total})"
    )
    return failure_count
