"""Tests for api/notifications.py — notification channel implementations."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


def _mock_async_client(mock_response: MagicMock) -> MagicMock:
    """Build a mock httpx.AsyncClient whose `.post()` returns `mock_response`."""
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


class TestResendNotificationChannel:
    """Tests for ResendNotificationChannel."""

    @pytest.mark.asyncio
    async def test_implements_notification_channel_protocol(self) -> None:
        from api.notifications import NotificationChannel, ResendNotificationChannel

        channel = ResendNotificationChannel(
            api_key="test-key",
            sender_email="noreply@test.com",
            sender_name="Test",
        )
        assert isinstance(channel, NotificationChannel)

    @pytest.mark.asyncio
    async def test_send_password_reset_calls_resend_api(self) -> None:
        from api.notifications import ResendNotificationChannel

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = _mock_async_client(mock_response)

        with patch("api.notifications.httpx.AsyncClient", return_value=mock_client):
            channel = ResendNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test Sender",
            )
            await channel.send_password_reset("user@example.com", "https://example.com/reset?token=abc")

        mock_client.post.assert_called_once()
        call_args, call_kwargs = mock_client.post.call_args
        assert call_args[0] == "https://api.resend.com/emails"
        assert call_kwargs["headers"] == {"Authorization": "Bearer test-key"}

        body = call_kwargs["json"]
        assert body["from"] == "Test Sender <noreply@test.com>"
        assert body["to"] == ["user@example.com"]
        assert body["subject"] == "Reset your Discogsography password"
        assert "reset?token=abc" in body["html"]
        # No tracking field is ever sent — Resend has click/open tracking off
        # by default for every domain, so there is nothing to configure or
        # disable per-message. Check every key, not just exact-name matches.
        assert not [key for key in body if "track" in key.lower()]
        assert set(body) == {"from", "to", "subject", "html"}

    @pytest.mark.asyncio
    async def test_outbound_link_delivered_byte_identical(self) -> None:
        """No click-tracking rewrite — the whole reason this channel exists.

        Assert the exact reset URL handed to `send_password_reset` appears
        byte-identical in the JSON body posted to the Resend API — not
        wrapped, shortened, or redirected through a tracking domain.
        """
        from api.notifications import ResendNotificationChannel

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = _mock_async_client(mock_response)

        reset_url = "https://discogsography.com/reset-password?token=abcDEF123-xyz_789"

        with patch("api.notifications.httpx.AsyncClient", return_value=mock_client):
            channel = ResendNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test Sender",
            )
            await channel.send_password_reset("user@example.com", reset_url)

        body = mock_client.post.call_args.kwargs["json"]
        # The link is HTML-escaped for safe embedding (quotes/entities), but the
        # URL itself — scheme, host, path, and every query parameter — must
        # survive unrewritten: no sendibt2.com-style redirect, no query params
        # appended or stripped, no shortened form.
        assert reset_url in body["html"]
        assert "sendibt2.com" not in body["html"]
        assert body["html"].count(reset_url) == 1

    @pytest.mark.asyncio
    async def test_multi_param_link_round_trips_through_html_escaping(self) -> None:
        """A URL with multiple query params survives HTML-escaping intact.

        `&` is escaped to `&amp;` for valid HTML — that is correct and mail
        clients unescape it. This asserts the escaping is the *only* thing
        that happens to the URL: unescape the rendered href and the original
        must come back exactly.
        """
        import html as html_module

        from api.notifications import ResendNotificationChannel

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = _mock_async_client(mock_response)

        reset_url = "https://discogsography.com/reset-password?token=abc123&source=email&ts=1234567890"

        with patch("api.notifications.httpx.AsyncClient", return_value=mock_client):
            channel = ResendNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test Sender",
            )
            await channel.send_password_reset("user@example.com", reset_url)

        rendered = mock_client.post.call_args.kwargs["json"]["html"]
        href = rendered.split('<a href="', 1)[1].split('"', 1)[0]
        assert html_module.unescape(href) == reset_url

    @pytest.mark.asyncio
    async def test_send_password_reset_swallows_api_error(self) -> None:
        from api.notifications import ResendNotificationChannel

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("API error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("api.notifications.httpx.AsyncClient", return_value=mock_client):
            channel = ResendNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test",
            )

            # Should not raise — errors are logged but swallowed to avoid
            # breaking the password reset UX when email delivery fails
            await channel.send_password_reset("user@example.com", "https://example.com/reset")

    @pytest.mark.asyncio
    async def test_send_password_reset_swallows_non_2xx_response(self) -> None:
        from api.notifications import ResendNotificationChannel

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("bad request", request=MagicMock(), response=MagicMock()))
        mock_client = _mock_async_client(mock_response)

        with patch("api.notifications.httpx.AsyncClient", return_value=mock_client):
            channel = ResendNotificationChannel(
                api_key="test-key",
                sender_email="noreply@test.com",
                sender_name="Test",
            )

            await channel.send_password_reset("user@example.com", "https://example.com/reset")
