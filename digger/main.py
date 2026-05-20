"""Digger worker entrypoint.

Starts health server (with Prometheus metrics) and scraper tasks.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress
from pathlib import Path

import structlog

from common.config import DiggerConfig, setup_logging
from common.health_server import HealthServer
from digger.health import get_health_data


logger = structlog.get_logger(__name__)

ASCII_ART = r"""
 ____  _
|  _ \(_) __ _  __ _  ___ _ __
| | | | |/ _` |/ _` |/ _ \ '__|
| |_| | | (_| | (_| |  __/ |
|____/|_|\__, |\__, |\___|_|
         |___/ |___/
"""


async def amain() -> None:
    """Async entrypoint for the digger worker."""
    cfg = DiggerConfig.from_env()
    setup_logging("digger", log_file=Path("/logs/digger.log"))

    print(ASCII_ART, flush=True)  # noqa: T201
    logger.info("🚀 Digger starting", rate_budget_per_hour=cfg.rate_budget_per_hour)

    # Start health + metrics server
    health_server = HealthServer(8012, get_health_data, metrics_enabled=True)
    health_server.start_background()
    logger.info("🏥 Health/metrics server started on port 8012")

    # Create the stop event lazily inside the running coroutine (binds to this
    # event loop), then register signal handlers — no None window.
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # --- Scraper wiring ---
    # All imports are local to avoid module-level asyncio primitive creation.
    from common.postgres_resilient import AsyncPostgreSQLPool  # noqa: PLC0415
    from redis.asyncio import from_url as redis_from_url  # noqa: PLC0415
    from digger.scraper.circuit_breaker import CircuitBreaker  # noqa: PLC0415
    from digger.scraper.executor import ScrapeExecutor  # noqa: PLC0415
    from digger.scraper.http_client import DiggerHttpClient  # noqa: PLC0415
    from digger.scraper.orchestrator import scrape_loop, state_loop  # noqa: PLC0415
    from digger.scraper.rate_budget import RateBudget  # noqa: PLC0415

    # Build connection params from config (individual fields → psycopg conninfo dict).
    # cfg.postgres_host already contains "host:port" from _build_postgres_connstr().
    _pg_host, _, _pg_port_str = cfg.postgres_host.partition(":")
    _pg_port = int(_pg_port_str) if _pg_port_str else 5432

    pool = AsyncPostgreSQLPool(
        connection_params={
            "host": _pg_host,
            "port": _pg_port,
            "user": cfg.postgres_username,
            "password": cfg.postgres_password,
            "dbname": cfg.postgres_database,
        }
    )
    await pool.initialize()
    logger.info("🐘 PostgreSQL pool initialized")

    # cfg.redis_host contains the full redis:// URL from _build_redis_url().
    redis = redis_from_url(cfg.redis_host)
    logger.info("🔴 Redis client created")

    http_client = DiggerHttpClient(user_agent=cfg.scraper_user_agent)
    rate = RateBudget(
        redis=redis,
        capacity=cfg.rate_budget_per_hour,
        refill_per_second=cfg.rate_budget_per_hour / 3600.0,
    )
    breaker = CircuitBreaker(
        window_seconds=cfg.circuit_breaker_window_seconds,
        failure_pct=cfg.circuit_breaker_failure_pct,
        cooldown_seconds=cfg.circuit_breaker_cooldown_seconds,
    )
    executor = ScrapeExecutor(http_client=http_client, pool=pool)

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            scrape_loop(
                pool=pool,
                executor=executor,
                rate=rate,
                breaker=breaker,
                stop_event=stop_event,
            ),
            name="scrape",
        ),
        asyncio.create_task(
            state_loop(pool=pool, stop_event=stop_event),
            name="state",
        ),
    ]
    logger.info("🔄 Scraper tasks started")

    try:
        await stop_event.wait()
    finally:
        logger.info("🛑 Digger shutting down")
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError):
                await t
        await http_client._client.aclose()
        await redis.aclose()
        await pool.close()
        health_server.stop()
        logger.info("✅ Digger shutdown complete")


def main() -> None:
    """Synchronous entrypoint called by the console script."""
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
