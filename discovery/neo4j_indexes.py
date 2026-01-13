"""Neo4j index management for Discovery service.

This module defines and creates indexes to optimize query performance.
"""

import asyncio
import logging
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase


logger = logging.getLogger(__name__)


# Index definitions based on query analysis
INDEXES = [
    # Full-text indexes for search queries
    {
        "name": "artist_name_fulltext",
        "type": "fulltext",
        "label": "Artist",
        "properties": ["name"],
        "description": "Full-text search on artist names (used in search endpoint)",
    },
    {
        "name": "release_title_fulltext",
        "type": "fulltext",
        "label": "Release",
        "properties": ["title"],
        "description": "Full-text search on release titles (used in search endpoint)",
    },
    {
        "name": "label_name_fulltext",
        "type": "fulltext",
        "label": "Label",
        "properties": ["name"],
        "description": "Full-text search on label names (used in search endpoint)",
    },
    # Range indexes for exact lookups and sorting
    {
        "name": "artist_id_index",
        "type": "range",
        "label": "Artist",
        "properties": ["id"],
        "description": "Fast lookup by artist ID (used in graph and details endpoints)",
    },
    {
        "name": "release_id_index",
        "type": "range",
        "label": "Release",
        "properties": ["id"],
        "description": "Fast lookup by release ID",
    },
    {
        "name": "label_id_index",
        "type": "range",
        "label": "Label",
        "properties": ["id"],
        "description": "Fast lookup by label ID",
    },
    {
        "name": "genre_id_index",
        "type": "range",
        "label": "Genre",
        "properties": ["id"],
        "description": "Fast lookup by genre ID",
    },
    {
        "name": "release_year_index",
        "type": "range",
        "label": "Release",
        "properties": ["year"],
        "description": "Range queries and sorting by year (used in trends endpoint)",
    },
    # Additional indexes for sorting
    {
        "name": "artist_name_index",
        "type": "range",
        "label": "Artist",
        "properties": ["name"],
        "description": "Sorting by artist name (used in search results)",
    },
    {
        "name": "release_title_index",
        "type": "range",
        "label": "Release",
        "properties": ["title"],
        "description": "Sorting by release title (used in search results)",
    },
    {
        "name": "label_name_index",
        "type": "range",
        "label": "Label",
        "properties": ["name"],
        "description": "Sorting by label name (used in search results)",
    },
    {
        "name": "genre_name_index",
        "type": "range",
        "label": "Genre",
        "properties": ["name"],
        "description": "Sorting by genre name (used in trends endpoint)",
    },
]


async def create_index(driver: AsyncDriver, index_def: dict[str, Any]) -> bool:
    """Create a single index if it doesn't exist.

    Args:
        driver: Neo4j async driver
        index_def: Index definition dict

    Returns:
        True if index was created or already exists, False on error
    """
    name = index_def["name"]
    index_type = index_def["type"]
    label = index_def["label"]
    properties = index_def["properties"]

    try:
        async with driver.session() as session:
            if index_type == "fulltext":
                # Full-text indexes use different syntax
                query = f"""
                CREATE FULLTEXT INDEX {name} IF NOT EXISTS
                FOR (n:{label})
                ON EACH [{", ".join([f"n.{prop}" for prop in properties])}]
                """
            else:  # range index
                # Range indexes for single property
                if len(properties) == 1:
                    query = f"""
                    CREATE INDEX {name} IF NOT EXISTS
                    FOR (n:{label})
                    ON (n.{properties[0]})
                    """
                else:
                    # Composite range index
                    props = ", ".join([f"n.{prop}" for prop in properties])
                    query = f"""
                    CREATE INDEX {name} IF NOT EXISTS
                    FOR (n:{label})
                    ON ({props})
                    """

            await session.run(query)
            logger.info(f"✅ Created index: {name} ({index_def['description']})")
            return True

    except Exception as e:
        logger.error(f"❌ Failed to create index {name}: {e}")
        return False


async def create_all_indexes(neo4j_address: str, neo4j_username: str, neo4j_password: str) -> None:
    """Create all defined indexes.

    Args:
        neo4j_address: Neo4j connection address (bolt://host:port)
        neo4j_username: Neo4j username
        neo4j_password: Neo4j password
    """
    logger.info("🚀 Starting Neo4j index creation...")

    driver = AsyncGraphDatabase.driver(neo4j_address, auth=(neo4j_username, neo4j_password))

    try:
        success_count = 0
        failure_count = 0

        for index_def in INDEXES:
            if await create_index(driver, index_def):
                success_count += 1
            else:
                failure_count += 1

        logger.info(f"✅ Index creation complete: {success_count} successful, {failure_count} failed (total: {len(INDEXES)})")

    finally:
        await driver.close()


async def list_indexes(neo4j_address: str, neo4j_username: str, neo4j_password: str) -> list[dict[str, Any]]:
    """List all existing indexes.

    Args:
        neo4j_address: Neo4j connection address (bolt://host:port)
        neo4j_username: Neo4j username
        neo4j_password: Neo4j password

    Returns:
        List of index information dictionaries
    """
    driver = AsyncGraphDatabase.driver(neo4j_address, auth=(neo4j_username, neo4j_password))

    try:
        async with driver.session() as session:
            result = await session.run("SHOW INDEXES")
            indexes = []
            async for record in result:
                indexes.append(dict(record))
            return indexes
    finally:
        await driver.close()


async def drop_index(neo4j_address: str, neo4j_username: str, neo4j_password: str, index_name: str) -> bool:
    """Drop a specific index.

    Args:
        neo4j_address: Neo4j connection address (bolt://host:port)
        neo4j_username: Neo4j username
        neo4j_password: Neo4j password
        index_name: Name of the index to drop

    Returns:
        True if successful, False otherwise
    """
    driver = AsyncGraphDatabase.driver(neo4j_address, auth=(neo4j_username, neo4j_password))

    try:
        async with driver.session() as session:
            await session.run(f"DROP INDEX {index_name} IF EXISTS")
            logger.info(f"✅ Dropped index: {index_name}")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to drop index {index_name}: {e}")
        return False
    finally:
        await driver.close()


if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    neo4j_address = os.getenv("NEO4J_ADDRESS", "bolt://localhost:7687")
    neo4j_username = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    asyncio.run(create_all_indexes(neo4j_address, neo4j_username, neo4j_password))
