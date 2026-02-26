#!/usr/bin/env python3
"""Explore service for interactive graph exploration of Discogs data."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import uvicorn

from common import (
    AsyncResilientNeo4jDriver,
    ExploreConfig,
    HealthServer,
    setup_logging,
)


logger = structlog.get_logger(__name__)

# CORS origins configurable via environment variable (comma-separated list)
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else None

# Module-level state
neo4j_driver: AsyncResilientNeo4jDriver | None = None
config: ExploreConfig | None = None


def get_health_data() -> dict[str, Any]:
    """Return health check data."""
    return {
        "status": "healthy" if neo4j_driver else "starting",
        "service": "explore",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle."""
    logger.info("🚀 Starting Explore service")

    global neo4j_driver, config
    config = ExploreConfig.from_env()
    logger.info("📋 Configuration loaded from environment")

    # Start health server on separate port
    health_server = HealthServer(8007, get_health_data)
    health_server.start_background()
    logger.info("🏥 Health server started on port 8007")

    # Initialize Neo4j driver
    try:
        neo4j_driver = AsyncResilientNeo4jDriver(
            uri=config.neo4j_address,
            auth=(config.neo4j_username, config.neo4j_password),
            max_retries=5,
            encrypted=False,
        )
        logger.info("🔗 Connected to Neo4j with resilient driver")
    except Exception as e:
        logger.error("❌ Failed to connect to Neo4j", error=str(e))
        raise

    logger.info("✅ Explore service ready")
    yield

    # Shutdown
    logger.info("🛑 Shutting down Explore service")
    if neo4j_driver:
        await neo4j_driver.close()
        logger.info("🔌 Neo4j connection closed")
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


if __name__ == "__main__":
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
        log_level="info",
    )
