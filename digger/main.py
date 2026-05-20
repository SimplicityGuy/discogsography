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

    tasks: list[asyncio.Task[None]] = []  # filled by future scraper tasks

    try:
        await stop_event.wait()
    finally:
        logger.info("🛑 Digger shutting down")
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError):
                await t
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
