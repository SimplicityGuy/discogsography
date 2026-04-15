"""Entity detail tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


HandlerFn = Callable[[Any, str], Awaitable[dict[str, Any] | None]]


async def _entity_details(entity_type: str, *, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    node = await handler(driver, name)
    if node is None:
        return {"error": f"{entity_type} '{name}' not found"}
    result = dict(node)
    result["_entity_type"] = entity_type
    return result


async def get_artist_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("artist", driver=driver, name=name, handler=handler)


async def get_label_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("label", driver=driver, name=name, handler=handler)


async def get_genre_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("genre", driver=driver, name=name, handler=handler)


async def get_style_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("style", driver=driver, name=name, handler=handler)


async def get_release_details(*, driver: Any, name: str, handler: HandlerFn) -> dict[str, Any]:
    return await _entity_details("release", driver=driver, name=name, handler=handler)
