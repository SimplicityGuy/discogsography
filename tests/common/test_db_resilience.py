"""Tests for database resilience utilities."""

import time
from unittest.mock import Mock

import pytest

from common.db_resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState, ExponentialBackoff


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_init(self) -> None:
        """Test CircuitBreaker initialization."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=3, recovery_timeout=30)
        breaker = CircuitBreaker(config)

        assert breaker.config == config
        assert breaker.failure_count == 0
        assert breaker.last_failure_time is None
        assert breaker.state == CircuitState.CLOSED

    def test_call_success(self) -> None:
        """Test successful call through circuit breaker."""
        config = CircuitBreakerConfig(name="TestBreaker")
        breaker = CircuitBreaker(config)

        func = Mock(return_value="success")
        result = breaker.call(func)

        assert result == "success"
        func.assert_called_once()
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    def test_call_failure(self) -> None:
        """Test failed call increments failure count."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=3)
        breaker = CircuitBreaker(config)

        func = Mock(side_effect=RuntimeError("Failed"))

        with pytest.raises(RuntimeError, match="Failed"):
            breaker.call(func)

        assert breaker.failure_count == 1
        assert breaker.last_failure_time is not None
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_opens_after_threshold(self) -> None:
        """Test circuit opens after reaching failure threshold."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=3)
        breaker = CircuitBreaker(config)

        func = Mock(side_effect=RuntimeError("Failed"))

        # Cause threshold failures
        for _ in range(3):
            with pytest.raises(RuntimeError):
                breaker.call(func)

        assert breaker.failure_count == 3
        assert breaker.state == CircuitState.OPEN

    def test_circuit_rejects_calls_when_open(self) -> None:
        """Test circuit breaker rejects calls when open."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=2, recovery_timeout=10)
        breaker = CircuitBreaker(config)

        func = Mock(side_effect=RuntimeError("Failed"))

        # Open the circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                breaker.call(func)

        # Next call should be rejected without calling func
        with pytest.raises(Exception, match="TestBreaker: Circuit breaker is OPEN"):
            breaker.call(Mock(return_value="success"))

    def test_circuit_half_open_after_timeout(self) -> None:
        """Test circuit enters half-open after recovery timeout."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=2, recovery_timeout=1)
        breaker = CircuitBreaker(config)

        func_fail = Mock(side_effect=RuntimeError("Failed"))

        # Open the circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                breaker.call(func_fail)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(1.1)

        func_success = Mock(return_value="success")
        result = breaker.call(func_success)

        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_call_async_success(self) -> None:
        """Test successful async call through circuit breaker."""
        config = CircuitBreakerConfig(name="TestBreaker")
        breaker = CircuitBreaker(config)

        async def async_func() -> str:
            return "success"

        result = await breaker.call_async(async_func)

        assert result == "success"
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_async_failure(self) -> None:
        """Test failed async call increments failure count."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=3)
        breaker = CircuitBreaker(config)

        async def async_func() -> None:
            raise RuntimeError("Failed")

        with pytest.raises(RuntimeError, match="Failed"):
            await breaker.call_async(async_func)

        assert breaker.failure_count == 1
        assert breaker.last_failure_time is not None

    @pytest.mark.asyncio
    async def test_call_async_opens_after_threshold(self) -> None:
        """Test async circuit opens after reaching failure threshold."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=2)
        breaker = CircuitBreaker(config)

        async def async_func() -> None:
            raise RuntimeError("Failed")

        # Cause threshold failures
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(async_func)

        assert breaker.failure_count == 2
        assert breaker.state == CircuitState.OPEN

    def test_custom_exception_type(self) -> None:
        """Test circuit breaker with custom exception type."""

        class CustomError(Exception):
            pass

        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=2, expected_exception=CustomError)
        breaker = CircuitBreaker(config)

        func = Mock(side_effect=CustomError("Custom error"))

        # CustomError should trigger circuit
        with pytest.raises(CustomError):
            breaker.call(func)

        assert breaker.failure_count == 1

        # Other exceptions should not be caught by circuit breaker
        func_other = Mock(side_effect=ValueError("Different error"))
        with pytest.raises(ValueError):
            breaker.call(func_other)

        # Failure count should not increase for different exception
        assert breaker.failure_count == 1


class TestExponentialBackoff:
    """Tests for ExponentialBackoff class."""

    def test_init(self) -> None:
        """Test ExponentialBackoff initialization."""
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=60.0, exponential_base=2.0, jitter=True)

        assert backoff.initial_delay == 1.0
        assert backoff.max_delay == 60.0
        assert backoff.exponential_base == 2.0
        assert backoff.jitter is True

    def test_get_delay_no_jitter(self) -> None:
        """Test delay calculation without jitter."""
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=60.0, exponential_base=2.0, jitter=False)

        assert backoff.get_delay(0) == 1.0  # 1.0 * 2^0
        assert backoff.get_delay(1) == 2.0  # 1.0 * 2^1
        assert backoff.get_delay(2) == 4.0  # 1.0 * 2^2
        assert backoff.get_delay(3) == 8.0  # 1.0 * 2^3

    def test_get_delay_respects_max(self) -> None:
        """Test that delay respects max_delay."""
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=10.0, exponential_base=2.0, jitter=False)

        # Should cap at max_delay
        assert backoff.get_delay(10) == 10.0
        assert backoff.get_delay(20) == 10.0

    def test_get_delay_with_jitter(self) -> None:
        """Test that jitter adds randomness."""
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=60.0, exponential_base=2.0, jitter=True)

        delay = backoff.get_delay(1)

        # With jitter, delay should be reasonable (allowing for jitter margin)
        assert 0.0 <= delay <= 3.0  # Base delay is 2.0, allow margin for jitter

    def test_different_exponential_base(self) -> None:
        """Test with different exponential base."""
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=100.0, exponential_base=3.0, jitter=False)

        assert backoff.get_delay(0) == 1.0  # 1.0 * 3^0
        assert backoff.get_delay(1) == 3.0  # 1.0 * 3^1
        assert backoff.get_delay(2) == 9.0  # 1.0 * 3^2

    def test_custom_initial_delay(self) -> None:
        """Test with custom initial delay."""
        backoff = ExponentialBackoff(initial_delay=5.0, max_delay=100.0, exponential_base=2.0, jitter=False)

        assert backoff.get_delay(0) == 5.0  # 5.0 * 2^0
        assert backoff.get_delay(1) == 10.0  # 5.0 * 2^1
        assert backoff.get_delay(2) == 20.0  # 5.0 * 2^2


class TestResilientConnection:
    """Tests for ResilientConnection class."""

    def test_get_connection_success(self) -> None:
        """Test getting a healthy connection."""
        from common.db_resilience import ResilientConnection

        mock_conn = Mock()
        connection_factory = Mock(return_value=mock_conn)
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test, max_retries=3, name="TestDB")

        conn = manager.get_connection()

        assert conn == mock_conn
        connection_factory.assert_called_once()
        connection_test.assert_called()

    def test_get_connection_reuses_healthy_connection(self) -> None:
        """Test that healthy connections are reused."""
        from common.db_resilience import ResilientConnection

        mock_conn = Mock()
        connection_factory = Mock(return_value=mock_conn)
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test)

        # First call
        conn1 = manager.get_connection()
        # Second call should reuse
        conn2 = manager.get_connection()

        assert conn1 == conn2
        connection_factory.assert_called_once()  # Called only once

    def test_get_connection_retries_on_failure(self) -> None:
        """Test connection retry logic."""
        from common.db_resilience import ResilientConnection

        mock_conn = Mock()
        connection_factory = Mock(side_effect=[RuntimeError("Fail 1"), RuntimeError("Fail 2"), mock_conn])
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test, max_retries=3)

        conn = manager.get_connection()

        assert conn == mock_conn
        assert connection_factory.call_count == 3  # Failed twice, succeeded third time

    def test_get_connection_fails_after_max_retries(self) -> None:
        """Test that connection fails after max retries."""
        from common.db_resilience import ResilientConnection

        connection_factory = Mock(side_effect=RuntimeError("Connection failed"))
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test, max_retries=2)

        with pytest.raises(Exception, match="Failed to establish connection after 2 attempts"):
            manager.get_connection()

        assert connection_factory.call_count == 2

    def test_get_connection_recreates_unhealthy_connection(self) -> None:
        """Test that unhealthy connections are recreated."""
        from common.db_resilience import ResilientConnection

        old_conn = Mock()
        new_conn = Mock()
        connection_factory = Mock(side_effect=[old_conn, new_conn])
        connection_test = Mock(side_effect=[True, False, True])  # First healthy, then unhealthy, then healthy

        manager = ResilientConnection(connection_factory, connection_test)

        # First call - creates connection
        conn1 = manager.get_connection()
        assert conn1 == old_conn

        # Second call - connection now unhealthy, should recreate
        conn2 = manager.get_connection()
        assert conn2 == new_conn
        assert connection_factory.call_count == 2

    def test_close(self) -> None:
        """Test closing connection."""
        from common.db_resilience import ResilientConnection

        mock_conn = Mock()
        connection_factory = Mock(return_value=mock_conn)
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test)

        # Get connection
        manager.get_connection()

        # Close it
        manager.close()

        mock_conn.close.assert_called_once()
        assert manager._connection is None


class TestAsyncResilientConnection:
    """Tests for AsyncResilientConnection class."""

    @pytest.mark.asyncio
    async def test_get_connection_success(self) -> None:
        """Test getting a healthy async connection."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test, max_retries=3, name="TestDB")

        conn = await manager.get_connection()

        assert conn == mock_conn
        connection_factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_reuses_healthy_connection(self) -> None:
        """Test that healthy connections are reused."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test)

        # First call
        conn1 = await manager.get_connection()
        # Second call should reuse
        conn2 = await manager.get_connection()

        assert conn1 == conn2
        connection_factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_retries_on_failure(self) -> None:
        """Test async connection retry logic."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        connection_factory = AsyncMock(side_effect=[RuntimeError("Fail 1"), RuntimeError("Fail 2"), mock_conn])
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test, max_retries=3)

        conn = await manager.get_connection()

        assert conn == mock_conn
        assert connection_factory.call_count == 3

    @pytest.mark.asyncio
    async def test_get_connection_fails_after_max_retries(self) -> None:
        """Test that async connection fails after max retries."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        connection_factory = AsyncMock(side_effect=RuntimeError("Connection failed"))
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test, max_retries=2)

        with pytest.raises(Exception, match="Failed to establish connection after 2 attempts"):
            await manager.get_connection()

        assert connection_factory.call_count == 2

    @pytest.mark.asyncio
    async def test_close_with_aclose(self) -> None:
        """Test closing async connection with aclose method."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        mock_conn.aclose = AsyncMock()
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test)

        await manager.get_connection()
        await manager.close()

        mock_conn.aclose.assert_called_once()
        assert manager._connection is None

    @pytest.mark.asyncio
    async def test_close_with_sync_close(self) -> None:
        """Test closing async connection with sync close method.

        Note: If close() is not async, the code will try to await it and fail,
        so the close will be caught in the exception handler and connection will be set to None.
        """
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        # Sync close method (this will cause an error when awaited)
        mock_conn.close = Mock()
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test)

        await manager.get_connection()
        await manager.close()

        # Connection should still be None even if close failed
        assert manager._connection is None

    @pytest.mark.asyncio
    async def test_mixed_sync_async_factory_and_test(self) -> None:
        """Test with mixed sync/async factory and test functions."""
        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        # Sync factory
        connection_factory = Mock(return_value=mock_conn)
        # Sync test
        connection_test = Mock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test)

        conn = await manager.get_connection()
        assert conn == mock_conn


