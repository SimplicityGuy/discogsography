"""Tests for CollaborationManager class."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.collaboration import (
    ActionType,
    CollaborationAction,
    CollaborationManager,
    CollaborationSession,
    SessionType,
)


class TestEnums:
    """Test enum definitions."""

    def test_session_type_enum(self) -> None:
        """Test SessionType enum values."""
        assert SessionType.EXPLORATION == "exploration"
        assert SessionType.PLAYLIST == "playlist"

    def test_action_type_enum(self) -> None:
        """Test ActionType enum values."""
        assert ActionType.VIEW_ARTIST == "view_artist"
        assert ActionType.ADD_TO_PLAYLIST == "add_to_playlist"


class TestDataclasses:
    """Test dataclass definitions."""

    def test_collaboration_action(self) -> None:
        """Test CollaborationAction dataclass."""
        action = CollaborationAction(
            action_id="123",
            user_id="user1",
            action_type=ActionType.VIEW_ARTIST,
            timestamp=datetime.now(UTC),
            data={"artist_name": "Test Artist"},
        )

        assert action.action_id == "123"
        assert action.user_id == "user1"
        assert action.action_type == ActionType.VIEW_ARTIST

    def test_collaboration_session(self) -> None:
        """Test CollaborationSession dataclass."""
        session = CollaborationSession(
            session_id="sess1",
            session_type=SessionType.EXPLORATION,
            created_by="user1",
            created_at=datetime.now(UTC),
        )

        assert session.session_id == "sess1"
        assert session.active is True
        assert len(session.participants) == 0


class TestCollaborationManagerInit:
    """Test CollaborationManager initialization."""

    def test_initialization(self) -> None:
        """Test manager initializes correctly."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        assert manager.ws_manager == mock_ws_manager
        assert manager.sessions == {}
        assert manager.user_sessions == {}
        assert manager.cursors == {}


class TestCreateSession:
    """Test creating collaboration sessions."""

    def test_create_session(self) -> None:
        """Test creating a new collaboration session."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        session = manager.create_session(
            user_id="user1",
            session_type=SessionType.PLAYLIST,
            initial_state={"name": "My Playlist"},
        )

        assert session.created_by == "user1"
        assert session.session_type == SessionType.PLAYLIST
        assert "user1" in session.participants
        assert session.state["name"] == "My Playlist"
        assert session.session_id in manager.sessions
        assert session.session_id in manager.user_sessions["user1"]


class TestJoinSession:
    """Test joining collaboration sessions."""

    @pytest.mark.asyncio
    async def test_join_session(self) -> None:
        """Test joining an existing session."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.subscribe = AsyncMock()
        mock_ws_manager.broadcast = AsyncMock()
        mock_ws_manager.send_to_connection = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)

        # Create session
        session = manager.create_session("user1", SessionType.EXPLORATION)

        # User2 joins
        result = await manager.join_session(session.session_id, "user2", "conn2")

        assert result is not None
        assert "user2" in session.participants
        assert session.session_id in manager.user_sessions["user2"]
        mock_ws_manager.subscribe.assert_called_once()
        mock_ws_manager.send_to_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_join_session_not_found(self) -> None:
        """Test joining non-existent session."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        result = await manager.join_session("invalid_id", "user1", "conn1")

        assert result is None

    @pytest.mark.asyncio
    async def test_join_session_inactive(self) -> None:
        """Test joining inactive session."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        session = manager.create_session("user1", SessionType.PLAYLIST)
        session.active = False

        result = await manager.join_session(session.session_id, "user2", "conn2")

        assert result is None


class TestLeaveSession:
    """Test leaving collaboration sessions."""

    @pytest.mark.asyncio
    async def test_leave_session(self) -> None:
        """Test leaving a session."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.unsubscribe = AsyncMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)

        session = manager.create_session("user1", SessionType.EXPLORATION)
        session.participants.add("user2")
        manager.user_sessions["user2"].add(session.session_id)

        await manager.leave_session(session.session_id, "user2", "conn2")

        assert "user2" not in session.participants
        mock_ws_manager.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_session_closes_empty(self) -> None:
        """Test session closes when last user leaves."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.unsubscribe = AsyncMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)

        session = manager.create_session("user1", SessionType.EXPLORATION)

        await manager.leave_session(session.session_id, "user1", "conn1")

        assert session.active is False

    @pytest.mark.asyncio
    async def test_leave_session_not_found(self) -> None:
        """Test leaving non-existent session."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        # Should not raise error
        await manager.leave_session("invalid_id", "user1", "conn1")


class TestPerformAction:
    """Test performing collaborative actions."""

    @pytest.mark.asyncio
    async def test_perform_action(self) -> None:
        """Test performing an action."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.EXPLORATION)

        action = await manager.perform_action(
            session.session_id,
            "user1",
            ActionType.VIEW_ARTIST,
            {"artist_name": "Test Artist"},
        )

        assert action is not None
        assert action.user_id == "user1"
        assert action.action_type == ActionType.VIEW_ARTIST
        assert len(session.actions) == 1

    @pytest.mark.asyncio
    async def test_perform_action_invalid_session(self) -> None:
        """Test performing action on invalid session."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        result = await manager.perform_action("invalid_id", "user1", ActionType.VIEW_ARTIST, {})

        assert result is None

    @pytest.mark.asyncio
    async def test_perform_add_to_playlist(self) -> None:
        """Test adding to playlist."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.PLAYLIST)

        await manager.perform_action(
            session.session_id,
            "user1",
            ActionType.ADD_TO_PLAYLIST,
            {"item": {"id": "123", "name": "Track"}},
        )

        assert "playlist" in session.state
        assert len(session.state["playlist"]) == 1

    @pytest.mark.asyncio
    async def test_perform_remove_from_playlist(self) -> None:
        """Test removing from playlist."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.PLAYLIST)

        # Add item first
        session.state["playlist"] = [{"item": {"id": "123"}, "added_by": "user1"}]

        # Remove it
        await manager.perform_action(
            session.session_id,
            "user1",
            ActionType.REMOVE_FROM_PLAYLIST,
            {"item_id": "123"},
        )

        assert len(session.state["playlist"]) == 0

    @pytest.mark.asyncio
    async def test_perform_share_discovery(self) -> None:
        """Test sharing discovery."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.DISCOVERY)

        await manager.perform_action(
            session.session_id,
            "user1",
            ActionType.SHARE_DISCOVERY,
            {"discovery": "New artist found!"},
        )

        assert "discoveries" in session.state
        assert len(session.state["discoveries"]) == 1


