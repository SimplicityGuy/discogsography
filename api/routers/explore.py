"""Explore endpoints — migrated from explore service."""

import asyncio
import base64
from collections import OrderedDict
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

from api.queries.neo4j_queries import (
    AUTOCOMPLETE_DISPATCH,
    COUNT_DISPATCH,
    DETAILS_DISPATCH,
    EXPAND_DISPATCH,
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
)


logger = structlog.get_logger(__name__)

router = APIRouter()
_security = HTTPBearer(auto_error=False)

_neo4j_driver: Any = None
_jwt_secret: str | None = None


def configure(neo4j: Any, jwt_secret: str | None) -> None:
    global _neo4j_driver, _jwt_secret
    _neo4j_driver = neo4j
    _jwt_secret = jwt_secret


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _verify_jwt(token: str, secret: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    expected_sig = base64.urlsafe_b64encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(sig_b64, expected_sig):
        return None
    try:
        payload: dict[str, Any] = json.loads(_b64url_decode(body_b64))
    except Exception:
        return None
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(int(exp), UTC) < datetime.now(UTC):
        return None
    return payload


async def _get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any] | None:
    if credentials is None or _jwt_secret is None:
        return None
    return _verify_jwt(credentials.credentials, _jwt_secret)


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
async def autocomplete(
    q: str = Query(..., min_length=2),
    type: str = Query("artist"),
    limit: int = Query(10, ge=1, le=50),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in AUTOCOMPLETE_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)
    cache_key = _get_cache_key(q, entity_type, limit)
    if cache_key in _autocomplete_cache:
        return ORJSONResponse(content={"results": _autocomplete_cache[cache_key]})
    query_func = AUTOCOMPLETE_DISPATCH[entity_type]
    results = await query_func(_neo4j_driver, q, limit)
    if len(_autocomplete_cache) >= _AUTOCOMPLETE_CACHE_MAX:
        evict_count = _AUTOCOMPLETE_CACHE_MAX // 4
        for _ in range(evict_count):
            _autocomplete_cache.popitem(last=False)
    _autocomplete_cache[cache_key] = results
    return ORJSONResponse(content={"results": results})


@router.get("/api/explore")
async def explore(
    name: str = Query(...),
    type: str = Query("artist"),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in EXPLORE_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)
    query_func = EXPLORE_DISPATCH[entity_type]
    result = await query_func(_neo4j_driver, name)
    if not result:
        return ORJSONResponse(content={"error": f"{type.capitalize()} '{name}' not found"}, status_code=404)
    categories = _build_categories(entity_type, result)
    return ORJSONResponse(content={"center": {"id": str(result["id"]), "name": result["name"], "type": entity_type}, "categories": categories})


@router.get("/api/expand")
async def expand(
    node_id: str = Query(...),
    type: str = Query(...),
    category: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    category_lower = category.lower()
    if entity_type not in EXPAND_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}"}, status_code=400)
    type_categories = EXPAND_DISPATCH[entity_type]
    if category_lower not in type_categories:
        valid = ", ".join(type_categories.keys())
        return ORJSONResponse(content={"error": f"Invalid category '{category}' for type '{type}'. Valid: {valid}"}, status_code=400)
    query_func = type_categories[category_lower]
    count_func = COUNT_DISPATCH[entity_type][category_lower]
    results, total = await asyncio.gather(
        query_func(_neo4j_driver, node_id, limit, offset),
        count_func(_neo4j_driver, node_id),
    )
    return ORJSONResponse(content={"children": results, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total})


@router.get("/api/node/{node_id}")
async def get_node_details(
    node_id: str,
    type: str = Query("artist"),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in DETAILS_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}"}, status_code=400)
    query_func = DETAILS_DISPATCH[entity_type]
    result = await query_func(_neo4j_driver, node_id)
    if not result:
        return ORJSONResponse(content={"error": f"{type.capitalize()} '{node_id}' not found"}, status_code=404)
    return ORJSONResponse(content=result)


@router.get("/api/trends")
async def get_trends(
    name: str = Query(...),
    type: str = Query("artist"),
) -> ORJSONResponse:
    if not _neo4j_driver:
        return ORJSONResponse(content={"error": "Service not ready"}, status_code=503)
    entity_type = type.lower()
    if entity_type not in TRENDS_DISPATCH:
        return ORJSONResponse(content={"error": f"Invalid type: {type}. Must be artist, genre, label, or style"}, status_code=400)
    query_func = TRENDS_DISPATCH[entity_type]
    results = await query_func(_neo4j_driver, name)
    return ORJSONResponse(content={"name": name, "type": entity_type, "data": results})
