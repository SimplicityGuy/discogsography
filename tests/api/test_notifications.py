"""Tests for api/notifications.py — notification channel implementations."""

import pytest


class TestLogNotificationChannel:
    """Tests for LogNotificationChannel."""

    @pytest.mark.asyncio
    async def test_send_password_reset_does_not_raise(self) -> None:
        from api.notifications import LogNotificationChannel

        channel = LogNotificationChannel()
        # Should complete without raising
        await channel.send_password_reset("user@example.com", "https://example.com/reset?token=abc123")

    @pytest.mark.asyncio
    async def test_implements_notification_channel_protocol(self) -> None:
        from api.notifications import LogNotificationChannel, NotificationChannel

        channel = LogNotificationChannel()
        # Verify it satisfies the protocol
        assert isinstance(channel, NotificationChannel)
