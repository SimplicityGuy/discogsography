"""Tests for digger/main.py — amain() and main() entrypoints.

All external dependencies (PostgreSQL, Redis, HTTP, health server, tasks) are
fully mocked so the test suite requires no real infrastructure.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Required env for DiggerConfig.from_env()
# ---------------------------------------------------------------------------

_DIGGER_REQUIRED: dict[str, str] = {
    "POSTGRES_HOST": "pg-host",
    "POSTGRES_USERNAME": "pg-user",
    "POSTGRES_PASSWORD": "pg-pass",
    "POSTGRES_DATABASE": "pg-db",
    "REDIS_HOST": "redis-host",
}


class TestAmain:
    """Unit tests for the amain() async entrypoint."""

    @pytest.mark.asyncio
    async def test_amain_starts_health_server_and_tasks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """amain() starts the health server and creates two asyncio tasks."""
        for k, v in _DIGGER_REQUIRED.items():
            monkeypatch.setenv(k, v)

        # Build mock objects
        mock_pool = AsyncMock()
        mock_redis = AsyncMock()
        mock_http_client = MagicMock()
        mock_http_client._client = AsyncMock()
        mock_health_server = MagicMock()
        mock_health_server_cls = MagicMock(return_value=mock_health_server)

        # scrape_loop / state_loop: coroutines that complete immediately
        async def _noop_scrape(**_kwargs: Any) -> None:
            pass

        async def _noop_state(**_kwargs: Any) -> None:
            pass

        with (
            patch("digger.main.setup_logging"),
            patch("digger.main.HealthServer", mock_health_server_cls),
            patch("digger.main.asyncio.get_running_loop", return_value=MagicMock()),
            patch("common.postgres_resilient.AsyncPostgreSQLPool", return_value=mock_pool),
            patch("redis.asyncio.from_url", return_value=mock_redis),
            patch("digger.scraper.http_client.DiggerHttpClient", return_value=mock_http_client),
            patch("digger.scraper.rate_budget.RateBudget", return_value=MagicMock()),
            patch("digger.scraper.circuit_breaker.CircuitBreaker", return_value=MagicMock()),
            patch("digger.scraper.executor.ScrapeExecutor", return_value=MagicMock()),
            patch("digger.scraper.orchestrator.scrape_loop", side_effect=_noop_scrape),
            patch("digger.scraper.orchestrator.state_loop", side_effect=_noop_state),
        ):
            from digger.main import amain

            async def _drive_amain() -> None:
                """Run amain but inject a stop_event that fires right away."""
                original_event_cls = asyncio.Event

                class _ImmediateEvent(original_event_cls):  # type: ignore[misc]
                    """An asyncio.Event that sets itself on first wait() call."""

                    async def wait(self) -> bool:
                        self.set()
                        return await super().wait()

                with patch("digger.main.asyncio.Event", _ImmediateEvent):
                    await amain()

            await _drive_amain()

        # Health server was constructed and started
        mock_health_server_cls.assert_called_once()
        mock_health_server.start_background.assert_called_once()

    @pytest.mark.asyncio
    async def test_amain_shuts_down_resources_on_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After stop_event fires, amain() closes pool, redis, http_client, and health server."""
        for k, v in _DIGGER_REQUIRED.items():
            monkeypatch.setenv(k, v)

        mock_pool = AsyncMock()
        mock_redis = AsyncMock()
        mock_http_client = MagicMock()
        mock_http_client._client = AsyncMock()
        mock_health_server = MagicMock()
        mock_health_server_cls = MagicMock(return_value=mock_health_server)

        async def _noop_scrape(**_kwargs: Any) -> None:
            pass

        async def _noop_state(**_kwargs: Any) -> None:
            pass

        with (
            patch("digger.main.setup_logging"),
            patch("digger.main.HealthServer", mock_health_server_cls),
            patch("common.postgres_resilient.AsyncPostgreSQLPool", return_value=mock_pool),
            patch("redis.asyncio.from_url", return_value=mock_redis),
            patch("digger.scraper.http_client.DiggerHttpClient", return_value=mock_http_client),
            patch("digger.scraper.rate_budget.RateBudget", return_value=MagicMock()),
            patch("digger.scraper.circuit_breaker.CircuitBreaker", return_value=MagicMock()),
            patch("digger.scraper.executor.ScrapeExecutor", return_value=MagicMock()),
            patch("digger.scraper.orchestrator.scrape_loop", side_effect=_noop_scrape),
            patch("digger.scraper.orchestrator.state_loop", side_effect=_noop_state),
        ):
            from digger.main import amain

            original_event_cls = asyncio.Event

            class _ImmediateEvent(original_event_cls):  # type: ignore[misc]
                async def wait(self) -> bool:
                    self.set()
                    return await super().wait()

            with patch("digger.main.asyncio.Event", _ImmediateEvent):
                await amain()

        # Teardown: pool, redis, http client, health server all closed/stopped
        mock_pool.close.assert_awaited_once()
        mock_redis.aclose.assert_awaited_once()
        mock_http_client._client.aclose.assert_awaited_once()
        mock_health_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_amain_starts_scheduler_when_token_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When DIGGER_API_SERVICE_TOKEN is set, amain() also starts the scheduler task."""
        for k, v in _DIGGER_REQUIRED.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("DIGGER_API_SERVICE_TOKEN", "svc-token")

        mock_pool = AsyncMock()
        mock_redis = AsyncMock()
        mock_http_client = MagicMock()
        mock_http_client._client = AsyncMock()
        mock_health_server = MagicMock()
        mock_health_server_cls = MagicMock(return_value=mock_health_server)

        async def _noop(**_kwargs: Any) -> None:
            pass

        with (
            patch("digger.main.setup_logging"),
            patch("digger.main.HealthServer", mock_health_server_cls),
            patch("common.postgres_resilient.AsyncPostgreSQLPool", return_value=mock_pool),
            patch("redis.asyncio.from_url", return_value=mock_redis),
            patch("digger.scraper.http_client.DiggerHttpClient", return_value=mock_http_client),
            patch("digger.scraper.rate_budget.RateBudget", return_value=MagicMock()),
            patch("digger.scraper.circuit_breaker.CircuitBreaker", return_value=MagicMock()),
            patch("digger.scraper.executor.ScrapeExecutor", return_value=MagicMock()),
            patch("digger.scraper.orchestrator.scrape_loop", side_effect=_noop),
            patch("digger.scraper.orchestrator.state_loop", side_effect=_noop),
            patch("digger.scheduler.runner.scheduler_loop", side_effect=_noop) as mock_scheduler,
        ):
            from digger.main import amain

            original_event_cls = asyncio.Event

            class _ImmediateEvent(original_event_cls):  # type: ignore[misc]
                async def wait(self) -> bool:
                    self.set()
                    return await super().wait()

            with patch("digger.main.asyncio.Event", _ImmediateEvent):
                await amain()

        mock_scheduler.assert_called_once()
        assert mock_scheduler.call_args.kwargs["service_token"] == "svc-token"


class TestMain:
    """Unit tests for the synchronous main() wrapper."""

    def test_main_calls_asyncio_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() delegates to asyncio.run() with the amain coroutine."""
        for k, v in _DIGGER_REQUIRED.items():
            monkeypatch.setenv(k, v)

        run_calls: list[Any] = []

        # Patch amain to a simple synchronous function so asyncio.run() receives
        # a coroutine, and capture the argument passed to asyncio.run().
        async def _fake_amain() -> None:
            pass

        def _capture_and_close(coro: Any) -> None:
            run_calls.append(coro)
            coro.close()

        with (
            patch("digger.main.amain", _fake_amain),
            patch("digger.main.asyncio.run", side_effect=_capture_and_close),
        ):
            from digger.main import main

            main()

        assert len(run_calls) == 1

    def test_main_handles_keyboard_interrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() catches KeyboardInterrupt and calls sys.exit(0)."""
        for k, v in _DIGGER_REQUIRED.items():
            monkeypatch.setenv(k, v)

        def _close_and_raise(coro: Any) -> None:
            coro.close()
            raise KeyboardInterrupt

        with (
            patch("digger.main.asyncio.run", side_effect=_close_and_raise),
            patch("digger.main.sys.exit") as mock_exit,
        ):
            from digger.main import main

            main()

        mock_exit.assert_called_once_with(0)
