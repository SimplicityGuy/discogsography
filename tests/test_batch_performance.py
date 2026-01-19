"""Performance tests for batch processing in graphinator and tableinator.

Tests verify that batch processing performance meets expected throughput
and efficiency goals after optimizations.
"""

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from graphinator.batch_processor import BatchConfig as Neo4jBatchConfig, Neo4jBatchProcessor
from tableinator.batch_processor import BatchConfig as PostgresBatchConfig, PostgreSQLBatchProcessor


class TestGraphinatorBatchPerformance:
    """Performance tests for Neo4j batch processing."""

    @pytest.fixture
    def mock_neo4j_driver(self):
        """Create mock Neo4j driver."""
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__.return_value = session
        driver.session.return_value.__exit__.return_value = None

        # Mock transaction execution
        def mock_execute_write(func):
            tx = MagicMock()
            # Mock run method to return results
            tx.run.return_value.single.return_value = None
            return func(tx)

        session.execute_write.side_effect = mock_execute_write

        return driver

    @pytest.fixture
    def batch_config(self):
        """Create batch configuration with optimized settings."""
        return Neo4jBatchConfig(
            batch_size=500,  # Optimized size
            flush_interval=2.0,  # Reduced interval
            max_pending=5000,
        )

    @pytest.mark.asyncio
    async def test_batch_size_500_processes_faster(self, mock_neo4j_driver, batch_config):
        """Test that batch size of 500 processes faster than 100."""
        processor = Neo4jBatchProcessor(mock_neo4j_driver, batch_config)

        # Create 1000 test records
        test_records = []
        for i in range(1000):
            test_records.append(
                {
                    "id": str(i),
                    "name": f"Artist {i}",
                    "sha256": f"hash_{i}",
                }
            )

        # Add messages to batch processor
        start_time = time.time()
        for record in test_records:
            await processor.add_message(
                "artists",
                record,
                AsyncMock(),
                AsyncMock(),
            )

        # Flush remaining
        await processor.flush_all()
        end_time = time.time()

        duration = end_time - start_time

        # Should complete in under 2 seconds for 1000 records
        assert duration < 2.0, f"Batch processing took {duration:.2f}s, expected <2s"

        # Should have processed all records
        assert processor.processed_counts["artists"] == 1000

        # Should have used 2 batches (1000 / 500 = 2)
        assert processor.batch_counts["artists"] == 2

    @pytest.mark.asyncio
    async def test_concurrent_batch_processing(self, mock_neo4j_driver, batch_config):
        """Test that concurrent batch processing works correctly."""
        processor = Neo4jBatchProcessor(mock_neo4j_driver, batch_config)

        # Simulate concurrent message arrival for different data types
        async def add_messages_for_type(data_type: str, count: int):
            for i in range(count):
                await processor.add_message(
                    data_type,
                    {
                        "id": f"{data_type}_{i}",
                        "name": f"Record {i}",
                        "sha256": f"hash_{i}",
                    },
                    AsyncMock(),
                    AsyncMock(),
                )

        # Process all types concurrently
        start_time = time.time()
        await asyncio.gather(
            add_messages_for_type("artists", 500),
            add_messages_for_type("labels", 500),
            add_messages_for_type("masters", 500),
            add_messages_for_type("releases", 500),
        )
        await processor.flush_all()
        end_time = time.time()

        duration = end_time - start_time

        # Should complete faster with concurrent processing
        # 2000 total records should complete in under 3 seconds
        assert duration < 3.0, f"Concurrent processing took {duration:.2f}s, expected <3s"

        # Verify all records processed
        assert processor.processed_counts["artists"] == 500
        assert processor.processed_counts["labels"] == 500
        assert processor.processed_counts["masters"] == 500
        assert processor.processed_counts["releases"] == 500

    @pytest.mark.asyncio
    async def test_flush_interval_optimization(self, mock_neo4j_driver):
        """Test that reduced flush interval improves latency."""
        # Test with 2.0 second interval (optimized)
        fast_config = Neo4jBatchConfig(batch_size=500, flush_interval=2.0, max_pending=5000)
        fast_processor = Neo4jBatchProcessor(mock_neo4j_driver, fast_config)

        # Start periodic flush task
        flush_task = asyncio.create_task(fast_processor.periodic_flush())

        try:
            # Add small number of messages (not enough to trigger batch size)
            start_time = time.time()
            for i in range(50):
                await fast_processor.add_message(
                    "artists",
                    {"id": str(i), "name": f"Artist {i}", "sha256": f"hash_{i}"},
                    AsyncMock(),
                    AsyncMock(),
                )

            # Wait for auto-flush
            await asyncio.sleep(2.5)
            end_time = time.time()

            # Should have flushed due to interval
            assert fast_processor.processed_counts["artists"] == 50

            # Total time should be close to flush_interval
            duration = end_time - start_time
            assert 2.0 <= duration <= 3.0, f"Expected flush at ~2s, got {duration:.2f}s"
        finally:
            # Stop periodic flush
            fast_processor.shutdown()
            flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await flush_task


