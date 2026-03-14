"""Search endpoint -- unified full-text search across all entity types."""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
import structlog

from api.limiter import limiter
from api.queries.search_queries import ALL_TYPES, execute_search


logger = structlog.get_logger(__name__)

router = APIRouter()

_pool: Any = None
_redis: Any = None


def configure(pool: Any, redis: Any) -> None:
    """Wire database pool and Redis client into the search router."""
    global _pool, _redis
    _pool = pool
    _redis = redis


_VALID_TYPES = set(ALL_TYPES)


@router.get("/api/search")
@limiter.limit("30/minute")
async def search(
    request: Request,  # noqa: ARG001 -- required by slowapi
    q: str = Query(..., min_length=3, description="Search query (minimum 3 characters)"),
    types: str = Query(
        default="artist,label,master,release",
        description="Comma-separated entity types to search",
    ),
    genres: str = Query(default="", description="Comma-separated genre filter"),
    year_min: int | None = Query(default=None, ge=1000, le=9999, description="Minimum release year"),
    year_max: int | None = Query(default=None, ge=1000, le=9999, description="Maximum release year"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> JSONResponse:
    """Search across artists, labels, masters, and releases using PostgreSQL full-text search.

    Returns relevance-ranked results with facet counts and result highlighting.
    Results are cached in Redis for 5 minutes.
    Rate limited to 30 requests/minute.
    """
    if _pool is None:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    # Parse and validate types
    requested_types = [t.strip().lower() for t in types.split(",") if t.strip()]
    if not requested_types:
        requested_types = list(ALL_TYPES)
    invalid = [t for t in requested_types if t not in _VALID_TYPES]
    if invalid:
        return JSONResponse(
            content={"error": f"Invalid type(s): {', '.join(invalid)}. Valid: {', '.join(sorted(_VALID_TYPES))}"},
            status_code=400,
        )

    # Parse genre filter
    genre_list = [g.strip() for g in genres.split(",") if g.strip()] if genres else []

    logger.debug("Search request", q=q, types=requested_types, genres=genre_list, year_min=year_min, year_max=year_max)

    result = await execute_search(
        pool=_pool,
        redis=_redis,
        q=q,
        types=requested_types,
        genres=genre_list,
        year_min=year_min,
        year_max=year_max,
        limit=limit,
        offset=offset,
    )

    return JSONResponse(content=result)
