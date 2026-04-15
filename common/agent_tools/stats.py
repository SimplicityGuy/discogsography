"""Stats tools — graph_stats, genre_tree."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


StatsFn = Callable[[Any], Awaitable[dict[str, Any]]]
TreeFn = Callable[[Any], Awaitable[list[dict[str, Any]]]]


async def get_graph_stats(*, driver: Any, stats_fn: StatsFn) -> dict[str, Any]:
    return await stats_fn(driver)


async def get_genre_tree(*, driver: Any, tree_fn: TreeFn) -> dict[str, Any]:
    tree = await tree_fn(driver)
    return {"genres": tree}
