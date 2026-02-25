"""In-memory snapshot store with TTL eviction for graph state persistence."""

from datetime import UTC, datetime, timedelta
import secrets
from typing import Any


class SnapshotStore:
    """Thread-safe in-memory store for graph snapshots with TTL eviction."""

    def __init__(self, ttl_days: int = 28, max_nodes: int = 100, max_entries: int = 1000) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._ttl_days: int = ttl_days
        self._max_nodes: int = max_nodes
        self._max_entries: int = max_entries

    @property
    def ttl_days(self) -> int:
        return self._ttl_days

    @property
    def max_nodes(self) -> int:
        return self._max_nodes

    def save(self, nodes: list[dict[str, Any]], center: dict[str, Any]) -> tuple[str, datetime]:
        """Save a snapshot and return (token, expires_at)."""
        self._evict_expired()
        token = secrets.token_urlsafe(12)
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=self._ttl_days)
        self._store[token] = {
            "nodes": nodes,
            "center": center,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        return token, expires_at

    def load(self, token: str) -> dict[str, Any] | None:
        """Load a snapshot by token, returning None if not found or expired."""
        entry = self._store.get(token)
        if entry is None:
            return None
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if datetime.now(UTC) > expires_at:
            del self._store[token]
            return None
        return {
            "nodes": entry["nodes"],
            "center": entry["center"],
            "created_at": entry["created_at"],
        }

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        now = datetime.now(UTC)
        expired = [token for token, entry in self._store.items() if datetime.fromisoformat(entry["expires_at"]) < now]
        for token in expired:
            del self._store[token]
