# Account Settings & 2FA UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user account settings page with profile info, password change, and 2FA setup/management to the explore frontend.

**Architecture:** New `POST /api/auth/change-password` backend endpoint in the existing auth router. New `#settingsPane` in explore frontend accessed via user dropdown menu. New `settings.js` module manages the settings UI including a 5-state 2FA state machine. All other frontend files receive minor additions (dropdown link, API client method, AuthManager changes, pane registration).

**Tech Stack:** Python/FastAPI (backend), vanilla JS/HTML/CSS with Tailwind + Alpine.js (frontend), qrcodejs CDN (already loaded) for QR rendering, pytest with mocks (backend tests), Vitest (frontend tests).

**XSS Safety:** All `innerHTML` usage contains only hardcoded template strings. Any dynamic user-provided data (email, Discogs username) is set via `textContent`. TOTP secrets and recovery codes are alphanumeric-only server outputs.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `api/models.py` | Modify | Add `ChangePasswordRequest` model |
| `api/routers/auth.py` | Modify | Add `POST /api/auth/change-password` endpoint |
| `tests/api/test_auth_router.py` | Modify | Add change-password tests |
| `explore/static/js/api-client.js` | Modify | Add `changePassword()` method |
| `explore/static/js/auth.js` | Modify | Store `created_at`, add `updateTotpEnabled()` |
| `explore/static/index.html` | Modify | Add settings pane HTML, dropdown link, script tag |
| `explore/static/js/settings.js` | Create | Settings pane controller with 2FA state machine |
| `explore/static/js/app.js` | Modify | Register settings pane, handle dropdown navigation |
| `explore/static/css/styles.css` | Modify | Settings card styles |

---

### Task 1: Add ChangePasswordRequest Model

**Files:**
- Modify: `api/models.py:395-399` (after `TwoFactorDisableModel`)

- [ ] **Step 1: Add the model**

In `api/models.py`, add after the `TwoFactorDisableModel` class (after line 399):

```python
class ChangePasswordRequest(BaseModel):
    """Request to change password while authenticated."""

    current_password: str
    new_password: str = Field(min_length=8, description="New password (minimum 8 characters)")
```

- [ ] **Step 2: Verify no syntax errors**

Run: `uv run python -c "from api.models import ChangePasswordRequest; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/models.py
git commit -m "feat: add ChangePasswordRequest model for password change endpoint"
```

---

### Task 2: Add Change Password Endpoint (TDD)

**Files:**
- Modify: `api/routers/auth.py` (add endpoint after `reset_confirm`, around line 328)
- Modify: `tests/api/test_auth_router.py` (add test class)

- [ ] **Step 1: Write failing tests**

Add to the end of `tests/api/test_auth_router.py`:

```python
class TestChangePassword:
    """Tests for POST /api/auth/change-password."""

    def test_change_password_success(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        mock_redis: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        """Happy path: correct current password, valid new password."""
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        response = test_client.post(
            "/api/auth/change-password",
            json={"current_password": "testpassword", "new_password": "newpassword123"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Password has been changed"
        # Verify DB update was called
        assert mock_cur.execute.call_count >= 2  # SELECT + UPDATE
        # Verify Redis session revocation key was set
        mock_redis.setex.assert_called()
        redis_call_args = mock_redis.setex.call_args
        assert redis_call_args[0][0].startswith("password_changed:")

    def test_change_password_wrong_current(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        """Wrong current password returns 401."""
        mock_cur.fetchone = AsyncMock(return_value=make_sample_user_row())
        response = test_client.post(
            "/api/auth/change-password",
            json={"current_password": "wrongpassword", "new_password": "newpassword123"},
            headers=auth_headers,
        )
        assert response.status_code == 401
        assert "Incorrect" in response.json()["detail"]

    def test_change_password_too_short(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """New password shorter than 8 characters returns 422 (validation error)."""
        response = test_client.post(
            "/api/auth/change-password",
            json={"current_password": "testpassword", "new_password": "short"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_change_password_unauthenticated(
        self,
        test_client: TestClient,
    ) -> None:
        """No auth token returns 403."""
        response = test_client.post(
            "/api/auth/change-password",
            json={"current_password": "testpassword", "new_password": "newpassword123"},
        )
        assert response.status_code == 403

    def test_change_password_user_not_found(
        self,
        test_client: TestClient,
        mock_cur: AsyncMock,
        auth_headers: dict[str, str],
    ) -> None:
        """User not in DB returns 404."""
        mock_cur.fetchone = AsyncMock(return_value=None)
        response = test_client.post(
            "/api/auth/change-password",
            json={"current_password": "testpassword", "new_password": "newpassword123"},
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_auth_router.py::TestChangePassword -v`
Expected: All 5 tests FAIL (404 — endpoint doesn't exist yet)

- [ ] **Step 3: Implement the endpoint**

In `api/routers/auth.py`:

1. Add `ChangePasswordRequest` to the imports from `api.models`:

```python
from api.models import (
    ChangePasswordRequest,
    LoginRequest,
    # ... rest unchanged
)
```

2. Add the endpoint after the `reset_confirm` function (after line 328, before the 2FA section):

```python
@router.post("/api/auth/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,  # noqa: ARG001
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    body: ChangePasswordRequest,
) -> JSONResponse:
    """Change password for the currently authenticated user."""
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    user_id = current_user.get("sub")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT hashed_password FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not _verify_password(body.current_password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password")

    hashed_password = _hash_password(body.new_password)
    now_ts = int(datetime.now(UTC).timestamp())

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET hashed_password = %s, password_changed_at = NOW(), updated_at = NOW() WHERE id = %s::uuid",
            (hashed_password, user_id),
        )

    # Invalidate all existing sessions (same pattern as reset-confirm)
    await _redis.setex(f"password_changed:{user_id}", _config.jwt_expire_minutes * 60, str(now_ts))

    logger.info("✅ Password changed", user_id=user_id)
    return JSONResponse(content={"message": "Password has been changed"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_auth_router.py::TestChangePassword -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full auth router test suite**

Run: `uv run pytest tests/api/test_auth_router.py -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 6: Run linting and type checking**

Run: `uv run ruff check api/routers/auth.py api/models.py && uv run mypy api/routers/auth.py api/models.py`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add api/routers/auth.py api/models.py tests/api/test_auth_router.py
git commit -m "feat: add POST /api/auth/change-password endpoint with tests (#280, #281)"
```

---

### Task 3: Add changePassword Method to API Client

**Files:**
- Modify: `explore/static/js/api-client.js:265` (after `twoFactorDisable`)

- [ ] **Step 1: Add the method**

In `explore/static/js/api-client.js`, add after the `twoFactorDisable` method (after line 265):

```javascript
    async changePassword(token, currentPassword, newPassword) {
        const response = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        });
        return response;
    }
