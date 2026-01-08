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
