"""Insights microservice — precomputed analytics and music trends.

Runs scheduled batch computations by fetching raw query results
from the API service over HTTP, stores precomputed results in
insights.* PostgreSQL tables, and exposes them via read-only
API endpoints.
"""

import asyncio
from collections.abc import AsyncGenerator
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import httpx
import redis.asyncio as aioredis
import structlog
import uvicorn

from common import AsyncPostgreSQLPool, HealthServer, setup_logging
from common.config import InsightsConfig
from insights.cache import InsightsCache
from insights.computations import run_all_computations
from insights.models import (
    AnniversaryItem,
    ArtistCentralityItem,
    ComputationStatus,
    DataCompletenessItem,
    GenreTrendItem,
    GenreTrendsResponse,
    LabelLongevityItem,
)


logger = structlog.get_logger(__name__)

INSIGHTS_PORT = 8008
INSIGHTS_HEALTH_PORT = 8009

# Module-level state
_config: InsightsConfig | None = None
_pool: AsyncPostgreSQLPool | None = None
_http_client: httpx.AsyncClient | None = None
_redis: aioredis.Redis | None = None
_cache: InsightsCache | None = None
_scheduler_task: asyncio.Task[None] | None = None
_last_computation: datetime | None = None


def get_health_data() -> dict[str, Any]:
    """Return health data for the health server."""
    return {
        "service": "insights",
        "status": "healthy" if _pool and _http_client else "starting",
        "timestamp": datetime.now(UTC).isoformat(),
        "last_computation": _last_computation.isoformat() if _last_computation else None,
    }


async def _scheduler_loop(
    client: httpx.AsyncClient,
    pool: Any,
    interval_hours: int = 24,
    milestone_years: list[int] | None = None,
    cache: Any | None = None,
) -> None:
    """Run insight computations on a recurring schedule."""
    global _last_computation
    interval_seconds = interval_hours * 3600

    while True:
        try:
            logger.info("Scheduler: starting insight computations...")
            await run_all_computations(client, pool, milestone_years=milestone_years)
            _last_computation = datetime.now(UTC)
            if cache:
                await cache.invalidate_all()
                logger.info("Scheduler: cache invalidated after computation")
            logger.info("Scheduler: computations complete", next_run_hours=interval_hours)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler: computation cycle failed, will retry next interval")

        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage service lifecycle — connect to databases and start scheduler."""
    global _config, _pool, _http_client, _redis, _cache, _scheduler_task

    setup_logging("insights", log_file=Path("/logs/insights.log"))
    logger.info("Insights service starting...")

    _config = InsightsConfig.from_env()

    # Start health server
    health_srv = HealthServer(INSIGHTS_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("Health server started", port=INSIGHTS_HEALTH_PORT)

    # Initialize PostgreSQL
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
    logger.info("PostgreSQL pool initialized")

    # Initialize HTTP client for API service
    _http_client = httpx.AsyncClient(base_url=_config.api_base_url, timeout=90.0)
    logger.info("API HTTP client initialized", base_url=_config.api_base_url)

    # Initialize Redis cache
    try:
        _redis = await aioredis.from_url(_config.redis_host, decode_responses=True)
        await _redis.ping()  # type: ignore[misc]  # redis.asyncio typing limitation
        ttl_seconds = _config.schedule_hours * 3600
        _cache = InsightsCache(_redis, ttl_seconds=ttl_seconds)
        logger.info("Redis cache initialized", ttl_hours=_config.schedule_hours)
    except Exception:
        logger.warning("Redis unavailable — caching disabled, falling back to PostgreSQL")
        _redis = None
        _cache = None

    # Start scheduler
    _scheduler_task = asyncio.create_task(
        _scheduler_loop(
            _http_client,
            _pool,
            interval_hours=_config.schedule_hours,
            milestone_years=list(_config.milestone_years),
            cache=_cache,
        )
    )
    logger.info("Scheduler started", interval_hours=_config.schedule_hours)

    logger.info("Insights service ready", port=INSIGHTS_PORT)
    yield

    # Shutdown
    logger.info("Insights service shutting down...")
    if _scheduler_task:
        _scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _scheduler_task
    if _redis:
        await _redis.aclose()
    if _http_client:
        await _http_client.aclose()
    if _pool:
        await _pool.close()
    health_srv.stop()
    logger.info("Insights service stopped")


app = FastAPI(
    title="Discogsography Insights",
    version="0.1.0",
    description="Precomputed analytics and music trends",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Service health check endpoint."""
    return JSONResponse(content=get_health_data())