```

- [ ] **Step 2: Commit**

```bash
git add explore/static/js/api-client.js
git commit -m "feat: add changePassword method to API client (#280, #281)"
```

---

### Task 4: Update AuthManager to Support totp_enabled Updates

**Files:**
- Modify: `explore/static/js/auth.js`

- [ ] **Step 1: Add updateTotpEnabled method**

In `explore/static/js/auth.js`, the `init()` method already calls `getMe()` and stores the result in `this._user`. The `/api/auth/me` response already includes `created_at` and `totp_enabled`, so `this._user` already has these fields. No change needed to `init()`.

Add a method to update `totp_enabled` locally. Add after the `notify()` method (after line 74):

```javascript
    /** Update totp_enabled flag without re-fetching from API. */
    updateTotpEnabled(enabled) {
        if (this._user) {
            this._user.totp_enabled = enabled;
        }
    }
```

- [ ] **Step 2: Commit**

```bash
git add explore/static/js/auth.js
git commit -m "feat: add updateTotpEnabled to AuthManager (#280, #281)"
```

---

### Task 5: Add Settings Pane HTML to index.html

**Files:**
- Modify: `explore/static/index.html`

- [ ] **Step 1: Add "Account Settings" link to user dropdown**

In `explore/static/index.html`, find the user dropdown menu. Add an "Account Settings" link after the Sync Collection link and before the `<hr>` + Logout section (after line 562, before line 563):

```html
                            <a class="flex items-center px-3 py-1.5 text-sm text-text-mid hover:bg-bg-hover cursor-pointer" href="#" id="accountSettingsBtn">
                                <span class="material-symbols-outlined mr-2" style="font-size:18px">settings</span>Account Settings
                            </a>
