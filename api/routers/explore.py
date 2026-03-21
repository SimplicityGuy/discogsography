"""Explore endpoints — migrated from explore service."""

import asyncio
from collections import OrderedDict
import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from neo4j.exceptions import ClientError as Neo4jClientError
import structlog

import api.dependencies as _dependencies
from api.limiter import limiter
from api.models import PathNode, PathResponse
from api.queries.neo4j_queries import (
    AUTOCOMPLETE_DISPATCH,
    COUNT_DISPATCH,
    DETAILS_DISPATCH,
    EXPAND_DISPATCH,
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
    find_shortest_path,
    get_genre_emergence,
    get_year_range,
)


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None
_redis: Any = None

# Redis cache TTL for trends/genre and trends/style (24 hours — data changes only on import)
_TRENDS_CACHE_TTL = 86400


def configure(neo4j: Any, jwt_secret: str | None, redis: Any = None) -> None:
    global _neo4j_driver, _redis
    _neo4j_driver = neo4j
    _redis = redis
    _dependencies.configure(jwt_secret)


_autocomplete_cache: OrderedDict[tuple[str, str, int], list[dict[str, Any]]] = OrderedDict()
_AUTOCOMPLETE_CACHE_MAX = 512


def _get_cache_key(query: str, entity_type: str, limit: int) -> tuple[str, str, int]:
    return (query.lower().strip(), entity_type, limit)


def _build_categories(entity_type: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if entity_type == "artist":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-aliases", "name": "Aliases & Members", "category": "aliases", "count": result.get("alias_count", 0)},
        ]
    if entity_type == "genre":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-styles", "name": "Styles", "category": "styles", "count": result.get("style_count", 0)},
        ]
    if entity_type == "label":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-genres", "name": "Genres", "category": "genres", "count": result.get("genre_count", 0)},
        ]
    if entity_type == "style":
        return [
            {"id": "cat-releases", "name": "Releases", "category": "releases", "count": result.get("release_count", 0)},
            {"id": "cat-artists", "name": "Artists", "category": "artists", "count": result.get("artist_count", 0)},
            {"id": "cat-labels", "name": "Labels", "category": "labels", "count": result.get("label_count", 0)},
            {"id": "cat-genres", "name": "Genres", "category": "genres", "count": result.get("genre_count", 0)},
        ]
    return []


@router.get("/api/autocomplete")
@limiter.limit("30/minute")
async def autocomplete(
    request: Request,  # noqa: ARG001
    q: str = Query(..., min_length=3),
    type: str = Query("artist"),
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in AUTOCOMPLETE_DISPATCH:
        return JSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)
    cache_key = _get_cache_key(q, entity_type, limit)
    if cache_key in _autocomplete_cache:
        return JSONResponse(content={"results": _autocomplete_cache[cache_key]})
    query_func = AUTOCOMPLETE_DISPATCH[entity_type]
    results = await query_func(_neo4j_driver, q, limit)
    if len(_autocomplete_cache) >= _AUTOCOMPLETE_CACHE_MAX:
        evict_count = _AUTOCOMPLETE_CACHE_MAX // 4
        for _ in range(evict_count):
            _autocomplete_cache.popitem(last=False)
    _autocomplete_cache[cache_key] = results
    return JSONResponse(content={"results": results})


@router.get("/api/explore")
async def explore(
    name: str = Query(...),
    type: str = Query("artist"),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in EXPLORE_DISPATCH:
        return JSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)
    query_func = EXPLORE_DISPATCH[entity_type]
    result = await query_func(_neo4j_driver, name)
    if not result:
        return JSONResponse(content={"error": f"{type.capitalize()} '{name}' not found"}, status_code=404)
    categories = _build_categories(entity_type, result)
    return JSONResponse(content={"center": {"id": str(result["id"]), "name": result["name"], "type": entity_type}, "categories": categories})


