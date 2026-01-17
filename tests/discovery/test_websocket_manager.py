"""Unit tests for WebSocket manager.

Tests WebSocketManager class methods, connection management, subscriptions,
broadcasting, and message handling.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.websocket_manager import (
    Channel,
    MessageType,
    WebSocketManager,
)


class TestWebSocketManager:
    """Tests for WebSocketManager class."""

    @pytest.fixture
    def manager(self):
        """Create a WebSocketManager instance."""
        return WebSocketManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket."""
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_initialization(self, manager):
        """Test WebSocketManager initialization."""
        assert isinstance(manager.connections, dict)
        assert isinstance(manager.subscriptions, dict)
        assert isinstance(manager.metadata, dict)
        assert isinstance(manager.message_history, dict)
        assert isinstance(manager.last_heartbeat, dict)
        assert manager.max_history == 50
        assert manager.heartbeat_interval == 30

    @pytest.mark.asyncio
    async def test_connect_basic(self, manager, mock_websocket):
        """Test basic WebSocket connection."""
        connection_id = "test-conn-1"
        user_id = "user-123"

        await manager.connect(mock_websocket, connection_id, user_id)

        # Verify connection was accepted
        mock_websocket.accept.assert_called_once()

        # Verify connection was registered
        assert connection_id in manager.connections
        assert manager.connections[connection_id] == mock_websocket

        # Verify metadata was created
        assert connection_id in manager.metadata
        assert manager.metadata[connection_id]["user_id"] == user_id
        assert "connected_at" in manager.metadata[connection_id]
        assert manager.metadata[connection_id]["channels"] == []

        # Verify heartbeat was initialized
        assert connection_id in manager.last_heartbeat

        # Verify welcome message was sent
        mock_websocket.send_json.assert_called_once()
        welcome_msg = mock_websocket.send_json.call_args[0][0]
        assert welcome_msg["type"] == MessageType.NOTIFICATION
        assert "Connected to Discovery service" in welcome_msg["message"]

    @pytest.mark.asyncio
    async def test_connect_without_user_id(self, manager, mock_websocket):
        """Test WebSocket connection without user ID."""
        connection_id = "test-conn-2"

        await manager.connect(mock_websocket, connection_id)

        # Should work without user_id
        assert connection_id in manager.connections
        assert manager.metadata[connection_id]["user_id"] is None

    @pytest.mark.asyncio
    async def test_disconnect(self, manager, mock_websocket):
        """Test WebSocket disconnection."""
        connection_id = "test-conn-1"

        # First connect
        await manager.connect(mock_websocket, connection_id, "user-123")

        # Subscribe to channels
        await manager.subscribe(connection_id, Channel.TRENDING)
        await manager.subscribe(connection_id, Channel.RECOMMENDATIONS)

        # Disconnect
        await manager.disconnect(connection_id)

        # Verify connection was removed
        assert connection_id not in manager.connections
        assert connection_id not in manager.metadata
        assert connection_id not in manager.last_heartbeat

        # Verify removed from all subscriptions
        assert connection_id not in manager.subscriptions.get(Channel.TRENDING, set())
        assert connection_id not in manager.subscriptions.get(Channel.RECOMMENDATIONS, set())

    @pytest.mark.asyncio
    async def test_subscribe(self, manager, mock_websocket):
        """Test channel subscription."""
        connection_id = "test-conn-1"
        channel = Channel.TRENDING

        # Connect first
        await manager.connect(mock_websocket, connection_id)

        # Clear welcome message call
        mock_websocket.send_json.reset_mock()

        # Subscribe
        await manager.subscribe(connection_id, channel)

        # Verify subscription was added
        assert connection_id in manager.subscriptions[channel]
        assert channel in manager.metadata[connection_id]["channels"]

        # Verify confirmation message was sent
        assert mock_websocket.send_json.call_count >= 1
        last_call = mock_websocket.send_json.call_args_list[-1][0][0]
        assert last_call["type"] == MessageType.NOTIFICATION
        assert "Subscribed to" in last_call["message"]
        assert last_call["channel"] == channel

    @pytest.mark.asyncio
    async def test_subscribe_with_message_history(self, manager, mock_websocket):
        """Test subscription sends recent message history."""
        connection_id = "test-conn-1"
        channel = Channel.TRENDING

        # Add some message history
        for i in range(15):
            manager.message_history[channel].append(
                {
                    "type": MessageType.UPDATE,
                    "data": f"message-{i}",
                }
            )

        # Connect and subscribe
        await manager.connect(mock_websocket, connection_id)
        mock_websocket.send_json.reset_mock()

        await manager.subscribe(connection_id, channel)

        # Should have sent last 10 messages from history + confirmation
        # (10 history messages + 1 confirmation = 11 calls)
        assert mock_websocket.send_json.call_count == 11

    @pytest.mark.asyncio
    async def test_subscribe_nonexistent_connection(self, manager):
        """Test subscribing with non-existent connection does nothing."""
        connection_id = "nonexistent"
        channel = Channel.TRENDING

        # Should not raise error
        await manager.subscribe(connection_id, channel)

        # Should not be subscribed
        assert connection_id not in manager.subscriptions.get(channel, set())

    @pytest.mark.asyncio
    async def test_unsubscribe(self, manager, mock_websocket):
        """Test channel unsubscription."""
        connection_id = "test-conn-1"
        channel = Channel.TRENDING

        # Connect and subscribe first
        await manager.connect(mock_websocket, connection_id)
        await manager.subscribe(connection_id, channel)

        # Clear previous calls
        mock_websocket.send_json.reset_mock()

        # Unsubscribe
        await manager.unsubscribe(connection_id, channel)

        # Verify unsubscription
        assert connection_id not in manager.subscriptions.get(channel, set())
        assert channel not in manager.metadata[connection_id]["channels"]

        # Verify confirmation message
        mock_websocket.send_json.assert_called_once()
        msg = mock_websocket.send_json.call_args[0][0]
        assert msg["type"] == MessageType.NOTIFICATION
        assert "Unsubscribed" in msg["message"]

    @pytest.mark.asyncio
    async def test_broadcast_basic(self, manager):
        """Test broadcasting message to channel subscribers."""
        channel = Channel.TRENDING

        # Create multiple connections
        websockets = []
        for i in range(3):
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            websockets.append(ws)

            connection_id = f"conn-{i}"
            await manager.connect(ws, connection_id)
            await manager.subscribe(connection_id, channel)

            # Clear setup calls
            ws.send_json.reset_mock()

        # Broadcast message
        message = {"type": MessageType.UPDATE, "data": "test"}
        sent_count = await manager.broadcast(channel, message)

        # Verify sent to all subscribers
        assert sent_count == 3

        # Verify all websockets received the message
        for ws in websockets:
            ws.send_json.assert_called_once()
            msg = ws.send_json.call_args[0][0]
            assert msg["type"] == MessageType.UPDATE
            assert "timestamp" in msg

    @pytest.mark.asyncio
    async def test_broadcast_with_exclusions(self, manager):
        """Test broadcasting with excluded connections."""
        channel = Channel.TRENDING

        # Create connections
        websockets = {}
        for i in range(3):
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()

            connection_id = f"conn-{i}"
            websockets[connection_id] = ws

            await manager.connect(ws, connection_id)
            await manager.subscribe(connection_id, channel)
            ws.send_json.reset_mock()

        # Broadcast excluding conn-1
        message = {"type": MessageType.UPDATE, "data": "test"}
        sent_count = await manager.broadcast(channel, message, exclude={"conn-1"})

        # Should send to 2 connections (excluding conn-1)
        assert sent_count == 2

        # Verify conn-1 did not receive message
        websockets["conn-1"].send_json.assert_not_called()

        # Verify others received message
        websockets["conn-0"].send_json.assert_called_once()
        websockets["conn-2"].send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_adds_to_history(self, manager):
        """Test broadcast adds message to history."""
        channel = Channel.TRENDING

        # Broadcast some messages
        for i in range(60):  # More than max_history
            await manager.broadcast(channel, {"type": MessageType.UPDATE, "data": f"msg-{i}"})

        # Verify history is trimmed to max_history
        assert len(manager.message_history[channel]) == manager.max_history

        # Verify most recent messages are kept
        last_msg = manager.message_history[channel][-1]
        assert last_msg["data"] == "msg-59"

    @pytest.mark.asyncio
    async def test_broadcast_handles_failed_connections(self, manager):
        """Test broadcast handles failed connections gracefully."""
        channel = Channel.TRENDING

        # Create working connection
        good_ws = MagicMock()
        good_ws.accept = AsyncMock()
        good_ws.send_json = AsyncMock()

        # Create failing connection
        bad_ws = MagicMock()
        bad_ws.accept = AsyncMock()
        bad_ws.send_json = AsyncMock(side_effect=Exception("Connection failed"))

        # Connect both
        await manager.connect(good_ws, "good-conn")
        await manager.connect(bad_ws, "bad-conn")

        await manager.subscribe("good-conn", channel)
        await manager.subscribe("bad-conn", channel)

        # Clear setup calls
        good_ws.send_json.reset_mock()
        bad_ws.send_json.reset_mock()

        # Broadcast
        message = {"type": MessageType.UPDATE, "data": "test"}
        sent_count = await manager.broadcast(channel, message)

        # Should succeed for good connection
        assert sent_count == 1
        good_ws.send_json.assert_called_once()

        # Failed connection should be removed
        assert "bad-conn" not in manager.connections

    @pytest.mark.asyncio
    async def test_send_to_connection(self, manager, mock_websocket):
        """Test sending message to specific connection."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)
        mock_websocket.send_json.reset_mock()

        # Send message
        message = {"type": MessageType.UPDATE, "data": "test"}
        await manager.send_to_connection(connection_id, message)

        # Verify message was sent
        mock_websocket.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_connection(self, manager):
        """Test sending to non-existent connection does nothing."""
        # Should not raise error
        await manager.send_to_connection("nonexistent", {"type": "test"})

    @pytest.mark.asyncio
    async def test_send_to_connection_handles_disconnect(self, manager, mock_websocket):
        """Test send_to_connection handles WebSocketDisconnect."""
        from fastapi import WebSocketDisconnect

        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)

        # Make send_json raise WebSocketDisconnect
        mock_websocket.send_json = AsyncMock(side_effect=WebSocketDisconnect())

        # Try to send
        await manager.send_to_connection(connection_id, {"type": "test"})

        # Connection should be removed
        assert connection_id not in manager.connections

    @pytest.mark.asyncio
    async def test_send_to_connection_handles_general_error(self, manager, mock_websocket):
        """Test send_to_connection handles general errors."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)

        # Make send_json raise error
        mock_websocket.send_json = AsyncMock(side_effect=RuntimeError("Send failed"))

        # Try to send
        await manager.send_to_connection(connection_id, {"type": "test"})

        # Connection should be removed
        assert connection_id not in manager.connections

    @pytest.mark.asyncio
    async def test_handle_message_subscribe(self, manager, mock_websocket):
        """Test handling SUBSCRIBE message."""
        connection_id = "test-conn"
        channel = Channel.TRENDING

        # Connect
        await manager.connect(mock_websocket, connection_id)

        # Handle subscribe message
        message = {"type": MessageType.SUBSCRIBE, "channel": channel}
        await manager.handle_message(connection_id, message)

        # Verify subscription
        assert connection_id in manager.subscriptions[channel]

    @pytest.mark.asyncio
    async def test_handle_message_unsubscribe(self, manager, mock_websocket):
        """Test handling UNSUBSCRIBE message."""
        connection_id = "test-conn"
        channel = Channel.TRENDING

        # Connect and subscribe first
        await manager.connect(mock_websocket, connection_id)
        await manager.subscribe(connection_id, channel)

        # Handle unsubscribe message
        message = {"type": MessageType.UNSUBSCRIBE, "channel": channel}
        await manager.handle_message(connection_id, message)

        # Verify unsubscription
        assert connection_id not in manager.subscriptions.get(channel, set())

    @pytest.mark.asyncio
    async def test_handle_message_ping(self, manager, mock_websocket):
        """Test handling PING message."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)
        old_heartbeat = manager.last_heartbeat[connection_id]

        # Clear welcome message
        mock_websocket.send_json.reset_mock()

        # Wait a moment to ensure different timestamp
        import asyncio

        await asyncio.sleep(0.01)

        # Handle ping message
        message = {"type": MessageType.PING}
        await manager.handle_message(connection_id, message)

        # Verify heartbeat was updated
        assert manager.last_heartbeat[connection_id] > old_heartbeat

        # Verify pong response
        mock_websocket.send_json.assert_called_once()
        pong = mock_websocket.send_json.call_args[0][0]
        assert pong["type"] == MessageType.PONG
        assert "timestamp" in pong

    @pytest.mark.asyncio
    async def test_handle_message_request_status(self, manager, mock_websocket):
        """Test handling REQUEST status message."""
        connection_id = "test-conn"
        user_id = "user-123"

        # Connect
        await manager.connect(mock_websocket, connection_id, user_id)
        mock_websocket.send_json.reset_mock()

        # Handle status request
        message = {"type": MessageType.REQUEST, "request": "status"}
        await manager.handle_message(connection_id, message)

        # Verify status response
        mock_websocket.send_json.assert_called_once()
        response = mock_websocket.send_json.call_args[0][0]
        assert response["type"] == MessageType.RESPONSE
        assert response["request"] == "status"
        assert response["data"]["connection_id"] == connection_id
        assert response["data"]["user_id"] == user_id
        assert "connected_at" in response["data"]

    @pytest.mark.asyncio
    async def test_handle_message_request_channels(self, manager, mock_websocket):
        """Test handling REQUEST channels message."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)
        mock_websocket.send_json.reset_mock()

        # Handle channels request
        message = {"type": MessageType.REQUEST, "request": "channels"}
        await manager.handle_message(connection_id, message)

        # Verify channels response
        mock_websocket.send_json.assert_called_once()
        response = mock_websocket.send_json.call_args[0][0]
        assert response["type"] == MessageType.RESPONSE
        assert response["request"] == "channels"
        assert "channels" in response["data"]

        # Verify all channel types are included
        channel_names = [ch["name"] for ch in response["data"]["channels"]]
        for channel in Channel:
            assert channel.value in channel_names

    @pytest.mark.asyncio
    async def test_handle_message_unknown_type(self, manager, mock_websocket):
        """Test handling unknown message type."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)

        # Handle unknown message type (should not raise error)
        message = {"type": "UNKNOWN_TYPE", "data": "test"}
        await manager.handle_message(connection_id, message)

        # Should log warning but not crash

    @pytest.mark.asyncio
    async def test_check_heartbeats(self, manager, mock_websocket):
        """Test heartbeat checking removes stale connections."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)

        # Set heartbeat to old time (beyond timeout)
        old_time = datetime.now(UTC) - timedelta(seconds=manager.heartbeat_interval * 3)
        manager.last_heartbeat[connection_id] = old_time

        # Check heartbeats
        await manager.check_heartbeats()

        # Connection should be removed
        assert connection_id not in manager.connections

    @pytest.mark.asyncio
    async def test_check_heartbeats_keeps_active_connections(self, manager, mock_websocket):
        """Test heartbeat checking keeps active connections."""
        connection_id = "test-conn"

        # Connect
        await manager.connect(mock_websocket, connection_id)

        # Recent heartbeat
        manager.last_heartbeat[connection_id] = datetime.now(UTC)

        # Check heartbeats
        await manager.check_heartbeats()

        # Connection should remain
        assert connection_id in manager.connections

    def test_get_statistics(self, manager):
        """Test getting manager statistics."""
        # Initially empty
        stats = manager.get_statistics()
        assert stats["total_connections"] == 0
        assert stats["total_subscriptions"] == 0

    @pytest.mark.asyncio
    async def test_get_statistics_with_data(self, manager):
        """Test statistics with active connections and subscriptions."""
        # Create connections and subscriptions
        for i in range(3):
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()

            connection_id = f"conn-{i}"
            await manager.connect(ws, connection_id)
            await manager.subscribe(connection_id, Channel.TRENDING)

        # Add one more subscription
        await manager.subscribe("conn-0", Channel.RECOMMENDATIONS)

        # Add message history
        manager.message_history[Channel.TRENDING].extend([{"data": "msg"}] * 10)

        # Get statistics
        stats = manager.get_statistics()

        assert stats["total_connections"] == 3
        assert stats["total_subscriptions"] == 4  # 3 trending + 1 recommendations
        assert stats["channels"][Channel.TRENDING] == 3
        assert stats["channels"][Channel.RECOMMENDATIONS] == 1
        assert stats["message_history_size"] == 10

    @pytest.mark.asyncio
    async def test_send_notification(self, manager):
        """Test sending notification to channel."""
        channel = Channel.TRENDING

        # Create connection and subscribe
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()

        await manager.connect(ws, "conn-1")
        await manager.subscribe("conn-1", channel)
        ws.send_json.reset_mock()

        # Send notification
        sent_count = await manager.send_notification(
            channel=channel,
            title="Test Title",
            message="Test Message",
            data={"key": "value"},
            level="info",
        )

        # Verify sent
        assert sent_count == 1
        ws.send_json.assert_called_once()

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == MessageType.NOTIFICATION
        assert msg["level"] == "info"
        assert msg["title"] == "Test Title"
        assert msg["message"] == "Test Message"
        assert msg["data"]["key"] == "value"
        assert msg["channel"] == channel

    @pytest.mark.asyncio
    async def test_send_update(self, manager):
        """Test sending update to channel."""
        channel = Channel.TRENDING

        # Create connection and subscribe
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()

        await manager.connect(ws, "conn-1")
        await manager.subscribe("conn-1", channel)
        ws.send_json.reset_mock()

        # Send update
        sent_count = await manager.send_update(
            channel=channel,
            update_type="artist_trending",
            data={"artist_id": "123"},
        )

        # Verify sent
        assert sent_count == 1
        ws.send_json.assert_called_once()

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == MessageType.UPDATE
        assert msg["update_type"] == "artist_trending"
        assert msg["data"]["artist_id"] == "123"
        assert msg["channel"] == channel


