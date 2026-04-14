"""Tests for api/notifications.py — notification channel implementations."""

from unittest.mock import MagicMock, patch

import pytest


class TestLogNotificationChannel:
    """Tests for LogNotificationChannel."""

    @pytest.mark.asyncio
    async def test_send_password_reset_does_not_raise(self) -> None:
        from api.notifications import LogNotificationChannel

        channel = LogNotificationChannel()
        await channel.send_password_reset("user@example.com", "https://example.com/reset?token=abc123")

    @pytest.mark.asyncio
    async def test_implements_notification_channel_protocol(self) -> None:
        from api.notifications import LogNotificationChannel, NotificationChannel

        channel = LogNotificationChannel()
        assert isinstance(channel, NotificationChannel)


class TestBrevoNotificationChannel:
    """Tests for BrevoNotificationChannel."""

    @pytest.mark.asyncio
    async def test_implements_notification_channel_protocol(self) -> None:
        from api.notifications import BrevoNotificationChannel, NotificationChannel

        with patch("api.notifications.Brevo"):
            channel = BrevoNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test",
            )
        assert isinstance(channel, NotificationChannel)

    @pytest.mark.asyncio
    async def test_send_password_reset_calls_brevo_api(self) -> None:
        from api.notifications import BrevoNotificationChannel

        mock_client = MagicMock()
        with patch("api.notifications.Brevo", return_value=mock_client):
            channel = BrevoNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test Sender",
            )

        await channel.send_password_reset("user@example.com", "https://example.com/reset?token=abc")

        mock_client.transactional_emails.send_transac_email.assert_called_once()
        call_kwargs = mock_client.transactional_emails.send_transac_email.call_args
        assert call_kwargs.kwargs["subject"] == "Reset your Discogsography password"
        assert "reset?token=abc" in call_kwargs.kwargs["html_content"]
        assert call_kwargs.kwargs["sender"].email == "noreply@test.com"
        assert call_kwargs.kwargs["sender"].name == "Test Sender"
        assert call_kwargs.kwargs["to"][0].email == "user@example.com"
        # Brevo's v3 transactional API rejects standard email headers (the SDK's
        # `headers` field only accepts `sender.ip`, `X-Mailin-custom`, etc.), so
        # `X-Mailin-Track*` cannot disable click tracking per-message — that
        # must be turned off in the Brevo dashboard. We assert no headers field
        # is sent so dead/misleading code can't reappear.
        assert "headers" not in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_send_password_reset_swallows_api_error(self) -> None:
        from api.notifications import BrevoNotificationChannel

        mock_client = MagicMock()
        mock_client.transactional_emails.send_transac_email.side_effect = RuntimeError("API error")

        with patch("api.notifications.Brevo", return_value=mock_client):
            channel = BrevoNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test",
            )

        # Should not raise — errors are logged but swallowed to avoid
        # breaking the password reset UX when email delivery fails
        await channel.send_password_reset("user@example.com", "https://example.com/reset")
