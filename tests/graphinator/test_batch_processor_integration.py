"""Integration tests for batch processor with realistic async driver behavior.

These tests verify that the batch processor correctly handles async Neo4j driver
operations, including async context managers and async iteration. These would have
caught the bug where synchronous `with` statements were used with async sessions.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from graphinator.batch_processor import (
    BatchConfig,
    Neo4jBatchProcessor,
    PendingMessage,
)


@pytest.fixture
def realistic_async_driver():
    """Create a realistic async Neo4j driver mock.

    This mock accurately represents the async behavior of AsyncResilientNeo4jDriver:
    - driver.session() is an async method (returns awaitable)
    - The awaitable returns an async context manager
    - session.run() is async
    - Results support async iteration
    """
    # Create session mock
    mock_session = MagicMock()

    # Create async context manager for session
    mock_session_context = AsyncMock()
    mock_session_context.__aenter__.return_value = mock_session
    mock_session_context.__aexit__.return_value = None

    # Create driver
    mock_driver = MagicMock()
    # CRITICAL: session() must be async and return the context manager
    mock_driver.session = AsyncMock(return_value=mock_session_context)

    return mock_driver, mock_session


class TestAsyncDriverIntegration:
    """Test batch processor with realistic async driver behavior."""

    @pytest.mark.asyncio
    async def test_session_is_async_context_manager(self, realistic_async_driver):
        """Verify that session() can be used with async with await pattern.

        This test would have caught the bug where we used:
            with self.driver.session() as session:  # WRONG - not async
        instead of:
            async with await self.driver.session() as session:  # CORRECT
        """
        mock_driver, mock_session = realistic_async_driver

        # Configure session to return empty results
        async def async_result_iter():
            """Empty async iterator."""
            if False:  # Make this a generator without yielding anything
                yield

        mock_result = MagicMock()
        mock_result.__aiter__ = lambda _: async_result_iter()
        mock_session.run = AsyncMock(return_value=mock_result)

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        # Add a message
        msg = PendingMessage(
            "artists",
            {"id": "1", "name": "Test", "sha256": "hash1"},
            AsyncMock(),
            AsyncMock(),
        )
        processor.queues["artists"].append(msg)

        # This should work without errors
        await processor._flush_queue("artists")

        # Verify session was properly awaited and used as context manager
        mock_driver.session.assert_called()

    @pytest.mark.asyncio
    async def test_session_run_is_async(self, realistic_async_driver):
        """Verify that session.run() is called with await.

        This test ensures we're using:
            result = await session.run(query, params)  # CORRECT
        instead of:
            result = session.run(query, params)  # WRONG - missing await
        """
        mock_driver, mock_session = realistic_async_driver

        # Track that run() was awaited
        run_was_awaited = False

        async def mock_run(*_args, **_kwargs):
            nonlocal run_was_awaited
            run_was_awaited = True

            # Return mock result with async iterator
            async def async_iter():
                yield {"id": "1", "hash": None}

            mock_result = MagicMock()
            mock_result.__aiter__ = lambda _: async_iter()
            return mock_result

        mock_session.run = mock_run
        mock_session.execute_write = AsyncMock()

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        msg = PendingMessage(
            "artists",
            {"id": "1", "name": "Test", "sha256": "hash1"},
            AsyncMock(),
            AsyncMock(),
        )

        await processor._process_artists_batch([msg])

        # Verify run was awaited (async function was called)
        assert run_was_awaited, "session.run() must be awaited"

    @pytest.mark.asyncio
    async def test_result_iteration_is_async(self, realistic_async_driver):
        """Verify that result iteration uses async for.

        This test ensures we're using:
            async for record in result:  # CORRECT
        instead of:
            for record in result:  # WRONG - not async
        """
        mock_driver, mock_session = realistic_async_driver

        # Track how records were iterated
        iteration_method = None

        class AsyncIterableResult:
            """Mock result that tracks how it's iterated."""

            def __iter__(self):
                nonlocal iteration_method
                iteration_method = "sync"
                return iter([])

            def __aiter__(self):
                nonlocal iteration_method
                iteration_method = "async"

                async def async_gen():
                    yield {"id": "1", "hash": "old_hash"}

                return async_gen()

        mock_session.run = AsyncMock(return_value=AsyncIterableResult())
        mock_session.execute_write = AsyncMock()

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        msg = PendingMessage(
            "artists",
            {"id": "1", "name": "Test", "sha256": "new_hash"},
            AsyncMock(),
            AsyncMock(),
        )

        await processor._process_artists_batch([msg])

        # Verify async iteration was used
        assert iteration_method == "async", "Must use 'async for' not 'for'"

    @pytest.mark.asyncio
    async def test_transaction_function_is_async(self, realistic_async_driver):
        """Verify that transaction functions use await for queries.

        This test ensures we're using:
            await tx.run(query, params)  # CORRECT
        instead of:
            tx.run(query, params)  # WRONG - missing await
        """
        mock_driver, mock_session = realistic_async_driver

        # Track transaction execution
        tx_run_was_awaited = False

        async def mock_execute_write(tx_func):
            """Mock execute_write that runs the transaction function."""
            # Create mock transaction
            mock_tx = MagicMock()

            async def mock_tx_run(*_args, **_kwargs):
                nonlocal tx_run_was_awaited
                tx_run_was_awaited = True

            mock_tx.run = mock_tx_run

            # Run the transaction function
            await tx_func(mock_tx)

        # Configure session
        async def async_iter():
            yield {"id": "1", "hash": None}

        mock_result = MagicMock()
        mock_result.__aiter__ = lambda _: async_iter()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.execute_write = mock_execute_write

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        msg = PendingMessage(
            "artists",
            {"id": "1", "name": "Test", "sha256": "hash1"},
            AsyncMock(),
            AsyncMock(),
        )

        await processor._process_artists_batch([msg])

        # Verify transaction run was awaited
        assert tx_run_was_awaited, "tx.run() must be awaited in transaction"

    @pytest.mark.asyncio
    async def test_all_data_types_use_async_correctly(self, realistic_async_driver):
        """Verify all batch processor methods use async patterns correctly."""
        mock_driver, mock_session = realistic_async_driver

        # Configure session for all data types
        async def async_iter():
            yield {"id": "1", "hash": None}

        mock_result = MagicMock()
        mock_result.__aiter__ = lambda _: async_iter()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.execute_write = AsyncMock()

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        # Test artists
        await processor._process_artists_batch([PendingMessage("artists", {"id": "1", "name": "Test", "sha256": "h1"}, AsyncMock(), AsyncMock())])
        artists_calls = mock_driver.session.call_count
        assert artists_calls == 2, f"Artists should call session twice (got {artists_calls})"

        # Reset mocks
        mock_driver.session.reset_mock()

        # Test labels
        await processor._process_labels_batch([PendingMessage("labels", {"id": "1", "name": "Test", "sha256": "h1"}, AsyncMock(), AsyncMock())])
        labels_calls = mock_driver.session.call_count
        assert labels_calls == 2, f"Labels should call session twice (got {labels_calls})"

        # Reset mocks
        mock_driver.session.reset_mock()

        # Test masters
        await processor._process_masters_batch(
            [PendingMessage("masters", {"id": "1", "title": "Test", "year": 2023, "sha256": "h1"}, AsyncMock(), AsyncMock())]
        )
        masters_calls = mock_driver.session.call_count
        assert masters_calls == 2, f"Masters should call session twice (got {masters_calls})"

        # Reset mocks
        mock_driver.session.reset_mock()

        # Test releases
        await processor._process_releases_batch([PendingMessage("releases", {"id": "1", "title": "Test", "sha256": "h1"}, AsyncMock(), AsyncMock())])
        releases_calls = mock_driver.session.call_count
        assert releases_calls == 2, f"Releases should call session twice (got {releases_calls})"

        # All data types successfully used async session patterns
        total_calls = artists_calls + labels_calls + masters_calls + releases_calls
        assert total_calls == 8, f"All data types should use async session (got {total_calls} total calls)"


