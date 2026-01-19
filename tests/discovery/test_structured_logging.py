"""Tests for structured logging with correlation IDs."""

from io import StringIO
import json

from fastapi.testclient import TestClient
import pytest
import structlog


@pytest.fixture
def log_output() -> StringIO:
    """Capture log output for testing."""
    return StringIO()


@pytest.fixture
def configure_test_logging(log_output: StringIO) -> None:
    """Configure logging to capture output for testing."""
    # Set up a simple JSON renderer for testing
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_output),
        cache_logger_on_first_use=False,
    )


def test_correlation_id_in_logs(discovery_client: TestClient, log_output: StringIO, configure_test_logging: None) -> None:
    """Test that correlation IDs are included in log entries."""
    # Make a request with a custom request ID
    request_id = "test-request-123"
    response = discovery_client.get("/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_service_context_in_logs(log_output: StringIO, configure_test_logging: None) -> None:
    """Test that service context is included in log entries."""
    # Bind service context
    structlog.contextvars.bind_contextvars(
        service="test-service",
        environment="test",
    )

    # Log a message
    logger = structlog.get_logger(__name__)
    logger.info("Test message", extra_field="test_value")

    # Get log output
    log_output.seek(0)
    log_lines = log_output.readlines()

    # Verify at least one log line was written
    assert len(log_lines) > 0

    # Parse the last log line
    log_entry = json.loads(log_lines[-1])

    # Verify service context is present
    assert log_entry["service"] == "test-service"
    assert log_entry["environment"] == "test"
    assert log_entry["event"] == "Test message"
    assert log_entry["extra_field"] == "test_value"

    # Clean up
    structlog.contextvars.clear_contextvars()


def test_request_context_correlation(log_output: StringIO, configure_test_logging: None) -> None:
    """Test that request context is properly correlated across log entries."""
    # Bind request context
    request_id = "correlation-test-456"
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method="GET",
        path="/api/test",
    )

    # Log multiple messages
    logger = structlog.get_logger(__name__)
    logger.info("First log entry")
    logger.info("Second log entry")
    logger.warning("Warning log entry")

    # Get log output
    log_output.seek(0)
    log_lines = log_output.readlines()

    # Verify we have multiple log entries
    assert len(log_lines) >= 3

    # Parse and verify all entries have the same request_id
    for line in log_lines[-3:]:
        log_entry = json.loads(line)
        assert log_entry["request_id"] == request_id
        assert log_entry["method"] == "GET"
        assert log_entry["path"] == "/api/test"

    # Clean up
    structlog.contextvars.clear_contextvars()


def test_context_isolation(log_output: StringIO, configure_test_logging: None) -> None:
    """Test that context variables are properly isolated between requests."""
    # First request context
    structlog.contextvars.bind_contextvars(request_id="request-1")
    logger = structlog.get_logger(__name__)
    logger.info("Request 1 log")

    # Clear context
    structlog.contextvars.clear_contextvars()

    # Second request context
    structlog.contextvars.bind_contextvars(request_id="request-2")
    logger.info("Request 2 log")

    # Get log output
    log_output.seek(0)
    log_lines = log_output.readlines()

    # Verify we have at least 2 log entries
    assert len(log_lines) >= 2

    # Parse log entries
    log_entry_1 = json.loads(log_lines[-2])
    log_entry_2 = json.loads(log_lines[-1])

    # Verify request IDs are different and properly isolated
    assert log_entry_1["request_id"] == "request-1"
    assert log_entry_2["request_id"] == "request-2"

    # Clean up
    structlog.contextvars.clear_contextvars()


def test_nested_context(log_output: StringIO, configure_test_logging: None) -> None:
    """Test that nested context binding works correctly."""
    # Bind base context
    structlog.contextvars.bind_contextvars(
        request_id="nested-test-789",
        service="test-service",
    )

    logger = structlog.get_logger(__name__)
    logger.info("Base context log")

    # Add additional context
    structlog.contextvars.bind_contextvars(user_id="user-123")
    logger.info("Enhanced context log")

    # Get log output
    log_output.seek(0)
    log_lines = log_output.readlines()

    # Parse log entries
    log_entry_1 = json.loads(log_lines[-2])
    log_entry_2 = json.loads(log_lines[-1])

    # Verify first entry has base context only
    assert log_entry_1["request_id"] == "nested-test-789"
    assert log_entry_1["service"] == "test-service"
    assert "user_id" not in log_entry_1

    # Verify second entry has both base and enhanced context
    assert log_entry_2["request_id"] == "nested-test-789"
    assert log_entry_2["service"] == "test-service"
    assert log_entry_2["user_id"] == "user-123"

    # Clean up
    structlog.contextvars.clear_contextvars()


def test_error_logging_with_context(log_output: StringIO, configure_test_logging: None) -> None:
    """Test that errors are logged with proper context."""
    # Bind context
    structlog.contextvars.bind_contextvars(
        request_id="error-test-999",
        endpoint="/api/error",
    )

    logger = structlog.get_logger(__name__)

    try:
        raise ValueError("Test error")
    except ValueError as e:
        logger.error("Error occurred", error=str(e), error_type=type(e).__name__)

    # Get log output
    log_output.seek(0)
    log_lines = log_output.readlines()

    # Parse the error log entry
    log_entry = json.loads(log_lines[-1])

    # Verify error details and context
    assert log_entry["request_id"] == "error-test-999"
    assert log_entry["endpoint"] == "/api/error"
    assert log_entry["event"] == "Error occurred"
    assert log_entry["error"] == "Test error"
    assert log_entry["error_type"] == "ValueError"
    assert log_entry["level"] == "error"

    # Clean up
    structlog.contextvars.clear_contextvars()


def test_log_levels_with_context(log_output: StringIO, configure_test_logging: None) -> None:
    """Test that different log levels work with context."""
    structlog.contextvars.bind_contextvars(request_id="level-test-111")

    logger = structlog.get_logger(__name__)
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")

    # Get log output
    log_output.seek(0)
    log_lines = log_output.readlines()

    # All entries should have the same request_id
    for line in log_lines:
        log_entry = json.loads(line)
        assert log_entry["request_id"] == "level-test-111"

    # Clean up
    structlog.contextvars.clear_contextvars()
