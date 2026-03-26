"""Notification channel abstraction for user-facing messages."""

from typing import Protocol, runtime_checkable

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

    async def send_password_reset(self, email: str, reset_url: str) -> None:
        """Log a password reset link."""
        logger.info("🔑 Password reset link generated", email=email, reset_url=reset_url)
