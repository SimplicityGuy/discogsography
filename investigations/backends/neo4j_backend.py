"""Neo4j graph backend implementation."""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase

from investigations.backends.base import GraphBackend


logger = logging.getLogger(__name__)


class Neo4jBackend(GraphBackend):
    """Neo4j Community Edition backend using the official async driver."""

    def __init__(self) -> None:
        self._driver: Any = None

    @property
    def name(self) -> str:
        return "neo4j"

    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:
        self._driver = AsyncGraphDatabase.driver(
            uri,
            auth=auth,
            max_connection_lifetime=30 * 60,
            max_connection_pool_size=50,
            connection_acquisition_timeout=60.0,
            **kwargs,
        )
        logger.info("Connected to Neo4j at %s", uri)

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def health_check(self) -> bool:
        try:
            async with self._driver.session(database="neo4j") as session:
                result = await session.run("RETURN 1 AS ok")
                await result.consume()
            return True
        except Exception:
            return False

    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(query, params or {})
            return [dict(record) async for record in result]

    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        async with self._driver.session(database="neo4j") as session:

            async def _work(tx: Any) -> None:
                await tx.run(query, params or {})

            await session.execute_write(_work)

    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        async with self._driver.session(database="neo4j") as session:

            async def _work(tx: Any) -> None:
                for q, p in queries:
                    await tx.run(q, p)

            await session.execute_write(_work)

    def get_schema_statements(self) -> list[str]:
        return [
            "CREATE CONSTRAINT artist_id IF NOT EXISTS FOR (a:Artist) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT label_id IF NOT EXISTS FOR (l:Label) REQUIRE l.id IS UNIQUE",
            "CREATE CONSTRAINT master_id IF NOT EXISTS FOR (m:Master) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT release_id IF NOT EXISTS FOR (r:Release) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE",
            "CREATE CONSTRAINT style_name IF NOT EXISTS FOR (s:Style) REQUIRE s.name IS UNIQUE",
            "CREATE INDEX artist_name IF NOT EXISTS FOR (a:Artist) ON (a.name)",
            "CREATE INDEX release_year IF NOT EXISTS FOR (r:Release) ON (r.year)",
            "CREATE INDEX master_year IF NOT EXISTS FOR (m:Master) ON (m.year)",
            "CREATE FULLTEXT INDEX artist_fulltext IF NOT EXISTS FOR (a:Artist) ON EACH [a.name]",
            "CREATE FULLTEXT INDEX label_fulltext IF NOT EXISTS FOR (l:Label) ON EACH [l.name]",
        ]

    async def clear_all_data(self) -> None:
        # Delete in batches to avoid memory issues
        while True:
            result = await self.execute_read("MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS deleted")
            if not result or result[0].get("deleted", 0) == 0:
                break

    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        set_clauses = ", ".join(f"n.{p} = row.{p}" for p in properties)
        return f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET {set_clauses}"

    def batch_create_relationships_query(self, from_label: str, rel_type: str, to_label: str) -> str:
        return f"UNWIND $rows AS row MATCH (a:{from_label} {{id: row.from_id}}) MATCH (b:{to_label} {{id: row.to_id}}) MERGE (a)-[:{rel_type}]->(b)"

    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        return (
            f"CALL db.index.fulltext.queryNodes('{index_name}', ${query_param}) "
            f"YIELD node, score "
            f"RETURN node.id AS id, node.name AS name, score "
            f"LIMIT {limit}"
        )

    def stats_query(self) -> str:
        return "CALL apoc.meta.stats() YIELD nodeCount, relCount RETURN nodeCount, relCount"

    def version_query(self) -> str:
        return "CALL dbms.components() YIELD name, versions RETURN name, versions"

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
