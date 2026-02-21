#!/usr/bin/env python3
"""One-shot schema initializer for discogsography.

Runs on every stack startup before any other service.  It:
  1. Ensures the PostgreSQL database exists (admin-level CREATE DATABASE).
  2. Creates / verifies all PostgreSQL tables and indexes via common.postgres_schema.
  3. Creates / verifies all Neo4j constraints and indexes via common.neo4j_schema.

All DDL statements are idempotent (IF NOT EXISTS) so subsequent runs are no-ops.
Exits 0 on success, 1 if any critical step fails.
"""

import asyncio
import os
import sys
from pathlib import Path

import psycopg
import structlog
from psycopg import sql

from common import (
    AsyncPostgreSQLPool,
    AsyncResilientNeo4jDriver,
    setup_logging,
)
from neo4j_schema import create_neo4j_schema
from postgres_schema import create_postgres_schema


logger = structlog.get_logger(__name__)

# ── Configuration from environment ───────────────────────────────────────────

NEO4J_ADDRESS = os.environ.get("NEO4J_ADDRESS", "bolt://neo4j:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "discogsography")

POSTGRES_ADDRESS = os.environ.get("POSTGRES_ADDRESS", "postgres:5432")
POSTGRES_USERNAME = os.environ.get("POSTGRES_USERNAME", "discogsography")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "discogsography")
POSTGRES_DATABASE = os.environ.get("POSTGRES_DATABASE", "discogsography")


def _postgres_connection_params() -> dict[str, str | int]:
    """Parse POSTGRES_ADDRESS into psycopg connection params."""
    if ":" in POSTGRES_ADDRESS:
        host, port_str = POSTGRES_ADDRESS.split(":", 1)
        port = int(port_str)
    else:
        host = POSTGRES_ADDRESS
        port = 5432
    return {
        "host": host,
        "port": port,
        "dbname": POSTGRES_DATABASE,
        "user": POSTGRES_USERNAME,
        "password": POSTGRES_PASSWORD,
    }


# ── PostgreSQL ────────────────────────────────────────────────────────────────


def _ensure_postgres_database(params: dict[str, str | int]) -> None:
    """Create the target database if it does not already exist (synchronous)."""
    admin_params = {**params, "dbname": "postgres"}
    logger.info("🔧 Ensuring PostgreSQL database exists...", database=POSTGRES_DATABASE)
    with psycopg.connect(**admin_params) as conn:  # type: ignore[arg-type]
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (POSTGRES_DATABASE,),
            )
            if cursor.fetchone():
                logger.info(
                    "✅ PostgreSQL database already exists", database=POSTGRES_DATABASE
                )
            else:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(POSTGRES_DATABASE)
                    )
                )
                logger.info(
                    "✅ PostgreSQL database created", database=POSTGRES_DATABASE
                )


async def _init_postgres(params: dict[str, str | int]) -> bool:
    """Create all tables and indexes.  Returns True on success."""
    pool: AsyncPostgreSQLPool | None = None
    try:
        pool = AsyncPostgreSQLPool(
            connection_params=params,
            max_connections=5,
            min_connections=1,
            max_retries=5,
            health_check_interval=30,
        )
        await pool.initialize()
        await create_postgres_schema(pool)
        return True
    except Exception as e:
        logger.error("❌ PostgreSQL schema init failed", error=str(e))
        return False
    finally:
        if pool:
            await pool.close()


# ── Neo4j ─────────────────────────────────────────────────────────────────────


async def _init_neo4j() -> bool:
    """Create all constraints and indexes.  Returns True on success."""
    driver: AsyncResilientNeo4jDriver | None = None
    try:
        driver = AsyncResilientNeo4jDriver(
            uri=NEO4J_ADDRESS,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        )

        # Verify connectivity first
        async with await driver.session(database="neo4j") as session:
            result = await session.run("RETURN 1 AS health")
            await result.single()
        logger.info("✅ Neo4j connectivity verified")

        await create_neo4j_schema(driver)
        return True
    except Exception as e:
        logger.error("❌ Neo4j schema init failed", error=str(e))
        return False
    finally:
        if driver:
            await driver.close()


# ── Entry point ───────────────────────────────────────────────────────────────


async def main() -> int:
    setup_logging("schema-init", log_file=Path("/logs/schema-init.log"))
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗                                   ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝                                   ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗                                   ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║                                   ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║                                   ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝                                   ")
    print("                                                                                        ")
    print("███████╗ ██████╗██╗  ██╗███████╗███╗   ███╗ █████╗    ██╗███╗   ██╗██╗████████╗")
    print("██╔════╝██╔════╝██║  ██║██╔════╝████╗ ████║██╔══██╗   ██║████╗  ██║██║╚══██╔══╝")
    print("███████╗██║     ███████║█████╗  ██╔████╔██║███████║   ██║██╔██╗ ██║██║   ██║   ")
    print("╚════██║██║     ██╔══██║██╔══╝  ██║╚██╔╝██║██╔══██║   ██║██║╚██╗██║██║   ██║   ")
    print("███████║╚██████╗██║  ██║███████╗██║ ╚═╝ ██║██║  ██║   ██║██║ ╚████║██║   ██║   ")
    print("╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝╚═╝  ╚═══╝╚═╝   ╚═╝   ")
    print()
    # fmt: on
    logger.info("🚀 Schema initializer starting...")

    params = _postgres_connection_params()

    # Step 1 – ensure database exists (sync, must happen before pool creation)
    try:
        _ensure_postgres_database(params)
    except Exception as e:
        logger.error("❌ Failed to ensure PostgreSQL database exists", error=str(e))
        return 1

    # Steps 2 & 3 – run in parallel
    postgres_ok, neo4j_ok = await asyncio.gather(
        _init_postgres(params),
        _init_neo4j(),
    )

    if postgres_ok and neo4j_ok:
        logger.info("✅ Schema initialization complete — all systems ready")
        return 0

    failures = []
    if not postgres_ok:
        failures.append("PostgreSQL")
    if not neo4j_ok:
        failures.append("Neo4j")
    logger.error("❌ Schema initialization failed", systems=", ".join(failures))
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
