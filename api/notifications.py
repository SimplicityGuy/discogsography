"""Notification channel abstraction for user-facing messages."""

import html
from typing import Protocol, runtime_checkable

import httpx
import structlog


logger = structlog.get_logger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


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


class ResendNotificationChannel:
    """Notification channel that sends emails via the Resend REST API.

    Plain `httpx` POST — no vendor SDK. Resend has click/open tracking off by
    default for every domain (no per-message field to disable), so the request
    body carries no tracking parameter and outbound links are never rewritten.
    """

    def __init__(self, api_key: str, sender_email: str, sender_name: str) -> None:
        self._api_key = api_key
        self._sender_email = sender_email
        self._sender_name = sender_name

    async def send_password_reset(self, email: str, reset_url: str) -> None:
        """Send a password reset email via Resend."""
        safe_url = html.escape(reset_url, quote=True)
        html_content = (
            "<html><body>"
            "<h2>Reset Your Password</h2>"
            "<p>You requested a password reset for your Discogsography account.</p>"
            f'<p><a href="{safe_url}" style="display:inline-block;padding:12px 24px;'
            "background-color:#3b82f6;color:#ffffff;text-decoration:none;"
            'border-radius:6px;font-weight:bold">Reset Password</a></p>'
            "<p>This link expires in 15 minutes. If you didn't request this, "
            "you can safely ignore this email.</p>"
            "<p>— Discogsography</p>"
            "</body></html>"
        )

        logger.debug("🔑 Sending password reset email", email=email)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    _RESEND_API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "from": f"{self._sender_name} <{self._sender_email}>",
                        "to": [email],
                        "subject": "Reset your Discogsography password",
                        "html": html_content,
                    },
                )
                response.raise_for_status()
            logger.info("📧 Password reset email sent", email=email)
        except Exception:
            logger.exception("❌ Failed to send password reset email", email=email)
