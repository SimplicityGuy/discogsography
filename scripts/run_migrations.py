#!/usr/bin/env python3
"""Run database migrations for incremental processing."""

import logging
import sys
from os import getenv
from pathlib import Path

import psycopg


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_migrations(connection_string: str) -> None:
    """Run all migrations in the migrations directory."""
    migrations_dir = Path(__file__).parent.parent / "migrations"

    if not migrations_dir.exists():
        logger.error(f"❌ Migrations directory not found: {migrations_dir}")
        sys.exit(1)

    # Get all SQL migration files, sorted by name
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        logger.warning("⚠️ No migration files found")
        return

    logger.info(f"🔧 Found {len(migration_files)} migration files")

    try:
        with (
            psycopg.connect(connection_string) as conn,
            conn.cursor() as cursor,
        ):
            # Create migrations tracking table if it doesn't exist
            cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        filename VARCHAR(255) PRIMARY KEY,
                        applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            conn.commit()

            # Check which migrations have been applied
            cursor.execute("SELECT filename FROM schema_migrations")
            applied_migrations = {row[0] for row in cursor.fetchall()}

            # Apply pending migrations
            for migration_file in migration_files:
                filename = migration_file.name

                if filename in applied_migrations:
                    logger.info(f"⏩ Skipping {filename} (already applied)")
                    continue

                logger.info(f"🔄 Applying migration: {filename}")

                # Read and execute migration
                migration_sql = migration_file.read_text()
                cursor.execute(migration_sql)

                # Record migration as applied
                cursor.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (filename,))
                conn.commit()

                logger.info(f"✅ Applied migration: {filename}")

        logger.info("✅ All migrations completed successfully")

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    # Get PostgreSQL configuration from environment
    postgres_host = getenv("POSTGRES_ADDRESS", "localhost:5432")
    postgres_user = getenv("POSTGRES_USERNAME", "discogsography")
    postgres_password = getenv("POSTGRES_PASSWORD", "discogsography")
    postgres_database = getenv("POSTGRES_DATABASE", "discogsography")

    if ":" in postgres_host:
        host, port = postgres_host.split(":", 1)
    else:
        host = postgres_host
        port = "5432"

    connection_string = (
        f"postgresql://{postgres_user}:{postgres_password}@{host}:{port}/{postgres_database}"
    )

    logger.info("🚀 Starting database migrations")
    logger.info(f"🐘 Connecting to PostgreSQL at {host}:{port}/{postgres_database}")

    run_migrations(connection_string)


if __name__ == "__main__":
    main()
