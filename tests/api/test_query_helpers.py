"""Tests for api/queries/helpers.py consolidated query execution helpers."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Autouse fixture — save/restore root logger level
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _preserve_root_log_level() -> Any:
    """Save and restore the root logger level around every test."""
    root = logging.getLogger()
    original = root.level
    yield
    root.setLevel(original)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncIter:
    """Async iterator that yields pre-built records for mock Neo4j results."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self._index = 0

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record


class _MockResult:
    """Mock Neo4j result that supports async iteration, .single(), and .consume()."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        single: dict[str, Any] | None = None,
        summary: Any = None,
    ) -> None:
        self._records = records or []
        self._single = single
        self._summary = summary

    def __aiter__(self) -> _AsyncIter:
        return _AsyncIter(self._records)

    async def single(self) -> dict[str, Any] | None:
        return self._single

    async def consume(self) -> Any:
        return self._summary


def _make_driver(
    records: list[dict[str, Any]] | None = None,
    single: dict[str, Any] | None = None,
    summary: Any = None,
) -> MagicMock:
    """Build a minimal mock AsyncResilientNeo4jDriver."""
    mock_result = _MockResult(records=records, single=single, summary=summary)
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=mock_result)

    driver = MagicMock()
    driver.session = MagicMock(return_value=mock_session)
    return driver


# ---------------------------------------------------------------------------
# TestRunQuery
# ---------------------------------------------------------------------------


class TestRunQuery:
    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self) -> None:
        from api.queries.helpers import run_query

        records = [{"id": "1", "name": "Rock"}, {"id": "2", "name": "Jazz"}]
        driver = _make_driver(records=records)
        result = await run_query(driver, "MATCH (n) RETURN n")
        assert result == records

    @pytest.mark.asyncio
    async def test_passes_timeout(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (n) RETURN n", timeout=30.0)
        session = driver.session.return_value
        _call_args = session.__aenter__.return_value.run.call_args
        assert _call_args.kwargs.get("timeout") == 30.0

    @pytest.mark.asyncio
    async def test_passes_database(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (n) RETURN n", database="mydb")
        driver.session.assert_called_once_with(database="mydb")

    @pytest.mark.asyncio
    async def test_no_database_kwarg_when_none(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        await run_query(driver, "MATCH (n) RETURN n")
        driver.session.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_logs_at_debug(self) -> None:
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.DEBUG)
        driver = _make_driver(records=[])
        with patch("api.queries.helpers.log_cypher_query") as mock_log:
            await run_query(driver, "MATCH (n) RETURN n", x=1)
            mock_log.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})

    @pytest.mark.asyncio
    async def test_no_log_at_info(self) -> None:
        """log_cypher_query is always called, but the underlying logger filters at INFO."""
        from api.queries.helpers import run_query

        logging.getLogger().setLevel(logging.INFO)
        driver = _make_driver(records=[])
        with patch("api.queries.helpers.log_cypher_query") as mock_log:
            await run_query(driver, "MATCH (n) RETURN n")
            # log_cypher_query is still called; it just won't emit at INFO
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_profile_prefix_when_enabled(self) -> None:
        from api.queries.helpers import run_query

        summary = MagicMock()
        summary.profile = {"args": {"string-representation": "plan"}}
        driver = _make_driver(records=[], summary=summary)

        with patch("api.queries.helpers.is_db_profiling", return_value=True), patch("api.queries.helpers.log_profile_result") as mock_profile:
            await run_query(driver, "MATCH (n) RETURN n")
            session = driver.session.return_value
            run_call = session.__aenter__.return_value.run.call_args
            assert run_call.args[0].startswith("PROFILE ")
            mock_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_profile_prefix_when_disabled(self) -> None:
        from api.queries.helpers import run_query

        driver = _make_driver(records=[])
        with patch("api.queries.helpers.is_db_profiling", return_value=False):
            await run_query(driver, "MATCH (n) RETURN n")
            session = driver.session.return_value
            run_call = session.__aenter__.return_value.run.call_args
            assert run_call.args[0] == "MATCH (n) RETURN n"


# ---------------------------------------------------------------------------
# TestRunSingle
# ---------------------------------------------------------------------------


class TestRunSingle:
    @pytest.mark.asyncio
    async def test_returns_dict(self) -> None:
        from api.queries.helpers import run_single

        record = {"id": "1", "name": "Radiohead"}
        driver = _make_driver(single=record)
        result = await run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        assert result == record

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        from api.queries.helpers import run_single

        driver = _make_driver(single=None)
        result = await run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_timeout(self) -> None:
        from api.queries.helpers import run_single

        driver = _make_driver(single={"id": "1"})
        await run_single(driver, "MATCH (a) RETURN a LIMIT 1", timeout=60.0)
        session = driver.session.return_value
        call_kwargs = session.__aenter__.return_value.run.call_args
        assert call_kwargs.kwargs.get("timeout") == 60.0

    @pytest.mark.asyncio
    async def test_passes_database(self) -> None:
        from api.queries.helpers import run_single

        driver = _make_driver(single={"id": "1"})
        await run_single(driver, "MATCH (a) RETURN a LIMIT 1", database="neo4j")
        driver.session.assert_called_once_with(database="neo4j")

    @pytest.mark.asyncio
    async def test_profile_prefix_when_enabled(self) -> None:
        from api.queries.helpers import run_single

        summary = MagicMock()
        summary.profile = {"args": {"string-representation": "plan"}}
        driver = _make_driver(single={"id": "1"}, summary=summary)

        with patch("api.queries.helpers.is_db_profiling", return_value=True), patch("api.queries.helpers.log_profile_result") as mock_profile:
            await run_single(driver, "MATCH (a) RETURN a LIMIT 1")
            session = driver.session.return_value
            run_call = session.__aenter__.return_value.run.call_args
            assert run_call.args[0].startswith("PROFILE ")
            mock_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_explain_on_error_with_profiling(self) -> None:
        from api.queries.helpers import run_single

        error = RuntimeError("timeout")
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=error)

        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        with (
            patch("api.queries.helpers.is_db_profiling", return_value=True),
            patch("api.queries.helpers._try_explain_on_error") as mock_explain,
            pytest.raises(RuntimeError, match="timeout"),
        ):
            await run_single(driver, "MATCH (a) RETURN a LIMIT 1")
        mock_explain.assert_called_once()


# ---------------------------------------------------------------------------
# TestRunCount
# ---------------------------------------------------------------------------


class TestRunCount:
    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single={"total": 42})
        result = await run_count(driver, "RETURN count(*) AS total")
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_result(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single=None)
        result = await run_count(driver, "RETURN count(*) AS total")
        assert result == 0

    @pytest.mark.asyncio
    async def test_passes_timeout(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single={"total": 1})
        await run_count(driver, "RETURN count(*) AS total", timeout=30.0)
        session = driver.session.return_value
        call_kwargs = session.__aenter__.return_value.run.call_args
        assert call_kwargs.kwargs.get("timeout") == 30.0

    @pytest.mark.asyncio
    async def test_passes_database(self) -> None:
        from api.queries.helpers import run_count

        driver = _make_driver(single={"total": 1})
        await run_count(driver, "RETURN count(*) AS total", database="neo4j")
        driver.session.assert_called_once_with(database="neo4j")

    @pytest.mark.asyncio
    async def test_profile_prefix_when_enabled(self) -> None:
        from api.queries.helpers import run_count

        summary = MagicMock()
        summary.profile = {"args": {"string-representation": "plan"}}
        driver = _make_driver(single={"total": 5}, summary=summary)

        with patch("api.queries.helpers.is_db_profiling", return_value=True), patch("api.queries.helpers.log_profile_result") as mock_profile:
            await run_count(driver, "RETURN count(*) AS total")
            session = driver.session.return_value
            run_call = session.__aenter__.return_value.run.call_args
            assert run_call.args[0].startswith("PROFILE ")
            mock_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_explain_on_error_with_profiling(self) -> None:
        from api.queries.helpers import run_count

        error = RuntimeError("timeout")
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=error)

        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        with (
            patch("api.queries.helpers.is_db_profiling", return_value=True),
            patch("api.queries.helpers._try_explain_on_error") as mock_explain,
            pytest.raises(RuntimeError, match="timeout"),
        ):
            await run_count(driver, "RETURN count(*) AS total")
        mock_explain.assert_called_once()


# ---------------------------------------------------------------------------
# TestExplainFallback
# ---------------------------------------------------------------------------


class TestExplainFallback:
    @pytest.mark.asyncio
    async def test_explain_attempted_on_error_with_profiling(self) -> None:
        """When profiling is enabled and a query fails, EXPLAIN should be attempted."""
        from api.queries.helpers import run_query

        # Make session.run raise an error
        error = RuntimeError("Neo4j timeout")
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=error)

        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        with (
            patch("api.queries.helpers.is_db_profiling", return_value=True),
            patch("api.queries.helpers._try_explain_on_error") as mock_explain,
        ):
            with pytest.raises(RuntimeError, match="Neo4j timeout"):
                await run_query(driver, "MATCH (n) RETURN n")
            mock_explain.assert_called_once()

    @pytest.mark.asyncio
    async def test_original_error_re_raised(self) -> None:
        """The original error must be re-raised after EXPLAIN attempt."""
        from api.queries.helpers import run_query

        error = RuntimeError("original error")
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.run = AsyncMock(side_effect=error)

        driver = MagicMock()
        driver.session = MagicMock(return_value=mock_session)

        with (
            patch("api.queries.helpers.is_db_profiling", return_value=True),
            patch("api.queries.helpers._try_explain_on_error"),
            pytest.raises(RuntimeError, match="original error"),
        ):
            await run_query(driver, "MATCH (n) RETURN n")

    @pytest.mark.asyncio
    async def test_explain_failure_is_swallowed(self) -> None:
        """If _try_explain_on_error itself fails, the original error still propagates."""
        from api.queries.helpers import _try_explain_on_error

        # Build a driver whose session.run raises during EXPLAIN
        explain_session = AsyncMock()
        explain_session.__aenter__ = AsyncMock(return_value=explain_session)
        explain_session.__aexit__ = AsyncMock(return_value=False)
        explain_session.run = AsyncMock(side_effect=RuntimeError("DB unreachable"))

        driver = MagicMock()
        driver.session = MagicMock(return_value=explain_session)

        original_error = RuntimeError("original")
        # Should NOT raise — failure is swallowed
        await _try_explain_on_error(driver, "MATCH (n) RETURN n", {"x": 1}, original_error)

    @pytest.mark.asyncio
    async def test_explain_passes_database(self) -> None:
        """_try_explain_on_error passes database kwarg to session."""
        from api.queries.helpers import _try_explain_on_error

        summary = MagicMock()
        summary.plan = {"args": {"string-representation": "plan"}}

        mock_result = AsyncMock()
        mock_result.consume = AsyncMock(return_value=summary)

        explain_session = AsyncMock()
        explain_session.__aenter__ = AsyncMock(return_value=explain_session)
        explain_session.__aexit__ = AsyncMock(return_value=False)
        explain_session.run = AsyncMock(return_value=mock_result)

        driver = MagicMock()
        driver.session = MagicMock(return_value=explain_session)

        with patch("api.queries.helpers.log_explain_result"):
            await _try_explain_on_error(driver, "MATCH (n) RETURN n", {}, RuntimeError("err"), database="neo4j")
        driver.session.assert_called_once_with(database="neo4j")

    @pytest.mark.asyncio
    async def test_explain_calls_log_explain_result(self) -> None:
        """Successful EXPLAIN should call log_explain_result."""
        from api.queries.helpers import _try_explain_on_error

        summary = MagicMock()
        summary.plan = {"args": {"string-representation": "plan output"}}

        mock_result = AsyncMock()
        mock_result.consume = AsyncMock(return_value=summary)

        explain_session = AsyncMock()
        explain_session.__aenter__ = AsyncMock(return_value=explain_session)
        explain_session.__aexit__ = AsyncMock(return_value=False)
        explain_session.run = AsyncMock(return_value=mock_result)

        driver = MagicMock()
        driver.session = MagicMock(return_value=explain_session)

        original_error = RuntimeError("timeout")
        with patch("api.queries.helpers.log_explain_result") as mock_log:
            await _try_explain_on_error(driver, "MATCH (n) RETURN n", {"x": 1}, original_error)
            mock_log.assert_called_once_with("MATCH (n) RETURN n", {"x": 1}, summary, original_error)
