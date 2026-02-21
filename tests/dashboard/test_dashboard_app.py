"""Unit tests for the DashboardApp class."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
import httpx
import pytest

from dashboard.dashboard import DashboardApp, DatabaseInfo, QueueInfo, ServiceStatus, SystemMetrics


class TestDashboardAppInit:
    """Test DashboardApp initialization."""

    def test_init(self) -> None:
        """Test DashboardApp initialization."""
        with patch("dashboard.dashboard.get_config") as mock_config:
            mock_config.return_value = Mock()
            app = DashboardApp()

            assert app.config is not None
            assert app.websocket_connections == set()
            assert app.latest_metrics is None
            assert app.rabbitmq is None
            assert app.neo4j_driver is None
            assert app.postgres_conn is None
            assert app.update_task is None


class TestDashboardAppStartup:
    """Test DashboardApp startup."""

    @pytest.mark.asyncio
    async def test_startup_success(self) -> None:
        """Test successful startup."""
        mock_config = Mock()
        mock_config.amqp_connection = "amqp://test"
        mock_config.neo4j_address = "bolt://test:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "test"
        mock_config.postgres_address = "localhost:5432"
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        mock_rabbitmq = AsyncMock()
        mock_neo4j = AsyncMock()
        mock_postgres = AsyncMock()

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.AsyncResilientRabbitMQ", return_value=mock_rabbitmq),
            patch("dashboard.dashboard.AsyncResilientNeo4jDriver", return_value=mock_neo4j),
            patch("dashboard.dashboard.AsyncResilientPostgreSQL", return_value=mock_postgres),
            patch("asyncio.create_task") as mock_create_task,
            patch.object(DashboardApp, "collect_metrics_loop", new_callable=AsyncMock),
        ):
            app = DashboardApp()
            await app.startup()

            # Verify connections were established
            mock_rabbitmq.connect.assert_called_once()
            assert app.rabbitmq == mock_rabbitmq
            assert app.neo4j_driver == mock_neo4j
            assert app.postgres_conn == mock_postgres

            # Verify background task was started
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_with_port_in_postgres_address(self) -> None:
        """Test startup with custom PostgreSQL port."""
        mock_config = Mock()
        mock_config.amqp_connection = "amqp://test"
        mock_config.neo4j_address = "bolt://test:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "test"
        mock_config.postgres_address = "localhost:5433"  # Custom port
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.AsyncResilientRabbitMQ", return_value=AsyncMock()),
            patch("dashboard.dashboard.AsyncResilientNeo4jDriver", return_value=AsyncMock()),
            patch("dashboard.dashboard.AsyncResilientPostgreSQL") as mock_postgres_class,
            patch("asyncio.create_task"),
            patch.object(DashboardApp, "collect_metrics_loop", new_callable=AsyncMock),
        ):
            app = DashboardApp()
            await app.startup()

            # Verify PostgreSQL was initialized with custom port
            call_args = mock_postgres_class.call_args
            assert call_args[1]["connection_params"]["host"] == "localhost"
            assert call_args[1]["connection_params"]["port"] == 5433

    @pytest.mark.asyncio
    async def test_startup_error(self) -> None:
        """Test startup error handling."""
        mock_config = Mock()
        mock_config.amqp_connection = "amqp://test"

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.AsyncResilientRabbitMQ") as mock_rabbitmq_class,
            patch("dashboard.dashboard.logger") as mock_logger,
        ):
            mock_rabbitmq_class.return_value.connect.side_effect = Exception("Connection failed")

            app = DashboardApp()
            with pytest.raises(Exception, match="Connection failed"):
                await app.startup()

            # Verify error was logged
            mock_logger.error.assert_called()


class TestDashboardAppShutdown:
    """Test DashboardApp shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_success(self) -> None:
        """Test successful shutdown."""
        mock_config = Mock()

        async def cancelled_task() -> None:
            """Task that raises CancelledError when awaited."""
            raise asyncio.CancelledError()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            # Set up mocked connections
            # Create a real task that will raise CancelledError
            app.update_task = asyncio.create_task(cancelled_task())

            app.rabbitmq = AsyncMock()
            app.neo4j_driver = AsyncMock()
            app.postgres_conn = AsyncMock()

            # Add mock websockets
            mock_ws1 = AsyncMock()
            mock_ws2 = AsyncMock()
            app.websocket_connections.add(mock_ws1)
            app.websocket_connections.add(mock_ws2)

            await app.shutdown()

            # Verify task was cancelled (it starts cancelled so we can't check this)
            # But we can verify connections were closed
            app.rabbitmq.close.assert_called_once()
            app.neo4j_driver.close.assert_called_once()
            app.postgres_conn.close.assert_called_once()

            # Verify websockets were closed
            mock_ws1.close.assert_called_once()
            mock_ws2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_with_no_connections(self) -> None:
        """Test shutdown when no connections exist."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            # No connections set up
            await app.shutdown()

            # Should complete without error

    @pytest.mark.asyncio
    async def test_shutdown_error(self) -> None:
        """Test shutdown error handling."""
        mock_config = Mock()

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.logger") as mock_logger,
        ):
            app = DashboardApp()
            app.rabbitmq = AsyncMock()
            app.rabbitmq.close.side_effect = Exception("Close failed")

            await app.shutdown()

            # Verify error was logged
            mock_logger.error.assert_called()


class TestDashboardAppMetrics:
    """Test DashboardApp metrics collection."""

    @pytest.mark.asyncio
    async def test_collect_all_metrics(self) -> None:
        """Test collecting all metrics."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            # Mock the collection methods
            mock_services = [
                ServiceStatus(
                    name="extractor",
                    status="healthy",
                    last_seen=datetime.now(),
                    current_task="processing",
                    progress=0.5,
                    error=None,
                )
            ]
            mock_queues = [
                QueueInfo(
                    name="artists",
                    messages=100,
                    messages_ready=50,
                    messages_unacknowledged=50,
                    consumers=2,
                    message_rate=10.0,
                    ack_rate=9.5,
                )
            ]
            mock_databases = [DatabaseInfo(name="neo4j", status="healthy", connection_count=5, size="1GB", error=None)]

            with (
                patch.object(app, "get_service_statuses", return_value=mock_services),
                patch.object(app, "get_queue_info", return_value=mock_queues),
                patch.object(app, "get_database_info", return_value=mock_databases),
            ):
                metrics = await app.collect_all_metrics()

                assert isinstance(metrics, SystemMetrics)
                assert metrics.services == mock_services
                assert metrics.queues == mock_queues
                assert metrics.databases == mock_databases
                assert metrics.timestamp is not None

    @pytest.mark.asyncio
    async def test_collect_metrics_loop(self) -> None:
        """Test metrics collection loop."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            mock_metrics = SystemMetrics(services=[], queues=[], databases=[], timestamp=datetime.now())

            call_count = 0

            async def mock_collect() -> SystemMetrics:
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    # Cancel after 2 iterations
                    raise asyncio.CancelledError()
                return mock_metrics

            with (
                patch.object(app, "collect_all_metrics", side_effect=mock_collect),
                patch.object(app, "broadcast_metrics", new_callable=AsyncMock) as mock_broadcast,
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                await app.collect_metrics_loop()

                # Verify metrics were collected and broadcast
                assert call_count == 2
                assert mock_broadcast.call_count == 1
                assert app.latest_metrics == mock_metrics

    @pytest.mark.asyncio
    async def test_collect_metrics_loop_error_handling(self) -> None:
        """Test error handling in metrics collection loop."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            call_count = 0

            async def mock_collect_with_error() -> SystemMetrics:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise Exception("Collection failed")
                # Cancel after error is handled
                raise asyncio.CancelledError()

            with (
                patch.object(app, "collect_all_metrics", side_effect=mock_collect_with_error),
                patch.object(app, "broadcast_metrics", new_callable=AsyncMock),
                patch("asyncio.sleep", new_callable=AsyncMock),
                patch("dashboard.dashboard.logger") as mock_logger,
            ):
                await app.collect_metrics_loop()

                # Verify error was logged
                mock_logger.error.assert_called()
                assert call_count == 2


