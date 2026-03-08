"""ArangoDB graph backend implementation.

ArangoDB uses AQL (ArangoDB Query Language) instead of Cypher. This backend
translates the benchmark workloads into equivalent AQL queries.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, ClassVar

from investigations.backends.base import GraphBackend


logger = logging.getLogger(__name__)


class ArangoDBBackend(GraphBackend):
    """ArangoDB Community Edition backend using python-arango."""

    DB_NAME = "discogsography"
    GRAPH_NAME = "discogs_graph"

    # Vertex collections
    VERTEX_COLLECTIONS: ClassVar[list[str]] = ["artists", "labels", "masters", "releases", "genres", "styles"]
    # Edge definitions
    EDGE_DEFINITIONS: ClassVar[list[dict[str, Any]]] = [
        {"edge_collection": "by", "from_vertex_collections": ["releases", "masters"], "to_vertex_collections": ["artists"]},
        {"edge_collection": "on", "from_vertex_collections": ["releases"], "to_vertex_collections": ["labels"]},
        {"edge_collection": "derived_from", "from_vertex_collections": ["releases"], "to_vertex_collections": ["masters"]},
        {"edge_collection": "is_rel", "from_vertex_collections": ["releases"], "to_vertex_collections": ["genres", "styles"]},
        {"edge_collection": "member_of", "from_vertex_collections": ["artists"], "to_vertex_collections": ["artists"]},
        {"edge_collection": "alias_of", "from_vertex_collections": ["artists"], "to_vertex_collections": ["artists"]},
        {"edge_collection": "sublabel_of", "from_vertex_collections": ["labels"], "to_vertex_collections": ["labels"]},
        {"edge_collection": "part_of", "from_vertex_collections": ["styles"], "to_vertex_collections": ["genres"]},
    ]

    def __init__(self) -> None:
        self._client: Any = None
        self._db: Any = None

    @property
    def name(self) -> str:
        return "arangodb"

    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:  # noqa: ARG002
        from arango import ArangoClient

        # Parse http://host:port format
        self._client = ArangoClient(hosts=uri)
        user = auth[0] if auth else "root"
        password = auth[1] if auth else "discogsography"

        sys_db = self._client.db("_system", username=user, password=password)
        if not sys_db.has_database(self.DB_NAME):
            sys_db.create_database(self.DB_NAME)

        self._db = self._client.db(self.DB_NAME, username=user, password=password)

        # Create graph with edge definitions if it doesn't exist
        if not self._db.has_graph(self.GRAPH_NAME):
            self._db.create_graph(self.GRAPH_NAME, edge_definitions=self.EDGE_DEFINITIONS)

        logger.info("Connected to ArangoDB at %s", uri)

    async def close(self) -> None:
        self._client = None
        self._db = None

    async def health_check(self) -> bool:
        try:
            self._db.version()
            return True
        except Exception:
            return False

    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cursor = self._db.aql.execute(query, bind_vars=params or {})
        return list(cursor)

    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        self._db.aql.execute(query, bind_vars=params or {})

    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        # ArangoDB supports transactions via the JS API; for benchmarking
        # we execute sequentially
        for q, p in queries:
            self._db.aql.execute(q, bind_vars=p)

    def get_schema_statements(self) -> list[str]:
        # ArangoDB schema is handled via collection/graph creation in connect()
        # Return index creation AQL
        return [
            # Persistent indexes on vertex collections
            "FOR doc IN artists COLLECT WITH COUNT INTO c RETURN c",  # no-op to verify collection
        ]

    def _ensure_indexes(self) -> None:
        """Create indexes on ArangoDB collections. Called after connect."""
        for col_name in self.VERTEX_COLLECTIONS:
            if self._db.has_collection(col_name):
                col = self._db.collection(col_name)
                col.add_persistent_index(fields=["entity_id"], unique=True)
                col.add_persistent_index(fields=["name"])
        # Fulltext indexes
        if self._db.has_collection("artists"):
            self._db.collection("artists").add_fulltext_index(fields=["name"])
        if self._db.has_collection("labels"):
            self._db.collection("labels").add_fulltext_index(fields=["name"])

    async def clear_all_data(self) -> None:
        with contextlib.suppress(Exception):
            if self._db.has_graph(self.GRAPH_NAME):
                self._db.delete_graph(self.GRAPH_NAME, drop_collections=True)
            self._db.create_graph(self.GRAPH_NAME, edge_definitions=self.EDGE_DEFINITIONS)

    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        collection = label.lower() + "s"  # Artist -> artists
        if label == "Style":
            collection = "styles"
        elif label == "Master":
            collection = "masters"
        elif label == "Release":
            collection = "releases"
        set_props = ", ".join(f"{p}: row.{p}" for p in properties)
        return f"FOR row IN @rows UPSERT {{entity_id: row.id}} INSERT {{entity_id: row.id, {set_props}}} UPDATE {{{set_props}}} IN {collection}"

    def batch_create_relationships_query(self, from_label: str, rel_type: str, to_label: str) -> str:
        from_col = from_label.lower() + "s"
        to_col = to_label.lower() + "s"
        edge_col = rel_type.lower()
        # Map relationship types to ArangoDB edge collection names
        edge_map = {
            "BY": "by",
            "ON": "on",
            "DERIVED_FROM": "derived_from",
            "IS": "is_rel",
            "MEMBER_OF": "member_of",
            "ALIAS_OF": "alias_of",
            "SUBLABEL_OF": "sublabel_of",
            "PART_OF": "part_of",
        }
        edge_col = edge_map.get(rel_type, edge_col)
        if from_label == "Style":
            from_col = "styles"
        elif from_label == "Master":
            from_col = "masters"
        elif from_label == "Release":
            from_col = "releases"
        if to_label == "Style":
            to_col = "styles"
        elif to_label == "Master":
            to_col = "masters"
        elif to_label == "Release":
            to_col = "releases"
        return (
            f"FOR row IN @rows "
            f"LET from_doc = FIRST(FOR d IN {from_col} FILTER d.entity_id == row.from_id RETURN d) "
            f"LET to_doc = FIRST(FOR d IN {to_col} FILTER d.entity_id == row.to_id RETURN d) "
            f"FILTER from_doc != null AND to_doc != null "
            f"UPSERT {{_from: from_doc._id, _to: to_doc._id}} "
            f"INSERT {{_from: from_doc._id, _to: to_doc._id}} "
            f"UPDATE {{}} "
            f"IN {edge_col}"
        )

    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        collection = "artists" if "artist" in index_name.lower() else "labels"
        return f"FOR doc IN FULLTEXT({collection}, 'name', @{query_param}) LIMIT {limit} RETURN {{id: doc.entity_id, name: doc.name, score: 1.0}}"

    def stats_query(self) -> str:
        return (
            "LET counts = (FOR col IN ['artists','labels','masters','releases','genres','styles'] "
            "  RETURN LENGTH(DOCUMENT(col))) "
            "RETURN {nodeCount: SUM(counts)}"
        )

    def version_query(self) -> str:
        return "RETURN {name: 'ArangoDB', version: '3.x'}"

    def point_lookup_query(self, label: str) -> str:
        collection = label.lower() + "s"
        if label == "Style":
            collection = "styles"
        elif label == "Master":
            collection = "masters"
        elif label == "Release":
            collection = "releases"
        return f"FOR doc IN {collection} FILTER doc.entity_id == @id RETURN {{id: doc.entity_id, name: doc.name}}"

    def traversal_query(self) -> str:
        return (
            "FOR a IN artists FILTER a.name == @name "
            "FOR r IN INBOUND a by "
            "FOR l IN OUTBOUND r on "
            "COLLECT label_id = l.entity_id, label_name = l.name WITH COUNT INTO release_count "
            "SORT release_count DESC "
            "LIMIT @offset, @limit "
            "RETURN {id: label_id, name: label_name, release_count: release_count}"
        )

    def aggregation_query(self) -> str:
        return (
            "FOR a IN artists FILTER a.name == @name "
            "FOR r IN INBOUND a by "
            "FILTER r.year > 0 "
            "COLLECT year = r.year WITH COUNT INTO count "
            "SORT year "
            "RETURN {year: year, count: count}"
        )
