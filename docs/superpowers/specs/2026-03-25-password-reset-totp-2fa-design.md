# Password Reset & TOTP Two-Factor Authentication

**Issue:** #190
**Date:** 2026-03-25
**Status:** Approved
**PR structure:** Single monolithic PR covering all phases

## Overview

Add self-service password reset and optional TOTP-based two-factor authentication to the Discogsography platform. Includes auth router extraction from `api/api.py` to follow existing router patterns, HKDF-based encryption key management, and full frontend support in the Explore UI.

## Design Decisions

| Decision                 | Choice                 | Rationale                                                                                      |
| ------------------------ | ---------------------- | ---------------------------------------------------------------------------------------------- |
| PR structure             | Single PR              | All three phases in one monolithic PR                                                          |
| Notification abstraction | Thin protocol          | `NotificationChannel` protocol with `LogNotificationChannel` — ready for email follow-on       |
| Encryption keys          | HKDF from master key   | `ENCRYPTION_MASTER_KEY` → derive per-purpose Fernet keys. Clean cutover with migration script. |
| Session revocation       | Redis-cached timestamp | `password_changed:<user_id>` in Redis, checked alongside existing jti blacklist                |
| Recovery code hashing    | SHA-256 (unsalted)     | Codes are 128+ bits of entropy — no dictionary attack risk. Industry standard.                 |
| QR code rendering        | qrcode.js via CDN      | ~4KB, no dependencies, fits vanilla JS pattern                                                 |
| Architecture             | Auth router extraction | Move existing auth endpoints to `api/routers/auth.py`, matching project convention             |

## Section 1: Encryption Key Migration & HKDF Derivation

### Current State

- `OAUTH_ENCRYPTION_KEY` env var holds a Fernet key
- Used in `api/auth.py` via `encrypt_oauth_token()` / `decrypt_oauth_token()`
- `ApiConfig` in `common/config.py` reads it as `oauth_encryption_key`

### New Design

**New env var:** `ENCRYPTION_MASTER_KEY` — a 32-byte base64-encoded secret.

**Key derivation** (in `api/auth.py`):

```
HKDF-SHA256(master_key, info=b"oauth-tokens") → Fernet key for OAuth
HKDF-SHA256(master_key, info=b"totp-secrets")  → Fernet key for TOTP
```

Uses `cryptography.hazmat.primitives.kdf.hkdf.HKDF` — already a transitive dependency via `cryptography`.

**Config changes** (`common/config.py`):

- Add `encryption_master_key: str | None` field to `ApiConfig`
- Remove `oauth_encryption_key` field
- Add derived properties: `oauth_encryption_key` and `totp_encryption_key` computed from master key via HKDF
- Startup validation: if `ENCRYPTION_MASTER_KEY` not set, log a warning and disable TOTP (OAuth falls back to unencrypted as it does today)

**Migration script** (`scripts/migrate-encryption-key.sh`):

Usage: `./scripts/migrate-encryption-key.sh <container> <pg_password> <old_oauth_key> <new_master_key>`

Follows the same pattern as `reset-password.sh` — runs Python inside the Docker container to access the database.

1. Takes container name, PostgreSQL password, old `OAUTH_ENCRYPTION_KEY`, and new `ENCRYPTION_MASTER_KEY` as args
1. Derives the new OAuth Fernet key from master key via HKDF
1. Re-encrypts all `oauth_tokens.access_token` and `oauth_tokens.access_secret` values
1. Verifies round-trip decryption for each token
1. Prints instructions for updating `.env` file

**`scripts/reset-password.sh` update:** Add `password_changed_at = NOW()` to the UPDATE statement. Also write `password_changed:<user_id>` to Redis.

## Section 2: Password Reset Flow

### Database Change

Add `password_changed_at TIMESTAMPTZ` column to `users` table in `schema-init/postgres_schema.py`. `DEFAULT NULL` — existing users haven't changed passwords, so their tokens remain valid (no `iat` check needed when `password_changed_at` is NULL).

### Redis Keys

| Key                          | Value                                | TTL                           |
| ---------------------------- | ------------------------------------ | ----------------------------- |
| `reset:<token>`              | JSON: `{user_id, email, created_at}` | 15 min                        |
| `password_changed:<user_id>` | Unix timestamp                       | Equal to `jwt_expire_minutes` |

