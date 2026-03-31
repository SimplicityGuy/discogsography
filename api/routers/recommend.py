"""Recommend endpoints — artist similarity, explore from here, enhanced recommendations."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
import structlog

from api.cache import RecommendCache
from api.dependencies import require_user
from api.limiter import limiter
from api.models import (
    DiscoveryNode,
    EntityRef,
    ExploreFromHereResponse,
    SimilarArtist,
    SimilarArtistsResponse,
)
from api.queries.recommend_queries import (
    MIN_ARTIST_RELEASES,
    compute_similar_artists,
    get_artist_identity,
    get_artist_profile,
    get_candidate_artists,
    get_explore_traversal,
    score_discoveries,
)
from api.queries.taste_queries import get_blind_spots, get_taste_heatmap


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None
_cache: RecommendCache | None = None


def configure(neo4j: Any, jwt_secret: str | None, redis: Any | None) -> None:  # noqa: ARG001
    """Configure the recommend router with Neo4j driver, JWT secret, and Redis cache."""
    global _neo4j_driver, _cache
    _neo4j_driver = neo4j
    if redis is not None:
        _cache = RecommendCache(redis=redis, default_ttl=3600)


_VALID_ENTITY_TYPES = {"artist", "label", "genre", "style"}

_SIMILARITY_CACHE_TTL = 86400  # 24 hours
_EXPLORE_CACHE_TTL = 3600  # 1 hour


@router.get("/api/recommend/similar/artist/{artist_id}")
@limiter.limit("30/minute")
async def similar_artists(
    request: Request,  # noqa: ARG001 -- required by slowapi
    artist_id: str,
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    """Find artists with the closest multi-dimensional similarity to the given artist."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    # Check cache
    cache_key = f"recommend:similar:artist:{artist_id}"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            cached["similar"] = cached["similar"][:limit]
            return JSONResponse(content=cached)

    identity = await get_artist_identity(_neo4j_driver, artist_id)
    if not identity:
        return JSONResponse(content={"error": f"Artist '{artist_id}' not found"}, status_code=404)

    if identity["release_count"] < MIN_ARTIST_RELEASES:
        return JSONResponse(
            content={"error": f"Artist '{artist_id}' has fewer than {MIN_ARTIST_RELEASES} releases"},
            status_code=422,
        )

    target_profile, candidates = await asyncio.gather(
        get_artist_profile(_neo4j_driver, artist_id),
        get_candidate_artists(_neo4j_driver, artist_id),
    )

    ranked = compute_similar_artists(target_profile, candidates, limit=50)

    response = SimilarArtistsResponse(
        artist_id=identity["artist_id"],
        artist_name=identity["artist_name"],
        similar=[SimilarArtist(**r) for r in ranked],
    )
    response_data = response.model_dump()

    if _cache:
        await _cache.set(cache_key, response_data, ttl=_SIMILARITY_CACHE_TTL)

    response_data["similar"] = response_data["similar"][:limit]
    return JSONResponse(content=response_data)


@router.get("/api/recommend/explore/{entity_type}/{entity_id}")
@limiter.limit("30/minute")
async def explore_from_here(
    request: Request,  # noqa: ARG001 -- required by slowapi
    entity_type: str,
    entity_id: str,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    hops: int = Query(2, ge=1, le=3),
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    """Personalized multi-hop traversal from an entity, ranked by user taste."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    if entity_type not in _VALID_ENTITY_TYPES:
        return JSONResponse(
            content={"error": f"Invalid entity_type '{entity_type}'. Must be one of: {', '.join(sorted(_VALID_ENTITY_TYPES))}"},
            status_code=400,
        )

    user_id: str = current_user.get("sub", "")

    # Check cache
    cache_key = f"recommend:explore:{user_id}:{entity_type}:{entity_id}"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            cached["discoveries"] = cached["discoveries"][:limit]
            return JSONResponse(content=cached)

    # Run traversal and user taste queries in parallel
    traversal_results, heatmap_result, blind_spots_raw = await asyncio.gather(
        get_explore_traversal(_neo4j_driver, entity_type, entity_id, hops=hops),
        get_taste_heatmap(_neo4j_driver, user_id),
        get_blind_spots(_neo4j_driver, user_id),
    )

    # Build flat genre vector from heatmap (aggregate across decades)
    cells, _total = heatmap_result
    genre_counts: dict[str, int] = {}
    for cell in cells:
        genre_counts[cell["genre"]] = genre_counts.get(cell["genre"], 0) + cell["count"]
    total_genre = sum(genre_counts.values())
    user_genre_vector = {g: c / total_genre for g, c in genre_counts.items()} if total_genre else {}

    blind_spot_genres = {bs["genre"] for bs in blind_spots_raw}

    scored = score_discoveries(traversal_results, user_genre_vector, blind_spot_genres, limit=50)

    # Determine the starting entity name from the first path element or use entity_id
    from_name = entity_id
    if traversal_results and traversal_results[0].get("path_names"):
        from_name = str(traversal_results[0]["path_names"][0])

    response = ExploreFromHereResponse.model_validate(
        {
            "from": EntityRef(id=entity_id, name=from_name, type=entity_type),
            "discoveries": [DiscoveryNode(**s) for s in scored],
        }
    )
    response_data = response.model_dump(by_alias=True)

    if _cache:
        await _cache.set(cache_key, response_data, ttl=_EXPLORE_CACHE_TTL)

    response_data["discoveries"] = response_data["discoveries"][:limit]
    return JSONResponse(content=response_data)
