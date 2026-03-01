"""Curator microservice for discogsography — Discogs collection and wantlist sync."""

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

from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver, HealthServer, setup_logging
from common.config import CuratorConfig


logger = structlog.get_logger(__name__)

_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins: list[str] | None = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else None

# Module-level state
_pool: AsyncPostgreSQLPool | None = None
_neo4j: AsyncResilientNeo4jDriver | None = None
_config: CuratorConfig | None = None

CURATOR_PORT = 8010
CURATOR_HEALTH_PORT = 8011


def get_health_data() -> dict[str, Any]:
    """Return health status for the curator service."""
    return {
        "status": "healthy" if _pool and _neo4j else "starting",
        "service": "curator",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage curator service lifecycle."""
    global _pool, _neo4j, _config

    logger.info("🚀 Curator service starting...")
    _config = CuratorConfig.from_env()

    # Start health server on separate port
    health_srv = HealthServer(CURATOR_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("🏥 Health server started", port=CURATOR_HEALTH_PORT)

    # PostgreSQL connection pool
    host, port_str = _config.postgres_host.rsplit(":", 1)
    _pool = AsyncPostgreSQLPool(
        connection_params={
            "host": host,
            "port": int(port_str),
            "dbname": _config.postgres_database,
            "user": _config.postgres_username,
            "password": _config.postgres_password,
        },
        max_connections=5,
        min_connections=1,
    )
    await _pool.initialize()
    logger.info("💾 Database pool initialized")

    # Neo4j connection
    _neo4j = AsyncResilientNeo4jDriver(
        uri=_config.neo4j_host,
        auth=(_config.neo4j_username, _config.neo4j_password),
        max_retries=5,
        encrypted=False,
    )
    logger.info("🔗 Neo4j driver initialized")
    logger.info("✅ Curator service ready", port=CURATOR_PORT)

    yield

    logger.info("🔧 Curator service shutting down...")
    if _pool:
        await _pool.close()
    if _neo4j:
        await _neo4j.close()
    health_srv.stop()
    logger.info("✅ Curator service stopped")


app = FastAPI(
    title="Discogsography Curator",
    version="0.1.0",
    description="Curator service for Discogsography",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3000", "http://localhost:8003"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Service health check endpoint."""
    return JSONResponse(content=get_health_data())


def main() -> None:
    """Entry point for the curator service."""
    setup_logging("curator", log_file=Path("/logs/curator.log"))
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝")
    print()
    print(" ██████╗██╗   ██╗██████╗  █████╗ ████████╗ ██████╗ ██████╗ ")
    print("██╔════╝██║   ██║██╔══██╗██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗")
    print("██║     ██║   ██║██████╔╝███████║   ██║   ██║   ██║██████╔╝")
    print("██║     ██║   ██║██╔══██╗██╔══██║   ██║   ██║   ██║██╔══██╗")
    print("╚██████╗╚██████╔╝██║  ██║██║  ██║   ██║   ╚██████╔╝██║  ██║")
    print(" ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝")
    print()
    # fmt: on
    uvicorn.run(app, host="0.0.0.0", port=CURATOR_PORT)  # noqa: S104  # nosec B104


if __name__ == "__main__":
    main()
