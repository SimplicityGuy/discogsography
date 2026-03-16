"""Dgraph graph backend implementation.

Dgraph uses DQL (Dgraph Query Language, formerly GraphQL+-) instead of Cypher.
This backend translates the benchmark workloads into equivalent DQL queries
and mutations.

Key differences from Cypher-based backends:
  - Predicate-centric data model (predicates are global, types group them)
  - JSON or N-Quad mutations instead of MERGE/SET
  - Upserts require query+mutation blocks
  - Full-text search via alloftext()/anyoftext() functions
  - System-assigned UIDs; external IDs stored as predicates with @upsert
"""

from __future__ import annotations

import json
import logging
from typing import Any

from investigations.backends.base import GraphBackend


logger = logging.getLogger(__name__)


class DgraphBackend(GraphBackend):
    """Dgraph backend using the official pydgraph Python client."""

    def __init__(self) -> None:
        self._client: Any = None
        self._client_stub: Any = None

    @property
    def name(self) -> str:
        return "dgraph"

    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:  # noqa: ARG002
        import pydgraph

        # URI expected as grpc://host:9080 or just host:9080
        grpc_addr = uri.replace("grpc://", "")
        self._client_stub = pydgraph.DgraphClientStub(grpc_addr)
        self._client = pydgraph.DgraphClient(self._client_stub)

        # Apply schema
        await self._apply_schema()
        logger.info("Connected to Dgraph at %s", grpc_addr)

    async def _apply_schema(self) -> None:
        """Set up Dgraph schema with predicates, types, and indexes."""
        import pydgraph

        schema = """
            # Entity predicates
            entity_id: string @index(exact) @upsert .
            name: string @index(term, exact, fulltext, trigram) .
            sha256: string @index(exact) .
            year: int @index(int) .
            title: string @index(term, fulltext) .

            # Relationship predicates (edges)
            by: [uid] @reverse @count .
            on: [uid] @reverse @count .
            derived_from: [uid] @reverse @count .
            is_genre: [uid] @reverse @count .
            is_style: [uid] @reverse @count .
            member_of: [uid] @reverse @count .
            alias_of: [uid] @reverse @count .
            sublabel_of: [uid] @reverse @count .
            part_of: [uid] @reverse @count .

            # Type definitions
            type Artist {
                entity_id
                name
                sha256
                <~by>
                member_of
                alias_of
            }

            type Label {
                entity_id
                name
                sha256
                <~on>
                sublabel_of
            }

            type Master {
                entity_id
                name
                sha256
                year
                <~derived_from>
            }

            type Release {
                entity_id
                name
                sha256
                year
                title
                by
                on
                derived_from
                is_genre
                is_style
            }

            type Genre {
                entity_id
                name
            }

            type Style {
                entity_id
                name
                part_of
            }
        """
        op = pydgraph.Operation(schema=schema)
        self._client.alter(op)

    async def close(self) -> None:
        if self._client_stub:
            self._client_stub.close()
            self._client_stub = None
            self._client = None

    async def health_check(self) -> bool:
        try:
            # Use a simple DQL query via the gRPC client to verify connectivity
            txn = self._client.txn(read_only=True)
            try:
                txn.query("{ _check(func: has(dgraph.type), first: 1) { uid } }")
            finally:
                txn.discard()
            return True
        except Exception:
            return False

    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        txn = self._client.txn(read_only=True)
        try:
            variables = {f"${k}": str(v) for k, v in (params or {}).items()}
            res = txn.query(query, variables=variables)
            data = json.loads(res.json)
            # DQL returns named result sets; flatten the first one
            for key in data:
                if isinstance(data[key], list):
                    result: list[dict[str, Any]] = data[key]
                    return result
            return []
        finally:
            txn.discard()

    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        """Execute a write operation.

        The benchmark runner calls this with marker query strings from
        batch_merge_nodes_query() / batch_create_relationships_query()
        and a params dict containing {"rows": [...]}.  We intercept those
        markers and translate into Dgraph JSON mutations.
        """
        if query.startswith("__dgraph_batch_merge_") and params and "rows" in params:
            self._handle_batch_merge(query, params["rows"])
            return

        if query.startswith("__dgraph_batch_rel_") and params and "rows" in params:
            self._handle_batch_rel(query, params["rows"])
            return

        # Generic mutation path
        txn = self._client.txn()
        try:
            if params and "mutation_json" in params:
                txn.mutate(set_obj=params["mutation_json"], commit_now=True)
            elif params and "set_nquads" in params:
                txn.mutate(set_nquads=params["set_nquads"], commit_now=True)
            else:
                txn.mutate(set_nquads=query, commit_now=True)
        finally:
            txn.discard()

    def _handle_batch_merge(self, marker: str, rows: list[dict[str, Any]]) -> None:
        """Convert batch_merge_nodes_query marker + rows into JSON mutations."""
        # Marker format: __dgraph_batch_merge_{Label}_{prop1,prop2,...}
        parts = marker.replace("__dgraph_batch_merge_", "").split("_", 1)
        label = parts[0]
        properties = parts[1].split(",") if len(parts) > 1 else []

        objects = []
        for row in rows:
            obj: dict[str, Any] = {
                "uid": f"_:{label.lower()}_{row['id']}",
                "dgraph.type": label,
                "entity_id": str(row["id"]),
            }
            for prop in properties:
                if prop in row:
                    obj[prop] = row[prop]
            objects.append(obj)

        txn = self._client.txn()
        try:
            txn.mutate(set_obj=objects, commit_now=True)
        finally:
            txn.discard()

    def _handle_batch_rel(self, marker: str, rows: list[dict[str, Any]]) -> None:
        """Convert batch_create_relationships_query marker + rows into mutations.

        Since Dgraph uses UIDs internally, we need to look up each entity_id
        to find the UID, then create the edge. We use an upsert block for this.
        """
        # Marker format: __dgraph_batch_rel_{FromLabel}_{REL_TYPE}_{ToLabel}
        parts = marker.replace("__dgraph_batch_rel_", "").split("_", 2)
        rel_type = parts[1].lower() if len(parts) > 1 else "unknown"

        # Map relationship types to Dgraph edge predicates
        edge_map = {
            "BY": "by",
            "ON": "on",
            "DERIVED_FROM": "derived_from",
            "IS": "is_genre",  # Default; caller distinguishes genre vs style
            "MEMBER_OF": "member_of",
            "ALIAS_OF": "alias_of",
            "SUBLABEL_OF": "sublabel_of",
            "PART_OF": "part_of",
        }
        edge_pred = edge_map.get(parts[1], rel_type) if len(parts) > 1 else rel_type

        for row in rows:
            from_id = str(row["from_id"])
            to_id = str(row["to_id"])

            query = f"""{{
                from as var(func: eq(entity_id, "{from_id}"))
                to as var(func: eq(entity_id, "{to_id}"))
            }}"""
            nquad = f"uid(from) <{edge_pred}> uid(to) ."

            txn = self._client.txn()
            try:
                mutation = txn.create_mutation(set_nquads=nquad)
                request = txn.create_request(
                    query=query,
                    mutations=[mutation],
                    commit_now=True,
                )
                txn.do_request(request)
            finally:
                txn.discard()

    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        txn = self._client.txn()
        try:
            for _q, p in queries:
                if "mutation_json" in p:
                    txn.mutate(set_obj=p["mutation_json"])
            txn.commit()
        finally:
            txn.discard()

    def get_schema_statements(self) -> list[str]:
        # Schema is applied in connect() via _apply_schema()
        return []

    async def clear_all_data(self) -> None:
        import pydgraph

        # Drop all data but keep schema
        op = pydgraph.Operation(drop_op=pydgraph.Operation.DATA)
        self._client.alter(op)

    # --- Backend-Specific Query Adapters ---

    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        # Returns a marker string; actual mutation is done via execute_write
        # with mutation_json in params
        return f"__dgraph_batch_merge_{label}_{','.join(properties)}"

    def batch_create_relationships_query(self, from_label: str, rel_type: str, to_label: str) -> str:
        return f"__dgraph_batch_rel_{from_label}_{rel_type}_{to_label}"

    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        # Dgraph fulltext search using alloftext()
        predicate = "name"
        type_filter = "Artist" if "artist" in index_name.lower() else "Label"
        return (
            "{"
            f"  results(func: alloftext({predicate}, ${query_param}), first: {limit}) "
            f"@filter(type({type_filter})) {{"
            "    id: entity_id"
            "    name: name"
            "  }"
            "}"
        )

    def stats_query(self) -> str:
        return """{
          artists(func: type(Artist)) { count(uid) }
          labels(func: type(Label)) { count(uid) }
          masters(func: type(Master)) { count(uid) }
          releases(func: type(Release)) { count(uid) }
        }"""

    def version_query(self) -> str:
        # Version is retrieved via HTTP, not DQL
        return "{ version(func: has(dgraph.type), first: 0) { uid } }"

    def point_lookup_query(self, label: str) -> str:
        return f"{{  results(func: eq(entity_id, $id)) @filter(type({label})) {{    id: entity_id    name: name  }}}}"

    def traversal_query(self) -> str:
        return """{
          var(func: eq(name, $name)) @filter(type(Artist)) {
            ~by {
              on {
                label_id as entity_id
                label_name as name
              }
            }
          }
          results(func: uid(label_id), orderasc: val(label_name), offset: $offset, first: $limit) {
            id: val(label_id)
            name: val(label_name)
          }
        }"""

    def aggregation_query(self) -> str:
        return """{
          results(func: eq(name, $name)) @filter(type(Artist)) {
            ~by @filter(gt(year, 0)) {
              year: year
            }
          }
        }"""