```

- [ ] **Step 2: Add settings pane HTML**

Add a new pane before the closing `</div><!-- /.main-content -->` (before line 1131). Place it after the gaps pane block and before the main-content closing div:

```html
        <!-- Settings pane — account management (no nav tab, activated from dropdown) -->
        <div class="pane" id="settingsPane">
            <div class="settings-page">
                <div class="settings-header">
                    <a href="#" class="settings-back-link" id="settingsBackBtn">
                        <span class="material-symbols-outlined" style="font-size:18px">arrow_back</span>
                        Back
                    </a>
                    <h2 class="settings-title">Account Settings</h2>
                </div>

                <!-- Profile Card -->
                <div class="settings-card" id="settingsProfileCard">
                    <div class="settings-card-header">
                        <span class="material-symbols-outlined">person</span>
                        <h3>Profile</h3>
                    </div>
                    <div class="settings-card-body">
                        <div class="settings-field">
                            <label class="settings-label">Email</label>
                            <div class="settings-value" id="settingsEmail"></div>
                        </div>
                        <div class="settings-field">
                            <label class="settings-label">Member since</label>
                            <div class="settings-value" id="settingsCreatedAt"></div>
                        </div>
                        <div class="settings-field">
                            <label class="settings-label">Discogs</label>
                            <div class="settings-value" id="settingsDiscogsStatus"></div>
                        </div>
                    </div>
                </div>

                <!-- Password Card -->
                <div class="settings-card" id="settingsPasswordCard">
                    <div class="settings-card-header">
                        <span class="material-symbols-outlined">lock</span>
                        <h3>Change Password</h3>
                    </div>
                    <div class="settings-card-body">
                        <div class="mb-3">
                            <label for="settingsCurrentPassword" class="settings-label">Current Password</label>
                            <input type="password" class="form-input-dark" id="settingsCurrentPassword" autocomplete="current-password" placeholder="Enter current password">
                        </div>
                        <div class="mb-3">
                            <label for="settingsNewPassword" class="settings-label">New Password</label>
                            <input type="password" class="form-input-dark" id="settingsNewPassword" autocomplete="new-password" placeholder="Minimum 8 characters">
                        </div>
                        <div class="mb-3">
                            <label for="settingsConfirmPassword" class="settings-label">Confirm New Password</label>
                            <input type="password" class="form-input-dark" id="settingsConfirmPassword" autocomplete="new-password" placeholder="Repeat new password">
                        </div>
                        <div class="mb-2 min-h-[1.2rem] text-sm text-accent-red" id="passwordChangeError"></div>
                        <div class="mb-2 min-h-[1.2rem] text-sm text-accent-green hidden" id="passwordChangeSuccess"></div>
                        <button class="btn-primary" id="changePasswordBtn" type="button">
                            <span class="material-symbols-outlined mr-1" style="font-size:18px">lock_reset</span>Change Password
                        </button>
                    </div>
                </div>

                <!-- Security Card (2FA) -->
                <div class="settings-card" id="settingsSecurityCard">
                    <div class="settings-card-header">
                        <span class="material-symbols-outlined">shield</span>
                        <h3>Two-Factor Authentication</h3>
                    </div>
                    <div class="settings-card-body" id="twoFactorContent">
                        <!-- Populated dynamically by settings.js -->
                    </div>
                </div>
            </div>
        </div>
```

- [ ] **Step 3: Add settings.js script tag**

In `explore/static/index.html`, add the `settings.js` script tag after `nlq.js` and before `app.js` (after the current line 1146 — line numbers will have shifted after adding the pane HTML):

```html
    <script src="js/settings.js"></script>
```

- [ ] **Step 4: Commit**

```bash
git add explore/static/index.html
git commit -m "feat: add settings pane HTML and dropdown link (#280, #281)"
```

---

### Task 6: Add Settings Card Styles

**Files:**
- Modify: `explore/static/css/styles.css`

- [ ] **Step 1: Add settings styles**

Append the following to `explore/static/css/styles.css`:

```css
/* ── Settings page ──────────────────────────────────────────────────────── */

.settings-page {
    max-width: 42rem;
    margin: 0 auto;
    padding: 2rem 1rem;
    overflow-y: auto;
    height: 100%;
}

.settings-header {
    margin-bottom: 1.5rem;
}

.settings-back-link {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--text-mid);
    font-size: 0.875rem;
    text-decoration: none;
    margin-bottom: 0.5rem;
    transition: color 0.15s;
}

.settings-back-link:hover {
    color: var(--text-high);
}

.settings-title {
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--text-high);
}

.settings-card {
    border: 1px solid var(--border-color);
    border-radius: 0.5rem;
    background: var(--card-bg);
    margin-bottom: 1rem;
}

.settings-card-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-high);
}

.settings-card-header h3 {
    font-size: 0.9375rem;
    font-weight: 600;
    margin: 0;
}

.settings-card-body {
    padding: 1rem;
}

.settings-field {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    padding: 0.375rem 0;
}

.settings-label {
    font-size: 0.8125rem;
    color: var(--text-mid);
    min-width: 6rem;
    flex-shrink: 0;
}

.settings-value {
    font-size: 0.875rem;
    color: var(--text-high);
}

/* 2FA status badges */
.twofa-badge {
    display: inline-block;
    padding: 0.125rem 0.625rem;
    border-radius: 0.75rem;
    font-size: 0.75rem;
    font-weight: 500;
}

.twofa-badge-enabled {
    background: rgba(34, 197, 94, 0.15);
    color: #22c55e;
}

.twofa-badge-disabled {
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
}

/* 2FA setup — QR code container */
.twofa-qr-container {
    display: flex;
    justify-content: center;
    margin: 1rem 0;
}

.twofa-qr-container img,
.twofa-qr-container canvas {
    border-radius: 0.5rem;
    background: white;
    padding: 0.5rem;
}

/* 2FA setup — manual secret display */
.twofa-manual-secret {
    text-align: center;
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-bottom: 1rem;
}

.twofa-manual-secret code {
    font-family: 'JetBrains Mono', monospace;
    background: var(--inner-bg);
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    letter-spacing: 0.1em;
}

/* 2FA setup — TOTP input group (reuses login 2FA pattern) */
.twofa-code-inputs {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    margin-bottom: 1rem;
}

