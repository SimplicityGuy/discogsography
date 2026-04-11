# Account Settings Page & 2FA Setup UI

**Issues:** #280, #281
**Date:** 2026-04-10

## Summary

Add a user account settings page to the explore frontend, accessible via the user dropdown menu. The page contains three stacked card sections: Profile (read-only info), Password (change password), and Security (2FA setup/management). Requires one new backend endpoint for password changes.

## Scope

### In scope
- Account settings pane with stacked card layout
- Profile card: email (read-only), account creation date, Discogs connection status
- Password card: change password form (current + new + confirm)
- Security card: full 2FA setup/disable lifecycle
- Backend `POST /api/auth/change-password` endpoint
- API client method for change-password
- Tests for the new endpoint

### Out of scope
- Display name / profile editing (no `display_name` column exists)
- Active sessions view
- Account deletion
- Regenerating recovery codes without disable/re-enable cycle

## Backend

### New Endpoint: `POST /api/auth/change-password`

**Location:** `api/routers/auth.py`

**Authentication:** Requires valid JWT bearer token (uses existing `get_current_user` dependency).

**Request body:**
```json
{
  "current_password": "string",
  "new_password": "string (min 8 characters)"
}
```

**Response (200):**
```json
{
  "message": "Password has been changed"
}
```

**Errors:**
- 401: Incorrect current password
- 400: New password too short (< 8 characters)
- 404: User not found

**Behavior:**
1. Fetch user from DB by `user_id` from JWT
2. Verify `current_password` against stored `hashed_password`
3. Hash `new_password` using existing `hash_password()` utility
4. Update `hashed_password`, `password_changed_at = now()`, `updated_at = now()` in users table
5. Set `password_changed:{user_id}` in Redis with TTL = `jwt_expire_minutes * 60` (revokes all existing sessions — same pattern as `reset-confirm`)
6. Return success

**Rate limit:** 5/minute (matching login rate limit).

**Request model:** Add `ChangePasswordRequest` to `api/models.py`:
```python
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
```

## Frontend

### Navigation

- Add "Account Settings" link to user dropdown menu in `index.html` (between Discogs actions and Logout)
- Clicking it activates `#settingsPane` and deactivates current pane
- Uses Material Symbols `settings` icon
- Track the previously active pane so a "Back" link can return to it

### Settings Pane (`#settingsPane`)

New pane div in `index.html`, same pattern as other panes (`<div class="pane" id="settingsPane">`).

**Layout:**
- Centered column: `max-w-2xl mx-auto` with vertical padding
- Page header: "Account Settings" title with back navigation
- Three stacked cards with consistent spacing

### Profile Card

**Content:**
- Section header with person icon
- Email address (read-only text, from `AuthManager._user.email`)
- Account creation date (formatted, from `/api/auth/me` `created_at` field)
- Discogs connection status badge (reuses existing `AuthManager._discogsStatus`)

**Data source:** `GET /api/auth/me` is already called during `AuthManager.init()`. The `created_at` field is already returned. Store it in AuthManager alongside existing user data.

### Password Card

**Content:**
- Section header with key/lock icon
- Three form fields: Current Password, New Password, Confirm New Password
- "Change Password" submit button (primary style)
- Success/error message area

**Validation (client-side):**
- All fields required
- New password minimum 8 characters
- New password and confirm must match
- Disable submit button while request is in-flight

**API call:** New `changePassword(token, currentPassword, newPassword)` method in `api-client.js`:
```javascript
async changePassword(token, currentPassword, newPassword) {
    const response = await fetch(`${this.baseUrl}/api/auth/change-password`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to change password');
    }
    return response.json();
}
```

**On success:**
- Show success message: "Password changed successfully"
- Clear all form fields
- After a brief delay, user's current session remains valid (the JWT they're using was issued before the password change, but the `password_changed_at` check uses `<=` so it will be invalidated — they'll need to log in again on next page load)

**On error:**
- Show error from API response (e.g., "Incorrect password")

### Security Card (2FA)

**State machine with 5 states:**

#### State: `disabled`
- Shown when `user.totp_enabled === false`
- Header: "Two-Factor Authentication" with shield icon
- Status badge: "Disabled" (red)
- Description: "Add an extra layer of security to your account"
- Button: "Enable 2FA" (primary) — transitions to `setup` state