class TestContextManagers:
    """Tests for context manager utilities."""

    def test_resilient_connection_context_manager(self) -> None:
        """Test resilient_connection context manager."""
        from common.db_resilience import ResilientConnection, resilient_connection

        mock_conn = Mock()
        connection_factory = Mock(return_value=mock_conn)
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test)

        with resilient_connection(manager) as conn:
            assert conn == mock_conn

        # Connection should still exist (not closed by context manager)
        assert manager._connection is not None

    @pytest.mark.asyncio
    async def test_async_resilient_connection_context_manager(self) -> None:
        """Test async_resilient_connection context manager."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection, async_resilient_connection

        mock_conn = Mock()
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test)

        async with async_resilient_connection(manager) as conn:
            assert conn == mock_conn

        # Connection should still exist (not closed by context manager)
        assert manager._connection is not None


class TestCircuitBreakerEdgeCases:
    """Additional edge case tests for CircuitBreaker."""

    def test_circuit_resets_on_success_after_failure(self) -> None:
        """Test that successful call resets failure count."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=3)
        breaker = CircuitBreaker(config)

        func_fail = Mock(side_effect=RuntimeError("Failed"))
        func_success = Mock(return_value="success")

        # Cause some failures
        with pytest.raises(RuntimeError):
            breaker.call(func_fail)
        assert breaker.failure_count == 1

        # Successful call should reset
        breaker.call(func_success)
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_with_zero_threshold(self) -> None:
        """Test circuit breaker with zero failure threshold (always open on failure)."""
        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=0)
        breaker = CircuitBreaker(config)

        # Should immediately open on first failure
        func = Mock(side_effect=RuntimeError("Failed"))
        with pytest.raises(RuntimeError):
            breaker.call(func)

        # Circuit should already be open
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_async_circuit_half_open_recovery(self) -> None:
        """Test async circuit recovery from half-open state."""
        import asyncio

        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=2, recovery_timeout=1)
        breaker = CircuitBreaker(config)

        async def fail_func() -> None:
            raise RuntimeError("Failed")

        # Open circuit
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(fail_func)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Successful call should close circuit
        async def success_func() -> str:
            return "success"

        result = await breaker.call_async(success_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    def test_multiple_exception_types(self) -> None:
        """Test circuit breaker with tuple of exception types."""

        class Error1(Exception):
            pass

        class Error2(Exception):
            pass

        config = CircuitBreakerConfig(name="TestBreaker", failure_threshold=2, expected_exception=(Error1, Error2))
        breaker = CircuitBreaker(config)

        # Both exception types should trigger circuit
        func1 = Mock(side_effect=Error1("error1"))
        with pytest.raises(Error1):
            breaker.call(func1)

        func2 = Mock(side_effect=Error2("error2"))
        with pytest.raises(Error2):
            breaker.call(func2)

        assert breaker.failure_count == 2
        assert breaker.state == CircuitState.OPEN


class TestExponentialBackoffEdgeCases:
    """Additional edge case tests for ExponentialBackoff."""

    def test_very_large_retry_count(self) -> None:
        """Test with very large retry count."""
        backoff = ExponentialBackoff(initial_delay=1.0, max_delay=100.0, exponential_base=2.0, jitter=False)

        # Even with huge retry count, should cap at max_delay
        delay = backoff.get_delay(1000)
        assert delay == 100.0

    def test_zero_initial_delay(self) -> None:
        """Test with zero initial delay."""
        backoff = ExponentialBackoff(initial_delay=0.0, max_delay=10.0, exponential_base=2.0, jitter=False)

        # All delays should be 0
        assert backoff.get_delay(0) == 0.0
        assert backoff.get_delay(5) == 0.0

    def test_jitter_consistency(self) -> None:
        """Test that jitter produces values within expected range."""
        backoff = ExponentialBackoff(initial_delay=10.0, max_delay=100.0, exponential_base=2.0, jitter=True)

        # Test multiple times to ensure jitter is bounded
        for _ in range(10):
            delay = backoff.get_delay(3)
            # Base delay would be 10.0 * 2^3 = 80.0
            # With jitter (up to 25%), should be between 80 and 100
            assert 80.0 <= delay <= 100.0


class TestConnectionTestFailures:
    """Test connection test failure scenarios."""

    def test_connection_test_exception(self) -> None:
        """Test handling of connection test exceptions."""
        from common.db_resilience import ResilientConnection

        mock_conn = Mock()
        connection_factory = Mock(return_value=mock_conn)
        connection_test = Mock(side_effect=RuntimeError("Test failed"))

        manager = ResilientConnection(connection_factory, connection_test, max_retries=2)

        # Should fail because connection test raises exception
        with pytest.raises(Exception, match="Failed to establish connection after 2 attempts"):
            manager.get_connection()

    @pytest.mark.asyncio
    async def test_async_connection_test_exception(self) -> None:
        """Test handling of async connection test exceptions."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(side_effect=RuntimeError("Test failed"))

        manager = AsyncResilientConnection(connection_factory, connection_test, max_retries=2)

        with pytest.raises(Exception, match="Failed to establish connection after 2 attempts"):
            await manager.get_connection()

    def test_connection_close_exception(self) -> None:
        """Test handling of exceptions during connection close."""
        from common.db_resilience import ResilientConnection

        mock_conn = Mock()
        mock_conn.close = Mock(side_effect=RuntimeError("Close failed"))
        connection_factory = Mock(return_value=mock_conn)
        connection_test = Mock(return_value=True)

        manager = ResilientConnection(connection_factory, connection_test)

        manager.get_connection()

        # Close should not raise even if close() fails
        manager.close()
        assert manager._connection is None

    @pytest.mark.asyncio
    async def test_async_connection_close_exception(self) -> None:
        """Test handling of exceptions during async connection close."""
        from unittest.mock import AsyncMock

        from common.db_resilience import AsyncResilientConnection

        mock_conn = Mock()
        mock_conn.aclose = AsyncMock(side_effect=RuntimeError("Close failed"))
        connection_factory = AsyncMock(return_value=mock_conn)
        connection_test = AsyncMock(return_value=True)

        manager = AsyncResilientConnection(connection_factory, connection_test)

        await manager.get_connection()

        # Close should not raise even if aclose() fails
        await manager.close()
        assert manager._connection is None
