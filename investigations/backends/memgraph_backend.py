"""Memgraph graph backend implementation.

Memgraph uses the Bolt protocol and Cypher, so it shares the neo4j Python driver.
Key differences from Neo4j:
  - No COUNT {} subqueries (Cypher 5.0)
  - No APOC procedures
  - Fulltext search uses Memgraph's built-in text search
  - Schema syntax differs (CREATE INDEX ON vs CREATE INDEX ... FOR)
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase

from investigations.backends.base import GraphBackend


logger = logging.getLogger(__name__)


class MemgraphBackend(GraphBackend):
    """Memgraph Community Edition backend using the neo4j Python driver."""

    def __init__(self) -> None:
        self._driver: Any = None

    @property
    def name(self) -> str:
        return "memgraph"

    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:
        # Memgraph typically doesn't require auth in dev mode
        self._driver = AsyncGraphDatabase.driver(
            uri,
            auth=auth or ("", ""),
            max_connection_pool_size=50,
            **kwargs,
        )
        logger.info("Connected to Memgraph at %s", uri)

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def health_check(self) -> bool:
        try:
            async with self._driver.session() as session:
                result = await session.run("RETURN 1 AS ok")
                await result.consume()
            return True
        except Exception:
            return False

    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run(query, params or {})
            return [dict(record) async for record in result]

    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        async with self._driver.session() as session:
            await session.run(query, params or {})

    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        async with self._driver.session() as session:

            async def _work(tx: Any) -> None:
                for q, p in queries:
                    await tx.run(q, p)

            await session.execute_write(_work)

    def get_schema_statements(self) -> list[str]:
        return [
            "CREATE INDEX ON :Artist(id)",
            "CREATE INDEX ON :Artist(name)",
            "CREATE INDEX ON :Label(id)",
            "CREATE INDEX ON :Label(name)",
            "CREATE INDEX ON :Master(id)",
            "CREATE INDEX ON :Release(id)",
            "CREATE INDEX ON :Release(year)",
            "CREATE INDEX ON :Genre(name)",
            "CREATE INDEX ON :Style(name)",
            # Memgraph uses text indexes for fulltext search
            "CREATE TEXT INDEX ON :Artist(name)",
            "CREATE TEXT INDEX ON :Label(name)",
        ]

    async def clear_all_data(self) -> None:
        await self.execute_write("MATCH (n) DETACH DELETE n")

    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        set_clauses = ", ".join(f"n.{p} = row.{p}" for p in properties)
        return f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET {set_clauses}"

    def batch_create_relationships_query(self, from_label: str, rel_type: str, to_label: str) -> str:
        return f"UNWIND $rows AS row MATCH (a:{from_label} {{id: row.from_id}}) MATCH (b:{to_label} {{id: row.to_id}}) MERGE (a)-[:{rel_type}]->(b)"

    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        # Memgraph text search syntax
        label = "Artist" if "artist" in index_name.lower() else "Label"
        return f"CALL text_search.search('{label}', ${query_param}) YIELD node RETURN node.id AS id, node.name AS name, 1.0 AS score LIMIT {limit}"

    def stats_query(self) -> str:
        return "MATCH (n) RETURN count(n) AS nodeCount"

    def version_query(self) -> str:
        return "CALL mg.info() YIELD key, value WHERE key = 'version' RETURN 'Memgraph' AS name, value AS version"

    def point_lookup_query(self, label: str) -> str:
        return f"MATCH (n:{label} {{id: $id}}) RETURN n.id AS id, n.name AS name"

    def traversal_query(self) -> str:
        return (
            "MATCH (r:Release)-[:BY]->(a:Artist {name: $name}), (r)-[:ON]->(l:Label) "
            "RETURN l.id AS id, l.name AS name, count(DISTINCT r) AS release_count "
            "ORDER BY release_count DESC "
            "SKIP $offset LIMIT $limit"
        )

    def aggregation_query(self) -> str:
        return (
            "MATCH (r:Release)-[:BY]->(a:Artist {name: $name}) "
            "WHERE r.year > 0 "
            "WITH r.year AS year, count(DISTINCT r) AS count "
            "RETURN year, count "
            "ORDER BY year"
        )
