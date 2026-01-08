"""Enhanced WebSocket implementation for live updates.

This module provides WebSocket connection management, message broadcasting,
and real-time update capabilities for the Discovery service.
"""

from collections import defaultdict
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect


logger = structlog.get_logger(__name__)


class MessageType(str, Enum):
    """WebSocket message types."""

    # Client -> Server
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"
    REQUEST = "request"

    # Server -> Client
    UPDATE = "update"
    NOTIFICATION = "notification"
    PONG = "pong"
    RESPONSE = "response"
    ERROR = "error"


class Channel(str, Enum):
    """Available subscription channels."""

    TRENDING = "trending"  # Trending artists/releases
    RECOMMENDATIONS = "recommendations"  # New recommendations
    DISCOVERIES = "discoveries"  # New discoveries
    ANALYTICS = "analytics"  # Analytics updates
    SEARCH = "search"  # Live search results
    GRAPH = "graph"  # Graph updates
    SYSTEM = "system"  # System notifications


class WebSocketManager:
    """Manage WebSocket connections and broadcasting."""

    def __init__(self) -> None:
        """Initialize WebSocket manager."""
        # Active connections: connection_id -> WebSocket
        self.connections: dict[str, WebSocket] = {}

        # Channel subscriptions: channel -> set of connection_ids
        self.subscriptions: dict[str, set[str]] = defaultdict(set)

        # Connection metadata: connection_id -> metadata
        self.metadata: dict[str, dict[str, Any]] = {}

        # Message history for reconnection
        self.message_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.max_history = 50  # Keep last 50 messages per channel

        # Connection heartbeat tracking
        self.last_heartbeat: dict[str, datetime] = {}
        self.heartbeat_interval = 30  # seconds

    async def connect(
        self,
        websocket: WebSocket,
        connection_id: str,
        user_id: str | None = None,
    ) -> None:
        """Accept and register a WebSocket connection.

        Args:
            websocket: WebSocket connection
            connection_id: Unique connection identifier
            user_id: Optional user identifier
        """
        await websocket.accept()

        self.connections[connection_id] = websocket
        self.metadata[connection_id] = {
            "user_id": user_id,
            "connected_at": datetime.now(UTC),
            "channels": [],
        }
        self.last_heartbeat[connection_id] = datetime.now(UTC)

        logger.info(
            "✅ WebSocket connected",
            connection_id=connection_id,
            user_id=user_id,
            total_connections=len(self.connections),
        )

        # Send welcome message
        await self.send_to_connection(
            connection_id,
            {
                "type": MessageType.NOTIFICATION,
                "message": "Connected to Discovery service",
                "connection_id": connection_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def disconnect(self, connection_id: str) -> None:
        """Disconnect and cleanup a WebSocket connection.

        Args:
            connection_id: Connection identifier
        """
        # Unsubscribe from all channels
        for channel in list(self.subscriptions.keys()):
            if connection_id in self.subscriptions[channel]:
                self.subscriptions[channel].remove(connection_id)

        # Remove connection
        self.connections.pop(connection_id, None)
        self.metadata.pop(connection_id, None)
        self.last_heartbeat.pop(connection_id, None)

        logger.info(
            "👋 WebSocket disconnected",
            connection_id=connection_id,
            total_connections=len(self.connections),
        )

    async def subscribe(self, connection_id: str, channel: str) -> None:
        """Subscribe a connection to a channel.

        Args:
            connection_id: Connection identifier
            channel: Channel name
        """
        if connection_id not in self.connections:
            return

        self.subscriptions[channel].add(connection_id)

        if connection_id in self.metadata and channel not in self.metadata[connection_id]["channels"]:
            self.metadata[connection_id]["channels"].append(channel)

        logger.info(
            "📡 Subscribed to channel",
            connection_id=connection_id,
            channel=channel,
            subscribers=len(self.subscriptions[channel]),
        )

        # Send recent message history
        if channel in self.message_history:
            for message in self.message_history[channel][-10:]:  # Last 10 messages
                await self.send_to_connection(connection_id, message)

        # Confirmation
        await self.send_to_connection(
            connection_id,
            {
                "type": MessageType.NOTIFICATION,
                "message": f"Subscribed to {channel}",
                "channel": channel,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def unsubscribe(self, connection_id: str, channel: str) -> None:
        """Unsubscribe a connection from a channel.

        Args:
            connection_id: Connection identifier
            channel: Channel name
        """
        if channel in self.subscriptions:
            self.subscriptions[channel].discard(connection_id)

        if connection_id in self.metadata:
            channels = self.metadata[connection_id]["channels"]
            if channel in channels:
                channels.remove(channel)

        logger.info(
            "📴 Unsubscribed from channel",
            connection_id=connection_id,
            channel=channel,
        )

        await self.send_to_connection(
            connection_id,
            {
                "type": MessageType.NOTIFICATION,
                "message": f"Unsubscribed from {channel}",
                "channel": channel,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def broadcast(
        self,
        channel: str,
        message: dict[str, Any],
        exclude: set[str] | None = None,
    ) -> int:
        """Broadcast a message to all subscribers of a channel.

        Args:
            channel: Channel to broadcast to
            message: Message to send
            exclude: Optional set of connection IDs to exclude

        Returns:
            Number of connections message was sent to
        """
        exclude = exclude or set()

        # Add to message history
        message["timestamp"] = datetime.now(UTC).isoformat()
        self.message_history[channel].append(message)

        # Trim history
        if len(self.message_history[channel]) > self.max_history:
            self.message_history[channel] = self.message_history[channel][-self.max_history :]

        # Send to subscribers
        sent_count = 0
        failed_connections = []

        for connection_id in self.subscriptions.get(channel, set()):
            if connection_id in exclude:
                continue

            try:
                await self.send_to_connection(connection_id, message)
                sent_count += 1
            except Exception as e:
                logger.warning(
                    "⚠️ Failed to send message",
                    connection_id=connection_id,
                    error=str(e),
                )
                failed_connections.append(connection_id)

        # Cleanup failed connections
        for connection_id in failed_connections:
            await self.disconnect(connection_id)

        logger.debug(
            "📢 Broadcast message",
            channel=channel,
            sent_to=sent_count,
            failed=len(failed_connections),
        )

        return sent_count

    async def send_to_connection(
        self,
        connection_id: str,
        message: dict[str, Any],
    ) -> None:
        """Send a message to a specific connection.

        Args:
            connection_id: Connection identifier
            message: Message to send
        """
        if connection_id not in self.connections:
            return

        websocket = self.connections[connection_id]

        try:
            await websocket.send_json(message)
        except WebSocketDisconnect:
            await self.disconnect(connection_id)
        except Exception as e:
            logger.error(
                "❌ Error sending WebSocket message",
                connection_id=connection_id,
                error=str(e),
            )
            await self.disconnect(connection_id)

    async def handle_message(
        self,
        connection_id: str,
        message: dict[str, Any],
    ) -> None:
        """Handle incoming WebSocket message.

        Args:
            connection_id: Connection identifier
            message: Received message
        """
        msg_type = message.get("type")

        if msg_type == MessageType.SUBSCRIBE:
            channel = message.get("channel")
            if channel:
                await self.subscribe(connection_id, channel)

        elif msg_type == MessageType.UNSUBSCRIBE:
            channel = message.get("channel")
            if channel:
                await self.unsubscribe(connection_id, channel)

        elif msg_type == MessageType.PING:
            self.last_heartbeat[connection_id] = datetime.now(UTC)
            await self.send_to_connection(
                connection_id,
                {
                    "type": MessageType.PONG,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        elif msg_type == MessageType.REQUEST:
            # Handle specific request types
            request_type = message.get("request")
            if request_type == "status":
                await self._send_status(connection_id)
            elif request_type == "channels":
                await self._send_available_channels(connection_id)

        else:
            logger.warning(
                "⚠️ Unknown message type",
                connection_id=connection_id,
                type=msg_type,
            )

    async def _send_status(self, connection_id: str) -> None:
        """Send connection status to client.

        Args:
            connection_id: Connection identifier
        """
        metadata = self.metadata.get(connection_id, {})

        await self.send_to_connection(
            connection_id,
            {
                "type": MessageType.RESPONSE,
                "request": "status",
                "data": {
                    "connection_id": connection_id,
                    "connected_at": (metadata["connected_at"].isoformat() if metadata.get("connected_at") else None),
                    "subscribed_channels": metadata.get("channels", []),
                    "user_id": metadata.get("user_id"),
                },
            },
        )

    async def _send_available_channels(self, connection_id: str) -> None:
        """Send list of available channels to client.

        Args:
            connection_id: Connection identifier
        """
        channels = [
            {
                "name": channel.value,
                "subscribers": len(self.subscriptions.get(channel.value, set())),
            }
            for channel in Channel
        ]

        await self.send_to_connection(
            connection_id,
            {
                "type": MessageType.RESPONSE,
                "request": "channels",
                "data": {"channels": channels},
            },
        )

    async def check_heartbeats(self) -> None:
        """Check connection heartbeats and disconnect stale connections."""
        now = datetime.now(UTC)
        stale_connections = []

        for connection_id, last_heartbeat in self.last_heartbeat.items():
            if (now - last_heartbeat).total_seconds() > self.heartbeat_interval * 2:
                stale_connections.append(connection_id)

        for connection_id in stale_connections:
            logger.warning("⚠️ Connection timeout", connection_id=connection_id)
            await self.disconnect(connection_id)

    def get_statistics(self) -> dict[str, Any]:
        """Get WebSocket manager statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "total_connections": len(self.connections),
            "channels": {channel: len(subscribers) for channel, subscribers in self.subscriptions.items()},
            "total_subscriptions": sum(len(subs) for subs in self.subscriptions.values()),
            "message_history_size": sum(len(history) for history in self.message_history.values()),
        }

    async def send_notification(
        self,
        channel: str,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
        level: str = "info",
    ) -> int:
        """Send a notification to a channel.

        Args:
            channel: Channel to send to
            title: Notification title
            message: Notification message
            data: Optional additional data
            level: Notification level (info, warning, error, success)

        Returns:
            Number of connections notified
        """
        notification = {
            "type": MessageType.NOTIFICATION,
            "level": level,
            "title": title,
            "message": message,
            "data": data or {},
            "channel": channel,
        }

        return await self.broadcast(channel, notification)

    async def send_update(
        self,
        channel: str,
        update_type: str,
        data: dict[str, Any],
    ) -> int:
        """Send an update to a channel.

        Args:
            channel: Channel to send to
            update_type: Type of update
            data: Update data

        Returns:
            Number of connections updated
        """
        update = {
            "type": MessageType.UPDATE,
            "update_type": update_type,
            "data": data,
            "channel": channel,
        }

        return await self.broadcast(channel, update)