class TestMessageTypeEnum:
    """Tests for MessageType enum."""

    def test_message_type_values(self):
        """Test MessageType enum values."""
        # Client -> Server
        assert MessageType.SUBSCRIBE == "subscribe"
        assert MessageType.UNSUBSCRIBE == "unsubscribe"
        assert MessageType.PING == "ping"
        assert MessageType.REQUEST == "request"

        # Server -> Client
        assert MessageType.UPDATE == "update"
        assert MessageType.NOTIFICATION == "notification"
        assert MessageType.PONG == "pong"
        assert MessageType.RESPONSE == "response"
        assert MessageType.ERROR == "error"


class TestChannelEnum:
    """Tests for Channel enum."""

    def test_channel_values(self):
        """Test Channel enum values."""
        assert Channel.TRENDING == "trending"
        assert Channel.RECOMMENDATIONS == "recommendations"
        assert Channel.DISCOVERIES == "discoveries"
        assert Channel.ANALYTICS == "analytics"
        assert Channel.SEARCH == "search"
        assert Channel.GRAPH == "graph"
        assert Channel.SYSTEM == "system"

    def test_channel_enumeration(self):
        """Test iterating over Channel enum."""
        channels = list(Channel)
        assert len(channels) == 7
        assert Channel.TRENDING in channels
        assert Channel.SYSTEM in channels
