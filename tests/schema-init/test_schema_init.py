"""Tests for schema-init/schema_init.py."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import schema_init
from schema_init import (
    _ensure_postgres_database,
    _init_neo4j,
    _init_postgres,
    _postgres_connection_params,
    main,
)


@pytest.fixture(autouse=True)
def _patch_setup_logging() -> Any:
    """Prevent setup_logging from trying to create /logs/ during tests."""
    with patch("schema_init.setup_logging"):
        yield


class TestPostgresConnectionParams:
    """Test _postgres_connection_params() parsing."""

    def test_host_and_port(self) -> None:
        with (
            patch("schema_init.POSTGRES_ADDRESS", "myhost:5433"),
            patch("schema_init.POSTGRES_DATABASE", "testdb"),
            patch("schema_init.POSTGRES_USERNAME", "testuser"),
            patch("schema_init.POSTGRES_PASSWORD", "testpass"),
        ):
            result = _postgres_connection_params()
        assert result == {
            "host": "myhost",
            "port": 5433,
            "dbname": "testdb",
            "user": "testuser",
            "password": "testpass",
        }

    def test_host_only_defaults_to_port_5432(self) -> None:
        with (
            patch("schema_init.POSTGRES_ADDRESS", "myhost"),
            patch("schema_init.POSTGRES_DATABASE", "db"),
            patch("schema_init.POSTGRES_USERNAME", "u"),
            patch("schema_init.POSTGRES_PASSWORD", "p"),
        ):
            result = _postgres_connection_params()
        assert result["host"] == "myhost"
        assert result["port"] == 5432

    def test_custom_database(self) -> None:
        with (
            patch("schema_init.POSTGRES_ADDRESS", "localhost:5432"),
            patch("schema_init.POSTGRES_DATABASE", "custom_db"),
            patch("schema_init.POSTGRES_USERNAME", "u"),
            patch("schema_init.POSTGRES_PASSWORD", "p"),
        ):
            result = _postgres_connection_params()
        assert result["dbname"] == "custom_db"

    def test_port_is_integer(self) -> None:
        with (
            patch("schema_init.POSTGRES_ADDRESS", "host:9999"),
            patch("schema_init.POSTGRES_DATABASE", "db"),
            patch("schema_init.POSTGRES_USERNAME", "u"),
            patch("schema_init.POSTGRES_PASSWORD", "p"),
        ):
            result = _postgres_connection_params()
        assert isinstance(result["port"], int)
        assert result["port"] == 9999


class TestEnsurePostgresDatabase:
    """Test _ensure_postgres_database() sync DB creation logic."""

    def _make_mock_conn(self, fetchone_result: Any) -> MagicMock:
        """Build a mock psycopg synchronous connection."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = fetchone_result

        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor_cm.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor_cm

        return mock_conn

    def test_database_already_exists_skips_create(self) -> None:
        mock_conn = self._make_mock_conn(fetchone_result=(1,))
        params = {"host": "localhost", "port": 5432, "dbname": "testdb", "user": "u", "password": "p"}

        with patch("schema_init.psycopg.connect", return_value=mock_conn), patch("schema_init.POSTGRES_DATABASE", "testdb"):
            _ensure_postgres_database(params)

        cursor = mock_conn.cursor.return_value.__enter__.return_value
        # Only SELECT executed — no CREATE
        assert cursor.execute.call_count == 1

    def test_database_missing_creates_it(self) -> None:
        mock_conn = self._make_mock_conn(fetchone_result=None)
        params = {"host": "localhost", "port": 5432, "dbname": "testdb", "user": "u", "password": "p"}

        with patch("schema_init.psycopg.connect", return_value=mock_conn), patch("schema_init.POSTGRES_DATABASE", "testdb"):
            _ensure_postgres_database(params)

        cursor = mock_conn.cursor.return_value.__enter__.return_value
        # SELECT + CREATE DATABASE
        assert cursor.execute.call_count == 2

    def test_connects_to_postgres_admin_db(self) -> None:
        mock_conn = self._make_mock_conn(fetchone_result=(1,))
        params = {"host": "myhost", "port": 5432, "dbname": "target_db", "user": "u", "password": "p"}

        with patch("schema_init.psycopg.connect", return_value=mock_conn) as mock_connect, patch("schema_init.POSTGRES_DATABASE", "target_db"):
            _ensure_postgres_database(params)

        # Must connect to "postgres" admin db, not the target db
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs.get("dbname") == "postgres"

    def test_sets_autocommit(self) -> None:
        mock_conn = self._make_mock_conn(fetchone_result=(1,))
        params = {"host": "localhost", "port": 5432, "dbname": "db", "user": "u", "password": "p"}

        with patch("schema_init.psycopg.connect", return_value=mock_conn), patch("schema_init.POSTGRES_DATABASE", "db"):
            _ensure_postgres_database(params)

        # autocommit must be enabled for CREATE DATABASE
        assert mock_conn.autocommit is True


