"""MusicBrainz enrichment API endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
import structlog

from api.limiter import limiter
from api.queries.musicbrainz_queries import (
    get_artist_external_links,
    get_artist_mb_relationships,
    get_artist_musicbrainz,
    get_enrichment_status,
)


logger = structlog.get_logger(__name__)
router = APIRouter()

_pool: Any = None
_neo4j_driver: Any = None


def configure(pool: Any, neo4j_driver: Any) -> None:
    """Configure router dependencies."""
    global _pool, _neo4j_driver
    _pool = pool
    _neo4j_driver = neo4j_driver


@router.get("/api/artist/{artist_id}/musicbrainz", status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def artist_musicbrainz(
    request: Request,  # noqa: ARG001 -- required by slowapi
    artist_id: int,
) -> JSONResponse:
    """Get MusicBrainz metadata for a Discogs artist."""
    if _neo4j_driver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    data = await get_artist_musicbrainz(_neo4j_driver, str(artist_id))
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No MusicBrainz data for this artist")
    return JSONResponse(content=data)


@router.get("/api/artist/{artist_id}/relationships", status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def artist_relationships(
    request: Request,  # noqa: ARG001 -- required by slowapi
    artist_id: int,
) -> JSONResponse:
    """Get MusicBrainz-sourced relationships for a Discogs artist."""
    if _neo4j_driver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    relationships = await get_artist_mb_relationships(_neo4j_driver, str(artist_id))
    return JSONResponse(content={"discogs_id": artist_id, "relationships": relationships})


@router.get("/api/artist/{artist_id}/external-links", status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def artist_external_links(
    request: Request,  # noqa: ARG001 -- required by slowapi
    artist_id: int,
) -> JSONResponse:
    """Get external links (Wikipedia, Wikidata, etc.) for a Discogs artist."""
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    links = await get_artist_external_links(_pool, artist_id)
    return JSONResponse(content={"discogs_id": artist_id, "links": links})


@router.get("/api/enrichment/status", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def enrichment_status_endpoint(
    request: Request,  # noqa: ARG001 -- required by slowapi
) -> JSONResponse:
    """Get MusicBrainz enrichment coverage statistics."""
    if _pool is None or _neo4j_driver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    stats = await get_enrichment_status(_pool, _neo4j_driver)
    return JSONResponse(content=stats)