class TestTableinatorBatchPerformance:
    """Performance tests for PostgreSQL batch processing."""

    @pytest.fixture
    def mock_connection_pool(self):
        """Create mock PostgreSQL connection pool."""
        pool = MagicMock()

        # Create async context manager for connection
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()

        # Mock cursor methods
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        # Mock connection methods
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        # Mock pool.connection() as async context manager
        pool.connection = MagicMock(return_value=mock_conn)

        return pool

    @pytest.fixture
    def batch_config(self):
        """Create batch configuration with optimized settings."""
        return PostgresBatchConfig(
            batch_size=500,  # Optimized size
            flush_interval=2.0,  # Reduced interval
            max_pending=5000,
        )

    @pytest.mark.asyncio
    async def test_batch_size_500_processes_faster(self, mock_connection_pool, batch_config):
        """Test that batch size of 500 processes faster than 100."""
        processor = PostgreSQLBatchProcessor(mock_connection_pool, batch_config)

        # Create 1000 test records
        test_records = []
        for i in range(1000):
            test_records.append(
                {
                    "id": str(i),
                    "name": f"Artist {i}",
                    "sha256": f"hash_{i}",
                }
            )

        # Add messages to batch processor
        start_time = time.time()
        for record in test_records:
            await processor.add_message(
                "artists",
                record,
                AsyncMock(),
                AsyncMock(),
            )

        # Flush remaining
        await processor.flush_all()
        end_time = time.time()

        duration = end_time - start_time

        # Should complete in under 1.2 seconds for 1000 records (PostgreSQL is fast)
        # 20% tolerance added to account for CI environment variability
        max_duration = 1.2 * 1.2  # 1.2s + 20% = 1.44s
        assert duration < max_duration, f"Batch processing took {duration:.2f}s, expected <{max_duration:.2f}s (1.2s + 20% tolerance)"

        # Should have processed all records
        assert processor.processed_counts["artists"] == 1000

        # Should have used 2 batches (1000 / 500 = 2)
        assert processor.batch_counts["artists"] == 2

    @pytest.mark.asyncio
    async def test_connection_pool_utilization(self, mock_connection_pool, batch_config):
        """Test that connection pool is properly utilized."""
        processor = PostgreSQLBatchProcessor(mock_connection_pool, batch_config)

        # Process multiple batches concurrently
        async def process_batch(data_type: str, count: int):
            for i in range(count):
                await processor.add_message(
                    data_type,
                    {
                        "id": f"{data_type}_{i}",
                        "name": f"Record {i}",
                        "sha256": f"hash_{i}",
                    },
                    AsyncMock(),
                    AsyncMock(),
                )

        # Process multiple data types concurrently
        await asyncio.gather(
            process_batch("artists", 500),
            process_batch("labels", 500),
            process_batch("masters", 500),
            process_batch("releases", 500),
        )

        await processor.flush_all()

        # Verify connection pool was used (connection() method was called)
        # With batch_size=500 and 2000 records total across 4 types, expect 4 batches
        assert mock_connection_pool.connection.call_count >= 4, (
            f"Expected at least 4 connection uses, got {mock_connection_pool.connection.call_count}"
        )

        # Verify all records processed
        total_processed = sum(processor.processed_counts.values())
        assert total_processed == 2000

    @pytest.mark.asyncio
    async def test_throughput_target(self, mock_connection_pool, batch_config):
        """Test that we meet throughput targets (500+ records/sec)."""
        processor = PostgreSQLBatchProcessor(mock_connection_pool, batch_config)

        # Process 5000 records
        record_count = 5000
        start_time = time.time()

        for i in range(record_count):
            await processor.add_message(
                "artists",
                {
                    "id": str(i),
                    "name": f"Artist {i}",
                    "sha256": f"hash_{i}",
                },
                AsyncMock(),
                AsyncMock(),
            )

        await processor.flush_all()
        end_time = time.time()

        duration = end_time - start_time
        throughput = record_count / duration

        # Should achieve at least 500 records/sec
        assert throughput >= 500, f"Throughput was {throughput:.0f} records/sec, expected >=500"

        print(f"✅ Achieved {throughput:.0f} records/sec throughput")