class TestInitPostgres:
    """Test _init_postgres() async wrapper."""

    @pytest.mark.asyncio
    async def test_success_returns_true(self) -> None:
        with patch("schema_init.AsyncPostgreSQLPool") as MockPool, patch("schema_init.create_postgres_schema", new_callable=AsyncMock):
            mock_pool = AsyncMock()
            MockPool.return_value = mock_pool

            result = await _init_postgres({"host": "localhost", "port": 5432, "dbname": "db", "user": "u", "password": "p"})

        assert result is True
        mock_pool.initialize.assert_awaited_once()
        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_failure_returns_false(self) -> None:
        with patch("schema_init.AsyncPostgreSQLPool") as MockPool:
            mock_pool = AsyncMock()
            mock_pool.initialize.side_effect = Exception("Connection refused")
            MockPool.return_value = mock_pool

            result = await _init_postgres({"host": "localhost"})

        assert result is False
        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schema_failure_returns_false(self) -> None:
        with (
            patch("schema_init.AsyncPostgreSQLPool") as MockPool,
            patch("schema_init.create_postgres_schema", new_callable=AsyncMock, side_effect=Exception("Schema error")),
        ):
            mock_pool = AsyncMock()
            MockPool.return_value = mock_pool

            result = await _init_postgres({})

        assert result is False
        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_always_closed(self) -> None:
        """Pool must be closed even if an exception occurs."""
        with (
            patch("schema_init.AsyncPostgreSQLPool") as MockPool,
            patch("schema_init.create_postgres_schema", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        ):
            mock_pool = AsyncMock()
            MockPool.return_value = mock_pool

            result = await _init_postgres({})

        assert result is False
        mock_pool.close.assert_awaited_once()


class TestInitNeo4j:
    """Test _init_neo4j() async wrapper."""

    def _make_mock_driver(self) -> MagicMock:
        driver = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"health": 1})
        mock_session.run = AsyncMock(return_value=mock_result)
        driver.session = AsyncMock(return_value=mock_session)
        driver.close = AsyncMock()
        return driver

    @pytest.mark.asyncio
    async def test_success_returns_true(self) -> None:
        mock_driver = self._make_mock_driver()
        with (
            patch("schema_init.AsyncResilientNeo4jDriver", return_value=mock_driver),
            patch("schema_init.create_neo4j_schema", new_callable=AsyncMock),
        ):
            result = await _init_neo4j()

        assert result is True
        mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_failure_returns_false(self) -> None:
        mock_driver = self._make_mock_driver()
        mock_driver.session.side_effect = Exception("Cannot reach Neo4j")
        with patch("schema_init.AsyncResilientNeo4jDriver", return_value=mock_driver):
            result = await _init_neo4j()

        assert result is False
        mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schema_failure_returns_false(self) -> None:
        mock_driver = self._make_mock_driver()
        with (
            patch("schema_init.AsyncResilientNeo4jDriver", return_value=mock_driver),
            patch("schema_init.create_neo4j_schema", new_callable=AsyncMock, side_effect=Exception("Cypher error")),
        ):
            result = await _init_neo4j()

        assert result is False
        mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_driver_always_closed(self) -> None:
        """Driver must be closed even if an exception occurs."""
        mock_driver = self._make_mock_driver()
        mock_driver.session.side_effect = RuntimeError("fatal")
        with patch("schema_init.AsyncResilientNeo4jDriver", return_value=mock_driver):
            result = await _init_neo4j()

        assert result is False
        mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_configured_credentials(self) -> None:
        mock_driver = self._make_mock_driver()
        with (
            patch("schema_init.AsyncResilientNeo4jDriver", return_value=mock_driver) as MockDriver,
            patch("schema_init.create_neo4j_schema", new_callable=AsyncMock),
            patch("schema_init.NEO4J_ADDRESS", "bolt://myhost:7687"),
            patch("schema_init.NEO4J_USERNAME", "myuser"),
            patch("schema_init.NEO4J_PASSWORD", "mypass"),
        ):
            await _init_neo4j()

        MockDriver.assert_called_once_with(
            uri="bolt://myhost:7687",
            auth=("myuser", "mypass"),
        )


