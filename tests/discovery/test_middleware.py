"""Tests for request tracking middleware."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from discovery.middleware import RequestIDMiddleware, get_request_id


@pytest.fixture
def app_with_middleware() -> FastAPI:
    """Create a FastAPI app with RequestIDMiddleware."""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request) -> dict[str, str]:
        """Test endpoint that returns request ID."""
        return {"request_id": get_request_id(request), "message": "success"}

    @app.get("/error")
    async def error_endpoint() -> None:
        """Test endpoint that raises an error."""
        raise ValueError("Test error")

    return app


@pytest.fixture
def client(app_with_middleware: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app_with_middleware)


def test_middleware_adds_request_id(client: TestClient) -> None:
    """Test that middleware adds request ID to response headers."""
    response = client.get("/test")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time" in response.headers


def test_middleware_generates_unique_ids(client: TestClient) -> None:
    """Test that middleware generates unique request IDs."""
    response1 = client.get("/test")
    response2 = client.get("/test")

    request_id_1 = response1.headers["X-Request-ID"]
    request_id_2 = response2.headers["X-Request-ID"]

    assert request_id_1 != request_id_2


def test_middleware_preserves_client_request_id(client: TestClient) -> None:
    """Test that middleware preserves client-provided request ID."""
    custom_id = "custom-request-id-123"

    response = client.get("/test", headers={"X-Request-ID": custom_id})

    assert response.headers["X-Request-ID"] == custom_id


def test_middleware_includes_request_id_in_response_body(client: TestClient) -> None:
    """Test that request ID is accessible in endpoint handlers."""
    response = client.get("/test")
    data = response.json()

    assert "request_id" in data
    assert data["request_id"] == response.headers["X-Request-ID"]


def test_middleware_measures_process_time(client: TestClient) -> None:
    """Test that middleware measures and includes process time."""
    response = client.get("/test")

    assert "X-Process-Time" in response.headers

    # Process time should be a valid float string
    process_time = float(response.headers["X-Process-Time"])
    assert process_time >= 0
    assert process_time < 1.0  # Should be very fast for a simple endpoint


def test_middleware_handles_errors(client: TestClient) -> None:
    """Test that middleware handles errors properly."""
    # The error endpoint will raise ValueError, which the TestClient will catch
    # The middleware will log the error with request context before re-raising
    with pytest.raises(ValueError, match="Test error"):
        client.get("/error")


def test_get_request_id_with_valid_request(app_with_middleware: FastAPI) -> None:
    """Test getting request ID from a valid request."""
    with TestClient(app_with_middleware) as client:
        response = client.get("/test")
        data = response.json()

        # The endpoint returns the request ID using get_request_id
        assert data["request_id"] != "unknown"


def test_request_id_format(client: TestClient) -> None:
    """Test that generated request IDs are valid UUIDs."""
    response = client.get("/test")
    request_id = response.headers["X-Request-ID"]

    # Should be a valid UUID format (8-4-4-4-12)
    assert len(request_id) == 36
    assert request_id.count("-") == 4


def test_multiple_requests_have_different_ids(client: TestClient) -> None:
    """Test that multiple concurrent requests get different IDs."""
    request_ids = set()

    # Make multiple requests
    for _ in range(10):
        response = client.get("/test")
        request_ids.add(response.headers["X-Request-ID"])

    # All request IDs should be unique
    assert len(request_ids) == 10


def test_process_time_header_format(client: TestClient) -> None:
    """Test that process time header is in correct format."""
    response = client.get("/test")
    process_time_str = response.headers["X-Process-Time"]

    # Should be in format like "0.0012" (4 decimal places)
    assert "." in process_time_str
    parts = process_time_str.split(".")
    assert len(parts) == 2
    assert len(parts[1]) == 4  # 4 decimal places
