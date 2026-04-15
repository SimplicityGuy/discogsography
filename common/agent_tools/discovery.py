"""Discovery tools — search, collaborators, trends."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


SearchFn = Callable[..., Awaitable[dict[str, Any]]]
CollaboratorsFn = Callable[..., Awaitable[list[dict[str, Any]]]]
TrendsHandler = Callable[[Any, str], Awaitable[list[dict[str, Any]]]]


async def search(
    *,
    pool: Any,
    redis: Any,
    q: str,
    types: list[str],
    genres: list[str],
    year_min: int | None,
    year_max: int | None,
    limit: int,
    offset: int,
    search_fn: SearchFn,
) -> dict[str, Any]:
    return await search_fn(
        pool=pool,
        redis=redis,
        q=q,
        types=types,
        genres=genres,
        year_min=year_min,
        year_max=year_max,
        limit=limit,
        offset=offset,
    )


async def get_collaborators(
    *,
    driver: Any,
    artist_id: str,
    limit: int,
    collaborators_fn: CollaboratorsFn,
) -> dict[str, Any]:
    collaborators = await collaborators_fn(driver, artist_id, limit=limit)
    return {"collaborators": collaborators}


async def get_trends(
    *,
    driver: Any,
    entity_type: str,
    name: str,
    handler: TrendsHandler | None,
) -> dict[str, Any]:
    if handler is None:
        return {"error": f"Unknown trends type: {entity_type}"}
    results = await handler(driver, name)
    return {"trends": results}
