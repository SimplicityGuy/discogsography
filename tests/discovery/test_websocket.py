"""WebSocket functionality tests for Discovery service.

Tests WebSocket connection, disconnection, broadcasting, and error handling.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def discovery_client() -> TestClient:
    """Create a test client for the discovery service."""
    from discovery.discovery import app

    return TestClient(app)


def test_websocket_connection_and_disconnection(discovery_client: TestClient) -> None:
    """Test WebSocket connection and disconnection."""
    with discovery_client.websocket_connect("/ws") as websocket:
        # Verify connection is established
        assert websocket is not None


def test_websocket_echo_functionality(discovery_client: TestClient) -> None:
    """Test WebSocket echo functionality."""
    with discovery_client.websocket_connect("/ws") as websocket:
        # Send a message
        test_message = "Hello, WebSocket!"
        websocket.send_text(test_message)

        # Receive echo response
        response = websocket.receive_json()

        # Verify response structure
        assert response["type"] == "echo"
        assert response["message"] == test_message
        assert "timestamp" in response


def test_websocket_multiple_messages(discovery_client: TestClient) -> None:
    """Test sending multiple messages through WebSocket."""
    with discovery_client.websocket_connect("/ws") as websocket:
        messages = ["First message", "Second message", "Third message"]

        for msg in messages:
            websocket.send_text(msg)
            response = websocket.receive_json()

            assert response["type"] == "echo"
            assert response["message"] == msg
            assert "timestamp" in response


def test_websocket_multiple_connections(discovery_client: TestClient) -> None:
    """Test multiple WebSocket connections simultaneously."""
    with (
        discovery_client.websocket_connect("/ws") as ws1,
        discovery_client.websocket_connect("/ws") as ws2,
        discovery_client.websocket_connect("/ws") as ws3,
    ):
        # All connections should be active
        assert ws1 is not None
        assert ws2 is not None
        assert ws3 is not None

        # Test that each connection can send/receive independently
        ws1.send_text("Connection 1")
        response1 = ws1.receive_json()
        assert response1["message"] == "Connection 1"

        ws2.send_text("Connection 2")
        response2 = ws2.receive_json()
        assert response2["message"] == "Connection 2"

        ws3.send_text("Connection 3")
        response3 = ws3.receive_json()
        assert response3["message"] == "Connection 3"


def test_websocket_json_message(discovery_client: TestClient) -> None:
    """Test sending JSON data through WebSocket."""
    with discovery_client.websocket_connect("/ws") as websocket:
        # Send JSON as text (since endpoint expects text)
        json_message = '{"action": "test", "data": "value"}'
        websocket.send_text(json_message)

        # Receive echo response
        response = websocket.receive_json()

        assert response["type"] == "echo"
        assert response["message"] == json_message
        assert "timestamp" in response


def test_websocket_empty_message(discovery_client: TestClient) -> None:
    """Test sending empty message through WebSocket."""
    with discovery_client.websocket_connect("/ws") as websocket:
        websocket.send_text("")

        response = websocket.receive_json()

        assert response["type"] == "echo"
        assert response["message"] == ""
        assert "timestamp" in response


def test_websocket_unicode_message(discovery_client: TestClient) -> None:
    """Test sending Unicode characters through WebSocket."""
    with discovery_client.websocket_connect("/ws") as websocket:
        unicode_message = "Hello 世界 🎵 Müsic"
        websocket.send_text(unicode_message)

        response = websocket.receive_json()

        assert response["type"] == "echo"
        assert response["message"] == unicode_message
        assert "timestamp" in response


def test_websocket_long_message(discovery_client: TestClient) -> None:
    """Test sending long message through WebSocket."""
    with discovery_client.websocket_connect("/ws") as websocket:
        # Create a long message (10KB)
        long_message = "A" * 10_000
        websocket.send_text(long_message)

        response = websocket.receive_json()

        assert response["type"] == "echo"
        assert response["message"] == long_message
        assert "timestamp" in response


def test_websocket_rapid_messages(discovery_client: TestClient) -> None:
    """Test sending rapid succession of messages."""
    with discovery_client.websocket_connect("/ws") as websocket:
        # Send 100 messages rapidly
        for i in range(100):
            websocket.send_text(f"Message {i}")
            response = websocket.receive_json()

            assert response["type"] == "echo"
            assert response["message"] == f"Message {i}"


def test_websocket_timestamp_format(discovery_client: TestClient) -> None:
    """Test that timestamp is in ISO format."""
    with discovery_client.websocket_connect("/ws") as websocket:
        websocket.send_text("test")

        response = websocket.receive_json()

        # Verify timestamp is present and is ISO format
        timestamp = response["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp  # ISO format contains 'T'
        assert len(timestamp) > 10  # Should be full ISO datetime


def test_websocket_connection_lifecycle(discovery_client: TestClient) -> None:
    """Test complete WebSocket connection lifecycle."""
    # Connect
    with discovery_client.websocket_connect("/ws") as websocket:
        # Verify connection
        assert websocket is not None

        # Use connection
        websocket.send_text("lifecycle test")
        response = websocket.receive_json()
        assert response["message"] == "lifecycle test"

    # After context manager exits, connection should be closed
    # No assertion needed - if no exception raised, lifecycle is correct


def test_websocket_sequential_connections(discovery_client: TestClient) -> None:
    """Test sequential WebSocket connections."""
    messages = ["First connection", "Second connection", "Third connection"]

    for msg in messages:
        with discovery_client.websocket_connect("/ws") as websocket:
            websocket.send_text(msg)
            response = websocket.receive_json()
            assert response["message"] == msg
