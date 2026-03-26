# Brevo Email Integration for Password Reset

**Date:** 2026-03-25
**Status:** Approved
**Builds on:** PR #210 (password reset & TOTP 2FA)

## Overview

Add a `BrevoNotificationChannel` implementation that sends password reset emails via the [Brevo transactional email API](https://developers.brevo.com/docs/api-clients/python). Auto-detected at startup: if `BREVO_API_KEY` is set, use Brevo; otherwise fall back to the existing `LogNotificationChannel`.

## Design

### `BrevoNotificationChannel` (`api/notifications.py`)

```python
class BrevoNotificationChannel:
    def __init__(self, api_key: str, sender_email: str, sender_name: str): ...
    async def send_password_reset(self, email: str, reset_url: str) -> None: ...
```

- Initializes `brevo.Brevo(api_key=api_key)` client
- `send_password_reset()` sends a transactional email with:
  - **Subject:** "Reset your Discogsography password"
  - **HTML body:** Simple, clean email with the reset link and 15-minute expiry notice
  - **Sender:** Configurable via `sender_email` / `sender_name`
  - **To:** The user's email address
- On Brevo API error: logs the error at ERROR level and re-raises the exception. The auth router's `reset_request` endpoint already handles notification failures gracefully (the reset token is still stored in Redis — the user just won't receive the email).
- Logs the reset URL at DEBUG level for delivery debugging.

### Config (`common/config.py` — `ApiConfig`)

| Field | Env Var | Default | Notes |
|-------|---------|---------|-------|
| `brevo_api_key` | `BREVO_API_KEY` | `None` | Read via `get_secret()` for Docker secrets support |
| `brevo_sender_email` | `BREVO_SENDER_EMAIL` | `"noreply@discogsography.com"` | Must be verified in Brevo |
| `brevo_sender_name` | `BREVO_SENDER_NAME` | `"Discogsography"` | Display name |

### Startup Auto-Detection (`api/api.py`)

In lifespan, replace `LogNotificationChannel()` with:

```python
if _config.brevo_api_key:
    notification_channel = BrevoNotificationChannel(
        api_key=_config.brevo_api_key,
        sender_email=_config.brevo_sender_email,
        sender_name=_config.brevo_sender_name,
    )
    logger.info("📧 Brevo email notifications enabled")
else:
    notification_channel = LogNotificationChannel()
    logger.info("📋 Using log-based notifications (no BREVO_API_KEY)")
```

### Dependency

`brevo-python>=1.0.0` added to `[project.optional-dependencies] api` in `pyproject.toml`.

### Testing (`tests/api/test_notifications.py`)

- Mock `brevo.Brevo` client, verify `send_transac_email` called with correct parameters
- Verify Brevo API error is logged and re-raised
- Verify `BrevoNotificationChannel` satisfies `NotificationChannel` protocol

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `brevo-python` dependency |
| `api/notifications.py` | Modify | Add `BrevoNotificationChannel` class |
| `common/config.py` | Modify | Add 3 Brevo config fields to `ApiConfig` |
| `api/api.py` | Modify | Auto-detect notification channel at startup |
| `tests/api/test_notifications.py` | Modify | Add Brevo channel tests |