@app.get("/api/insights/top-artists")
async def top_artists(
    limit: int = Query(100, ge=1, le=500),
    metric: str = Query("centrality"),
) -> JSONResponse:
    """Return top artists by centrality (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = f"insights:top-artists:{limit}"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            return JSONResponse(content=cached)

    async with _pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        await cursor.execute(
            "SELECT rank, artist_id, artist_name, edge_count, computed_at FROM insights.artist_centrality ORDER BY rank LIMIT %s",
            (limit,),
        )
        rows = await cursor.fetchall()

    items = [ArtistCentralityItem(rank=r[0], artist_id=r[1], artist_name=r[2], edge_count=r[3]).model_dump() for r in rows]
    result = {"metric": metric, "items": items, "count": len(items)}
    if _cache:
        await _cache.set(cache_key, result)
    return JSONResponse(content=result)


@app.get("/api/insights/genre-trends")
async def genre_trends(genre: str = Query(...)) -> JSONResponse:
    """Return release count per decade for a specific genre (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = f"insights:genre-trends:{genre}"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            return JSONResponse(content=cached)

    async with _pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        await cursor.execute(
            "SELECT genre, decade, release_count FROM insights.genre_trends WHERE genre = %s ORDER BY decade",
            (genre,),
        )
        rows = await cursor.fetchall()

    trends = [GenreTrendItem(decade=r[1], release_count=r[2]).model_dump() for r in rows]
    peak = max(trends, key=lambda t: t["release_count"])["decade"] if trends else None
    resp = GenreTrendsResponse(genre=genre, trends=[GenreTrendItem(**t) for t in trends], peak_decade=peak)
    result = resp.model_dump()
    if _cache:
        await _cache.set(cache_key, result)
    return JSONResponse(content=result)


@app.get("/api/insights/label-longevity")
async def label_longevity(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """Return labels ranked by years of active operation (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = f"insights:label-longevity:{limit}"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            return JSONResponse(content=cached)

    async with _pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        await cursor.execute(
            "SELECT rank, label_id, label_name, first_year, last_year, "
            "years_active, total_releases, peak_decade, still_active "
            "FROM insights.label_longevity ORDER BY rank LIMIT %s",
            (limit,),
        )
        rows = await cursor.fetchall()

    items = [
        LabelLongevityItem(
            rank=r[0],
            label_id=r[1],
            label_name=r[2],
            first_year=r[3],
            last_year=r[4],
            years_active=r[5],
            total_releases=r[6],
            peak_decade=r[7],
            still_active=r[8],
        ).model_dump()
        for r in rows
    ]
    result = {"items": items, "count": len(items)}
    if _cache:
        await _cache.set(cache_key, result)
    return JSONResponse(content=result)


@app.get("/api/insights/this-month")
async def this_month() -> JSONResponse:
    """Return releases with notable anniversaries this calendar month (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    now = datetime.now(UTC)
    cache_key = f"insights:this-month:{now.year}-{now.month}"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            return JSONResponse(content=cached)

    async with _pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        await cursor.execute(
            "SELECT master_id, title, artist_name, release_year, anniversary "
            "FROM insights.monthly_anniversaries "
            "WHERE computed_year = %s AND computed_month = %s "
            "ORDER BY anniversary DESC, release_year ASC",
            (now.year, now.month),
        )
        rows = await cursor.fetchall()

    items = [
        AnniversaryItem(
            master_id=r[0],
            title=r[1],
            artist_name=r[2],
            release_year=r[3],
            anniversary=r[4],
        ).model_dump()
        for r in rows
    ]
    result = {"month": now.month, "year": now.year, "items": items, "count": len(items)}
    if _cache:
        await _cache.set(cache_key, result)
    return JSONResponse(content=result)


@app.get("/api/insights/data-completeness")
async def data_completeness() -> JSONResponse:
    """Return data completeness scores per entity type (precomputed)."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    cache_key = "insights:data-completeness"
    if _cache:
        cached = await _cache.get(cache_key)
        if cached is not None:
            return JSONResponse(content=cached)

    async with _pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        await cursor.execute(
            "SELECT entity_type, total_count, with_image, with_year, "
            "with_country, with_genre, completeness_pct "
            "FROM insights.data_completeness ORDER BY entity_type"
        )
        rows = await cursor.fetchall()

    items = [
        DataCompletenessItem(
            entity_type=r[0],
            total_count=r[1],
            with_image=r[2],
            with_year=r[3],
            with_country=r[4],
            with_genre=r[5],
            completeness_pct=float(r[6]),
        ).model_dump()
        for r in rows
    ]
    result = {"items": items, "count": len(items)}
    if _cache:
        await _cache.set(cache_key, result)
    return JSONResponse(content=result)


@app.get("/api/insights/status")
async def computation_status() -> JSONResponse:
    """Return the latest computation status for each insight type."""
    if not _pool:
        return JSONResponse(content={"error": "Service not ready"}, status_code=503)

    insight_types = ["artist_centrality", "genre_trends", "label_longevity", "anniversaries", "data_completeness"]
    statuses: list[dict[str, Any]] = []

    async with _pool.connection() as conn, conn.cursor() as cursor:
        cursor = cast("Any", cursor)
        for itype in insight_types:
            await cursor.execute(
                "SELECT insight_type, status, completed_at, duration_ms "
                "FROM insights.computation_log "
                "WHERE insight_type = %s ORDER BY started_at DESC LIMIT 1",
                (itype,),
            )
            row = await cursor.fetchone()
            if row:
                statuses.append(
                    ComputationStatus(
                        insight_type=row[0],
                        status=row[1],
                        last_computed=row[2],
                        duration_ms=row[3],
                    ).model_dump()
                )
            else:
                statuses.append(ComputationStatus(insight_type=itype, status="never_run").model_dump())

    return JSONResponse(content={"statuses": statuses})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=INSIGHTS_PORT, log_level=os.getenv("LOG_LEVEL", "INFO").lower())  # noqa: S104  # nosec B104