/* Recovery codes grid */
.recovery-codes-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.375rem 1.5rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.875rem;
    padding: 1rem;
    background: var(--inner-bg);
    border-radius: 0.5rem;
    margin-bottom: 1rem;
    color: var(--text-high);
}

/* Recovery codes warning banner */
.recovery-warning {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    background: rgba(234, 179, 8, 0.1);
    border: 1px solid rgba(234, 179, 8, 0.3);
    border-radius: 0.5rem;
    margin-bottom: 1rem;
    font-size: 0.8125rem;
    color: var(--text-high);
}
```

- [ ] **Step 2: Commit**

```bash
git add explore/static/css/styles.css
git commit -m "feat: add settings page and 2FA card styles (#280, #281)"
```

---

### Task 7: Create settings.js — Settings Pane Controller

**Files:**
- Create: `explore/static/js/settings.js`

- [ ] **Step 1: Create the settings module**

Create `explore/static/js/settings.js`:

```javascript
/**
 * Settings pane controller.
 * Manages profile display, password change, and 2FA state machine.
 *
 * XSS safety: All innerHTML content is hardcoded template strings.
 * User-provided data (email, username) is set via textContent only.
 * TOTP secrets and recovery codes are alphanumeric server outputs.
 */
class SettingsPane {
    constructor() {
        this._recoveryCodes = null;
        this._setupData = null;
        this._twoFaState = 'disabled'; // disabled | setup | recovery | enabled | disable-confirm
        this._bound = false;
    }

    /** Initialise content and bind events (called when pane activates). */
    init() {
        this._loadProfile();
        this._renderTwoFaState();
        if (!this._bound) {
            this._bindEvents();
            this._bound = true;
        }
    }

    // ── Profile ────────────────────────────────────────────────────────

    _loadProfile() {
        const user = window.authManager.getUser();
        const discogs = window.authManager.getDiscogsStatus();

        const emailEl = document.getElementById('settingsEmail');
        const createdEl = document.getElementById('settingsCreatedAt');
        const discogsEl = document.getElementById('settingsDiscogsStatus');

        if (emailEl) emailEl.textContent = user?.email || '—';
        if (createdEl && user?.created_at) {
            const d = new Date(user.created_at);
            createdEl.textContent = d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
        }
        if (discogsEl) {
            discogsEl.textContent = '';
            const badge = document.createElement('span');
            badge.className = discogs?.connected
                ? 'twofa-badge twofa-badge-enabled'
                : 'twofa-badge twofa-badge-disabled';
            badge.textContent = discogs?.connected ? 'Connected' : 'Not connected';
            discogsEl.appendChild(badge);
            if (discogs?.connected && discogs?.username) {
                const usernameSpan = document.createElement('span');
                usernameSpan.className = 'text-sm t-mid ml-1';
                usernameSpan.textContent = ` (${discogs.username})`;
                discogsEl.appendChild(usernameSpan);
            }
        }

        // Set initial 2FA state from user data
        this._twoFaState = user?.totp_enabled ? 'enabled' : 'disabled';
    }

    // ── Password Change ────────────────────────────────────────────────

    _bindEvents() {
        const changeBtn = document.getElementById('changePasswordBtn');
        if (changeBtn) {
            changeBtn.addEventListener('click', () => this._handleChangePassword());
        }
    }

    async _handleChangePassword() {
        const currentPw = document.getElementById('settingsCurrentPassword');
        const newPw = document.getElementById('settingsNewPassword');
        const confirmPw = document.getElementById('settingsConfirmPassword');
        const errorEl = document.getElementById('passwordChangeError');
        const successEl = document.getElementById('passwordChangeSuccess');
        const btn = document.getElementById('changePasswordBtn');

        // Clear messages
        errorEl.textContent = '';
        successEl.classList.add('hidden');

        // Client-side validation
        if (!currentPw.value || !newPw.value || !confirmPw.value) {
            errorEl.textContent = 'All fields are required';
            return;
        }
        if (newPw.value.length < 8) {
            errorEl.textContent = 'New password must be at least 8 characters';
            return;
        }
        if (newPw.value !== confirmPw.value) {
            errorEl.textContent = 'New passwords do not match';
            return;
        }

        btn.disabled = true;
        try {
            const token = window.authManager.getToken();
            const response = await window.apiClient.changePassword(token, currentPw.value, newPw.value);
            if (!response.ok) {
                const err = await response.json();
                errorEl.textContent = err.detail || 'Failed to change password';
                return;
            }
            // Success
            currentPw.value = '';
            newPw.value = '';
            confirmPw.value = '';
            successEl.textContent = 'Password changed successfully. You will be logged out on next page load.';
            successEl.classList.remove('hidden');
        } catch {
            errorEl.textContent = 'Network error — please try again';
        } finally {
            btn.disabled = false;
        }
    }

    // ── 2FA State Machine ──────────────────────────────────────────────

