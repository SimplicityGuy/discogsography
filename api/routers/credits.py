"""Credits & Provenance endpoints — the people behind the music."""

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
import structlog

from api.limiter import limiter
from api.models import (
    ConnectionEntry,
    CreditEntry,
    LeaderboardEntry,
    PersonAutocompleteEntry,
    PersonConnectionsResponse,
    PersonCreditsResponse,
    PersonProfileResponse,
    PersonTimelineResponse,
    ReleaseCreditEntry,
    ReleaseCreditsResponse,
    RoleLeaderboardResponse,
    SharedCreditEntry,
    SharedCreditsResponse,
    TimelineEntry,
)
from api.queries.credits_queries import (
    autocomplete_person,
    get_person_connections,
    get_person_credits,
    get_person_profile,
    get_person_role_breakdown,
    get_person_timeline,
    get_release_credits,
    get_role_leaderboard,
    get_shared_credits,
)
from common.credit_roles import ALL_CATEGORIES


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None
_redis: Any = None

# Redis cache TTL for credits (24 hours — data changes only on import)
_CREDITS_CACHE_TTL = 86400


def configure(neo4j: Any, redis: Any = None) -> None:
    global _neo4j_driver, _redis
    _neo4j_driver = neo4j
    _redis = redis


# ── Person sub-routes MUST be declared before the catch-all {name} route ──


@router.get("/api/credits/person/{name}/timeline")
@limiter.limit("60/minute")
async def person_timeline(
    request: Request,  # noqa: ARG001 -- required by slowapi
    name: str,
) -> JSONResponse:
    """Credits over time — year-by-year activity."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    records = await get_person_timeline(_neo4j_driver, name)
    if not records:
        return JSONResponse(content={"error": f"No timeline data for '{name}'"}, status_code=404)

    timeline = [TimelineEntry(year=r["year"], category=r["category"], count=r["count"]) for r in records]
    response = PersonTimelineResponse(name=name, timeline=timeline)
    return JSONResponse(content=response.model_dump())


@router.get("/api/credits/person/{name}/profile")
@limiter.limit("60/minute")
async def person_profile(
    request: Request,  # noqa: ARG001 -- required by slowapi
    name: str,
) -> JSONResponse:
    """Summary profile for a credited person."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    profile = await get_person_profile(_neo4j_driver, name)
    if not profile:
        return JSONResponse(content={"error": f"Person '{name}' not found"}, status_code=404)

    role_breakdown = await get_person_role_breakdown(_neo4j_driver, name)

    response = PersonProfileResponse(
        name=profile["name"],
        total_credits=profile["total_credits"],
        categories=profile["categories"] or [],
        first_year=profile["first_year"],
        last_year=profile["last_year"],
        artist_id=profile["artist_id"],
        artist_name=profile["artist_name"],
        role_breakdown=[{"category": r["category"], "count": r["count"]} for r in role_breakdown],
    )
    return JSONResponse(content=response.model_dump())


@router.get("/api/credits/person/{name}")
@limiter.limit("60/minute")
async def person_credits(
    request: Request,  # noqa: ARG001 -- required by slowapi
    name: str,
) -> JSONResponse:
    """All releases a person is credited on, grouped by role."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = f"credits:person:{name}"
    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Credits person cache get failed", key=cache_key)

    records = await get_person_credits(_neo4j_driver, name)
    if not records:
        return JSONResponse(content={"error": f"No credits found for '{name}'"}, status_code=404)

    credits = [
        CreditEntry(
            release_id=r["release_id"],
            title=r["title"] or "Unknown",
            year=r["year"],
            role=r["role"],
            category=r["category"],
            artists=r["artists"] or [],
            labels=r["labels"] or [],
        )
        for r in records
    ]
    response = PersonCreditsResponse(name=name, total_credits=len(credits), credits=credits)
    response_data = response.model_dump()

    if _redis:
        try:
            await _redis.setex(cache_key, _CREDITS_CACHE_TTL, json.dumps(response_data, default=str))
        except Exception:
            logger.debug("⚠️ Credits person cache set failed", key=cache_key)

    return JSONResponse(content=response_data)


@router.get("/api/credits/release/{release_id}")
@limiter.limit("60/minute")
async def release_credits(
    request: Request,  # noqa: ARG001 -- required by slowapi
    release_id: str,
) -> JSONResponse:
    """Full credits breakdown for a release."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    records = await get_release_credits(_neo4j_driver, release_id)
    if not records:
        return JSONResponse(content={"error": f"No credits found for release '{release_id}'"}, status_code=404)

    credits = [
        ReleaseCreditEntry(
            name=r["name"],
            role=r["role"],
            category=r["category"],
            artist_id=r["artist_id"],
            artist_name=r["artist_name"],
        )
        for r in records
    ]
    response = ReleaseCreditsResponse(release_id=release_id, credits=credits)
    return JSONResponse(content=response.model_dump())


