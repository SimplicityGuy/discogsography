"""Abstract base class for graph database backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GraphBackend(ABC):
    """Abstract interface for graph database backends.

    Each backend implements database-specific connection handling, query execution,
    schema management, and query adapters. Services interact only with this interface.
    """

    # --- Connection Lifecycle ---

    @abstractmethod
    async def connect(self, uri: str, auth: tuple[str, str] | None = None, **kwargs: Any) -> None:
        """Establish connection to the graph database."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release resources."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the database is reachable and responding."""

    # --- Query Execution ---

    @abstractmethod
    async def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only query. Returns list of record dicts."""

    @abstractmethod
    async def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        """Execute a single write query."""

    @abstractmethod
    async def execute_write_batch(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        """Execute multiple write queries in a single transaction."""

    # --- Schema Management ---

    @abstractmethod
    def get_schema_statements(self) -> list[str]:
        """Return DDL statements for constraints, indexes, and fulltext indexes."""

    # --- Data Management ---

    @abstractmethod
    async def clear_all_data(self) -> None:
        """Delete all nodes and relationships. Used between benchmark runs."""

    # --- Backend-Specific Query Adapters ---

    @abstractmethod
    def batch_merge_nodes_query(self, label: str, properties: list[str]) -> str:
        """Return the UNWIND/MERGE query for batch node creation.

        Args:
            label: Node label (e.g., "Artist", "Release")
            properties: Property names to SET (e.g., ["name", "sha256"])
        """

    @abstractmethod
    def batch_create_relationships_query(
        self,
        from_label: str,
        rel_type: str,
        to_label: str,
    ) -> str:
        """Return the UNWIND/MATCH/MERGE query for batch relationship creation.

        Expects params with $rows containing dicts with 'from_id' and 'to_id'.
        """

    @abstractmethod
    def fulltext_search_query(self, index_name: str, query_param: str, limit: int = 10) -> str:
        """Return the fulltext search query string for this backend."""

    @abstractmethod
    def stats_query(self) -> str:
        """Return the query to get node/relationship counts."""

    @abstractmethod
    def version_query(self) -> str:
        """Return the query to get the database version."""

    @abstractmethod
    def point_lookup_query(self, label: str) -> str:
        """Return a single-node lookup query by id property."""

    @abstractmethod
    def traversal_query(self) -> str:
        """Return a multi-hop traversal query (releases by artist, grouped by label)."""

    @abstractmethod
    def aggregation_query(self) -> str:
        """Return a year-grouped aggregation query for releases by artist."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
