"""Apache AGE (PostgreSQL extension) graph backend implementation.

AGE provides graph functionality via Cypher queries executed through SQL wrapper
functions. Queries are wrapped in SELECT * FROM cypher('graph_name', $$ ... $$).
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import psycopg

from investigations.backends.base import GraphBackend


logger = logging.getLogger(__name__)


class ApacheAGEBackend(GraphBackend):
    """Apache AGE backend using psycopg3."""

    GRAPH_NAME = "discogsography"

    def __init__(self) -> None:
        self._conn: psycopg.AsyncConnection[Any] | None = None
        self._conninfo: str = ""

    @property
    def name(self) -> str:
        return "age"

    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:  # noqa: ARG002
        # URI format: postgresql://user:pass@host:port/dbname
        self._conninfo = uri
        self._conn = await psycopg.AsyncConnection.connect(uri, autocommit=True)
        # Load AGE extension and set search path
        await self._conn.execute("CREATE EXTENSION IF NOT EXISTS age")
        await self._conn.execute("SET search_path = ag_catalog, '$user', public")
        # Create graph if it doesn't exist
        with contextlib.suppress(Exception):
            await self._conn.execute(f"SELECT create_graph('{self.GRAPH_NAME}')")
        logger.info("Connected to Apache AGE at %s", uri)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def health_check(self) -> bool:
        try:
            if self._conn is None:
                return False
            await self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def _cypher_sql(self, cypher: str, result_columns: str = "v agtype") -> str:
        """Wrap a Cypher query in the AGE SQL function call.

        Dollar-quoting ($$...$$) handles all escaping — single quotes
        inside the Cypher body do not need to be doubled.
        """
        return f"SELECT * FROM cypher('{self.GRAPH_NAME}', $$ {cypher} $$) AS ({result_columns})"  # noqa: S608  # nosec B608

    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            msg = "Not connected to AGE"
            raise RuntimeError(msg)
        # AGE doesn't support Cypher parameters natively in the SQL wrapper;
        # we do string substitution for benchmarking purposes only.
        resolved = self._resolve_params(query, params)
        sql = self._cypher_sql(resolved, result_columns=self._infer_columns(query))
        async with self._conn.cursor() as cur:
            await cur.execute(sql)
            cols = [desc.name for desc in cur.description] if cur.description else []
            rows = await cur.fetchall()
            return [dict(zip(cols, row, strict=False)) for row in rows]

    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        if self._conn is None:
            msg = "Not connected to AGE"
            raise RuntimeError(msg)
        # For UNWIND $rows queries, expand each row individually to avoid
        # AGE's parameter handling limitations.
        if params and "rows" in params and "UNWIND $rows" in query:
            await self._execute_unwind_rows(query, params)
            return
        resolved = self._resolve_params(query, params)
        sql = self._cypher_sql(resolved)
        async with self._conn.cursor() as cur:
            await cur.execute(sql)

    async def _execute_unwind_rows(self, query: str, params: dict[str, Any]) -> None:
        """Execute an UNWIND $rows query by expanding rows into a Cypher literal list.

        AGE doesn't support native Cypher parameters in the SQL wrapper, so we
        must inline the full list as a Cypher literal.  The `_to_cypher_literal`
        method produces valid AGE map syntax ({key: 'val'} — unquoted keys).
        """
        if self._conn is None:  # pragma: no cover — caller already checked
            msg = "Not connected to AGE"
            raise RuntimeError(msg)
        rows_literal = self._to_cypher_literal(params["rows"])
        # Merge any other params (unlikely, but safe)
        other_params = {k: v for k, v in params.items() if k != "rows"}
        resolved = query.replace("$rows", rows_literal)
        resolved = self._resolve_params(resolved, other_params if other_params else None)
        sql = self._cypher_sql(resolved)
        async with self._conn.cursor() as cur:
            await cur.execute(sql)

    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        if self._conn is None:
            msg = "Not connected to AGE"
            raise RuntimeError(msg)
        async with self._conn.transaction():
            for q, p in queries:
                if p and "rows" in p and "UNWIND $rows" in q:
                    await self._execute_unwind_rows(q, p)
                else:
                    resolved = self._resolve_params(q, p)
                    sql = self._cypher_sql(resolved)
                    async with self._conn.cursor() as cur:
                        await cur.execute(sql)

    def _resolve_params(self, query: str, params: dict[str, Any] | None) -> str:
        """Replace $param placeholders with literal values for AGE."""
        if not params:
            return query
        result = query
        for key, value in params.items():
            result = result.replace(f"${key}", self._to_cypher_literal(value))
        return result

    def _to_cypher_literal(self, value: Any) -> str:
        """Convert a Python value to an AGE Cypher literal.

        AGE map syntax: {key: 'string_val', num: 42}  (unquoted keys, single-quoted strings).
        """
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        if isinstance(value, dict):
            entries = ", ".join(f"{k}: {self._to_cypher_literal(v)}" for k, v in value.items())
            return f"{{{entries}}}"
        if isinstance(value, (list, tuple)):
            items = ", ".join(self._to_cypher_literal(v) for v in value)
            return f"[{items}]"
        return str(value)

    def _infer_columns(self, query: str) -> str:
        """Infer result column definitions from RETURN clause for AGE SQL wrapper."""
        # Simple heuristic: extract aliases from RETURN clause
        upper = query.upper()
        ret_idx = upper.rfind("RETURN")
        if ret_idx == -1:
            return "v agtype"
        return_clause = query[ret_idx + 6 :].strip()
        # Remove ORDER BY, SKIP, LIMIT
        for kw in ["ORDER BY", "SKIP", "LIMIT"]:
            idx = return_clause.upper().find(kw)
            if idx != -1:
                return_clause = return_clause[:idx].strip()
        parts = [p.strip() for p in return_clause.split(",")]
        cols = []
        for part in parts:
            # Extract alias after AS, or use last word
            upper_part = part.upper()
            as_idx = upper_part.rfind(" AS ")
            alias = part[as_idx + 4 :].strip() if as_idx != -1 else part.split(".")[-1].strip()
            cols.append(f"{alias} agtype")
        return ", ".join(cols) if cols else "v agtype"

    def get_schema_statements(self) -> list[str]:
        # These are raw SQL — not Cypher — so they must bypass _cypher_sql().
        # Returning empty here; schema is applied in apply_schema() instead.
        return []

    async def apply_schema(self) -> None:
        """Create vertex and edge labels via raw SQL (not Cypher)."""
        if self._conn is None:
            msg = "Not connected to AGE"
            raise RuntimeError(msg)
        vlabels = ["Artist", "Label", "Master", "Release", "Genre", "Style"]
        elabels = ["BY", "ON", "DERIVED_FROM", "IS", "MEMBER_OF", "ALIAS_OF", "SUBLABEL_OF", "PART_OF"]
        for label in vlabels:
            with contextlib.suppress(Exception):
                await self._conn.execute(f"SELECT create_vlabel('{self.GRAPH_NAME}', '{label}')")
        for label in elabels:
            with contextlib.suppress(Exception):
                await self._conn.execute(f"SELECT create_elabel('{self.GRAPH_NAME}', '{label}')")

    async def clear_all_data(self) -> None:
        if self._conn is None:
            msg = "Not connected to AGE"
            raise RuntimeError(msg)
        with contextlib.suppress(Exception):
            await self._conn.execute(f"SELECT drop_graph('{self.GRAPH_NAME}', true)")
            await self._conn.execute(f"SELECT create_graph('{self.GRAPH_NAME}')")

    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        set_clauses = ", ".join(f"n.{p} = row.{p}" for p in properties)
        return f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET {set_clauses}"

    def batch_create_relationships_query(self, from_label: str, rel_type: str, to_label: str) -> str:
        return f"UNWIND $rows AS row MATCH (a:{from_label} {{id: row.from_id}}) MATCH (b:{to_label} {{id: row.to_id}}) MERGE (a)-[:{rel_type}]->(b)"

    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        # AGE doesn't have native fulltext; use CONTAINS as approximation
        label = "Artist" if "artist" in index_name.lower() else "Label"
        return f"MATCH (n:{label}) WHERE n.name CONTAINS ${query_param} RETURN n.id AS id, n.name AS name, 1.0 AS score LIMIT {limit}"

    def stats_query(self) -> str:
        return "MATCH (n) RETURN count(n) AS nodeCount"

    def version_query(self) -> str:
        return "RETURN 'Apache AGE' AS name, '1.0' AS version"

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
