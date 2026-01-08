"""Real-time collaboration features.

This module enables multiple users to collaborate in real-time,
sharing discoveries, exploring together, and building collaborative playlists.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

from discovery.websocket_manager import WebSocketManager


logger = structlog.get_logger(__name__)


class SessionType(str, Enum):
    """Types of collaboration sessions."""

    EXPLORATION = "exploration"  # Explore music graph together
    PLAYLIST = "playlist"  # Collaborative playlist building
    DISCOVERY = "discovery"  # Share discoveries
    ANALYSIS = "analysis"  # Analyze music trends together


class ActionType(str, Enum):
    """Types of collaborative actions."""

    VIEW_ARTIST = "view_artist"
    VIEW_RELEASE = "view_release"
    ADD_TO_PLAYLIST = "add_to_playlist"
    REMOVE_FROM_PLAYLIST = "remove_from_playlist"
    COMMENT = "comment"
    REACT = "react"
    SHARE_DISCOVERY = "share_discovery"
    CURSOR_MOVE = "cursor_move"


@dataclass
class CollaborationAction:
    """A collaborative action performed by a user."""

    action_id: str
    user_id: str
    action_type: ActionType
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollaborationSession:
    """A collaboration session."""

    session_id: str
    session_type: SessionType
    created_by: str
    created_at: datetime
    participants: set[str] = field(default_factory=set)
    state: dict[str, Any] = field(default_factory=dict)
    actions: list[CollaborationAction] = field(default_factory=list)
    active: bool = True


class CollaborationManager:
    """Manage real-time collaboration sessions."""

    def __init__(self, websocket_manager: WebSocketManager) -> None:
        """Initialize collaboration manager.

        Args:
            websocket_manager: WebSocket manager instance
        """
        self.ws_manager = websocket_manager

        # Active sessions: session_id -> Session
        self.sessions: dict[str, CollaborationSession] = {}

        # User -> sessions mapping
        self.user_sessions: dict[str, set[str]] = defaultdict(set)

        # Session cursors (for presence awareness)
        self.cursors: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)  # session_id -> user_id -> cursor_data

    def create_session(
        self,
        user_id: str,
        session_type: SessionType,
        initial_state: dict[str, Any] | None = None,
    ) -> CollaborationSession:
        """Create a new collaboration session.

        Args:
            user_id: User creating the session
            session_type: Type of session
            initial_state: Initial session state

        Returns:
            Created session
        """
        session_id = str(uuid.uuid4())

        session = CollaborationSession(
            session_id=session_id,
            session_type=session_type,
            created_by=user_id,
            created_at=datetime.now(UTC),
            participants={user_id},
            state=initial_state or {},
        )

        self.sessions[session_id] = session
        self.user_sessions[user_id].add(session_id)

        logger.info(
            "✅ Created collaboration session",
            session_id=session_id,
            type=session_type,
            user=user_id,
        )

        return session

    async def join_session(
        self,
        session_id: str,
        user_id: str,
        connection_id: str,
    ) -> CollaborationSession | None:
        """Join an existing collaboration session.

        Args:
            session_id: Session to join
            user_id: User joining
            connection_id: WebSocket connection ID

        Returns:
            Session object or None if not found
        """
        if session_id not in self.sessions:
            logger.warning("⚠️ Session not found", session_id=session_id)
            return None

        session = self.sessions[session_id]

        if not session.active:
            logger.warning("⚠️ Session is not active", session_id=session_id)
            return None

        # Add participant
        session.participants.add(user_id)
        self.user_sessions[user_id].add(session_id)

        logger.info(
            "👥 User joined session",
            session_id=session_id,
            user_id=user_id,
            participants=len(session.participants),
        )

        # Subscribe to session channel
        channel = f"session_{session_id}"
        await self.ws_manager.subscribe(connection_id, channel)

        # Notify other participants
        await self._broadcast_to_session(
            session_id,
            {
                "action": "user_joined",
                "user_id": user_id,
                "participants": list(session.participants),
                "timestamp": datetime.now(UTC).isoformat(),
            },
            exclude={connection_id},
        )

        # Send session state to new participant
        await self.ws_manager.send_to_connection(
            connection_id,
            {
                "type": "session_state",
                "session_id": session_id,
                "state": session.state,
                "participants": list(session.participants),
                "recent_actions": [self._action_to_dict(a) for a in session.actions[-20:]],
            },
        )

        return session

    async def leave_session(
        self,
        session_id: str,
        user_id: str,
        connection_id: str,
    ) -> None:
        """Leave a collaboration session.

        Args:
            session_id: Session to leave
            user_id: User leaving
            connection_id: WebSocket connection ID
        """
        if session_id not in self.sessions:
            return

        session = self.sessions[session_id]
        session.participants.discard(user_id)

        if user_id in self.user_sessions:
            self.user_sessions[user_id].discard(session_id)

        # Remove cursor
        if session_id in self.cursors:
            self.cursors[session_id].pop(user_id, None)

        logger.info(
            "👋 User left session",
            session_id=session_id,
            user_id=user_id,
            remaining=len(session.participants),
        )

        # Unsubscribe from session channel
        channel = f"session_{session_id}"
        await self.ws_manager.unsubscribe(connection_id, channel)

        # Notify other participants
        await self._broadcast_to_session(
            session_id,
            {
                "action": "user_left",
                "user_id": user_id,
                "participants": list(session.participants),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # Close session if no participants
        if not session.participants:
            session.active = False
            logger.info("🔒 Session closed (no participants)", session_id=session_id)

    async def perform_action(
        self,
        session_id: str,
        user_id: str,
        action_type: ActionType,
        data: dict[str, Any],
    ) -> CollaborationAction | None:
        """Perform a collaborative action.

        Args:
            session_id: Session ID
            user_id: User performing action
            action_type: Type of action
            data: Action data

        Returns:
            Created action or None
        """
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]

        # Create action
        action = CollaborationAction(
            action_id=str(uuid.uuid4()),
            user_id=user_id,
            action_type=action_type,
            timestamp=datetime.now(UTC),
            data=data,
        )

        # Add to session
        session.actions.append(action)

        # Update session state based on action
        await self._update_session_state(session, action)

        logger.debug(
            "📝 Collaboration action",
            session_id=session_id,
            user_id=user_id,
            action=action_type,
        )

        # Broadcast to participants
        await self._broadcast_to_session(
            session_id,
            {
                "action": "action_performed",
                "action_data": self._action_to_dict(action),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return action

    async def update_cursor(
        self,
        session_id: str,
        user_id: str,
        cursor_data: dict[str, Any],
    ) -> None:
        """Update user cursor position (for presence awareness).

        Args:
            session_id: Session ID
            user_id: User ID
            cursor_data: Cursor position/state data
        """
        if session_id not in self.sessions:
            return

        self.cursors[session_id][user_id] = cursor_data

        # Broadcast cursor update (throttled in practice)
        await self._broadcast_to_session(
            session_id,
            {
                "action": "cursor_update",
                "user_id": user_id,
                "cursor": cursor_data,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def _update_session_state(
        self,
        session: CollaborationSession,
        action: CollaborationAction,
    ) -> None:
        """Update session state based on action.

        Args:
            session: Session to update
            action: Action that was performed
        """
        if action.action_type == ActionType.ADD_TO_PLAYLIST:
            # Add to playlist
            if "playlist" not in session.state:
                session.state["playlist"] = []

            item = action.data.get("item")
            if item:
                session.state["playlist"].append(
                    {
                        "item": item,
                        "added_by": action.user_id,
                        "added_at": action.timestamp.isoformat(),
                    }
                )

        elif action.action_type == ActionType.REMOVE_FROM_PLAYLIST:
            # Remove from playlist
            if "playlist" in session.state:
                item_id = action.data.get("item_id")
                session.state["playlist"] = [item for item in session.state["playlist"] if item.get("item", {}).get("id") != item_id]

        elif action.action_type == ActionType.VIEW_ARTIST:
            # Track current view
            session.state["current_artist"] = action.data.get("artist_name")

        elif action.action_type == ActionType.SHARE_DISCOVERY:
            # Add to discoveries
            if "discoveries" not in session.state:
                session.state["discoveries"] = []

            session.state["discoveries"].append(
                {
                    "discovery": action.data,
                    "shared_by": action.user_id,
                    "shared_at": action.timestamp.isoformat(),
                }
            )

    async def _broadcast_to_session(
        self,
        session_id: str,
        message: dict[str, Any],
        exclude: set[str] | None = None,
    ) -> None:
        """Broadcast message to all session participants.

        Args:
            session_id: Session ID
            message: Message to broadcast
            exclude: Optional connection IDs to exclude
        """
        channel = f"session_{session_id}"
        await self.ws_manager.broadcast(channel, message, exclude=exclude)

    def _action_to_dict(self, action: CollaborationAction) -> dict[str, Any]:
        """Convert action to dictionary.

        Args:
            action: Action to convert

        Returns:
            Dictionary representation
        """
        return {
            "action_id": action.action_id,
            "user_id": action.user_id,
            "action_type": action.action_type,
            "timestamp": action.timestamp.isoformat(),
            "data": action.data,
        }

    def get_session(self, session_id: str) -> CollaborationSession | None:
        """Get session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session or None
        """
        return self.sessions.get(session_id)

    def get_user_sessions(self, user_id: str) -> list[CollaborationSession]:
        """Get all active sessions for a user.

        Args:
            user_id: User ID

        Returns:
            List of sessions
        """
        session_ids = self.user_sessions.get(user_id, set())
        return [self.sessions[sid] for sid in session_ids if sid in self.sessions and self.sessions[sid].active]

    def get_session_cursors(self, session_id: str) -> dict[str, dict[str, Any]]:
        """Get all cursors for a session.

        Args:
            session_id: Session ID

        Returns:
            Dictionary of user cursors
        """
        return self.cursors.get(session_id, {})

    async def send_comment(
        self,
        session_id: str,
        user_id: str,
        comment: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Send a comment in the session.

        Args:
            session_id: Session ID
            user_id: User ID
            comment: Comment text
            context: Optional context (artist, release, etc.)
        """
        await self.perform_action(
            session_id,
            user_id,
            ActionType.COMMENT,
            {
                "comment": comment,
                "context": context or {},
            },
        )

    async def react(
        self,
        session_id: str,
        user_id: str,
        reaction: str,
        target_action_id: str,
    ) -> None:
        """React to an action in the session.

        Args:
            session_id: Session ID
            user_id: User ID
            reaction: Reaction emoji/type
            target_action_id: ID of action being reacted to
        """
        await self.perform_action(
            session_id,
            user_id,
            ActionType.REACT,
            {
                "reaction": reaction,
                "target_action_id": target_action_id,
            },
        )

    def get_statistics(self) -> dict[str, Any]:
        """Get collaboration statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len([s for s in self.sessions.values() if s.active]),
            "total_participants": sum(len(s.participants) for s in self.sessions.values()),
            "sessions_by_type": {
                session_type: len([s for s in self.sessions.values() if s.session_type == session_type]) for session_type in SessionType
            },
        }
