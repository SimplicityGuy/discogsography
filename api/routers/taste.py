"""Taste fingerprint endpoints — genre heatmap, obscurity, drift, blind spots."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
import structlog

import api.dependencies as _dependencies
from api.dependencies import require_user
from api.models import (
    BlindSpot,
    FingerprintResponse,
    HeatmapCell,
    HeatmapResponse,
    ObscurityScore,
    TasteDriftYear,
)
from api.queries.taste_queries import (
    get_blind_spots,
    get_collection_count,
    get_obscurity_score,
    get_taste_drift,
    get_taste_heatmap,
    get_top_labels,
)
from api.taste_card import render_taste_card


logger = structlog.get_logger(__name__)

router = APIRouter()

_neo4j_driver: Any = None

_MIN_COLLECTION_ITEMS = 10


def configure(neo4j: Any, jwt_secret: str | None) -> None:
    """Configure the taste router with Neo4j driver and JWT secret."""
    global _neo4j_driver
    _neo4j_driver = neo4j
    _dependencies.configure(jwt_secret)


def _peak_decade(cells: list[dict[str, Any]]) -> int | None:
    """Return the decade with the most releases, or None if no data."""
    if not cells:
        return None
    decade_totals: dict[int, int] = {}
    for cell in cells:
        decade_totals[cell["decade"]] = decade_totals.get(cell["decade"], 0) + cell["count"]
    return max(decade_totals, key=lambda d: decade_totals[d])


async def _check_minimum(driver: Any, user_id: str) -> JSONResponse | None:
    """Return a 422 response if the user's collection is too small, else None."""
    count = await get_collection_count(driver, user_id)
    if count < _MIN_COLLECTION_ITEMS:
        return JSONResponse(
            content={"detail": f"Collection must have at least {_MIN_COLLECTION_ITEMS} items (currently {count})"},
            status_code=422,
        )
    return None


@router.get("/api/user/taste/heatmap")
async def taste_heatmap(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    """Return genre x decade heatmap for the authenticated user."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    err = await _check_minimum(_neo4j_driver, user_id)
    if err:
        return err
    cells, total = await get_taste_heatmap(_neo4j_driver, user_id)
    resp = HeatmapResponse(
        cells=[HeatmapCell(**c) for c in cells],
        total=total,
    )
    return JSONResponse(content=resp.model_dump())


@router.get("/api/user/taste/fingerprint")
async def taste_fingerprint(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    """Return full taste fingerprint combining all sub-queries."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    err = await _check_minimum(_neo4j_driver, user_id)
    if err:
        return err

    heatmap_result, obscurity_result, drift_result, blind_spots_result = await asyncio.gather(
        get_taste_heatmap(_neo4j_driver, user_id),
        get_obscurity_score(_neo4j_driver, user_id),
        get_taste_drift(_neo4j_driver, user_id),
        get_blind_spots(_neo4j_driver, user_id),
    )

    cells, _total = heatmap_result
    resp = FingerprintResponse(
        heatmap=[HeatmapCell(**c) for c in cells],
        obscurity=ObscurityScore(**obscurity_result),
        drift=[TasteDriftYear(**d) for d in drift_result],
        blind_spots=[BlindSpot(**b) for b in blind_spots_result],
        peak_decade=_peak_decade(cells),
    )
    return JSONResponse(content=resp.model_dump())


@router.get("/api/user/taste/blindspots")
async def taste_blindspots(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
    limit: int = Query(5, ge=1, le=20),
) -> JSONResponse:
    """Return genres the user's favourite artists release in but the user hasn't collected."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    err = await _check_minimum(_neo4j_driver, user_id)
    if err:
        return err
    spots = await get_blind_spots(_neo4j_driver, user_id, limit=limit)
    return JSONResponse(content={"blind_spots": [BlindSpot(**b).model_dump() for b in spots]})


@router.get("/api/user/taste/card")
async def taste_card(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> Response:
    """Return an SVG taste card for the authenticated user."""
    if not _neo4j_driver:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)
    user_id: str = current_user.get("sub", "")
    err = await _check_minimum(_neo4j_driver, user_id)
    if err:
        return err

    heatmap_result, obscurity_result, drift_result, labels_result = await asyncio.gather(
        get_taste_heatmap(_neo4j_driver, user_id),
        get_obscurity_score(_neo4j_driver, user_id),
        get_taste_drift(_neo4j_driver, user_id),
        get_top_labels(_neo4j_driver, user_id, limit=5),
    )

    cells, _total = heatmap_result
    svg = render_taste_card(
        peak_decade=_peak_decade(cells),
        obscurity_score=obscurity_result["score"],
        top_genres=[c["genre"] for c in cells[:5]],
        top_labels=[lb["label"] for lb in labels_result],
        drift=[TasteDriftYear(**d) for d in drift_result],
    )
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
