"""Tests for query_debug module."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _preserve_root_logger_level() -> None:  # type: ignore[misc]
    """Save and restore root logger level between tests."""
    original_level = logging.getLogger().level
    yield  # type: ignore[misc]
    logging.getLogger().level = original_level


@pytest.fixture(autouse=True)
def _reset_profiling_logger() -> None:  # type: ignore[misc]
    """Reset the cached profiling logger between tests."""
    import common.query_debug as mod

    mod._profiling_logger = None
    yield  # type: ignore[misc]
    mod._profiling_logger = None


class TestIsDebug:
    """Test is_debug function."""

    def test_returns_true_when_root_logger_at_debug(self) -> None:
        """is_debug returns True when root logger is at DEBUG."""
        logging.getLogger().setLevel(logging.DEBUG)

        from common.query_debug import is_debug

        assert is_debug() is True

    def test_returns_false_when_root_logger_at_info(self) -> None:
        """is_debug returns False when root logger is at INFO."""
        logging.getLogger().setLevel(logging.INFO)

        from common.query_debug import is_debug

        assert is_debug() is False

    def test_returns_false_when_root_logger_at_warning(self) -> None:
        """is_debug returns False when root logger is at WARNING."""
        logging.getLogger().setLevel(logging.WARNING)

        from common.query_debug import is_debug

        assert is_debug() is False


class TestIsCypherProfiling:
    """Test is_cypher_profiling function."""

    def test_returns_true_when_debug_and_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns True when debug AND CYPHER_PROFILING=true."""
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "true")

        from common.query_debug import is_cypher_profiling

        assert is_cypher_profiling() is True

    def test_returns_true_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns True with case-insensitive env var."""
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "TRUE")

        from common.query_debug import is_cypher_profiling

        assert is_cypher_profiling() is True

    def test_returns_false_when_not_debug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns False when not at DEBUG level."""
        logging.getLogger().setLevel(logging.INFO)
        monkeypatch.setenv("CYPHER_PROFILING", "true")

        from common.query_debug import is_cypher_profiling

        assert is_cypher_profiling() is False

    def test_returns_false_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns False when CYPHER_PROFILING is not set."""
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.delenv("CYPHER_PROFILING", raising=False)

        from common.query_debug import is_cypher_profiling

        assert is_cypher_profiling() is False

    def test_returns_false_when_env_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns False when CYPHER_PROFILING=false."""
        logging.getLogger().setLevel(logging.DEBUG)
        monkeypatch.setenv("CYPHER_PROFILING", "false")

        from common.query_debug import is_cypher_profiling

        assert is_cypher_profiling() is False


class TestGetProfilingLogger:
    """Test get_profiling_logger function."""

    def test_returns_logger_with_file_handler(self, tmp_path: Path) -> None:
        """Logger writes to profiling.log file."""
        log_file = tmp_path / "profiling.log"

        with patch("common.query_debug.PROFILING_LOG_PATH", log_file):
            from common.query_debug import get_profiling_logger

            logger = get_profiling_logger()

        assert logger.name == "cypher_profiling"
        assert logger.propagate is False
        assert len(logger.handlers) >= 1

    def test_caches_logger(self, tmp_path: Path) -> None:
        """Logger is cached after first call."""
        log_file = tmp_path / "profiling.log"

        with patch("common.query_debug.PROFILING_LOG_PATH", log_file):
            from common.query_debug import get_profiling_logger

            logger1 = get_profiling_logger()
            logger2 = get_profiling_logger()

        assert logger1 is logger2


class TestLogCypherQuery:
    """Test log_cypher_query function."""

    def test_logs_at_debug_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs Cypher query at DEBUG level."""
        logging.getLogger().setLevel(logging.DEBUG)

        from common.query_debug import log_cypher_query

        with caplog.at_level(logging.DEBUG, logger="common.query_debug"):
            log_cypher_query("MATCH (n) RETURN n", {"limit": 10})

        assert "🔗 Cypher query:" in caplog.text
        assert "MATCH (n) RETURN n" in caplog.text
        assert "{'limit': 10}" in caplog.text

    def test_does_not_log_at_info_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Does not log Cypher query when logger is at INFO."""
        logging.getLogger().setLevel(logging.INFO)

        from common.query_debug import log_cypher_query

        with caplog.at_level(logging.INFO, logger="common.query_debug"):
            log_cypher_query("MATCH (n) RETURN n", {"limit": 10})

        assert "Cypher query:" not in caplog.text