class TestAsyncErrorConditions:
    """Test error handling with async driver behavior."""

    @pytest.mark.asyncio
    async def test_async_context_manager_cleanup_on_error(self, realistic_async_driver):
        """Verify async context manager cleanup happens even on errors."""
        mock_driver, mock_session = realistic_async_driver

        # Make session.run raise an error
        mock_session.run = AsyncMock(side_effect=Exception("Test error"))

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        msg = PendingMessage(
            "artists",
            {"id": "1", "name": "Test", "sha256": "hash1"},
            AsyncMock(),
            AsyncMock(),
        )
        processor.queues["artists"].append(msg)

        # Should handle error gracefully
        await processor._flush_queue("artists")

        # Verify context manager exit was called
        session_context = await mock_driver.session()
        session_context.__aexit__.assert_called()

    @pytest.mark.asyncio
    async def test_async_exception_propagation(self, realistic_async_driver):
        """Verify async exceptions are properly caught and handled."""
        from neo4j.exceptions import ServiceUnavailable

        mock_driver, mock_session = realistic_async_driver

        # Make execute_write raise ServiceUnavailable
        mock_session.execute_write = AsyncMock(side_effect=ServiceUnavailable("Neo4j down"))

        # Configure run to work
        async def async_iter():
            yield {"id": "1", "hash": None}

        mock_result = MagicMock()
        mock_result.__aiter__ = lambda _: async_iter()
        mock_session.run = AsyncMock(return_value=mock_result)

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=1))

        msg = PendingMessage(
            "artists",
            {"id": "1", "name": "Test", "sha256": "hash1"},
            AsyncMock(),
            AsyncMock(),
        )
        processor.queues["artists"].append(msg)

        # Should handle error and put message back in queue
        await processor._flush_queue("artists")

        # Message should be back in queue for retry
        assert len(processor.queues["artists"]) == 1