### Endpoints (in `api/routers/auth.py`)

**`POST /api/auth/reset-request`** — rate limited 3/min

- Accepts `{email}`
- Looks up user by email. If not found, returns same 200 response (anti-enumeration)
- Generates `secrets.token_urlsafe(32)`, stores in Redis
- Logs reset link: `{base_url}/reset?token={token}`
- Sends via `NotificationChannel` (log implementation for now)
- Returns `{"message": "If an account exists, a reset link has been sent"}`

**`POST /api/auth/reset-confirm`** — rate limited 5/min

- Accepts `{token, new_password}`
- Fetches `reset:<token>` from Redis. If missing/expired → 400
- Validates password (min 8 chars, reuse Pydantic model)
- Updates `hashed_password` and `password_changed_at` in PostgreSQL
- Writes `password_changed:<user_id>` to Redis
- Deletes `reset:<token>` from Redis (single-use)
- Returns `{"message": "Password has been reset"}`

### Token Validation Change (in `_get_current_user`)

After the existing jti blacklist check, add:

```python
if user_id and _redis:
    pw_changed = await _redis.get(f"password_changed:{user_id}")
    if pw_changed and iat < int(pw_changed):
        raise HTTPException(status_code=401, detail="Token has been revoked")
```

### Notification Channel (`api/notifications.py`)

```python
class NotificationChannel(Protocol):
    async def send_password_reset(self, email: str, reset_url: str) -> None: ...

class LogNotificationChannel:
    async def send_password_reset(self, email: str, reset_url: str) -> None:
        logger.info("🔑 Password reset link", email=email, url=reset_url)
```

Injected into the auth router at startup.

## Section 3: TOTP Two-Factor Authentication

### Database Changes (added to `users` table)

| Column                 | Type          | Default | Notes                         |
| ---------------------- | ------------- | ------- | ----------------------------- |
| `totp_secret`          | `VARCHAR`     | `NULL`  | Fernet-encrypted TOTP secret  |
| `totp_enabled`         | `BOOLEAN`     | `FALSE` | Whether 2FA is active         |
| `totp_recovery_codes`  | `JSONB`       | `NULL`  | Array of SHA-256 hashed codes |
| `totp_failed_attempts` | `INTEGER`     | `0`     | Brute force counter           |
| `totp_locked_until`    | `TIMESTAMPTZ` | `NULL`  | Lockout expiry                |

### Redis Keys

| Key                         | Value                    | TTL   |
| --------------------------- | ------------------------ | ----- |
| `2fa_challenge:<token_jti>` | JSON: `{user_id, email}` | 5 min |

### Auth Utility Functions (in `api/auth.py`)

- `generate_totp_secret() → str` — `pyotp.random_base32()`
- `encrypt_totp_secret(secret, key) → str` — Fernet encrypt with TOTP-derived key
- `decrypt_totp_secret(encrypted, key) → str` — Fernet decrypt
- `verify_totp_code(secret, code) → bool` — `pyotp.TOTP(secret).verify(code, valid_window=1)` (±1 period = 90s window)
- `generate_recovery_codes() → tuple[list[str], list[str]]` — returns `(plaintext_codes, sha256_hashes)`. 8 codes, `secrets.token_urlsafe(12)` each.
- `hash_recovery_code(code) → str` — `hashlib.sha256(code.encode()).hexdigest()`
- `create_challenge_token(user_id, email) → str` — short-lived JWT with `type: "2fa_challenge"` claim, 5 min TTL

### Endpoints (in `api/routers/auth.py`)

**`POST /api/auth/2fa/setup`** — authenticated

- Generates TOTP secret, encrypts and stores (does NOT set `totp_enabled = TRUE` yet)
- Returns `{secret, otpauth_uri, recovery_codes}`
- `otpauth_uri` format: `otpauth://totp/Discogsography:{email}?secret={base32}&issuer=Discogsography`

**`POST /api/auth/2fa/confirm`** — authenticated, accepts `{code}`

- Decrypts stored secret, verifies code
- If valid: sets `totp_enabled = TRUE`, hashes and stores recovery codes
- If invalid: returns 400

**Modified `POST /api/auth/login`**