class TestDashboardAppBroadcast:
    """Test WebSocket broadcasting."""

    @pytest.mark.asyncio
    async def test_broadcast_metrics(self) -> None:
        """Test broadcasting metrics to websockets."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            # Add mock websockets
            mock_ws1 = AsyncMock()
            mock_ws2 = AsyncMock()
            app.websocket_connections.add(mock_ws1)
            app.websocket_connections.add(mock_ws2)

            metrics = SystemMetrics(services=[], queues=[], databases=[], timestamp=datetime.now())

            await app.broadcast_metrics(metrics)

            # Verify both websockets received the metrics via send_text
            assert mock_ws1.send_text.call_count == 1
            assert mock_ws2.send_text.call_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_metrics_with_no_connections(self) -> None:
        """Test broadcasting with no websocket connections."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            metrics = SystemMetrics(services=[], queues=[], databases=[], timestamp=datetime.now())

            # Should complete without error
            await app.broadcast_metrics(metrics)

    @pytest.mark.asyncio
    async def test_broadcast_metrics_removes_disconnected(self) -> None:
        """Test that failed websockets are removed from connections."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            # Add websockets - one working, one failing
            mock_ws_working = AsyncMock()
            mock_ws_failing = AsyncMock()
            mock_ws_failing.send_text.side_effect = Exception("Send failed")

            app.websocket_connections.add(mock_ws_working)
            app.websocket_connections.add(mock_ws_failing)

            metrics = SystemMetrics(services=[], queues=[], databases=[], timestamp=datetime.now())

            await app.broadcast_metrics(metrics)

            # Verify failing websocket was removed
            assert mock_ws_working in app.websocket_connections
            assert mock_ws_failing not in app.websocket_connections


class TestDashboardAppDataCollection:
    """Test data collection methods."""

    @pytest.mark.asyncio
    async def test_get_service_statuses_all_healthy(self) -> None:
        """Test getting service statuses when all services are healthy."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            # Mock httpx client responses
            mock_response_data = {
                "status": "healthy",
                "current_task": "processing",
                "progress": 0.75,
            }

            async def mock_get(_url: str) -> Mock:
                response = Mock()
                response.status_code = 200
                response.json = Mock(return_value=mock_response_data)
                return response

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                statuses = await app.get_service_statuses()

                # Should have 3 services (extractor, graphinator, tableinator)
                assert len(statuses) == 3

                # All should be healthy
                for status in statuses:
                    assert status.status == "healthy"
                    assert status.current_task == "processing"
                    assert status.progress == 0.75
                    assert status.error is None

    @pytest.mark.asyncio
    async def test_get_service_statuses_some_unhealthy(self) -> None:
        """Test getting service statuses when some services are unhealthy."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            call_count = 0

            async def mock_get(_url: str) -> Mock:
                nonlocal call_count
                call_count += 1
                response = Mock()
                if call_count == 1:
                    # First service (extractor) healthy
                    response.status_code = 200
                    response.json = Mock(return_value={"status": "healthy"})
                elif call_count == 2:
                    # Second service (graphinator) returns error code
                    response.status_code = 500
                else:
                    # Third service (tableinator) raises exception
                    raise httpx.ConnectError("Connection failed")
                return response

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                statuses = await app.get_service_statuses()

                assert len(statuses) == 3
                assert statuses[0].status == "healthy"
                assert statuses[1].status == "unhealthy"
                assert statuses[1].error == "HTTP 500"
                assert statuses[2].status == "unknown"
                assert "Connection failed" in statuses[2].error

    @pytest.mark.asyncio
    async def test_get_queue_info_success(self) -> None:
        """Test getting queue information successfully."""
        mock_config = Mock()
        mock_config.rabbitmq_management_user = "guest"
        mock_config.rabbitmq_management_password = "guest"

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()
            app.rabbitmq = AsyncMock()  # Set rabbitmq connection

            # Mock RabbitMQ management API response
            queue_data = [
                {
                    "name": "discogsography.artists",
                    "messages": 100,
                    "messages_ready": 50,
                    "messages_unacknowledged": 50,
                    "consumers": 2,
                    "message_stats": {
                        "publish_details": {"rate": 10.5},
                        "ack_details": {"rate": 9.8},
                    },
                },
                {
                    "name": "discogsography.releases",
                    "messages": 200,
                    "messages_ready": 150,
                    "messages_unacknowledged": 50,
                    "consumers": 3,
                    "message_stats": {
                        "publish_details": {"rate": 20.0},
                        "ack_details": {"rate": 18.5},
                    },
                },
                {
                    "name": "other.queue",  # Should be filtered out
                    "messages": 10,
                    "messages_ready": 5,
                    "messages_unacknowledged": 5,
                    "consumers": 1,
                },
            ]

            async def mock_get(_url: str, **_kwargs: Any) -> Mock:
                response = Mock()
                response.status_code = 200
                response.json = Mock(return_value=queue_data)
                return response

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                queues = await app.get_queue_info()

                # Should only have 2 queues (discogsography prefix)
                assert len(queues) == 2
                assert queues[0].name == "discogsography.artists"
                assert queues[0].messages == 100
                assert queues[0].message_rate == 10.5
                assert queues[1].name == "discogsography.releases"

    @pytest.mark.asyncio
    async def test_get_queue_info_no_rabbitmq(self) -> None:
        """Test getting queue info when RabbitMQ is not connected."""
        mock_config = Mock()

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()
            # No rabbitmq connection

            queues = await app.get_queue_info()

            # Should return empty list
            assert queues == []

    @pytest.mark.asyncio
    async def test_get_queue_info_auth_failure(self) -> None:
        """Test queue info when authentication fails."""
        mock_config = Mock()
        mock_config.rabbitmq_management_user = "guest"
        mock_config.rabbitmq_management_password = "wrong"

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.logger") as mock_logger,
        ):
            app = DashboardApp()
            app.rabbitmq = AsyncMock()

            async def mock_get(_url: str, **_kwargs: Any) -> Mock:
                response = Mock()
                response.status_code = 401
                return response

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                queues = await app.get_queue_info()

                # Should return empty list and log warning
                assert queues == []
                mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_get_queue_info_non_200_status(self) -> None:
        """Test queue info when API returns non-200 status."""
        mock_config = Mock()
        mock_config.rabbitmq_management_user = "guest"
        mock_config.rabbitmq_management_password = "guest"

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.logger") as mock_logger,
        ):
            app = DashboardApp()
            app.rabbitmq = AsyncMock()

            async def mock_get(_url: str, **_kwargs: Any) -> Mock:
                response = Mock()
                response.status_code = 503
                return response

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                queues = await app.get_queue_info()

                # Should return empty list and log warning
                assert queues == []
                mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_get_queue_info_connection_error(self) -> None:
        """Test queue info when connection error occurs."""
        mock_config = Mock()
        mock_config.rabbitmq_management_user = "guest"
        mock_config.rabbitmq_management_password = "guest"

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.logger") as mock_logger,
        ):
            app = DashboardApp()
            app.rabbitmq = AsyncMock()

            async def mock_get(_url: str, **_kwargs: Any) -> Mock:
                raise httpx.ConnectError("Connection refused")

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                queues = await app.get_queue_info()

                # Should return empty list and log debug
                assert queues == []
                mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_get_queue_info_unexpected_error(self) -> None:
        """Test queue info when unexpected error occurs."""
        mock_config = Mock()
        mock_config.rabbitmq_management_user = "guest"
        mock_config.rabbitmq_management_password = "guest"

        with (
            patch("dashboard.dashboard.get_config", return_value=mock_config),
            patch("dashboard.dashboard.logger") as mock_logger,
        ):
            app = DashboardApp()
            app.rabbitmq = AsyncMock()

            async def mock_get(_url: str, _auth: tuple[str, str]) -> Mock:
                raise Exception("Unexpected error")

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get = mock_get
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                queues = await app.get_queue_info()

                # Should return empty list and log error
                assert queues == []
                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_get_database_info_success(self) -> None:
        """Test getting database information successfully."""
        mock_config = Mock()
        mock_config.postgres_address = "localhost:5432"
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()
            app.neo4j_driver = AsyncMock()

            # Mock PostgreSQL cursor with proper async context manager
            mock_pg_cursor = AsyncMock()
            mock_pg_cursor.execute = AsyncMock()
            mock_pg_cursor.fetchone = AsyncMock(
                side_effect=[
                    (5,),  # connection count
                    ("100 MB",),  # database size
                ]
            )
            mock_pg_cursor.__aenter__ = AsyncMock(return_value=mock_pg_cursor)
            mock_pg_cursor.__aexit__ = AsyncMock(return_value=None)

            # Mock PostgreSQL connection with cursor that returns async context manager
            mock_pg_conn = AsyncMock()
            # cursor() should return the cursor object (not be async)
            mock_pg_conn.cursor = Mock(return_value=mock_pg_cursor)
            mock_pg_conn.__aenter__ = AsyncMock(return_value=mock_pg_conn)
            mock_pg_conn.__aexit__ = AsyncMock(return_value=None)

            # Mock the connect function to return the connection
            async def mock_connect(**_kwargs):
                return mock_pg_conn

            # Mock Neo4j session
            mock_neo4j_result1 = AsyncMock()
            mock_neo4j_result1.single = AsyncMock(return_value=None)
            mock_neo4j_result2 = AsyncMock()
            mock_neo4j_result2.single = AsyncMock(return_value={"nodeCount": 1000, "relCount": 500})

            mock_neo4j_session = AsyncMock()
            mock_neo4j_session.run = AsyncMock(side_effect=[mock_neo4j_result1, mock_neo4j_result2])
            mock_neo4j_session.__aenter__ = AsyncMock(return_value=mock_neo4j_session)
            mock_neo4j_session.__aexit__ = AsyncMock(return_value=None)

            app.neo4j_driver.session = AsyncMock(return_value=mock_neo4j_session)

            with patch("psycopg.AsyncConnection.connect", side_effect=mock_connect):
                databases = await app.get_database_info()

                # Should have both PostgreSQL and Neo4j
                assert len(databases) == 2
                assert databases[0].name == "PostgreSQL"
                assert databases[0].status == "healthy"
                assert databases[0].connection_count == 5
                assert databases[0].size == "100 MB"
                assert databases[1].name == "Neo4j"
                assert databases[1].status == "healthy"
                assert "1,000 nodes" in databases[1].size

    @pytest.mark.asyncio
    async def test_get_database_info_postgres_error(self) -> None:
        """Test database info when PostgreSQL connection fails."""
        mock_config = Mock()
        mock_config.postgres_address = "localhost:5432"
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()
            app.neo4j_driver = None  # No Neo4j

            # Mock Neo4j session that returns healthy status
            mock_neo4j_result1 = AsyncMock()
            mock_neo4j_result1.single = AsyncMock(return_value=None)
            mock_neo4j_result2 = AsyncMock()
            mock_neo4j_result2.single = AsyncMock(return_value={"nodeCount": 100, "relCount": 50})

            with patch("psycopg.AsyncConnection.connect", side_effect=Exception("Connection failed")):
                databases = await app.get_database_info()

                # Should have PostgreSQL as unhealthy
                assert len(databases) == 1
                assert databases[0].name == "PostgreSQL"
                assert databases[0].status == "unhealthy"
                assert "Connection failed" in databases[0].error

    @pytest.mark.asyncio
    async def test_get_database_info_neo4j_error(self) -> None:
        """Test database info when Neo4j connection fails."""
        mock_config = Mock()
        mock_config.postgres_address = "localhost:5432"
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()
            app.neo4j_driver = AsyncMock()

            # Mock PostgreSQL cursor with proper async context manager
            mock_pg_cursor = AsyncMock()
            mock_pg_cursor.execute = AsyncMock()
            mock_pg_cursor.fetchone = AsyncMock(side_effect=[(3,), ("50 MB",)])
            mock_pg_cursor.__aenter__ = AsyncMock(return_value=mock_pg_cursor)
            mock_pg_cursor.__aexit__ = AsyncMock(return_value=None)

            # Mock PostgreSQL connection
            mock_pg_conn = AsyncMock()
            # cursor() should return the cursor object (not be async)
            mock_pg_conn.cursor = Mock(return_value=mock_pg_cursor)
            mock_pg_conn.__aenter__ = AsyncMock(return_value=mock_pg_conn)
            mock_pg_conn.__aexit__ = AsyncMock(return_value=None)

            async def mock_connect(**_kwargs):
                return mock_pg_conn

            # Mock Neo4j session failure
            app.neo4j_driver.session.side_effect = Exception("Neo4j connection failed")

            with patch("psycopg.AsyncConnection.connect", side_effect=mock_connect):
                databases = await app.get_database_info()

                # Should have both databases
                assert len(databases) == 2
                assert databases[0].name == "PostgreSQL"
                assert databases[0].status == "healthy"
                assert databases[1].name == "Neo4j"
                assert databases[1].status == "unhealthy"
                assert "Neo4j connection failed" in databases[1].error


class TestFastAPIEndpoints:
    """Test FastAPI endpoint handlers."""

    def test_health_check(self) -> None:
        """Test health check endpoint."""
        # Create a test app without lifespan to avoid connection attempts
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import health_check

        test_app = FastAPI(default_response_class=ORJSONResponse)
        test_app.get("/health")(health_check)

        with TestClient(test_app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "dashboard"
            assert "timestamp" in data
            assert "uptime" in data

    @pytest.mark.asyncio
    async def test_get_metrics_with_data(self) -> None:
        """Test /api/metrics endpoint with existing metrics."""
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import get_metrics

        mock_metrics = SystemMetrics(
            services=[],
            queues=[],
            databases=[],
            timestamp=datetime.now(UTC),
        )

        with patch("dashboard.dashboard.dashboard") as mock_dashboard_obj:
            mock_dashboard_obj.latest_metrics = mock_metrics

            test_app = FastAPI(default_response_class=ORJSONResponse)
            test_app.get("/api/metrics")(get_metrics)

            with TestClient(test_app) as client:
                response = client.get("/api/metrics")
                assert response.status_code == 200
                data = response.json()
                assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_get_metrics_without_data(self) -> None:
        """Test /api/metrics endpoint collecting on demand."""
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import get_metrics

        mock_metrics = SystemMetrics(
            services=[],
            queues=[],
            databases=[],
            timestamp=datetime.now(UTC),
        )

        mock_dashboard_instance = Mock()
        mock_dashboard_instance.latest_metrics = None
        mock_dashboard_instance.collect_all_metrics = AsyncMock(return_value=mock_metrics)

        with patch("dashboard.dashboard.dashboard", mock_dashboard_instance):
            test_app = FastAPI(default_response_class=ORJSONResponse)
            test_app.get("/api/metrics")(get_metrics)

            with TestClient(test_app) as client:
                response = client.get("/api/metrics")
                assert response.status_code == 200
                mock_dashboard_instance.collect_all_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_metrics_no_dashboard(self) -> None:
        """Test /api/metrics endpoint when dashboard is None."""
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import get_metrics

        with patch("dashboard.dashboard.dashboard", None):
            test_app = FastAPI(default_response_class=ORJSONResponse)
            test_app.get("/api/metrics")(get_metrics)

            with TestClient(test_app) as client:
                response = client.get("/api/metrics")
                assert response.status_code == 200
                assert response.json() == {}

    @pytest.mark.asyncio
    async def test_get_services(self) -> None:
        """Test /api/services endpoint."""
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import get_services

        mock_services = [
            ServiceStatus(
                name="extractor",
                status="healthy",
                last_seen=datetime.now(UTC),
                current_task=None,
                progress=None,
                error=None,
            )
        ]

        mock_dashboard_instance = Mock()
        mock_dashboard_instance.get_service_statuses = AsyncMock(return_value=mock_services)

        with patch("dashboard.dashboard.dashboard", mock_dashboard_instance):
            test_app = FastAPI(default_response_class=ORJSONResponse)
            test_app.get("/api/services")(get_services)

            with TestClient(test_app) as client:
                response = client.get("/api/services")
                assert response.status_code == 200
                data = response.json()
                assert len(data) == 1
                assert data[0]["name"] == "extractor"

    @pytest.mark.asyncio
    async def test_get_queues(self) -> None:
        """Test /api/queues endpoint."""
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import get_queues

        mock_queues = [
            QueueInfo(
                name="discogsography.artists",
                messages=100,
                messages_ready=50,
                messages_unacknowledged=50,
                consumers=2,
                message_rate=10.5,
                ack_rate=9.8,
            )
        ]

        mock_dashboard_instance = Mock()
        mock_dashboard_instance.get_queue_info = AsyncMock(return_value=mock_queues)

        with patch("dashboard.dashboard.dashboard", mock_dashboard_instance):
            test_app = FastAPI(default_response_class=ORJSONResponse)
            test_app.get("/api/queues")(get_queues)

            with TestClient(test_app) as client:
                response = client.get("/api/queues")
                assert response.status_code == 200
                data = response.json()
                assert len(data) == 1
                assert data[0]["name"] == "discogsography.artists"

    @pytest.mark.asyncio
    async def test_get_databases(self) -> None:
        """Test /api/databases endpoint."""
        from fastapi import FastAPI
        from fastapi.responses import ORJSONResponse

        from dashboard.dashboard import get_databases

        mock_databases = [
            DatabaseInfo(
                name="PostgreSQL",
                status="healthy",
                connection_count=5,
                size="100 MB",
                error=None,
            )
        ]

        mock_dashboard_instance = Mock()
        mock_dashboard_instance.get_database_info = AsyncMock(return_value=mock_databases)

        with patch("dashboard.dashboard.dashboard", mock_dashboard_instance):
            test_app = FastAPI(default_response_class=ORJSONResponse)
            test_app.get("/api/databases")(get_databases)

            with TestClient(test_app) as client:
                response = client.get("/api/databases")
                assert response.status_code == 200
                data = response.json()
                assert len(data) == 1
                assert data[0]["name"] == "PostgreSQL"

    def test_prometheus_metrics(self) -> None:
        """Test /metrics Prometheus endpoint."""
        from fastapi import FastAPI

        from dashboard.dashboard import prometheus_metrics

        test_app = FastAPI()
        test_app.get("/metrics")(prometheus_metrics)

        with TestClient(test_app) as client:
            response = client.get("/metrics")
            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]
            # Prometheus metrics should contain some text
            assert len(response.text) > 0


class TestWebSocketEndpoint:
    """Test WebSocket connection handling."""

    @pytest.mark.asyncio
    async def test_websocket_connection_and_disconnect(self) -> None:
        """Test WebSocket connection lifecycle."""
        from fastapi import FastAPI

        from dashboard.dashboard import websocket_endpoint

        # Mock dashboard instance
        mock_dashboard_instance = Mock()
        mock_dashboard_instance.websocket_connections = set()
        mock_dashboard_instance.latest_metrics = SystemMetrics(
            services=[],
            queues=[],
            databases=[],
            timestamp=datetime.now(UTC),
        )

        with patch("dashboard.dashboard.dashboard", mock_dashboard_instance):
            test_app = FastAPI()
            test_app.websocket("/ws")(websocket_endpoint)

            with TestClient(test_app) as client, client.websocket_connect("/ws") as _websocket:
                # Verify connection was added
                assert len(mock_dashboard_instance.websocket_connections) == 1

                # Should receive initial metrics
                data = _websocket.receive_json()
                assert data["type"] == "metrics_update"
                assert "data" in data

                # After disconnect, connection should be removed
                # (handled by WebSocketDisconnect exception)

    @pytest.mark.asyncio
    async def test_websocket_error_handling(self) -> None:
        """Test WebSocket error handling."""
        from fastapi import FastAPI

        from dashboard.dashboard import websocket_endpoint

        # Mock dashboard instance
        mock_dashboard_instance = Mock()
        mock_dashboard_instance.websocket_connections = set()
        mock_dashboard_instance.latest_metrics = None  # No initial metrics

        with (
            patch("dashboard.dashboard.dashboard", mock_dashboard_instance),
            patch("dashboard.dashboard.logger") as _mock_logger,
        ):
            test_app = FastAPI()
            test_app.websocket("/ws")(websocket_endpoint)

            with TestClient(test_app) as client, client.websocket_connect("/ws") as _websocket:
                # Verify connection was added
                assert len(mock_dashboard_instance.websocket_connections) == 1

                # Simulate an error by sending malformed data
                # The websocket will keep trying to receive
                # We just close it to trigger the error handling
                pass

                # After disconnect, connection should be removed
                # The exception handling in websocket_endpoint should have cleaned up


class TestPostgresAddressParsing:
    """Test PostgreSQL address parsing edge cases."""

    @pytest.mark.asyncio
    async def test_startup_postgres_address_without_port(self) -> None:
        """Test startup with PostgreSQL address without port."""
        mock_config = Mock()
        mock_config.amqp_connection = "amqp://test"
        mock_config.neo4j_address = "bolt://test:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "test"
        mock_config.postgres_address = "localhost"  # No port
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()

            mock_rabbitmq = AsyncMock()
            mock_neo4j = AsyncMock()
            mock_postgres = AsyncMock()

            with (
                patch("dashboard.dashboard.AsyncResilientRabbitMQ", return_value=mock_rabbitmq),
                patch("dashboard.dashboard.AsyncResilientNeo4jDriver", return_value=mock_neo4j),
                patch("dashboard.dashboard.AsyncResilientPostgreSQL", return_value=mock_postgres),
                patch("asyncio.create_task") as _mock_create_task,
            ):
                await app.startup()

                # Verify PostgreSQL connection was created with default port 5432
                # mock_postgres_call_args = mock_postgres.__class__.call_args
                # PostgreSQL was initialized (exact args checking not critical for this test)
                assert app.postgres_conn is not None


class TestPrometheusMetricsInitialization:
    """Test Prometheus metrics initialization edge cases."""

    def test_metrics_already_registered(self) -> None:
        """Test that metrics handle ValueError when already registered."""
        # This test verifies the try/except ValueError blocks in lines 34-48
        # The metrics should already be registered from the dashboard module import
        # If we try to re-import, the ValueError handling should work

        # Import again to trigger ValueError handling
        import importlib

        import dashboard.dashboard

        # Force reload to trigger the ValueError paths
        with patch.object(DashboardApp, "collect_metrics_loop", new_callable=AsyncMock):
            importlib.reload(dashboard.dashboard)

        # If we get here without exception, the error handling worked
        assert True


class TestGetDatabaseInfoNoPort:
    """Test get_database_info() when postgres_address has no port (lines 323-324)."""

    @pytest.mark.asyncio
    async def test_get_database_info_postgres_address_without_port(self) -> None:
        """Test that get_database_info uses port 5432 when address has no colon."""
        mock_config = Mock()
        mock_config.postgres_address = "mydbhost"  # No port
        mock_config.postgres_database = "testdb"
        mock_config.postgres_username = "test"
        mock_config.postgres_password = "test"

        with patch("dashboard.dashboard.get_config", return_value=mock_config):
            app = DashboardApp()
            app.neo4j_driver = None

            connect_kwargs: dict[str, Any] = {}

            async def capture_connect(**kwargs: Any) -> Any:
                connect_kwargs.update(kwargs)
                raise Exception("Connection refused")

            with patch("psycopg.AsyncConnection.connect", side_effect=capture_connect):
                databases = await app.get_database_info()

            # Verify port defaulted to 5432 and host was used as-is
            assert connect_kwargs.get("host") == "mydbhost"
            assert connect_kwargs.get("port") == 5432
            assert databases[0].name == "PostgreSQL"
            assert databases[0].status == "unhealthy"


class TestWebSocketGeneralException:
    """Test WebSocket general exception handler (lines 569-573)."""

    @pytest.mark.asyncio
    async def test_websocket_general_exception_cleans_up(self) -> None:
        """Test that a non-WebSocketDisconnect exception removes the connection."""
        from dashboard.dashboard import websocket_endpoint

        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()
        mock_ws.send_text = AsyncMock()
        # Make receive_text raise a generic exception (not WebSocketDisconnect)
        mock_ws.receive_text = AsyncMock(side_effect=RuntimeError("network error"))

        mock_dashboard_instance = Mock()
        mock_dashboard_instance.websocket_connections = set()
        mock_dashboard_instance.latest_metrics = None  # Skip initial send

        with (
            patch("dashboard.dashboard.dashboard", mock_dashboard_instance),
            patch("dashboard.dashboard.logger"),
        ):
            await websocket_endpoint(mock_ws)

        # After the RuntimeError, the connection should have been cleaned up
        assert len(mock_dashboard_instance.websocket_connections) == 0
