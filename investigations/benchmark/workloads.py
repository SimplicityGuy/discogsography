"""Workload definitions for graph database benchmarking.

Seven workloads matching actual Discogsography usage patterns.
Each workload is backend-agnostic — the runner uses GraphBackend methods
to generate appropriate queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkloadType(StrEnum):
    READ = "read"
    WRITE = "write"
    MIXED = "mixed"


@dataclass
class Workload:
    name: str
    description: str
    workload_type: WorkloadType
    iterations: int = 200
    batch_sizes: list[int] = field(default_factory=list)
    readers: int = 0
    writers: int = 0
    duration_seconds: int = 0


WORKLOADS: list[Workload] = [
    Workload(
        name="batch_write_nodes",
        description="UNWIND/MERGE node creation (graphinator pattern)",
        workload_type=WorkloadType.WRITE,
        iterations=50,
        batch_sizes=[50, 100, 500, 1000],
    ),
    Workload(
        name="batch_write_full_tx",
        description="Full release transaction (6 queries, graphinator pattern)",
        workload_type=WorkloadType.WRITE,
        iterations=50,
    ),
    Workload(
        name="point_read",
        description="Single node lookup by indexed property",
        workload_type=WorkloadType.READ,
        iterations=1000,
    ),
    Workload(
        name="graph_traversal",
        description="Multi-hop explore/expand pattern (releases by artist, grouped by label)",
        workload_type=WorkloadType.READ,
        iterations=200,
    ),
    Workload(
        name="fulltext_search",
        description="Autocomplete fulltext search",
        workload_type=WorkloadType.READ,
        iterations=500,
    ),
    Workload(
        name="aggregation",
        description="Trends query with year grouping",
        workload_type=WorkloadType.READ,
        iterations=200,
    ),
    Workload(
        name="concurrent_mixed",
        description="Simultaneous reads and writes",
        workload_type=WorkloadType.MIXED,
        readers=4,
        writers=2,
        duration_seconds=30,
    ),
]


def get_workload(name: str) -> Workload:
    """Get a workload by name."""
    for w in WORKLOADS:
        if w.name == name:
            return w
    msg = f"Unknown workload: {name}. Available: {[w.name for w in WORKLOADS]}"
    raise ValueError(msg)


def get_workload_params(workload_name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Generate query parameters for a workload from the test data.

    Returns parameters needed to execute the workload queries.
    """
    import random

    artists = data["artists"]
    releases = data["releases"]

    if workload_name == "point_read":
        artist = random.choice(artists)  # noqa: S311  # nosec B311
        return {"id": artist["id"]}

    if workload_name in ("graph_traversal", "aggregation"):
        # Pick an artist that has releases (from the non-orphan set)
        # Use lower-numbered artists which are more likely to have BY edges
        idx = min(int(random.expovariate(5) * len(artists)), len(artists) - 1)
        return {
            "name": artists[idx]["name"],
            "offset": 0,
            "limit": 20,
        }

    if workload_name == "fulltext_search":
        artist = random.choice(artists)  # noqa: S311  # nosec B311
        # Use first word of name as search term
        search_term = artist["name"].split()[0] if " " in artist["name"] else artist["name"][:5]
        return {"search_term": search_term}

    if workload_name == "batch_write_nodes":
        # Generate a batch of new artist nodes
        base_id = len(artists) + random.randint(0, 1_000_000)  # noqa: S311  # nosec B311
        return {"rows": [{"id": str(base_id + i), "name": f"Bench Artist {base_id + i}", "sha256": f"bench-{base_id + i}"} for i in range(100)]}

    if workload_name == "batch_write_full_tx":
        # Simulate a full release write transaction
        release = random.choice(releases)  # noqa: S311  # nosec B311
        return {"release": release}

    return {}
