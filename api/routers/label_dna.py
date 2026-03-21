"""Label DNA endpoints — fingerprint and compare record labels."""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
import structlog

from api.limiter import limiter
from api.models import (
    DecadeCount,
    FormatWeight,
    GenreWeight,
    LabelCompareEntry,
    LabelCompareResponse,
    LabelDNA,
    SimilarLabel,
    SimilarLabelsResponse,
    StyleWeight,
)
from api.queries.label_dna_queries import (
    MIN_RELEASES,
    compute_similar_labels,
    get_candidate_labels_genre_vectors,
    get_label_active_years,
    get_label_decade_profile,
    get_label_format_profile,
    get_label_genre_profile,
    get_label_identity,
    get_label_style_profile,
)


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None
_redis: Any = None

# Redis cache TTL for label DNA (24 hours — data changes only on import)
_LABEL_DNA_CACHE_TTL = 86400


def configure(neo4j: Any, redis: Any = None) -> None:
    global _neo4j_driver, _redis
    _neo4j_driver = neo4j
    _redis = redis


def _add_percentages(items: list[dict[str, Any]], total: int) -> list[dict[str, Any]]:
    """Add percentage field to each item based on total."""
    return [{**item, "percentage": round(item["count"] / total * 100, 1) if total else 0.0} for item in items]


async def _build_dna(label_id: str) -> tuple[LabelDNA | None, str]:
    """Build a full LabelDNA fingerprint for a label.

    Returns (dna, reason) — reason is "ok", "not_found", or "too_few".
    """
    identity = await get_label_identity(_neo4j_driver, label_id)
    if not identity:
        return None, "not_found"

    if identity["release_count"] < MIN_RELEASES:
        return None, "too_few"

    genres, styles, decades, active_years, formats = await asyncio.gather(
        get_label_genre_profile(_neo4j_driver, label_id),
        get_label_style_profile(_neo4j_driver, label_id),
        get_label_decade_profile(_neo4j_driver, label_id),
        get_label_active_years(_neo4j_driver, label_id),
        get_label_format_profile(_neo4j_driver, label_id),
    )

    release_count = identity["release_count"]
    artist_count = identity["artist_count"]

    # Artist diversity: unique artists / total releases (capped at 1.0)
    artist_diversity = round(min(artist_count / release_count, 1.0), 4) if release_count else 0.0

    # Peak decade
    peak_decade = max(decades, key=lambda d: d["count"])["decade"] if decades else None

    # Prolificacy: releases per active year
    num_active_years = len(active_years)
    prolificacy = round(release_count / num_active_years, 2) if num_active_years else 0.0

    # Total counts for percentage calculation
    genre_total = sum(g["count"] for g in genres)
    style_total = sum(s["count"] for s in styles)
    decade_total = sum(d["count"] for d in decades)
    format_total = sum(f["count"] for f in formats)

    return LabelDNA(
        label_id=identity["label_id"],
        label_name=identity["label_name"],
        release_count=release_count,
        artist_count=artist_count,
        artist_diversity=artist_diversity,
        active_years=active_years,
        peak_decade=peak_decade,
        prolificacy=prolificacy,
        genres=[GenreWeight(**g) for g in _add_percentages(genres, genre_total)],
        styles=[StyleWeight(**s) for s in _add_percentages(styles, style_total)],
        formats=[FormatWeight(**f) for f in _add_percentages(formats, format_total)],
        decades=[DecadeCount(**d) for d in _add_percentages(decades, decade_total)],
    ), "ok"


@router.get("/api/label/{label_id}/dna")
@limiter.limit("30/minute")
async def label_dna(
    request: Request,  # noqa: ARG001 -- required by slowapi
    label_id: str,
) -> JSONResponse:
    """Get the full DNA fingerprint for a label."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    # Check Redis cache first
    cache_key = f"label-dna:{label_id}"
    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Label DNA cache get failed", key=cache_key)

    dna, reason = await _build_dna(label_id)
    if dna is None:
        if reason == "not_found":
            return JSONResponse(content={"error": f"Label '{label_id}' not found"}, status_code=404)
        return JSONResponse(
            content={"error": f"Label '{label_id}' has fewer than {MIN_RELEASES} releases"},
            status_code=422,
        )

    response = dna.model_dump()

    # Cache the result
    if _redis:
        try:
            await _redis.setex(cache_key, _LABEL_DNA_CACHE_TTL, json.dumps(response, default=str))
        except Exception:
            logger.debug("⚠️ Label DNA cache set failed", key=cache_key)

    return JSONResponse(content=response)


@router.get("/api/label/{label_id}/similar")
@limiter.limit("30/minute")
async def similar_labels(
    request: Request,  # noqa: ARG001 -- required by slowapi
    label_id: str,
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    """Find labels with the closest DNA fingerprint to the given label."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    # Check Redis cache first (keyed by label_id + limit)
    cache_key = f"label-similar:{label_id}:{limit}"
    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return JSONResponse(content=json.loads(cached))
        except Exception:
            logger.debug("⚠️ Label similar cache get failed", key=cache_key)

    identity = await get_label_identity(_neo4j_driver, label_id)
    if not identity:
        return JSONResponse(content={"error": f"Label '{label_id}' not found"}, status_code=404)

    if identity["release_count"] < MIN_RELEASES:
        return JSONResponse(
            content={"error": f"Label '{label_id}' has fewer than {MIN_RELEASES} releases"},
            status_code=422,
        )

    target_genres, candidates = await asyncio.gather(
        get_label_genre_profile(_neo4j_driver, label_id),
        get_candidate_labels_genre_vectors(_neo4j_driver, label_id),
    )

    ranked = compute_similar_labels(target_genres, candidates, limit=limit)

    response = SimilarLabelsResponse(
        label_id=identity["label_id"],
        label_name=identity["label_name"],
        similar=[SimilarLabel(**r) for r in ranked],
    )
    response_data = response.model_dump()

    # Cache the result
    if _redis:
        try:
            await _redis.setex(cache_key, _LABEL_DNA_CACHE_TTL, json.dumps(response_data, default=str))
        except Exception:
            logger.debug("⚠️ Label similar cache set failed", key=cache_key)

    return JSONResponse(content=response_data)


@router.get("/api/label/dna/compare")
@limiter.limit("30/minute")
async def compare_labels(
    request: Request,  # noqa: ARG001 -- required by slowapi
    ids: str = Query(..., description="Comma-separated label IDs (2-5)"),
) -> JSONResponse:
    """Side-by-side DNA comparison of multiple labels."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    label_ids = [lid.strip() for lid in ids.split(",") if lid.strip()]
    if len(label_ids) < 2:
        return JSONResponse(content={"error": "At least 2 label IDs required"}, status_code=400)
    if len(label_ids) > 5:
        return JSONResponse(content={"error": "At most 5 label IDs allowed"}, status_code=400)

    dna_results = await asyncio.gather(*[_build_dna(lid) for lid in label_ids])

    entries = []
    for lid, (dna, reason) in zip(label_ids, dna_results, strict=True):
        if dna is None:
            if reason == "not_found":
                return JSONResponse(content={"error": f"Label '{lid}' not found"}, status_code=404)
            return JSONResponse(
                content={"error": f"Label '{lid}' has fewer than {MIN_RELEASES} releases"},
                status_code=422,
            )
        entries.append(LabelCompareEntry(dna=dna))

    response = LabelCompareResponse(labels=entries)
    return JSONResponse(content=response.model_dump())
