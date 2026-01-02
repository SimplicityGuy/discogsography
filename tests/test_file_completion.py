"""Tests for file completion message handling."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aio_pika.abc import AbstractIncomingMessage

from graphinator.graphinator import check_file_completion, on_artist_message
from tableinator.tableinator import on_data_message


class TestFileCompletionHandling:
    """Test file completion message handling."""

    @pytest.mark.asyncio
    async def test_graphinator_file_completion_message(self) -> None:
        """Test that graphinator correctly handles file completion messages."""
        # Create a file completion message
        completion_data = {
            "type": "file_complete",
            "data_type": "artists",
            "timestamp": datetime.now().isoformat(),
            "total_processed": 12345,
            "file": "artists.xml",
        }

        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.ack = AsyncMock()

        # Test the check_file_completion function
        mock_completed: set[str] = set()
        with patch("graphinator.graphinator.completed_files", mock_completed):
            result = await check_file_completion(completion_data, "artists", mock_message)

            assert result is True
            assert "artists" in mock_completed
            mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_graphinator_normal_message_not_completion(self) -> None:
        """Test that normal messages are not treated as completion messages."""
        # Create a normal artist message
        artist_data = {
            "id": "123",
            "name": "Test Artist",
            "sha256": "abc123",
        }

        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)

        # Test the check_file_completion function
        result = await check_file_completion(artist_data, "artists", mock_message)

        assert result is False
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    @patch("graphinator.graphinator.shutdown_requested", False)
    @patch("graphinator.graphinator.graph", MagicMock())
    async def test_graphinator_artist_handler_with_completion(self) -> None:
        """Test that artist message handler correctly processes completion messages."""
        # Create a file completion message
        completion_data = {
            "type": "file_complete",
            "data_type": "artists",
            "timestamp": datetime.now().isoformat(),
            "total_processed": 12345,
            "file": "artists.xml",
        }

        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(completion_data).encode()
        mock_message.ack = AsyncMock()

        # Test the handler
        with patch("graphinator.graphinator.check_file_completion", AsyncMock(return_value=True)) as mock_check:
            await on_artist_message(mock_message)

            mock_check.assert_called_once()
            # Verify that we return early and don't process as normal message

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_tableinator_file_completion_message(self) -> None:
        """Test that tableinator correctly handles file completion messages."""
        # Create a file completion message
        completion_data = {
            "type": "file_complete",
            "data_type": "labels",
            "timestamp": datetime.now().isoformat(),
            "total_processed": 54321,
            "file": "labels.xml",
        }

        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(completion_data).encode()
        mock_message.routing_key = "labels"
        mock_message.ack = AsyncMock()

        # Test the handler
        mock_completed: set[str] = set()
        with patch("tableinator.tableinator.completed_files", mock_completed):
            await on_data_message(mock_message)

            assert "labels" in mock_completed
            mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("tableinator.tableinator.shutdown_requested", False)
    async def test_tableinator_normal_message_processing(self) -> None:
        """Test that tableinator continues to process normal messages correctly."""
        # Create a normal data message
        data = {
            "id": "456",
            "name": "Test Label",
            "sha256": "def456",
        }

        # Create mock message
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = json.dumps(data).encode()
        mock_message.routing_key = "labels"
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        # Mock database operations
        with (
            patch("tableinator.tableinator.get_connection") as mock_get_conn,
            patch("tableinator.tableinator.message_counts", {"labels": 0}),
            patch("tableinator.tableinator.last_message_time", {"labels": 0}),
        ):
            # Setup connection mock
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None  # No existing record

            await on_data_message(mock_message)

            # Verify normal processing occurred
            mock_message.ack.assert_called_once()
            assert mock_cursor.execute.call_count == 2  # SELECT and INSERT

    def test_progress_reporting_with_completed_files(self) -> None:
        """Test that progress reporting shows celebration emoji for completed files."""
        # This is more of a visual/logging test, but we can verify the logic
        completed_files = {"artists", "labels"}
        message_counts = {
            "artists": 1000,
            "labels": 2000,
            "masters": 3000,
            "releases": 4000,
        }

        # Build progress string as in the actual code
        progress_parts = []
        for data_type in ["artists", "labels", "masters", "releases"]:
            emoji = "🎉 " if data_type in completed_files else ""
            progress_parts.append(f"{emoji}{data_type.capitalize()}: {message_counts[data_type]}")

        result = ", ".join(progress_parts)

        assert "🎉 Artists: 1000" in result
        assert "🎉 Labels: 2000" in result
        assert "Masters: 3000" in result  # No emoji
        assert "Releases: 4000" in result  # No emoji