@router.get("/api/expand")
async def expand(
    node_id: str = Query(...),
    type: str = Query(...),
    category: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    before_year: int | None = Query(default=None, ge=1900, le=2030),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    category_lower = category.lower()
    if entity_type not in EXPAND_DISPATCH:
        return JSONResponse(content={"error": f"Invalid type: {type}"}, status_code=400)
    type_categories = EXPAND_DISPATCH[entity_type]
    if category_lower not in type_categories:
        valid = ", ".join(type_categories.keys())
        return JSONResponse(content={"error": f"Invalid category '{category}' for type '{type}'. Valid: {valid}"}, status_code=400)
    query_func = type_categories[category_lower]
    count_func = COUNT_DISPATCH[entity_type][category_lower]
    results, total = await asyncio.gather(
        query_func(_neo4j_driver, node_id, limit, offset, before_year=before_year),
        count_func(_neo4j_driver, node_id, before_year=before_year),
    )
    return JSONResponse(content={"children": results, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total})


@router.get("/api/explore/year-range")
async def year_range() -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    result = await get_year_range(_neo4j_driver)
    if result is None:
        return JSONResponse(content={"min_year": None, "max_year": None})
    # Clamp to valid bounds so the frontend slider stays within the
    # before_year validation range (ge=1900, le=2030).
    min_year = max(1900, min(2030, result.get("min_year", 1900)))
    max_year = max(1900, min(2030, result.get("max_year", 2030)))
    return JSONResponse(content={"min_year": min_year, "max_year": max_year})


@router.get("/api/explore/genre-emergence")
async def genre_emergence(
    before_year: int = Query(..., ge=1900, le=2030),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    result = await get_genre_emergence(_neo4j_driver, before_year)
    return JSONResponse(content=result)


@router.get("/api/node/{node_id}")
async def get_node_details(
    node_id: str,
    type: str = Query("artist"),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in DETAILS_DISPATCH:
        return JSONResponse(content={"error": f"Invalid type: {type}"}, status_code=400)
    query_func = DETAILS_DISPATCH[entity_type]
    result = await query_func(_neo4j_driver, node_id)
    if not result:
        return JSONResponse(content={"error": f"{type.capitalize()} '{node_id}' not found"}, status_code=404)
    return JSONResponse(content=result)


@router.get("/api/trends")
async def get_trends(
    name: str = Query(...),
    type: str = Query("artist"),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in TRENDS_DISPATCH:
        return JSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)

    # Cache genre and style trends in Redis (data changes only on import)
    if _redis and entity_type in ("genre", "style"):
        cache_key = f"trends:{entity_type}:{name}"
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Trends cache get failed", key=cache_key)

    query_func = TRENDS_DISPATCH[entity_type]
    results = await query_func(_neo4j_driver, name)
    response = {"name": name, "type": entity_type, "data": results}

    if _redis and entity_type in ("genre", "style"):
        cache_key = f"trends:{entity_type}:{name}"
        try:
            await _redis.setex(cache_key, _TRENDS_CACHE_TTL, json.dumps(response))
        except Exception:
            logger.debug("⚠️ Trends cache set failed", key=cache_key)

    return JSONResponse(content=response)


_VALID_PATH_TYPES = frozenset(EXPLORE_DISPATCH.keys())
_MAX_PATH_DEPTH = 10
_DEFAULT_PATH_DEPTH = 6


def _node_label_to_type(labels: list[str]) -> str:
    """Convert a Neo4j label list to a lowercase entity type string."""
    for label in labels:
        lower = label.lower()
        if lower in _VALID_PATH_TYPES:
            return lower
    return labels[0].lower() if labels else "unknown"


@router.get("/api/path")
async def find_path(
    from_name: str = Query(...),
    from_type: str = Query("artist"),
    to_name: str = Query(...),
    to_type: str = Query("artist"),
    max_depth: int = Query(_DEFAULT_PATH_DEPTH, ge=1, le=_MAX_PATH_DEPTH),
) -> JSONResponse:
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    from_type_lower = from_type.lower()
    to_type_lower = to_type.lower()

    if from_type_lower not in _VALID_PATH_TYPES:
        return JSONResponse(
            content={"error": f"Invalid from_type: {from_type}. Must be one of: {', '.join(sorted(_VALID_PATH_TYPES))}"},
            status_code=400,
        )
    if to_type_lower not in _VALID_PATH_TYPES:
        return JSONResponse(
            content={"error": f"Invalid to_type: {to_type}. Must be one of: {', '.join(sorted(_VALID_PATH_TYPES))}"},
            status_code=400,
        )

    from_explore = EXPLORE_DISPATCH[from_type_lower]
    to_explore = EXPLORE_DISPATCH[to_type_lower]

    from_node, to_node = await asyncio.gather(
        from_explore(_neo4j_driver, from_name),
        to_explore(_neo4j_driver, to_name),
    )

    if not from_node:
        return JSONResponse(
            content={"error": f"{from_type.capitalize()} '{from_name}' not found"},
            status_code=404,
        )
    if not to_node:
        return JSONResponse(
            content={"error": f"{to_type.capitalize()} '{to_name}' not found"},
            status_code=404,
        )

    try:
        raw = await find_shortest_path(
            _neo4j_driver,
            str(from_node["id"]),
            str(to_node["id"]),
            max_depth=max_depth,
            from_type=from_type_lower,
            to_type=to_type_lower,
        )
    except Neo4jClientError as exc:
        if "TransactionTimedOut" in str(exc):
            logger.warning("⏱️ Path query timed out", from_name=from_name, to_name=to_name, max_depth=max_depth)
            return JSONResponse(
                content={"error": "Path query timed out — try reducing max_depth or searching closer nodes"},
                status_code=504,
            )
        raise

    if raw is None:
        return JSONResponse(content=PathResponse(found=False, length=None, path=[]).model_dump())

    raw_nodes: list[dict[str, Any]] = raw["nodes"]
    raw_rels: list[str] = raw["rels"]

    path_nodes = [
        PathNode(
            id=str(n["id"]),
            name=str(n["name"]),
            type=_node_label_to_type(n["labels"]),
            rel=raw_rels[i - 1] if i > 0 else None,
        )
        for i, n in enumerate(raw_nodes)
    ]

    return JSONResponse(
        content=PathResponse(
            found=True,
            length=len(raw_rels),
            path=path_nodes,
        ).model_dump()
    )