- After password validation, check `totp_enabled`
- If `TRUE`: return `{requires_2fa: true, challenge_token: "..."}` with HTTP 200
- If `FALSE`: return access token as today

**`POST /api/auth/2fa/verify`** — accepts `{challenge_token, code}`

- Validates challenge token (type, expiry, jti in Redis)
- Checks lockout (`totp_locked_until`)
- Verifies TOTP code against decrypted secret
- On success: resets failed attempts, returns full access JWT
- On failure: increments `totp_failed_attempts`. At 5 failures in 15 min → set `totp_locked_until`

**`POST /api/auth/2fa/recovery`** — accepts `{challenge_token, code}`

- Same challenge validation as verify
- SHA-256 hashes submitted code, compares against stored hashes
- On match: removes used code from array, returns full access JWT
- If last code used: warn in response that no recovery codes remain

**`POST /api/auth/2fa/disable`** — authenticated, accepts `{code, password}`

- Requires both current TOTP code AND password
- Clears `totp_secret`, `totp_enabled`, `totp_recovery_codes`, resets attempts

## Section 4: Auth Router Extraction

### What moves from `api/api.py` to `api/routers/auth.py`

**Existing endpoints that move:**

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

**What stays in `api/api.py`:**

- `_create_access_token()` — used by OAuth verify endpoint too
- `_get_current_user()` — dependency used by all routers
- `OAuthVerifyRequest` and all OAuth endpoints (`/api/oauth/*`)
- Lifespan, health, search, middleware setup

**Router pattern** (matching existing routers):

```python
# api/routers/auth.py
router = APIRouter(prefix="/api/auth", tags=["auth"])

def setup(app, pool, redis, config, get_current_user, create_access_token, notification_channel):
    # store references, register routes
```

The `setup()` function receives dependencies from `api/api.py` during lifespan.

### New Pydantic Models (in `api/models.py`)

- `ResetRequestModel` — `{email}`
- `ResetConfirmModel` — `{token, new_password}` (password min 8)
- `TwoFactorSetupResponse` — `{secret, otpauth_uri, recovery_codes}`
- `TwoFactorCodeModel` — `{code}` (6-digit string)
- `TwoFactorVerifyModel` — `{challenge_token, code}`
- `TwoFactorRecoveryModel` — `{challenge_token, code}`
- `TwoFactorDisableModel` — `{code, password}`
- `ChallengeResponse` — `{requires_2fa, challenge_token}`

## Section 5: Frontend Changes

All changes in the Explore frontend (`explore/static/`).

### Password Reset UI (`index.html` + `app.js`)

- **"Forgot password?" link** — right-aligned below the password field on the login tab
- **Reset request form** — replaces login tab content: email input + "Send Reset Link" button + "Back to login" link
- **Success state** — "If an account exists, a reset link has been sent" message
- **New password form** — `app.js` checks `window.location.search` on page load; if `reset_token` param is present, auto-opens the auth modal with the new password form (new password + confirm password fields). Clears the query param from the URL after consuming it.
- **Success redirect** — after reset, show success message and return to login tab. User must log in again (with 2FA if enabled).

### 2FA Login UI (`index.html` + `auth.js`)

- **2FA code entry** — replaces login form when `requires_2fa: true` returned. Six individual digit inputs with auto-advance focus.
- **Recovery code link** — "Use a recovery code instead" below the verify button
- **Recovery code form** — single text input for the recovery code string
- **Back navigation** — "Back to code entry" from recovery form

### 2FA Setup UI (`index.html` + `app.js`)

- **Account settings section** — new "Two-Factor Authentication" panel in user settings area
- **QR code display** — rendered by `qrcode.js` from CDN, with manual secret shown below
- **Confirmation input** — 6-digit code to verify setup
- **Recovery codes display** — grid of 8 codes with "Download Codes" button (text file download)
- **Disable 2FA** — requires TOTP code + password confirmation

### API Client (`api-client.js`)

New methods:

- `resetRequest(email)`
- `resetConfirm(token, newPassword)`
- `twoFactorSetup(token)`
- `twoFactorConfirm(token, code)`
- `twoFactorVerify(challengeToken, code)`
- `twoFactorRecovery(challengeToken, code)`
- `twoFactorDisable(token, code, password)`