class TestMain:
    """Test main() orchestration."""

    @pytest.mark.asyncio
    async def test_all_success_returns_zero(self) -> None:
        with (
            patch("schema_init._ensure_postgres_database"),
            patch("schema_init._init_postgres", new_callable=AsyncMock, return_value=True),
            patch("schema_init._init_neo4j", new_callable=AsyncMock, return_value=True),
        ):
            result = await main()

        assert result == 0

    @pytest.mark.asyncio
    async def test_postgres_init_fails_returns_one(self) -> None:
        with (
            patch("schema_init._ensure_postgres_database"),
            patch("schema_init._init_postgres", new_callable=AsyncMock, return_value=False),
            patch("schema_init._init_neo4j", new_callable=AsyncMock, return_value=True),
        ):
            result = await main()

        assert result == 1

    @pytest.mark.asyncio
    async def test_neo4j_init_fails_returns_one(self) -> None:
        with (
            patch("schema_init._ensure_postgres_database"),
            patch("schema_init._init_postgres", new_callable=AsyncMock, return_value=True),
            patch("schema_init._init_neo4j", new_callable=AsyncMock, return_value=False),
        ):
            result = await main()

        assert result == 1

    @pytest.mark.asyncio
    async def test_both_fail_returns_one(self) -> None:
        with (
            patch("schema_init._ensure_postgres_database"),
            patch("schema_init._init_postgres", new_callable=AsyncMock, return_value=False),
            patch("schema_init._init_neo4j", new_callable=AsyncMock, return_value=False),
        ):
            result = await main()

        assert result == 1

    @pytest.mark.asyncio
    async def test_ensure_database_exception_returns_one(self) -> None:
        with (
            patch("schema_init._ensure_postgres_database", side_effect=Exception("Cannot connect to postgres")),
            patch("schema_init._init_postgres", new_callable=AsyncMock, return_value=True),
            patch("schema_init._init_neo4j", new_callable=AsyncMock, return_value=True),
        ):
            result = await main()

        assert result == 1

    @pytest.mark.asyncio
    async def test_postgres_and_neo4j_run_in_parallel(self) -> None:
        """Both init functions should be called via asyncio.gather."""
        import asyncio

        pg_started = asyncio.Event()
        neo4j_started = asyncio.Event()

        async def slow_pg(*_: Any, **__: Any) -> bool:
            pg_started.set()
            await asyncio.sleep(0)  # yield
            return True

        async def slow_neo4j(*_: Any, **__: Any) -> bool:
            neo4j_started.set()
            await asyncio.sleep(0)  # yield
            return True

        with (
            patch("schema_init._ensure_postgres_database"),
            patch("schema_init._init_postgres", side_effect=slow_pg),
            patch("schema_init._init_neo4j", side_effect=slow_neo4j),
        ):
            result = await main()

        assert result == 0
        assert pg_started.is_set()
        assert neo4j_started.is_set()


class TestModuleVariables:
    """Verify module-level environment variable defaults."""

    def test_neo4j_address_has_default(self) -> None:
        assert schema_init.NEO4J_ADDRESS

    def test_postgres_address_has_default(self) -> None:
        assert schema_init.POSTGRES_ADDRESS

    def test_postgres_database_has_default(self) -> None:
        assert schema_init.POSTGRES_DATABASE
