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
from fastapi.responses import JSONResponse, Response, StreamingResponse
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

    # Initialize HTTP client during startup to avoid lazy-init race condition
    global _http_client
    _http_client = httpx.AsyncClient(base_url=_api_base_url, timeout=150.0)

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
    allow_credentials=True,
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(content=get_health_data())


_PROXY_SKIP_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})

# Content-Type prefix used by sse_starlette's EventSourceResponse (see
# api/routers/nlq.py) for the NLQ 'Ask' streaming endpoint.
_STREAMING_CONTENT_TYPE_PREFIX = "text/event-stream"

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        msg = "HTTP client not initialized — service not started"
        raise RuntimeError(msg)
    return _http_client


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(path: str, request: Request) -> Response:
    """Proxy /api/* requests to the API service.

    Uses a streamed httpx request/response instead of the non-streaming
    client.request()/.content, which used to buffer the ENTIRE upstream body
    before returning. That broke Server-Sent-Event endpoints (e.g. the NLQ 'Ask'
    endpoint /api/nlq/query): events were held back until the whole stream
    finished, and a long-running answer that went quiet between events for
    longer than the client's fixed total timeout was aborted with a 504,
    discarding an otherwise-successful response. text/event-stream responses are
    now forwarded chunk-by-chunk via StreamingResponse with the read timeout
    disabled; every other response is still read fully and returned as before.
    """
    client = _get_http_client()
    url = f"/api/{path}"
    forward_headers = {k: v for k, v in request.headers.items() if k.lower() not in _PROXY_SKIP_HEADERS}

    req = client.build_request(
        method=request.method,
        url=url,
        # request.query_params is a Starlette multi-dict — wrapping it in
        # dict() keeps only the LAST value per repeated key (e.g.
        # ?formats=Vinyl&formats=CD collapses to formats=CD), silently
        # dropping multi-value filters. Build an httpx.QueryParams from
        # the multi-item list so every repeated key is preserved.
        params=httpx.QueryParams(tuple(request.query_params.multi_items())),
        content=await request.body(),
        headers=forward_headers,
        # Disable the read timeout: an SSE response may legitimately go quiet
        # between events for longer than the client's total 150s timeout without
        # being stalled (e.g. a long Anthropic generation phase). Connect/write/pool
        # timeouts are unchanged so a genuinely dead upstream is still caught.
        timeout=httpx.Timeout(150.0, read=None),
    )

    try:
        proxied = await client.send(req, stream=True)
    except httpx.TimeoutException:
        logger.warning("⚠️ Proxy request timed out", path=path)
        return JSONResponse(content={"error": "Request timed out"}, status_code=504)
    except httpx.HTTPError as exc:
        logger.error("❌ Proxy request failed", path=path, error=str(exc))
        return JSONResponse(content={"error": "Upstream service error"}, status_code=502)

    skip_response_headers = {"content-encoding", "transfer-encoding", "content-length"}
    response_headers = {k: v for k, v in proxied.headers.items() if k.lower() not in skip_response_headers}
    content_type = proxied.headers.get("content-type", "")

    if content_type.startswith(_STREAMING_CONTENT_TYPE_PREFIX):

        async def _forward_stream() -> AsyncGenerator[bytes]:
            try:
                async for chunk in proxied.aiter_raw():
                    yield chunk
            except httpx.HTTPError as exc:
                logger.warning("⚠️ Proxy stream interrupted", path=path, error=str(exc))
            finally:
                await proxied.aclose()

        return StreamingResponse(_forward_stream(), status_code=proxied.status_code, headers=response_headers, media_type=content_type)

    try:
        await proxied.aread()
    except httpx.TimeoutException:
        await proxied.aclose()
        logger.warning("⚠️ Proxy request timed out", path=path)
        return JSONResponse(content={"error": "Request timed out"}, status_code=504)
    except httpx.HTTPError as exc:
        await proxied.aclose()
        logger.error("❌ Proxy request failed", path=path, error=str(exc))
        return JSONResponse(content={"error": "Upstream service error"}, status_code=502)
    await proxied.aclose()

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