    _renderTwoFaState() {
        const container = document.getElementById('twoFactorContent');
        if (!container) return;

        // Clear previous content safely
        container.textContent = '';

        switch (this._twoFaState) {
            case 'disabled':
                this._renderDisabledState(container);
                break;
            case 'setup':
                this._renderSetupState(container);
                break;
            case 'recovery':
                this._renderRecoveryState(container);
                break;
            case 'enabled':
                this._renderEnabledState(container);
                break;
            case 'disable-confirm':
                this._renderDisableConfirmState(container);
                break;
        }
    }

    _renderDisabledState(container) {
        const wrapper = document.createElement('div');

        const statusRow = document.createElement('div');
        statusRow.className = 'flex items-center justify-between mb-2';
        const statusInfo = document.createElement('div');
        const statusLine = document.createElement('div');
        statusLine.className = 'text-sm t-high';
        statusLine.textContent = 'Status: ';
        const badge = document.createElement('span');
        badge.className = 'twofa-badge twofa-badge-disabled';
        badge.textContent = 'Disabled';
        statusLine.appendChild(badge);
        statusInfo.appendChild(statusLine);
        const desc = document.createElement('p');
        desc.className = 'text-xs t-dim mt-1';
        desc.textContent = 'Add an extra layer of security to your account';
        statusInfo.appendChild(desc);
        statusRow.appendChild(statusInfo);
        wrapper.appendChild(statusRow);

        const btn = document.createElement('button');
        btn.className = 'btn-primary btn-sm';
        btn.id = 'enable2faBtn';
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined mr-1';
        icon.style.fontSize = '18px';
        icon.textContent = 'lock';
        btn.appendChild(icon);
        btn.appendChild(document.createTextNode('Enable 2FA'));
        btn.addEventListener('click', () => this._startSetup());
        wrapper.appendChild(btn);

        container.appendChild(wrapper);
    }

    _renderEnabledState(container) {
        const wrapper = document.createElement('div');

        const statusRow = document.createElement('div');
        statusRow.className = 'flex items-center justify-between mb-2';
        const statusInfo = document.createElement('div');
        const statusLine = document.createElement('div');
        statusLine.className = 'text-sm t-high';
        statusLine.textContent = 'Status: ';
        const badge = document.createElement('span');
        badge.className = 'twofa-badge twofa-badge-enabled';
        badge.textContent = 'Enabled';
        statusLine.appendChild(badge);
        statusInfo.appendChild(statusLine);
        const desc = document.createElement('p');
        desc.className = 'text-xs t-dim mt-1';
        desc.textContent = 'Your account is protected with an authenticator app';
        statusInfo.appendChild(desc);
        statusRow.appendChild(statusInfo);
        wrapper.appendChild(statusRow);

        const btn = document.createElement('button');
        btn.className = 'btn-outline-danger btn-sm';
        btn.textContent = 'Disable 2FA';
        btn.addEventListener('click', () => {
            this._twoFaState = 'disable-confirm';
            this._renderTwoFaState();
        });
        wrapper.appendChild(btn);

        container.appendChild(wrapper);
    }

    async _startSetup() {
        const container = document.getElementById('twoFactorContent');
        container.textContent = 'Setting up...';

        try {
            const token = window.authManager.getToken();
            const response = await window.apiClient.twoFactorSetup(token);
            if (!response.ok) {
                const err = await response.json();
                container.textContent = '';
                const errP = document.createElement('p');
                errP.className = 'text-sm text-accent-red';
                errP.textContent = err.detail || 'Setup failed';
                container.appendChild(errP);
                return;
            }
            this._setupData = await response.json();
            this._recoveryCodes = this._setupData.recovery_codes;
            this._twoFaState = 'setup';
            this._renderTwoFaState();
        } catch {
            container.textContent = '';
            const errP = document.createElement('p');
            errP.className = 'text-sm text-accent-red';
            errP.textContent = 'Network error — please try again';
            container.appendChild(errP);
        }
    }

