"""Graph data tools — find_path, collaborators, stats."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


ResolveNameFn = Callable[[Any, str, str], Awaitable[dict[str, Any] | None]]
FindShortestPathFn = Callable[..., Awaitable[dict[str, Any] | None]]


async def find_path(
    *,
    driver: Any,
    from_name: str,
    from_type: str,
    to_name: str,
    to_type: str,
    max_depth: int = 6,
    resolve_name: ResolveNameFn,
    find_shortest_path_fn: FindShortestPathFn,
) -> dict[str, Any]:
    """Find the shortest path between two entities by name.

    The caller injects ``resolve_name`` and ``find_shortest_path_fn`` so this
    module has zero coupling to ``api.queries``. The NLQ engine and the MCP
    server each pass their own resolver bound to the same shared implementation.
    """
    from_node = await resolve_name(driver, from_name, from_type)
    if from_node is None:
        return {"error": f"{from_type} '{from_name}' not found"}
    to_node = await resolve_name(driver, to_name, to_type)
    if to_node is None:
        return {"error": f"{to_type} '{to_name}' not found"}

    result = await find_shortest_path_fn(
        driver=driver,
        from_id=str(from_node["id"]),
        to_id=str(to_node["id"]),
        max_depth=max_depth,
        from_type=from_type,
        to_type=to_type,
    )
    if result is None:
        return {"error": "No path found between the specified entities"}
    return result
