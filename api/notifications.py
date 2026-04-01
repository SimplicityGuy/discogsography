"""Notification channel abstraction for user-facing messages."""

import asyncio
from typing import Protocol, runtime_checkable

from brevo import Brevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)
import structlog


logger = structlog.get_logger(__name__)


@runtime_checkable
class NotificationChannel(Protocol):
    """Protocol for sending notifications to users."""

    async def send_password_reset(self, email: str, reset_url: str) -> None:
        """Send a password reset link to the user."""
        ...  # pragma: no cover


class LogNotificationChannel:
    """Notification channel that logs messages (development/MVP use)."""

    async def send_password_reset(self, email: str, reset_url: str) -> None:  # noqa: ARG002  # reset_url unused in log channel
        """Log a password reset link (URL intentionally not logged for security)."""
        logger.info("🔑 Password reset link generated", email=email)


class BrevoNotificationChannel:
    """Notification channel that sends emails via Brevo transactional API."""

    def __init__(self, api_key: str, sender_email: str, sender_name: str) -> None:
        self._client = Brevo(api_key=api_key)
        self._sender_email = sender_email
        self._sender_name = sender_name

    async def send_password_reset(self, email: str, reset_url: str) -> None:
        """Send a password reset email via Brevo."""
        html_content = (
            "<html><body>"
            "<h2>Reset Your Password</h2>"
            "<p>You requested a password reset for your Discogsography account.</p>"
            f'<p><a href="{reset_url}" style="display:inline-block;padding:12px 24px;'
            "background-color:#3b82f6;color:#ffffff;text-decoration:none;"
            'border-radius:6px;font-weight:bold">Reset Password</a></p>'
            "<p>This link expires in 15 minutes. If you didn't request this, "
            "you can safely ignore this email.</p>"
            "<p>— Discogsography</p>"
            "</body></html>"
        )

        logger.debug("🔑 Sending password reset email", email=email)
        try:
            await asyncio.to_thread(
                self._client.transactional_emails.send_transac_email,
                subject="Reset your Discogsography password",
                html_content=html_content,
                sender=SendTransacEmailRequestSender(
                    name=self._sender_name,
                    email=self._sender_email,
                ),
                to=[SendTransacEmailRequestToItem(email=email)],
            )
            logger.info("📧 Password reset email sent", email=email)
        except Exception:
            logger.exception("❌ Failed to send password reset email", email=email)