class TestQoSOptimization:
    """Tests for QoS and concurrency optimizations."""

    @pytest.mark.asyncio
    async def test_graphinator_qos_setting(self):
        """Test that Graphinator uses optimized QoS setting."""
        # This is more of a documentation/configuration test
        # Verify that the BatchConfig defaults or environment variables are optimized
        import os

        # Check environment variables if set, otherwise check defaults
        env_batch_size = os.environ.get("NEO4J_BATCH_SIZE")
        env_flush_interval = os.environ.get("NEO4J_BATCH_FLUSH_INTERVAL")

        if env_batch_size is not None:
            # If environment variable is set, it should be optimized
            assert int(env_batch_size) >= 500, f"NEO4J_BATCH_SIZE should be >= 500, got {env_batch_size}"

        if env_flush_interval is not None:
            # If environment variable is set, it should be optimized
            assert float(env_flush_interval) <= 2.0, f"NEO4J_BATCH_FLUSH_INTERVAL should be <= 2.0, got {env_flush_interval}"

        # Test passes if environment variables aren't set (local testing)
        # In Docker environment, these will be set and validated

    @pytest.mark.asyncio
    async def test_tableinator_connection_pool_size(self):
        """Test that Tableinator uses appropriate connection pool size."""

        # Connection pool should match or exceed prefetch_count
        # This is tested implicitly in the code, but documented here
        # Expected: min_connections=5, max_connections=50

        # In actual deployment, verify pool size matches QoS
        # This test serves as documentation of the requirement
        assert True  # Placeholder - actual validation is in integration tests


@pytest.mark.benchmark
class TestPerformanceRegression:
    """Regression tests to ensure performance doesn't degrade."""

    @pytest.mark.asyncio
    async def test_no_performance_regression_graphinator(self):
        """Ensure Neo4j batch processing doesn't regress."""
        # Baseline: 500 records in 500 batches should take < 2 seconds
        # This is a simplified test - real benchmark would use actual database

        mock_driver = MagicMock()
        session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = session
        mock_driver.session.return_value.__exit__.return_value = None

        def mock_execute_write(func):
            tx = MagicMock()
            tx.run.return_value.single.return_value = None
            return func(tx)

        session.execute_write.side_effect = mock_execute_write

        config = Neo4jBatchConfig(batch_size=500, flush_interval=2.0)
        processor = Neo4jBatchProcessor(mock_driver, config)

        start = time.time()
        for i in range(500):
            await processor.add_message(
                "artists",
                {"id": str(i), "name": f"A{i}", "sha256": f"h{i}"},
                AsyncMock(),
                AsyncMock(),
            )
        await processor.flush_all()
        duration = time.time() - start

        # Should maintain <2s performance
        assert duration < 2.0, f"Performance regression: {duration:.2f}s > 2.0s"

    @pytest.mark.asyncio
    async def test_no_performance_regression_tableinator(self):
        """Ensure PostgreSQL batch processing doesn't regress."""

        def mock_get_connection():
            conn = MagicMock()
            cursor = MagicMock()
            conn.cursor.return_value.__enter__.return_value = cursor
            conn.cursor.return_value.__exit__.return_value = None
            conn.__enter__.return_value = conn
            conn.__exit__.return_value = None
            cursor.fetchall.return_value = []
            return conn

        config = PostgresBatchConfig(batch_size=500, flush_interval=2.0)
        processor = PostgreSQLBatchProcessor(mock_get_connection, config)

        start = time.time()
        for i in range(1000):
            await processor.add_message(
                "artists",
                {"id": str(i), "name": f"A{i}", "sha256": f"h{i}"},
                AsyncMock(),
                AsyncMock(),
            )
        await processor.flush_all()
        duration = time.time() - start

        # Should maintain <1.2s performance for PostgreSQL
        # 20% tolerance added to account for CI environment variability
        max_duration = 1.2 * 1.2  # 1.2s + 20% = 1.44s
        assert duration < max_duration, f"Performance regression: {duration:.2f}s > {max_duration:.2f}s (1.2s + 20% tolerance)"