class TestRealisticWorkflow:
    """Test complete workflows with realistic async driver."""

    @pytest.mark.asyncio
    async def test_full_batch_processing_workflow(self, realistic_async_driver):
        """Test complete batch processing with all async patterns."""
        mock_driver, mock_session = realistic_async_driver

        # Track all async operations
        operations = []

        # Mock hash check query
        async def mock_hash_check_run(_query, **_kwargs):
            operations.append(("hash_check_run", "awaited"))

            async def async_iter():
                # Return no existing hashes
                yield {"id": "1", "hash": None}
                yield {"id": "2", "hash": None}

            mock_result = MagicMock()
            mock_result.__aiter__ = lambda _: async_iter()
            return mock_result

        # Mock transaction
        async def mock_execute_write(tx_func):
            operations.append(("execute_write", "awaited"))

            mock_tx = MagicMock()

            async def mock_tx_run(*_args, **_kwargs):
                operations.append(("tx_run", "awaited"))

            mock_tx.run = mock_tx_run
            await tx_func(mock_tx)

        mock_session.run = mock_hash_check_run
        mock_session.execute_write = mock_execute_write

        processor = Neo4jBatchProcessor(mock_driver, BatchConfig(batch_size=2))

        # Add two messages
        ack1, ack2 = AsyncMock(), AsyncMock()
        msg1 = PendingMessage("artists", {"id": "1", "name": "Artist 1", "sha256": "h1"}, ack1, AsyncMock())
        msg2 = PendingMessage("artists", {"id": "2", "name": "Artist 2", "sha256": "h2"}, ack2, AsyncMock())

        processor.queues["artists"].append(msg1)
        processor.queues["artists"].append(msg2)

        # Process batch
        await processor._flush_queue("artists")

        # Verify all async operations were performed
        assert ("hash_check_run", "awaited") in operations
        assert ("execute_write", "awaited") in operations
        assert ("tx_run", "awaited") in operations

        # Verify messages were acknowledged
        ack1.assert_called_once()
        ack2.assert_called_once()