### New JS Dependency

`qrcode.js` via CDN `<script>` tag in `index.html`.

## Section 6: Testing Strategy

### Test Files

**`tests/api/test_auth_router.py`** — new file:

- Existing register/login/logout/me tests move here from `tests/api/test_api.py`
- Password reset: happy path, expired token, invalid token, rate limiting, anti-enumeration
- 2FA setup: generate secret, confirm with valid code, reject invalid code
- 2FA login: challenge token flow, verify with valid code, reject invalid, lockout after 5 failures
- 2FA recovery: use code, code consumed (single-use), last code warning
- 2FA disable: requires both code + password, rejects wrong password

**`tests/api/test_auth.py`** — extended with:

- HKDF key derivation (different info strings produce different keys)
- TOTP utility functions (generate, encrypt/decrypt, verify)
- Recovery code hashing
- Challenge token creation/validation

**`tests/api/test_notifications.py`** — minimal:

- `LogNotificationChannel.send_password_reset` logs correctly

**`tests/api/test_encryption_migration.py`** — migration script test:

- Re-encrypt with new derived key, verify old tokens still decrypt

### Perf Tests (`tests/perftest/config.yaml`)

New entries for: `POST /api/auth/reset-request`, `POST /api/auth/reset-confirm`, `POST /api/auth/2fa/setup`, `POST /api/auth/2fa/verify`.

### Coverage Target

80%+ for all new auth code.

## Section 7: File Change Summary

| File                                | Action | Description                                                                                          |
| ----------------------------------- | ------ | ---------------------------------------------------------------------------------------------------- |
| `api/auth.py`                       | Modify | Add HKDF derivation, TOTP utilities, challenge token functions                                       |
| `api/api.py`                        | Modify | Remove auth endpoints, add auth router setup, update `_get_current_user` with password_changed check |
| `api/routers/auth.py`               | Create | All auth endpoints (existing + reset + 2FA)                                                          |
| `api/notifications.py`              | Create | NotificationChannel protocol + LogNotificationChannel                                                |
| `api/models.py`                     | Modify | Add reset + 2FA Pydantic models                                                                      |
| `common/config.py`                  | Modify | Replace `oauth_encryption_key` with `encryption_master_key` + derived properties                     |
| `schema-init/postgres_schema.py`    | Modify | Add `password_changed_at` + TOTP columns to users table                                              |
| `explore/static/index.html`         | Modify | Add forgot password link, reset forms, 2FA code entry, 2FA setup UI                                  |
| `explore/static/js/api-client.js`   | Modify | Add reset + 2FA API methods                                                                          |
| `explore/static/js/auth.js`         | Modify | Handle 2FA challenge state in login flow                                                             |
| `scripts/reset-password.sh`         | Modify | Add `password_changed_at`, Redis write                                                               |
| `scripts/migrate-encryption-key.sh` | Create | One-time OAuth token re-encryption                                                                   |
| `pyproject.toml`                    | Modify | Add `pyotp` dependency                                                                               |
| `tests/api/test_auth_router.py`     | Create | All auth endpoint tests                                                                              |
| `tests/api/test_notifications.py`   | Create | Notification channel tests                                                                           |
| `tests/perftest/config.yaml`        | Modify | Add new endpoint entries                                                                             |

## Security Considerations

- **Anti-enumeration:** Same response for known/unknown emails on reset-request and register
- **Rate limiting:** All new endpoints rate-limited (3/min reset-request, 5/min others)
- **Brute force protection:** 2FA lockout after 5 failed attempts in 15 minutes
- **Token entropy:** Reset tokens use `secrets.token_urlsafe(32)` (256 bits)
- **Single-use tokens:** Reset tokens deleted from Redis after use
- **Session revocation:** Password change invalidates all existing JWTs via Redis timestamp
- **2FA survives password reset:** Resetting a password does not disable 2FA. User must provide TOTP code on next login.
- **TOTP secrets encrypted at rest:** Fernet encryption with HKDF-derived key
- **Recovery codes:** SHA-256 hashed, single-use, 128+ bits of entropy each
- **Challenge tokens:** Short-lived (5 min), typed (`2fa_challenge`), not usable as access tokens
- **Constant-time comparison:** Existing `hmac.compare_digest` pattern maintained