    _renderSetupState(container) {
        const secret = this._setupData.secret;
        // TOTP secrets are base32 alphanumeric — safe for textContent
        const formattedSecret = secret.replace(/(.{4})/g, '$1 ').trim();

        // Step 1: QR Code
        const step1Title = document.createElement('div');
        step1Title.className = 'text-sm font-semibold t-high mb-1';
        step1Title.textContent = 'Step 1: Scan QR Code';
        container.appendChild(step1Title);

        const step1Desc = document.createElement('p');
        step1Desc.className = 'text-xs t-dim mb-2';
        step1Desc.textContent = 'Open your authenticator app and scan the code below';
        container.appendChild(step1Desc);

        const qrContainer = document.createElement('div');
        qrContainer.className = 'twofa-qr-container';
        qrContainer.id = 'twofa-qr-target';
        container.appendChild(qrContainer);

        const manualSecret = document.createElement('div');
        manualSecret.className = 'twofa-manual-secret';
        manualSecret.textContent = "Can't scan? Enter this code manually: ";
        const codeEl = document.createElement('code');
        codeEl.textContent = formattedSecret;
        manualSecret.appendChild(codeEl);
        container.appendChild(manualSecret);

        // Step 2: Verification code
        const step2Title = document.createElement('div');
        step2Title.className = 'text-sm font-semibold t-high mb-1';
        step2Title.textContent = 'Step 2: Enter Verification Code';
        container.appendChild(step2Title);

        const step2Desc = document.createElement('p');
        step2Desc.className = 'text-xs t-dim mb-2';
        step2Desc.textContent = 'Enter the 6-digit code from your authenticator app';
        container.appendChild(step2Desc);

        const inputsDiv = document.createElement('div');
        inputsDiv.className = 'twofa-code-inputs';
        inputsDiv.id = 'setup-totp-inputs';
        for (let i = 0; i < 6; i++) {
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.className = 'form-input-dark w-10 text-center text-xl font-mono';
            inp.maxLength = 1;
            inp.inputMode = 'numeric';
            inp.setAttribute('data-setup-totp', String(i));
            inputsDiv.appendChild(inp);
        }
        container.appendChild(inputsDiv);

        const errorEl = document.createElement('div');
        errorEl.className = 'min-h-[1.2rem] text-sm text-accent-red text-center mb-2';
        errorEl.id = 'setup-totp-error';
        container.appendChild(errorEl);

        // Buttons
        const btnRow = document.createElement('div');
        btnRow.className = 'flex gap-2';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn-secondary btn-sm';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            this._setupData = null;
            this._recoveryCodes = null;
            this._twoFaState = 'disabled';
            this._renderTwoFaState();
        });
        btnRow.appendChild(cancelBtn);

        const verifyBtn = document.createElement('button');
        verifyBtn.className = 'btn-success btn-sm';
        verifyBtn.id = 'setup-verify-btn';
        const verifyIcon = document.createElement('span');
        verifyIcon.className = 'material-symbols-outlined mr-1';
        verifyIcon.style.fontSize = '18px';
        verifyIcon.textContent = 'verified';
        verifyBtn.appendChild(verifyIcon);
        verifyBtn.appendChild(document.createTextNode('Verify & Enable'));
        verifyBtn.addEventListener('click', () => this._confirmSetup());
        btnRow.appendChild(verifyBtn);

        container.appendChild(btnRow);

        // Render QR code using qrcodejs (already loaded in index.html)
        if (typeof QRCode !== 'undefined') {
            new QRCode(qrContainer, {
                text: this._setupData.otpauth_uri,
                width: 160,
                height: 160,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M,
            });
        }

        // Bind TOTP input auto-advance
        this._bindTotpInputs('data-setup-totp');
    }

    async _confirmSetup() {
        const code = this._collectTotpCode('data-setup-totp');
        const errorEl = document.getElementById('setup-totp-error');
        const btn = document.getElementById('setup-verify-btn');

        if (code.length !== 6) {
            errorEl.textContent = 'Please enter all 6 digits';
            return;
        }

        btn.disabled = true;
        try {
            const token = window.authManager.getToken();
            const response = await window.apiClient.twoFactorConfirm(token, code);
            if (!response.ok) {
                const err = await response.json();
                errorEl.textContent = err.detail || 'Invalid code';
                this._clearTotpInputs('data-setup-totp');
                return;
            }
            // Success — update local state and show recovery codes
            window.authManager.updateTotpEnabled(true);
            this._twoFaState = 'recovery';
            this._renderTwoFaState();
        } catch {
            errorEl.textContent = 'Network error — please try again';
        } finally {
            btn.disabled = false;
        }
    }

    _renderRecoveryState(container) {
        const codes = this._recoveryCodes || [];

        // Warning banner
        const warning = document.createElement('div');
        warning.className = 'recovery-warning';
        const warnIcon = document.createElement('span');
        warnIcon.className = 'material-symbols-outlined';
        warnIcon.style.fontSize = '20px';
        warnIcon.style.color = '#eab308';
        warnIcon.textContent = 'warning';
        warning.appendChild(warnIcon);
        const warnText = document.createElement('div');
        const strong = document.createElement('strong');
        strong.textContent = 'Save these recovery codes now.';
        warnText.appendChild(strong);
        warnText.appendChild(document.createTextNode(' You won\'t be able to see them again. Each code can only be used once.'));
        warning.appendChild(warnText);
        container.appendChild(warning);

        // Codes grid
        const grid = document.createElement('div');
        grid.className = 'recovery-codes-grid';
        codes.forEach(code => {
            const div = document.createElement('div');
            div.textContent = code;
            grid.appendChild(div);
        });
        container.appendChild(grid);

        // Buttons
        const btnRow = document.createElement('div');
        btnRow.className = 'flex gap-2';

        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn-secondary btn-sm';
        const copyIcon = document.createElement('span');
        copyIcon.className = 'material-symbols-outlined mr-1';
        copyIcon.style.fontSize = '18px';
        copyIcon.textContent = 'content_copy';
        copyBtn.appendChild(copyIcon);
        copyBtn.appendChild(document.createTextNode('Copy Codes'));
        copyBtn.addEventListener('click', () => {
            const text = codes.join('\n');
            navigator.clipboard.writeText(text).then(() => {
                copyBtn.textContent = '';
                const checkIcon = document.createElement('span');
                checkIcon.className = 'material-symbols-outlined mr-1';
                checkIcon.style.fontSize = '18px';
                checkIcon.textContent = 'check';
                copyBtn.appendChild(checkIcon);
                copyBtn.appendChild(document.createTextNode('Copied!'));
                setTimeout(() => {
                    copyBtn.textContent = '';
                    const icon2 = document.createElement('span');
                    icon2.className = 'material-symbols-outlined mr-1';
                    icon2.style.fontSize = '18px';
                    icon2.textContent = 'content_copy';
                    copyBtn.appendChild(icon2);
                    copyBtn.appendChild(document.createTextNode('Copy Codes'));
                }, 2000);
            });
        });
        btnRow.appendChild(copyBtn);

        const savedBtn = document.createElement('button');
        savedBtn.className = 'btn-primary btn-sm';
        savedBtn.textContent = 'I\'ve Saved My Codes';
        savedBtn.addEventListener('click', () => {
            this._recoveryCodes = null;
            this._setupData = null;
            this._twoFaState = 'enabled';
            this._renderTwoFaState();
        });
        btnRow.appendChild(savedBtn);

        container.appendChild(btnRow);
    }

    _renderDisableConfirmState(container) {
        const title = document.createElement('div');
        title.className = 'text-sm font-semibold t-high mb-2';
        title.textContent = 'Confirm Disable 2FA';
        container.appendChild(title);

        const desc = document.createElement('p');
        desc.className = 'text-xs t-dim mb-3';
        desc.textContent = 'Enter your current TOTP code and password to disable two-factor authentication.';
        container.appendChild(desc);

        // TOTP Code
        const codeLabel = document.createElement('label');
        codeLabel.className = 'settings-label mb-1 block';
        codeLabel.textContent = 'TOTP Code';
        container.appendChild(codeLabel);

        const inputsDiv = document.createElement('div');
        inputsDiv.className = 'twofa-code-inputs mb-3';
        inputsDiv.id = 'disable-totp-inputs';
        for (let i = 0; i < 6; i++) {
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.className = 'form-input-dark w-10 text-center text-xl font-mono';
            inp.maxLength = 1;
            inp.inputMode = 'numeric';
            inp.setAttribute('data-disable-totp', String(i));
            inputsDiv.appendChild(inp);
        }
        container.appendChild(inputsDiv);

        // Password
        const pwLabel = document.createElement('label');
        pwLabel.className = 'settings-label mb-1 block';
        pwLabel.htmlFor = 'disable2faPassword';
        pwLabel.textContent = 'Password';
        container.appendChild(pwLabel);

        const pwDiv = document.createElement('div');
        pwDiv.className = 'mb-3';
        const pwInput = document.createElement('input');
        pwInput.type = 'password';
        pwInput.className = 'form-input-dark';
        pwInput.id = 'disable2faPassword';
        pwInput.placeholder = 'Your current password';
        pwInput.style.maxWidth = '20rem';
        pwDiv.appendChild(pwInput);
        container.appendChild(pwDiv);

        // Error
        const errorEl = document.createElement('div');
        errorEl.className = 'min-h-[1.2rem] text-sm text-accent-red mb-2';
        errorEl.id = 'disable-2fa-error';
        container.appendChild(errorEl);

        // Buttons
        const btnRow = document.createElement('div');
        btnRow.className = 'flex gap-2';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn-secondary btn-sm';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            this._twoFaState = 'enabled';
            this._renderTwoFaState();
        });
        btnRow.appendChild(cancelBtn);

        const disableBtn = document.createElement('button');
        disableBtn.className = 'btn-sm';
        disableBtn.id = 'disable-confirm-btn';
        disableBtn.style.background = 'var(--accent-red)';
        disableBtn.style.color = 'white';
        disableBtn.style.border = 'none';
        disableBtn.textContent = 'Disable 2FA';
        disableBtn.addEventListener('click', () => this._handleDisable());
        btnRow.appendChild(disableBtn);

        container.appendChild(btnRow);

        this._bindTotpInputs('data-disable-totp');
    }

    async _handleDisable() {
        const code = this._collectTotpCode('data-disable-totp');
        const password = document.getElementById('disable2faPassword')?.value;
        const errorEl = document.getElementById('disable-2fa-error');
        const btn = document.getElementById('disable-confirm-btn');

        if (code.length !== 6) {
            errorEl.textContent = 'Please enter all 6 digits';
            return;
        }
        if (!password) {
            errorEl.textContent = 'Password is required';
            return;
        }

        btn.disabled = true;
        try {
            const token = window.authManager.getToken();
            const response = await window.apiClient.twoFactorDisable(token, code, password);
            if (!response.ok) {
                const err = await response.json();
                errorEl.textContent = err.detail || 'Failed to disable 2FA';
                return;
            }
            window.authManager.updateTotpEnabled(false);
            this._twoFaState = 'disabled';
            this._renderTwoFaState();
        } catch {
            errorEl.textContent = 'Network error — please try again';
        } finally {
            btn.disabled = false;
        }
    }

    // ── TOTP Input Helpers ─────────────────────────────────────────────

    /** Bind auto-advance and paste handling for 6-digit TOTP inputs. */
    _bindTotpInputs(dataAttr) {
        const inputs = document.querySelectorAll(`[${dataAttr}]`);
        inputs.forEach((input, i) => {
            input.addEventListener('input', () => {
                // Only allow digits
                input.value = input.value.replace(/\D/g, '');
                if (input.value && i < inputs.length - 1) {
                    inputs[i + 1].focus();
                }
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !input.value && i > 0) {
                    inputs[i - 1].focus();
                }
            });
            // Handle paste of full code
            input.addEventListener('paste', (e) => {
                const text = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g, '');
                if (text.length >= 6) {
                    e.preventDefault();
                    for (let j = 0; j < 6 && j < text.length; j++) {
                        inputs[j].value = text[j];
                    }
                    inputs[Math.min(5, text.length - 1)].focus();
                }
            });
        });
    }

    /** Collect the 6-digit code from TOTP inputs. */
    _collectTotpCode(dataAttr) {
        const inputs = document.querySelectorAll(`[${dataAttr}]`);
        return Array.from(inputs).map(i => i.value).join('');
    }

    /** Clear all TOTP inputs. */
    _clearTotpInputs(dataAttr) {
        document.querySelectorAll(`[${dataAttr}]`).forEach(i => { i.value = ''; });
        document.querySelector(`[${dataAttr}="0"]`)?.focus();
    }
}

