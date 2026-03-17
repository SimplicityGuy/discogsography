#!/usr/bin/env python3
"""Explore service for interactive graph exploration of Discogs data."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import httpx
import structlog
import uvicorn

from common import (
    HealthServer,
    setup_logging,
)


logger = structlog.get_logger(__name__)

# CORS origins configurable via environment variable (comma-separated list)
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else None

# API service base URL for proxying /api/* requests
_api_base_url = os.environ.get("API_BASE_URL", "http://api:8004")


def get_health_data() -> dict[str, Any]:
    """Return health check data."""
    return {
        "status": "healthy",
        "service": "explore",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
    logger.info("🚀 Starting Explore service")

    # Start health server on separate port
    health_server = HealthServer(8007, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8007")

    logger.info("✅ Explore service ready")
    yield

    # Shutdown
    logger.info("🛑 Shutting down Explore service")
    if _http_client is not None:
        await _http_client.aclose()
    health_server.stop()
    logger.info("✅ Explore service shutdown complete")


app = FastAPI(
    title="Discogsography Explore",
    version="0.1.0",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3000", "http://localhost:8003"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(content=get_health_data())


_PROXY_SKIP_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(base_url=_api_base_url, timeout=90.0)
    return _http_client


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(path: str, request: Request) -> Response:
    """Proxy /api/* requests to the API service."""
    client = _get_http_client()
    url = f"/api/{path}"
    forward_headers = {k: v for k, v in request.headers.items() if k.lower() not in _PROXY_SKIP_HEADERS}
    try:
        proxied = await client.request(
            method=request.method,
            url=url,
            params=dict(request.query_params),
            content=await request.body(),
            headers=forward_headers,
        )
    except httpx.TimeoutException:
        logger.warning("⏱️ Proxy request timed out", path=path)
        return JSONResponse(content={"error": "Request timed out"}, status_code=504)
    except httpx.HTTPError as exc:
        logger.error("❌ Proxy request failed", path=path, error=str(exc))
        return JSONResponse(content={"error": "Upstream service error"}, status_code=502)
    skip_response_headers = {"content-encoding", "transfer-encoding", "content-length"}
    response_headers = {k: v for k, v in proxied.headers.items() if k.lower() not in skip_response_headers}
    return Response(content=proxied.content, status_code=proxied.status_code, headers=response_headers)


# Serve UI — must be mounted after all API routes so /health and /api/* take priority
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")


def main() -> None:  # pragma: no cover
    """Entry point for the Explore service."""
    setup_logging("explore", log_file=Path("/logs/explore.log"))
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗               ")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝               ")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗               ")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║               ")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║               ")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝               ")
    print("                                                                     ")
    print("███████╗██╗  ██╗██████╗ ██╗      ██████╗ ██████╗ ███████╗            ")
    print("██╔════╝╚██╗██╔╝██╔══██╗██║     ██╔═══██╗██╔══██╗██╔════╝            ")
    print("█████╗   ╚███╔╝ ██████╔╝██║     ██║   ██║██████╔╝█████╗              ")
    print("██╔══╝   ██╔██╗ ██╔═══╝ ██║     ██║   ██║██╔══██╗██╔══╝              ")
    print("███████╗██╔╝ ██╗██║     ███████╗╚██████╔╝██║  ██║███████╗            ")
    print("╚══════╝╚═╝  ╚═╝╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝            ")
    print()
    # fmt: on
    uvicorn.run(
        "explore.explore:app",
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8006,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
    )


if __name__ == "__main__":
    main()
