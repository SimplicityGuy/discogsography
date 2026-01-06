"""Tests for Neo4j resilient connection module."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from common.db_resilience import ExponentialBackoff
from common.neo4j_resilient import (
    AsyncResilientNeo4jDriver,
    ResilientNeo4jDriver,
    with_async_neo4j_retry,
    with_neo4j_retry,
)


class TestResilientNeo4jDriver:
    """Tests for ResilientNeo4jDriver class."""

    @pytest.fixture
    def mock_driver(self) -> Mock:
        """Create a mock Neo4j driver."""
        driver = Mock()
        session = Mock()
        result = Mock()
        record = MagicMock()
        record.__getitem__ = Mock(return_value=1)
        record.get = Mock(return_value=1)
        result.single = Mock(return_value=record)
        session.run = Mock(return_value=result)
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)
        driver.session = Mock(return_value=session)
        driver.close = Mock()
        return driver

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_init(self, mock_graph_db: Mock) -> None:
        """Test ResilientNeo4jDriver initialization."""
        uri = "neo4j://localhost:7687"
        auth = ("neo4j", "password")

        driver = ResilientNeo4jDriver(uri, auth, max_retries=3)

        assert driver.uri == uri
        assert driver.auth == auth
        assert driver.health_check_query == "RETURN 1 as healthy"
        assert driver.driver_kwargs["max_connection_pool_size"] == 50
        assert driver.driver_kwargs["keep_alive"] is True

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_create_driver(self, mock_graph_db: Mock, mock_driver: Mock) -> None:
        """Test driver creation."""
        mock_graph_db.driver = Mock(return_value=mock_driver)
        uri = "neo4j://localhost:7687"
        auth = ("neo4j", "password")

        resilient_driver = ResilientNeo4jDriver(uri, auth)
        created_driver = resilient_driver._create_driver()

        assert created_driver == mock_driver
        mock_graph_db.driver.assert_called_once_with(uri, auth=auth, **resilient_driver.driver_kwargs)

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_test_driver_success(self, mock_graph_db: Mock, mock_driver: Mock) -> None:
        """Test driver health check success."""
        mock_graph_db.driver = Mock(return_value=mock_driver)
        uri = "neo4j://localhost:7687"
        auth = ("neo4j", "password")

        resilient_driver = ResilientNeo4jDriver(uri, auth)
        result = resilient_driver._test_driver(mock_driver)

        assert result is True
        mock_driver.session.assert_called_once_with(database="neo4j")

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_test_driver_failure(self, mock_graph_db: Mock) -> None:
        """Test driver health check failure."""
        failing_driver = Mock()
        failing_driver.session = Mock(side_effect=ServiceUnavailable("Connection failed"))

        resilient_driver = ResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        result = resilient_driver._test_driver(failing_driver)

        assert result is False

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_session(self, mock_graph_db: Mock, mock_driver: Mock) -> None:
        """Test session creation."""
        mock_graph_db.driver = Mock(return_value=mock_driver)
        uri = "neo4j://localhost:7687"
        auth = ("neo4j", "password")

        resilient_driver = ResilientNeo4jDriver(uri, auth)

        # Mock get_connection to return the mock driver directly
        resilient_driver.get_connection = Mock(return_value=mock_driver)

        session = resilient_driver.session(database="neo4j")

        mock_driver.session.assert_called_once_with(database="neo4j")

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_close(self, mock_graph_db: Mock, mock_driver: Mock) -> None:
        """Test driver closure."""
        mock_graph_db.driver = Mock(return_value=mock_driver)

        resilient_driver = ResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        resilient_driver._connection = mock_driver

        resilient_driver.close()

        mock_driver.close.assert_called_once()
        assert resilient_driver._connection is None

    @patch("common.neo4j_resilient.GraphDatabase")
    def test_close_with_error(self, mock_graph_db: Mock) -> None:
        """Test driver closure with error."""
        failing_driver = Mock()
        failing_driver.close = Mock(side_effect=Exception("Close failed"))

        resilient_driver = ResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        resilient_driver._connection = failing_driver

        # Should not raise exception
        resilient_driver.close()

        assert resilient_driver._connection is None


class TestAsyncResilientNeo4jDriver:
    """Tests for AsyncResilientNeo4jDriver class."""

    @pytest.fixture
    def mock_async_driver(self) -> AsyncMock:
        """Create a mock async Neo4j driver."""
        driver = AsyncMock()
        session = AsyncMock()
        result = AsyncMock()
        record = MagicMock()
        record.__getitem__ = Mock(return_value=1)
        result.single = AsyncMock(return_value=record)
        session.run = AsyncMock(return_value=result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        driver.session = Mock(return_value=session)
        driver.close = AsyncMock()
        return driver

    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    def test_init(self, mock_async_graph_db: Mock) -> None:
        """Test AsyncResilientNeo4jDriver initialization."""
        uri = "neo4j://localhost:7687"
        auth = ("neo4j", "password")

        driver = AsyncResilientNeo4jDriver(uri, auth, max_retries=3)

        assert driver.uri == uri
        assert driver.auth == auth
        assert driver.health_check_query == "RETURN 1 as healthy"
        assert driver.driver_kwargs["max_connection_pool_size"] == 50

    @pytest.mark.asyncio
    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    async def test_create_driver(self, mock_async_graph_db: Mock, mock_async_driver: AsyncMock) -> None:
        """Test async driver creation."""
        mock_async_graph_db.driver = Mock(return_value=mock_async_driver)

        resilient_driver = AsyncResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        created_driver = await resilient_driver._create_driver()

        assert created_driver == mock_async_driver
        mock_async_graph_db.driver.assert_called_once()

    @pytest.mark.asyncio
    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    async def test_test_driver_success(self, mock_async_graph_db: Mock, mock_async_driver: AsyncMock) -> None:
        """Test async driver health check success."""
        resilient_driver = AsyncResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        result = await resilient_driver._test_driver(mock_async_driver)

        assert result is True

    @pytest.mark.asyncio
    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    async def test_test_driver_failure(self, mock_async_graph_db: Mock) -> None:
        """Test async driver health check failure."""
        failing_driver = AsyncMock()
        failing_driver.session = Mock(side_effect=ServiceUnavailable("Connection failed"))

        resilient_driver = AsyncResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        result = await resilient_driver._test_driver(failing_driver)

        assert result is False

    @pytest.mark.asyncio
    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    async def test_session(self, mock_async_graph_db: Mock, mock_async_driver: AsyncMock) -> None:
        """Test async session creation."""
        mock_async_graph_db.driver = Mock(return_value=mock_async_driver)

        resilient_driver = AsyncResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))

        # Mock get_connection to return the mock driver directly
        resilient_driver.get_connection = AsyncMock(return_value=mock_async_driver)

        session = await resilient_driver.session(database="neo4j")

        mock_async_driver.session.assert_called_once_with(database="neo4j")

    @pytest.mark.asyncio
    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    async def test_close(self, mock_async_graph_db: Mock, mock_async_driver: AsyncMock) -> None:
        """Test async driver closure."""
        resilient_driver = AsyncResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        resilient_driver._connection = mock_async_driver

        await resilient_driver.close()

        mock_async_driver.close.assert_called_once()
        assert resilient_driver._connection is None

    @pytest.mark.asyncio
    @patch("common.neo4j_resilient.AsyncGraphDatabase")
    async def test_close_with_error(self, mock_async_graph_db: Mock) -> None:
        """Test async driver closure with error."""
        failing_driver = AsyncMock()
        failing_driver.close = AsyncMock(side_effect=Exception("Close failed"))

        resilient_driver = AsyncResilientNeo4jDriver("neo4j://localhost:7687", ("neo4j", "password"))
        resilient_driver._connection = failing_driver

        # Should not raise exception
        await resilient_driver.close()

        assert resilient_driver._connection is None


class TestNeo4jRetryDecorator:
    """Tests for with_neo4j_retry decorator."""

    def test_success_on_first_try(self) -> None:
        """Test successful execution on first try."""
        mock_func = Mock(return_value="success")
        wrapped = with_neo4j_retry(mock_func, max_retries=3)

        result = wrapped()

        assert result == "success"
        mock_func.assert_called_once()

    def test_retry_on_service_unavailable(self) -> None:
        """Test retry on ServiceUnavailable exception."""
        mock_func = Mock(side_effect=[ServiceUnavailable("Connection failed"), ServiceUnavailable("Connection failed"), "success"])

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)
        wrapped = with_neo4j_retry(mock_func, max_retries=3, backoff=backoff)

        result = wrapped()

        assert result == "success"
        assert mock_func.call_count == 3

    def test_retry_on_session_expired(self) -> None:
        """Test retry on SessionExpired exception."""
        mock_func = Mock(side_effect=[SessionExpired(None, "Session expired"), "success"])

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)
        wrapped = with_neo4j_retry(mock_func, max_retries=3, backoff=backoff)

        result = wrapped()

        assert result == "success"
        assert mock_func.call_count == 2

    def test_max_retries_exceeded(self) -> None:
        """Test failure after max retries exceeded."""
        mock_func = Mock(side_effect=ServiceUnavailable("Connection failed"))

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)
        wrapped = with_neo4j_retry(mock_func, max_retries=2, backoff=backoff)

        with pytest.raises(ServiceUnavailable):
            wrapped()

        assert mock_func.call_count == 2


class TestAsyncNeo4jRetryDecorator:
    """Tests for with_async_neo4j_retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        """Test successful async execution on first try."""
        mock_func = AsyncMock(return_value="success")
        wrapped = with_async_neo4j_retry(mock_func, max_retries=3)

        result = await wrapped()

        assert result == "success"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_service_unavailable(self) -> None:
        """Test async retry on ServiceUnavailable exception."""
        mock_func = AsyncMock(side_effect=[ServiceUnavailable("Connection failed"), ServiceUnavailable("Connection failed"), "success"])

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)
        wrapped = with_async_neo4j_retry(mock_func, max_retries=3, backoff=backoff)

        result = await wrapped()

        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_session_expired(self) -> None:
        """Test async retry on SessionExpired exception."""
        mock_func = AsyncMock(side_effect=[SessionExpired(None, "Session expired"), "success"])

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)
        wrapped = with_async_neo4j_retry(mock_func, max_retries=3, backoff=backoff)

        result = await wrapped()

        assert result == "success"
        assert mock_func.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self) -> None:
        """Test async failure after max retries exceeded."""
        mock_func = AsyncMock(side_effect=ServiceUnavailable("Connection failed"))

        backoff = ExponentialBackoff(initial_delay=0.01, max_delay=0.1)
        wrapped = with_async_neo4j_retry(mock_func, max_retries=2, backoff=backoff)

        with pytest.raises(ServiceUnavailable):
            await wrapped()

        assert mock_func.call_count == 2
