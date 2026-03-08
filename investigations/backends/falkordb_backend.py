"""FalkorDB (Redis-based graph database) backend implementation.

FalkorDB uses its own Cypher-like query language (openCypher subset) and
the falkordb Python client. It runs as a Redis module.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from investigations.backends.base import GraphBackend


logger = logging.getLogger(__name__)


class FalkorDBBackend(GraphBackend):
    """FalkorDB backend using the falkordb Python client."""

    GRAPH_NAME = "discogsography"

    def __init__(self) -> None:
        self._db: Any = None
        self._graph: Any = None

    @property
    def name(self) -> str:
        return "falkordb"

    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:  # noqa: ARG002
        from falkordb import FalkorDB  # type: ignore[import-untyped,unused-ignore]

        # Parse redis://host:port format
        host = "localhost"
        port = 6379
        if "://" in uri:
            parts = uri.split("://")[1]
            if ":" in parts:
                host, port_str = parts.split(":")
                port = int(port_str.split("/")[0])
            else:
                host = parts.split("/")[0]

        self._db = FalkorDB(host=host, port=port)
        self._graph = self._db.select_graph(self.GRAPH_NAME)
        logger.info("Connected to FalkorDB at %s:%d", host, port)

    async def close(self) -> None:
        # FalkorDB client doesn't need explicit close
        self._db = None
        self._graph = None

    async def health_check(self) -> bool:
        try:
            self._graph.query("RETURN 1")
            return True
        except Exception:
            return False

    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self._graph.query(query, params=params)
        return self._result_to_dicts(result)

    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        self._graph.query(query, params=params)

    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        # FalkorDB doesn't support multi-statement transactions;
        # execute queries sequentially
        for q, p in queries:
            self._graph.query(q, params=p)

    def _result_to_dicts(self, result: Any) -> list[dict[str, Any]]:
        """Convert FalkorDB result set to list of dicts."""
        if not result.result_set:
            return []
        headers = result.header
        return [dict(zip(headers, row, strict=False)) for row in result.result_set]

    def get_schema_statements(self) -> list[str]:
        return [
            "CREATE INDEX FOR (a:Artist) ON (a.id)",
            "CREATE INDEX FOR (a:Artist) ON (a.name)",
            "CREATE INDEX FOR (l:Label) ON (l.id)",
            "CREATE INDEX FOR (l:Label) ON (l.name)",
            "CREATE INDEX FOR (m:Master) ON (m.id)",
            "CREATE INDEX FOR (r:Release) ON (r.id)",
            "CREATE INDEX FOR (r:Release) ON (r.year)",
            "CREATE INDEX FOR (g:Genre) ON (g.name)",
            "CREATE INDEX FOR (s:Style) ON (s.name)",
            # FalkorDB fulltext indexes
            "CALL db.idx.fulltext.createNodeIndex('Artist', 'name')",
            "CALL db.idx.fulltext.createNodeIndex('Label', 'name')",
        ]

    async def clear_all_data(self) -> None:
        with contextlib.suppress(Exception):
            self._graph.delete()
            self._graph = self._db.select_graph(self.GRAPH_NAME)

    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        set_clauses = ", ".join(f"n.{p} = row.{p}" for p in properties)
        return f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET {set_clauses}"

    def batch_create_relationships_query(self, from_label: str, rel_type: str, to_label: str) -> str:
        return f"UNWIND $rows AS row MATCH (a:{from_label} {{id: row.from_id}}) MATCH (b:{to_label} {{id: row.to_id}}) MERGE (a)-[:{rel_type}]->(b)"

    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        label = "Artist" if "artist" in index_name.lower() else "Label"
        return (
            f"CALL db.idx.fulltext.queryNodes('{label}', ${query_param}) "
            f"YIELD node "
            f"RETURN node.id AS id, node.name AS name, 1.0 AS score "
            f"LIMIT {limit}"
        )

    def stats_query(self) -> str:
        return "MATCH (n) RETURN count(n) AS nodeCount"

    def version_query(self) -> str:
        return "RETURN 'FalkorDB' AS name, '1.0' AS version"

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