class TestLogSqlQuery:
    """Test log_sql_query function."""

    def test_logs_at_debug_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs SQL query at DEBUG level."""
        logging.getLogger().setLevel(logging.DEBUG)

        from common.query_debug import log_sql_query

        with caplog.at_level(logging.DEBUG, logger="common.query_debug"):
            log_sql_query("SELECT * FROM artists", {"id": 1}, None)

        assert "🐘 SQL query:" in caplog.text
        assert "SELECT * FROM artists" in caplog.text

    def test_does_not_log_at_info_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Does not log SQL query when logger is at INFO."""
        logging.getLogger().setLevel(logging.INFO)

        from common.query_debug import log_sql_query

        with caplog.at_level(logging.INFO, logger="common.query_debug"):
            log_sql_query("SELECT * FROM artists", {"id": 1}, None)

        assert "SQL query:" not in caplog.text

    def test_renders_composable_query(self, caplog: pytest.LogCaptureFixture) -> None:
        """Renders psycopg Composable objects via as_string."""
        logging.getLogger().setLevel(logging.DEBUG)

        composable = MagicMock()
        composable.as_string.return_value = "SELECT * FROM labels WHERE id = 1"
        cursor = MagicMock()

        from common.query_debug import log_sql_query

        with caplog.at_level(logging.DEBUG, logger="common.query_debug"):
            log_sql_query(composable, {"id": 1}, cursor)

        composable.as_string.assert_called_once_with(cursor)
        assert "SELECT * FROM labels WHERE id = 1" in caplog.text


class TestExecuteSql:
    """Test execute_sql function."""

    @pytest.mark.asyncio
    async def test_delegates_to_cursor_execute(self) -> None:
        """execute_sql calls cursor.execute with query and params."""
        cursor = AsyncMock()

        from common.query_debug import execute_sql

        await execute_sql(cursor, "SELECT 1", {"x": 42})

        cursor.execute.assert_awaited_once_with("SELECT 1", {"x": 42})

    @pytest.mark.asyncio
    async def test_logs_at_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """execute_sql logs the SQL query at DEBUG level."""
        logging.getLogger().setLevel(logging.DEBUG)
        cursor = AsyncMock()

        from common.query_debug import execute_sql

        with caplog.at_level(logging.DEBUG, logger="common.query_debug"):
            await execute_sql(cursor, "SELECT 1", {"x": 42})

        assert "🐘 SQL query:" in caplog.text

    @pytest.mark.asyncio
    async def test_passes_none_params(self) -> None:
        """execute_sql works with params=None."""
        cursor = AsyncMock()

        from common.query_debug import execute_sql

        await execute_sql(cursor, "SELECT 1")

        cursor.execute.assert_awaited_once_with("SELECT 1", None)


class TestLogProfileResult:
    """Test log_profile_result function."""

    def test_writes_profile_to_profiling_logger(self, tmp_path: Path) -> None:
        """Writes PROFILE results to profiling log."""
        log_file = tmp_path / "profiling.log"

        summary = MagicMock()
        summary.profile = {"args": {"string-representation": "NodeByLabel\n  rows: 10"}}

        with patch("common.query_debug.PROFILING_LOG_PATH", log_file):
            import common.query_debug as mod

            mod._profiling_logger = None

            from common.query_debug import log_profile_result

            log_profile_result("MATCH (n) RETURN n", {"limit": 10}, summary)

        content = log_file.read_text()
        assert "PROFILE result for Cypher query:" in content
        assert "MATCH (n) RETURN n" in content
        assert "{'limit': 10}" in content
        assert "NodeByLabel" in content

    def test_handles_object_profile(self, tmp_path: Path) -> None:
        """Handles profile as object with args attribute."""
        log_file = tmp_path / "profiling.log"

        profile_obj = MagicMock()
        profile_obj.args = {"string-representation": "AllNodesScan\n  rows: 5"}
        summary = MagicMock()
        summary.profile = profile_obj

        with patch("common.query_debug.PROFILING_LOG_PATH", log_file):
            import common.query_debug as mod

            mod._profiling_logger = None

            from common.query_debug import log_profile_result

            log_profile_result("MATCH (n)", {}, summary)

        content = log_file.read_text()
        assert "AllNodesScan" in content


class TestLogExplainResult:
    """Test log_explain_result function."""

    def test_writes_explain_with_error_info(self, tmp_path: Path) -> None:
        """Writes EXPLAIN results with original error to profiling log."""
        log_file = tmp_path / "profiling.log"

        summary = MagicMock()
        summary.plan = {"args": {"string-representation": "ProduceResults\n  rows: 0"}}

        original_error = ValueError("Connection timeout")

        with patch("common.query_debug.PROFILING_LOG_PATH", log_file):
            import common.query_debug as mod

            mod._profiling_logger = None

            from common.query_debug import log_explain_result

            log_explain_result("MATCH (n) RETURN n", {"limit": 10}, summary, original_error)

        content = log_file.read_text()
        assert "EXPLAIN (after error) for Cypher query:" in content
        assert "MATCH (n) RETURN n" in content
        assert "Original error: ValueError: Connection timeout" in content
        assert "ProduceResults" in content