// Global instance
window.settingsPane = new SettingsPane();
```

- [ ] **Step 2: Verify no syntax errors**

```bash
node -c explore/static/js/settings.js
```
Expected: No syntax errors

- [ ] **Step 3: Commit**

```bash
git add explore/static/js/settings.js
git commit -m "feat: add settings.js controller with 2FA state machine (#280, #281)"
```

---

### Task 8: Integrate Settings Pane into app.js

**Files:**
- Modify: `explore/static/js/app.js`

- [ ] **Step 1: Add settings pane handling to _switchPane**

In `explore/static/js/app.js`, find the `_switchPane(pane)` method (around line 841). Add a condition for the settings pane in the lazy-load section. After the credits pane check (after line 888 — `window.creditsPanel.load();`), add:

```javascript
        } else if (pane === 'settings') {
            window.settingsPane.init();
        }
```

- [ ] **Step 2: Add event handlers for settings navigation**

In `explore/static/js/app.js`, find the `_bindEvents` method where dropdown / auth UI events are bound (search for `logoutBtn` or `connectDiscogsBtn`). Add the account settings button handler nearby:

```javascript
        // Account Settings button
        const accountSettingsBtn = document.getElementById('accountSettingsBtn');
        if (accountSettingsBtn) {
            accountSettingsBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this._previousPane = this.activePane;
                this._switchPane('settings');
                // Close the dropdown
                const dropdown = accountSettingsBtn.closest('[x-data]');
                if (dropdown) {
                    const data = _alpineData(dropdown);
                    if (data) data.open = false;
                }
            });
        }

        // Settings back button
        const settingsBackBtn = document.getElementById('settingsBackBtn');
        if (settingsBackBtn) {
            settingsBackBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this._switchPane(this._previousPane || 'explore');
            });
        }
