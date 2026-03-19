"""Collection gap analysis endpoints — "Complete My Collection" feature."""

from collections import OrderedDict
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
import structlog

import api.dependencies as _dependencies
from api.dependencies import require_user
from api.queries.gap_queries import (
    get_artist_gap_summary,
    get_artist_gaps,
    get_artist_metadata,
    get_label_gap_summary,
    get_label_gaps,
    get_label_metadata,
    get_master_gap_summary,
    get_master_gaps,
    get_master_metadata,
)
from common.query_debug import execute_sql


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None
_pg_pool: Any = None

# LRU cache for gap summary counts (keyed by user+entity, with TTL)
_summary_cache: OrderedDict[tuple[str, str, str], tuple[float, dict[str, Any]]] = OrderedDict()
_SUMMARY_CACHE_MAX = 256
_SUMMARY_CACHE_TTL = 300  # 5 minutes


def configure(neo4j: Any, pg_pool: Any, jwt_secret: str | None) -> None:
    global _neo4j_driver, _pg_pool
    _neo4j_driver = neo4j
    _pg_pool = pg_pool
    _dependencies.configure(jwt_secret)


def _get_cached_summary(user_id: str, entity_type: str, entity_id: str) -> dict[str, Any] | None:
    key = (user_id, entity_type, entity_id)
    entry = _summary_cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > _SUMMARY_CACHE_TTL:
        _summary_cache.pop(key, None)
        return None
    _summary_cache.move_to_end(key)
    return data


def _set_cached_summary(user_id: str, entity_type: str, entity_id: str, data: dict[str, Any]) -> None:
    key = (user_id, entity_type, entity_id)
    _summary_cache[key] = (time.monotonic(), data)
    _summary_cache.move_to_end(key)
    while len(_summary_cache) > _SUMMARY_CACHE_MAX:
        _summary_cache.popitem(last=False)


@router.get("/api/collection/formats")
async def collection_formats(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    """Return distinct format names from the user's synced collection."""
    if not _pg_pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")

    async with _pg_pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            SELECT DISTINCT f->>'name' AS format_name
            FROM user_collections, jsonb_array_elements(formats) AS f
            WHERE user_id = %s::uuid AND formats IS NOT NULL
            ORDER BY format_name
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    return JSONResponse(content={"formats": [r["format_name"] for r in rows if r["format_name"]]})


@router.get("/api/collection/gaps/label/{label_id}")
async def label_gaps(
    label_id: str,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    exclude_wantlist: bool = Query(False),
    formats: list[str] | None = Query(None),
) -> JSONResponse:
    """Get releases on a label that the user does not own."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")

    metadata = await get_label_metadata(_neo4j_driver, label_id)
    if metadata is None:
        return JSONResponse(content={"error": "Label not found"}, status_code=404)

    summary = _get_cached_summary(user_id, "label", label_id)
    if summary is None:
        summary = await get_label_gap_summary(_neo4j_driver, user_id, label_id)
        _set_cached_summary(user_id, "label", label_id, summary)

    results, total = await get_label_gaps(
        _neo4j_driver,
        user_id,
        label_id,
        limit,
        offset,
        exclude_wantlist,
        formats,
    )

    return JSONResponse(
        content={
            "entity": {"id": metadata["id"], "name": metadata["name"], "type": "label"},
            "summary": summary,
            "filters": {"formats": formats or []},
            "results": results,
            "pagination": {"total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total},
        }
    )


@router.get("/api/collection/gaps/artist/{artist_id}")
async def artist_gaps(
    artist_id: str,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    exclude_wantlist: bool = Query(False),
    formats: list[str] | None = Query(None),
) -> JSONResponse:
    """Get releases by an artist that the user does not own."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")

    metadata = await get_artist_metadata(_neo4j_driver, artist_id)
    if metadata is None:
        return JSONResponse(content={"error": "Artist not found"}, status_code=404)

    summary = _get_cached_summary(user_id, "artist", artist_id)
    if summary is None:
        summary = await get_artist_gap_summary(_neo4j_driver, user_id, artist_id)
        _set_cached_summary(user_id, "artist", artist_id, summary)

    results, total = await get_artist_gaps(
        _neo4j_driver,
        user_id,
        artist_id,
        limit,
        offset,
        exclude_wantlist,
        formats,
    )

    return JSONResponse(
        content={
            "entity": {"id": metadata["id"], "name": metadata["name"], "type": "artist"},
            "summary": summary,
            "filters": {"formats": formats or []},
            "results": results,
            "pagination": {"total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total},
        }
    )


@router.get("/api/collection/gaps/master/{master_id}")
async def master_gaps(
    master_id: str,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    exclude_wantlist: bool = Query(False),
    formats: list[str] | None = Query(None),
) -> JSONResponse:
    """Get pressings of a master release that the user does not own."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")

    metadata = await get_master_metadata(_neo4j_driver, master_id)
    if metadata is None:
        return JSONResponse(content={"error": "Master not found"}, status_code=404)

    summary = _get_cached_summary(user_id, "master", master_id)
    if summary is None:
        summary = await get_master_gap_summary(_neo4j_driver, user_id, master_id)
        _set_cached_summary(user_id, "master", master_id, summary)

    results, total = await get_master_gaps(
        _neo4j_driver,
        user_id,
        master_id,
        limit,
        offset,
        exclude_wantlist,
        formats,
    )

    return JSONResponse(
        content={
            "entity": {"id": metadata["id"], "name": metadata["name"], "type": "master"},
            "summary": summary,
            "filters": {"formats": formats or []},
            "results": results,
            "pagination": {"total": total, "offset": offset, "limit": limit, "has_more": offset + len(results) < total},
        }
    )
