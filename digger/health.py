"""Health data provider for the digger service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def get_health_data() -> dict[str, Any]:
    """Return current health data for the digger service."""
    return {
        "status": "ok",
        "service": "digger",
        "timestamp": datetime.now(UTC).isoformat(),
    }