```

- [ ] **Step 3: Verify no syntax errors**

```bash
node -c explore/static/js/app.js
```
Expected: No syntax errors

- [ ] **Step 4: Commit**

```bash
git add explore/static/js/app.js
git commit -m "feat: integrate settings pane into app.js navigation (#280, #281)"
```

---

### Task 9: Rebuild Tailwind CSS

**Files:**
- Modify: `explore/static/tailwind.css` (build output)

- [ ] **Step 1: Rebuild Tailwind**

The settings pane HTML uses Tailwind utility classes (`flex`, `items-center`, `gap-2`, `mb-3`, `text-sm`, etc.). Rebuild the Tailwind output:

```bash
cd explore && npx tailwindcss -i tailwind.input.css -o static/tailwind.css --minify && cd ..
```

Expected: `tailwind.css` updated with no errors

- [ ] **Step 2: Commit if changed**

```bash
git add explore/static/tailwind.css
git commit -m "chore: rebuild tailwind CSS with settings pane classes (#280, #281)"
```

---

### Task 10: Run Full Test Suite and Lint

**Files:** None (verification only)

- [ ] **Step 1: Run all Python tests**

```bash
just test
```
Expected: All tests pass

- [ ] **Step 2: Run JS tests**

```bash
just test-js
```
Expected: All tests pass

- [ ] **Step 3: Run linting**

```bash
just lint
```
Expected: No errors

- [ ] **Step 4: Run type checking**

```bash
uv run mypy api/routers/auth.py api/models.py
```
Expected: No errors