@router.get("/api/credits/role/{role}/top")
@limiter.limit("30/minute")
async def role_leaderboard(
    request: Request,  # noqa: ARG001 -- required by slowapi
    role: str,
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Most prolific people in a given role category."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    if role not in ALL_CATEGORIES:
        return JSONResponse(
            content={"error": f"Invalid role category '{role}'. Valid: {', '.join(ALL_CATEGORIES)}"},
            status_code=400,
        )

    cache_key = f"credits:leaderboard:{role}:{limit}"
    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Credits leaderboard cache get failed", key=cache_key)

    records = await get_role_leaderboard(_neo4j_driver, role, limit)
    entries = [LeaderboardEntry(name=r["name"], credit_count=r["credit_count"]) for r in records]
    response = RoleLeaderboardResponse(category=role, entries=entries)
    response_data = response.model_dump()

    if _redis:
        try:
            await _redis.setex(cache_key, _CREDITS_CACHE_TTL, json.dumps(response_data, default=str))
        except Exception:
            logger.debug("⚠️ Credits leaderboard cache set failed", key=cache_key)

    return JSONResponse(content=response_data)


@router.get("/api/credits/shared")
@limiter.limit("30/minute")
async def shared_credits(
    request: Request,  # noqa: ARG001 -- required by slowapi
    person1: str = Query(..., description="First person name"),
    person2: str = Query(..., description="Second person name"),
) -> JSONResponse:
    """Releases where two people are both credited."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    records = await get_shared_credits(_neo4j_driver, person1, person2)
    shared = [
        SharedCreditEntry(
            release_id=r["release_id"],
            title=r["title"] or "Unknown",
            year=r["year"],
            person1_role=r["person1_role"],
            person2_role=r["person2_role"],
            artists=r["artists"] or [],
        )
        for r in records
    ]
    response = SharedCreditsResponse(person1=person1, person2=person2, shared_releases=shared)
    return JSONResponse(content=response.model_dump())


@router.get("/api/credits/connections/{name}")
@limiter.limit("30/minute")
async def person_connections(
    request: Request,  # noqa: ARG001 -- required by slowapi
    name: str,
    depth: int = Query(2, ge=1, le=3),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    """People connected through shared releases (collaboration graph)."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    records = await get_person_connections(_neo4j_driver, name, depth, limit)
    connections = [ConnectionEntry(name=r["name"], shared_count=r["shared_count"]) for r in records]
    response = PersonConnectionsResponse(name=name, connections=connections)
    return JSONResponse(content=response.model_dump())


@router.get("/api/credits/autocomplete")
@limiter.limit("120/minute")
async def credits_autocomplete(
    request: Request,  # noqa: ARG001 -- required by slowapi
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    """Search credits by person name."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    records = await autocomplete_person(_neo4j_driver, q, limit)
    results = [PersonAutocompleteEntry(name=r["name"], score=r["score"]) for r in records]
    return JSONResponse(content={"results": [r.model_dump() for r in results]})
