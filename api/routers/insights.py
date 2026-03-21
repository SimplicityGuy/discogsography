"""Proxy router for insights service endpoints.

Forwards /api/insights/* requests to the insights microservice
running on port 8008.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx
import structlog


logger = structlog.get_logger(__name__)

router = APIRouter()

_INSIGHTS_BASE_URL = "http://insights:8008"
_client: httpx.AsyncClient | None = None


def configure(insights_base_url: str | None = None) -> None:
    """Configure the insights proxy."""
    global _INSIGHTS_BASE_URL
    if insights_base_url:
        _INSIGHTS_BASE_URL = insights_base_url


async def _forward(request: Request, path: str) -> JSONResponse:
    """Forward a request to the insights service, preserving the status code."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)

    url = f"{_INSIGHTS_BASE_URL}{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    response = await _client.get(url)
    return JSONResponse(content=response.json(), status_code=response.status_code)


@router.get("/api/insights/top-artists")
async def proxy_top_artists(request: Request) -> JSONResponse:
    """Proxy top artists endpoint."""
    try:
        return await _forward(request, "/api/insights/top-artists")
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/genre-trends")
async def proxy_genre_trends(request: Request) -> JSONResponse:
    """Proxy genre trends endpoint."""
    try:
        return await _forward(request, "/api/insights/genre-trends")
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/label-longevity")
async def proxy_label_longevity(request: Request) -> JSONResponse:
    """Proxy label longevity endpoint."""
    try:
        return await _forward(request, "/api/insights/label-longevity")
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/this-month")
async def proxy_this_month(request: Request) -> JSONResponse:
    """Proxy this month endpoint."""
    try:
        return await _forward(request, "/api/insights/this-month")
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/data-completeness")
async def proxy_data_completeness(request: Request) -> JSONResponse:
    """Proxy data completeness endpoint."""
    try:
        return await _forward(request, "/api/insights/data-completeness")
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)


@router.get("/api/insights/status")
async def proxy_status(request: Request) -> JSONResponse:
    """Proxy computation status endpoint."""
    try:
        return await _forward(request, "/api/insights/status")
    except Exception:
        logger.exception("❌ Insights service unavailable")
        return JSONResponse(content={"error": "Insights service unavailable"}, status_code=503)