#### State: `setup`
- Shown after clicking "Enable 2FA"
- Calls `POST /api/auth/2fa/setup` to get `secret`, `otpauth_uri`, `recovery_codes`
- Stores `recovery_codes` in memory for the `recovery` state
- Displays:
  - "Step 1: Scan QR Code" — QR code rendered client-side from `otpauth_uri`
  - Manual secret fallback: formatted `secret` in monospace (spaced every 4 chars)
  - "Step 2: Enter Verification Code" — 6 individual digit inputs (same pattern as existing login 2FA)
- Buttons: "Cancel" (returns to `disabled`), "Verify & Enable" (calls confirm)
- On "Verify & Enable": calls `POST /api/auth/2fa/confirm` with the 6-digit code
  - Success: transitions to `recovery` state
  - Error: shows error message, clears inputs

#### State: `recovery`
- Shown once after successful 2FA confirmation
- Warning banner: "Save these recovery codes now. You won't be able to see them again."
- Recovery codes in 2-column monospace grid (8 codes from setup response)
- "Copy Codes" button: copies all codes to clipboard (newline-separated)
- "I've Saved My Codes" button: transitions to `enabled` state, clears codes from memory

#### State: `enabled`
- Shown when `user.totp_enabled === true`
- Header: "Two-Factor Authentication" with shield icon
- Status badge: "Enabled" (green)
- Description: "Your account is protected with an authenticator app"
- Button: "Disable 2FA" (outline-danger) — transitions to `disable-confirm` state

#### State: `disable-confirm`
- Inline form (replaces the enabled state content, no modal)
- Two fields: TOTP Code (6-digit), Password
- Buttons: "Cancel" (returns to `enabled`), "Disable 2FA" (danger)
- On submit: calls `POST /api/auth/2fa/disable` with code + password
  - Success: updates `user.totp_enabled = false`, transitions to `disabled`
  - Error: shows error message

### QR Code Rendering

Use `qrcode-generator` (aka `qrcode.js` — ~3KB minified, no dependencies) loaded from CDN (`https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js`). The `otpauth_uri` from the setup endpoint is encoded into a QR code rendered as an inline SVG via `qr.createSvgTag()`. Fallback: the manual secret is always displayed below the QR code for users who can't scan.

### JavaScript Module: `settings.js`

New file `explore/static/js/settings.js`:

**Responsibilities:**
- Initialize settings pane content when activated
- Manage 2FA state machine transitions
- Handle form submissions (password change, 2FA setup/confirm/disable)
- Render QR code from otpauth URI
- Copy recovery codes to clipboard

**Integration points:**
- `AuthManager`: reads user data, `totp_enabled` status, token
- `ApiClient`: calls change-password, 2FA endpoints
- `app.js`: registers as a pane, handles activation/deactivation

**AuthManager changes:**
- Store `created_at` from `/api/auth/me` response in user data
- Add method to update `totp_enabled` locally after setup/disable (avoids extra API call)

### Pane Switching Integration (`app.js`)

- Register `settingsPane` in the pane switching system
- Settings pane has no nav tab — it's activated programmatically from the dropdown
- When settings is activated, track the previous pane for "Back" navigation
- When "Back" is clicked, restore the previous pane

## Testing

### Backend Tests (`tests/api/test_auth_router.py`)

New test cases for `POST /api/auth/change-password`:
- Happy path: correct current password, valid new password — returns 200
- Wrong current password — returns 401
- New password too short (< 8 chars) — returns 400
- Unauthenticated request — returns 401
- User not found (edge case) — returns 404
- Verify `password_changed_at` is updated after successful change
- Verify Redis `password_changed:{user_id}` key is set (session revocation)

### Frontend Tests

- Settings pane rendering and card visibility
- 2FA state transitions (disabled → setup → recovery → enabled → disable-confirm → disabled)
- Password form validation (matching passwords, minimum length)

## Files to Modify

| File | Change |
|------|--------|
| `api/routers/auth.py` | Add `change-password` endpoint |
| `api/models.py` | Add `ChangePasswordRequest` model |
| `explore/static/index.html` | Add settings pane HTML, dropdown link, QR library CDN |
| `explore/static/js/settings.js` | New file — settings pane controller |
| `explore/static/js/api-client.js` | Add `changePassword()` method |
| `explore/static/js/auth.js` | Store `created_at`, add `totp_enabled` update method |
| `explore/static/js/app.js` | Register settings pane, handle dropdown navigation |
| `explore/static/css/styles.css` | Settings card styles (if not fully covered by Tailwind) |
| `tests/api/test_auth_router.py` | Add change-password tests |