class TestUpdateCursor:
    """Test cursor updates."""

    @pytest.mark.asyncio
    async def test_update_cursor(self) -> None:
        """Test updating cursor position."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.EXPLORATION)

        await manager.update_cursor(session.session_id, "user1", {"x": 100, "y": 200})

        assert manager.cursors[session.session_id]["user1"] == {"x": 100, "y": 200}

    @pytest.mark.asyncio
    async def test_update_cursor_invalid_session(self) -> None:
        """Test updating cursor on invalid session."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        # Should not raise error
        await manager.update_cursor("invalid_id", "user1", {"x": 100, "y": 200})


class TestHelperMethods:
    """Test helper methods."""

    def test_action_to_dict(self) -> None:
        """Test converting action to dict."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        action = CollaborationAction(
            action_id="123",
            user_id="user1",
            action_type=ActionType.COMMENT,
            timestamp=datetime.now(UTC),
            data={"text": "Hello"},
        )

        result = manager._action_to_dict(action)

        assert result["action_id"] == "123"
        assert result["user_id"] == "user1"
        assert result["data"]["text"] == "Hello"

    def test_get_session(self) -> None:
        """Test getting session by ID."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        session = manager.create_session("user1", SessionType.EXPLORATION)

        result = manager.get_session(session.session_id)

        assert result == session
        assert manager.get_session("invalid_id") is None

    def test_get_user_sessions(self) -> None:
        """Test getting user sessions."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        manager.create_session("user1", SessionType.EXPLORATION)
        manager.create_session("user1", SessionType.PLAYLIST)
        session3 = manager.create_session("user1", SessionType.DISCOVERY)
        session3.active = False

        sessions = manager.get_user_sessions("user1")

        assert len(sessions) == 2  # Only active sessions
        assert session3 not in sessions

    def test_get_session_cursors(self) -> None:
        """Test getting session cursors."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        session = manager.create_session("user1", SessionType.EXPLORATION)
        manager.cursors[session.session_id] = {"user1": {"x": 100, "y": 200}}

        cursors = manager.get_session_cursors(session.session_id)

        assert cursors["user1"] == {"x": 100, "y": 200}
        assert manager.get_session_cursors("invalid_id") == {}


class TestSendCommentAndReact:
    """Test comment and react methods."""

    @pytest.mark.asyncio
    async def test_send_comment(self) -> None:
        """Test sending a comment."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.EXPLORATION)

        await manager.send_comment(session.session_id, "user1", "Great music!", {"artist": "Test"})

        assert len(session.actions) == 1
        assert session.actions[0].action_type == ActionType.COMMENT

    @pytest.mark.asyncio
    async def test_react(self) -> None:
        """Test reacting to an action."""
        mock_ws_manager = MagicMock()
        mock_ws_manager.broadcast = AsyncMock()

        manager = CollaborationManager(mock_ws_manager)
        session = manager.create_session("user1", SessionType.EXPLORATION)

        await manager.react(session.session_id, "user1", "👍", "action123")

        assert len(session.actions) == 1
        assert session.actions[0].action_type == ActionType.REACT


class TestGetStatistics:
    """Test getting collaboration statistics."""

    def test_get_statistics(self) -> None:
        """Test getting collaboration stats."""
        mock_ws_manager = MagicMock()
        manager = CollaborationManager(mock_ws_manager)

        session1 = manager.create_session("user1", SessionType.EXPLORATION)
        manager.create_session("user2", SessionType.PLAYLIST)
        session1.participants.add("user2")

        stats = manager.get_statistics()

        assert stats["total_sessions"] == 2
        assert stats["active_sessions"] == 2
        assert stats["total_participants"] == 3  # (user1+user2 in session1) + (user2 in session2)
        assert "sessions_by_type" in stats
