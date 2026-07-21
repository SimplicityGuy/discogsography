/**
 * Settings pane controller — account management and 2FA state machine.
 *
 * 2FA states: disabled → setup → recovery → enabled
 *                                enabled → disableConfirm → disabled
 */
class SettingsPane {
    constructor() {
        this._initialized = false;
        this._twoFaState = 'disabled'; // disabled | setup | recovery | enabled | disableConfirm
        this._setupData = null;        // { secret, otpauth_uri } from /api/auth/2fa/setup
        this._recoveryCodes = null;    // string[] from /api/auth/2fa/confirm
        // App tokens (third-party app authorization)
        this._appTokensView = 'list';   // list | minting | revealing
        this._activeTokens = [];
        this._revokedTokens = [];
        this._mintedPlaintext = null;   // held only while view === 'revealing'
        this._mintedTokenMeta = null;   // { name, scopes } shown alongside plaintext
    }

    /** Called when pane activates. Loads profile, renders 2FA, binds events once. */
    init() {
        this._loadProfile();
        this._renderTwoFaState();
        this._loadAppTokens();

        if (!this._initialized) {
            this._bindEvents();
            this._initialized = true;
        }
    }

    // ------------------------------------------------------------------ //
    // Profile card
    // ------------------------------------------------------------------ //

    _loadProfile() {
        const user = window.authManager.getUser();
        if (!user) return;

        const emailEl = document.getElementById('settingsEmail');
        if (emailEl) emailEl.textContent = user.email || '';

        const createdEl = document.getElementById('settingsCreatedAt');
        if (createdEl) {
            if (user.created_at) {
                const d = new Date(user.created_at);
                createdEl.textContent = d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
            } else {
                createdEl.textContent = '';
            }
        }

        const discogsEl = document.getElementById('settingsDiscogsStatus');
        if (discogsEl) {
            const status = window.authManager.getDiscogsStatus();
            if (status && status.connected) {
                discogsEl.textContent = '';
                const badge = document.createElement('span');
                badge.className = 'twofa-badge twofa-badge-enabled';
                badge.textContent = 'Connected';
                discogsEl.appendChild(badge);
                if (status.username) {
                    const username = document.createElement('span');
                    username.className = 'ml-2 text-text-mid text-sm';
                    username.textContent = status.username;
                    discogsEl.appendChild(username);
                }
            } else {
                discogsEl.textContent = 'Not connected';
            }
        }

        // Derive 2FA state from user data — but never while a transient flow
        // (setup / recovery / disableConfirm) is in progress. init() runs on
        // EVERY pane activation, so re-entering Settings mid-flow would
        // otherwise clobber the one-time recovery-codes screen (codes are
        // returned once by /2fa/setup and cannot be re-fetched), mirroring
        // the 'revealing' guard in _loadAppTokens above.
        if (!['setup', 'recovery', 'disableConfirm'].includes(this._twoFaState)) {
            this._twoFaState = user.totp_enabled ? 'enabled' : 'disabled';
        }
    }

    // ------------------------------------------------------------------ //
    // Event binding
    // ------------------------------------------------------------------ //

    _bindEvents() {
        const changeBtn = document.getElementById('changePasswordBtn');
        if (changeBtn) {
            changeBtn.addEventListener('click', () => this._handleChangePassword());
        }
    }

    // ------------------------------------------------------------------ //
    // Change password
    // ------------------------------------------------------------------ //

    async _handleChangePassword() {
        const currentPw = document.getElementById('settingsCurrentPassword');
        const newPw = document.getElementById('settingsNewPassword');
        const confirmPw = document.getElementById('settingsConfirmPassword');
        const errorEl = document.getElementById('passwordChangeError');
        const successEl = document.getElementById('passwordChangeSuccess');

        errorEl.textContent = '';
        successEl.textContent = '';
        successEl.classList.add('hidden');

        const current = currentPw.value;
        const next = newPw.value;
        const confirm = confirmPw.value;

        if (!current) { errorEl.textContent = 'Current password is required'; return; }
        if (!next || next.length < 8) { errorEl.textContent = 'New password must be at least 8 characters'; return; }
        if (next !== confirm) { errorEl.textContent = 'Passwords do not match'; return; }

        const token = window.authManager.getToken();
        if (!token) { errorEl.textContent = 'Not authenticated'; return; }

        const btn = document.getElementById('changePasswordBtn');
        btn.disabled = true;

        try {
            const response = await window.apiClient.changePassword(token, current, next);
            if (response.ok) {
                successEl.textContent = 'Password changed successfully';
                successEl.classList.remove('hidden');
                currentPw.value = '';
                newPw.value = '';
                confirmPw.value = '';
            } else {
                const data = await response.json().catch(() => ({}));
                errorEl.textContent = data.detail || 'Failed to change password';
            }
        } catch {
            errorEl.textContent = 'Network error — please try again';
        } finally {
            btn.disabled = false;
        }
    }

    // ------------------------------------------------------------------ //
    // 2FA state machine
    // ------------------------------------------------------------------ //

    _renderTwoFaState() {
        const container = document.getElementById('twoFactorContent');
        if (!container) return;
        container.textContent = '';

        switch (this._twoFaState) {
            case 'disabled':       this._renderDisabledState(container); break;
            case 'enabled':        this._renderEnabledState(container); break;
            case 'setup':          this._renderSetupState(container); break;
            case 'recovery':       this._renderRecoveryState(container); break;
            case 'disableConfirm': this._renderDisableConfirmState(container); break;
        }
    }

    // -- Disabled state ------------------------------------------------ //

    _renderDisabledState(container) {
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between';

        const left = document.createElement('div');
        const statusLabel = document.createElement('span');
        statusLabel.className = 'text-sm text-text-mid mr-2';
        statusLabel.textContent = 'Status:';
        const badge = document.createElement('span');
        badge.className = 'twofa-badge twofa-badge-disabled';
        badge.textContent = 'Disabled';
        left.appendChild(statusLabel);
        left.appendChild(badge);

        const btn = document.createElement('button');
        btn.className = 'btn-primary';
        btn.type = 'button';
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined mr-1';
        icon.style.fontSize = '18px';
        icon.textContent = 'security';
        btn.appendChild(icon);
        btn.appendChild(document.createTextNode('Enable 2FA'));
        btn.addEventListener('click', () => this._startSetup());

        row.appendChild(left);
        row.appendChild(btn);
        container.appendChild(row);
    }

    // -- Enabled state ------------------------------------------------- //

    _renderEnabledState(container) {
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between';

        const left = document.createElement('div');
        const statusLabel = document.createElement('span');
        statusLabel.className = 'text-sm text-text-mid mr-2';
        statusLabel.textContent = 'Status:';
        const badge = document.createElement('span');
        badge.className = 'twofa-badge twofa-badge-enabled';
        badge.textContent = 'Enabled';
        left.appendChild(statusLabel);
        left.appendChild(badge);

        const btn = document.createElement('button');
        btn.className = 'btn-danger';
        btn.type = 'button';
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined mr-1';
        icon.style.fontSize = '18px';
        icon.textContent = 'shield';
        btn.appendChild(icon);
        btn.appendChild(document.createTextNode('Disable 2FA'));
        btn.addEventListener('click', () => {
            this._twoFaState = 'disableConfirm';
            this._renderTwoFaState();
        });

        row.appendChild(left);
        row.appendChild(btn);
        container.appendChild(row);
    }

    // -- Setup state --------------------------------------------------- //

    _renderSetupState(container) {
        if (!this._setupData) return;

        // Instructions
        const instructions = document.createElement('p');
        instructions.className = 'text-sm text-text-mid mb-3';
        instructions.textContent = 'Scan the QR code with your authenticator app, then enter the 6-digit code to verify.';
        container.appendChild(instructions);

        // QR code
        const qrContainer = document.createElement('div');
        qrContainer.className = 'twofa-qr-container';
        container.appendChild(qrContainer);
        /* global QRCode */
        new QRCode(qrContainer, {
            text: this._setupData.otpauth_uri,
            width: 160,
            height: 160,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M,
        });

        // Manual secret
        const manualDiv = document.createElement('div');
        manualDiv.className = 'twofa-manual-secret';
        const manualLabel = document.createElement('span');
        manualLabel.textContent = 'Manual entry: ';
        const codeEl = document.createElement('code');
        codeEl.textContent = this._setupData.secret;
        manualDiv.appendChild(manualLabel);
        manualDiv.appendChild(codeEl);
        container.appendChild(manualDiv);

        // TOTP 6-digit inputs
        const inputGroup = document.createElement('div');
        inputGroup.className = 'twofa-code-inputs';
        for (let i = 0; i < 6; i++) {
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.inputMode = 'numeric';
            inp.maxLength = 1;
            inp.className = 'form-input-dark text-center';
            inp.style.width = '2.5rem';
            inp.style.fontSize = '1.25rem';
            inp.dataset.setupTotp = String(i);
            inputGroup.appendChild(inp);
        }
        container.appendChild(inputGroup);
        this._bindTotpInputs('setupTotp');

        // Error
        const errorEl = document.createElement('div');
        errorEl.className = 'text-sm text-accent-red min-h-[1.2rem] mb-2';
        errorEl.id = 'setupTotpError';
        container.appendChild(errorEl);

        // Buttons
        const btnRow = document.createElement('div');
        btnRow.className = 'flex gap-2';

        const verifyBtn = document.createElement('button');
        verifyBtn.className = 'btn-primary';
        verifyBtn.type = 'button';
        verifyBtn.textContent = 'Verify & Enable';
        verifyBtn.addEventListener('click', () => this._confirmSetup());

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn-secondary';
        cancelBtn.type = 'button';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            this._setupData = null;
            this._twoFaState = 'disabled';
            this._renderTwoFaState();
        });

        btnRow.appendChild(verifyBtn);
        btnRow.appendChild(cancelBtn);
        container.appendChild(btnRow);
    }

    // -- Recovery state ------------------------------------------------ //

    _renderRecoveryState(container) {
        // Warning banner
        const warning = document.createElement('div');
        warning.className = 'recovery-warning';
        const warnIcon = document.createElement('span');
        warnIcon.className = 'material-symbols-outlined';
        warnIcon.style.fontSize = '20px';
        warnIcon.style.color = '#eab308';
        warnIcon.textContent = 'warning';
        const warnText = document.createElement('span');
        warnText.textContent = 'Save these recovery codes in a secure location. Each code can only be used once. If you lose access to your authenticator app, you can use these codes to sign in.';
        warning.appendChild(warnIcon);
        warning.appendChild(warnText);
        container.appendChild(warning);

        // Codes grid
        const grid = document.createElement('div');
        grid.className = 'recovery-codes-grid';
        if (this._recoveryCodes) {
            for (const code of this._recoveryCodes) {
                const cell = document.createElement('div');
                cell.textContent = code;
                grid.appendChild(cell);
            }
        }
        container.appendChild(grid);

        // Buttons
        const btnRow = document.createElement('div');
        btnRow.className = 'flex gap-2';

        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn-secondary';
        copyBtn.type = 'button';
        const copyIcon = document.createElement('span');
        copyIcon.className = 'material-symbols-outlined mr-1';
        copyIcon.style.fontSize = '18px';
        copyIcon.textContent = 'content_copy';
        copyBtn.appendChild(copyIcon);
        copyBtn.appendChild(document.createTextNode('Copy Codes'));
        copyBtn.addEventListener('click', () => {
            if (this._recoveryCodes) {
                navigator.clipboard.writeText(this._recoveryCodes.join('\n')).then(() => {
                    copyBtn.textContent = 'Copied!';
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
            }
        });

        const doneBtn = document.createElement('button');
        doneBtn.className = 'btn-primary';
        doneBtn.type = 'button';
        doneBtn.textContent = "I've Saved My Codes";
        doneBtn.addEventListener('click', () => {
            this._recoveryCodes = null;
            this._setupData = null;
            this._twoFaState = 'enabled';
            this._renderTwoFaState();
        });

        btnRow.appendChild(copyBtn);
        btnRow.appendChild(doneBtn);
        container.appendChild(btnRow);
    }

    // -- Disable confirm state ----------------------------------------- //

    _renderDisableConfirmState(container) {
        const instructions = document.createElement('p');
        instructions.className = 'text-sm text-text-mid mb-3';
        instructions.textContent = 'Enter your current TOTP code and password to disable two-factor authentication.';
        container.appendChild(instructions);

        // TOTP inputs
        const label1 = document.createElement('label');
        label1.className = 'settings-label mb-1 block';
        label1.textContent = 'Authenticator Code';
        container.appendChild(label1);

        const inputGroup = document.createElement('div');
        inputGroup.className = 'twofa-code-inputs';
        for (let i = 0; i < 6; i++) {
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.inputMode = 'numeric';
            inp.maxLength = 1;
            inp.className = 'form-input-dark text-center';
            inp.style.width = '2.5rem';
            inp.style.fontSize = '1.25rem';
            inp.dataset.disableTotp = String(i);
            inputGroup.appendChild(inp);
        }
        container.appendChild(inputGroup);
        this._bindTotpInputs('disableTotp');

        // Password
        const label2 = document.createElement('label');
        label2.className = 'settings-label mb-1 block';
        label2.textContent = 'Password';
        container.appendChild(label2);

        const pwInput = document.createElement('input');
        pwInput.type = 'password';
        pwInput.className = 'form-input-dark mb-3';
        pwInput.id = 'disableTotpPassword';
        pwInput.autocomplete = 'current-password';
        pwInput.placeholder = 'Enter your password';
        container.appendChild(pwInput);

        // Error
        const errorEl = document.createElement('div');
        errorEl.className = 'text-sm text-accent-red min-h-[1.2rem] mb-2';
        errorEl.id = 'disableTotpError';
        container.appendChild(errorEl);

        // Buttons
        const btnRow = document.createElement('div');
        btnRow.className = 'flex gap-2';

        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn-danger';
        confirmBtn.type = 'button';
        confirmBtn.textContent = 'Disable 2FA';
        confirmBtn.addEventListener('click', () => this._handleDisable());

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn-secondary';
        cancelBtn.type = 'button';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            this._twoFaState = 'enabled';
            this._renderTwoFaState();
        });

        btnRow.appendChild(confirmBtn);
        btnRow.appendChild(cancelBtn);
        container.appendChild(btnRow);
    }

    // ------------------------------------------------------------------ //
    // 2FA actions
    // ------------------------------------------------------------------ //

    async _startSetup() {
        const token = window.authManager.getToken();
        if (!token) return;

        try {
            const response = await window.apiClient.twoFactorSetup(token);
            if (response.ok) {
                this._setupData = await response.json();
                this._twoFaState = 'setup';
                this._renderTwoFaState();
            } else {
                const data = await response.json().catch(() => ({}));
                // Show a temporary error in the container
                const container = document.getElementById('twoFactorContent');
                if (container) {
                    const err = document.createElement('div');
                    err.className = 'text-sm text-accent-red';
                    err.textContent = data.detail || 'Failed to start 2FA setup';
                    container.appendChild(err);
                }
            }
        } catch {
            // Network error — ignore silently, button remains clickable
        }
    }

    async _confirmSetup() {
        const code = this._collectTotpCode('setupTotp');
        const errorEl = document.getElementById('setupTotpError');
        if (!errorEl) return;
        errorEl.textContent = '';

        if (code.length !== 6 || !/^\d{6}$/.test(code)) {
            errorEl.textContent = 'Please enter a 6-digit code';
            return;
        }

        const token = window.authManager.getToken();
        if (!token) { errorEl.textContent = 'Not authenticated'; return; }

        try {
            const response = await window.apiClient.twoFactorConfirm(token, code);
            if (response.ok) {
                await response.json().catch(() => ({}));
                // Recovery codes were returned by /api/auth/2fa/setup, not /confirm.
                this._recoveryCodes = this._setupData?.recovery_codes || [];
                window.authManager.updateTotpEnabled(true);
                this._twoFaState = 'recovery';
                this._renderTwoFaState();
            } else {
                const data = await response.json().catch(() => ({}));
                errorEl.textContent = data.detail || 'Invalid code';
                this._clearTotpInputs('setupTotp');
            }
        } catch {
            errorEl.textContent = 'Network error — please try again';
        }
    }

    async _handleDisable() {
        const code = this._collectTotpCode('disableTotp');
        const password = document.getElementById('disableTotpPassword')?.value || '';
        const errorEl = document.getElementById('disableTotpError');
        if (!errorEl) return;
        errorEl.textContent = '';

        if (code.length !== 6 || !/^\d{6}$/.test(code)) {
            errorEl.textContent = 'Please enter a 6-digit code';
            return;
        }
        if (!password) {
            errorEl.textContent = 'Password is required';
            return;
        }

        const token = window.authManager.getToken();
        if (!token) { errorEl.textContent = 'Not authenticated'; return; }

        try {
            const response = await window.apiClient.twoFactorDisable(token, code, password);
            if (response.ok) {
                window.authManager.updateTotpEnabled(false);
                this._twoFaState = 'disabled';
                this._renderTwoFaState();
            } else {
                const data = await response.json().catch(() => ({}));
                errorEl.textContent = data.detail || 'Failed to disable 2FA';
                this._clearTotpInputs('disableTotp');
            }
        } catch {
            errorEl.textContent = 'Network error — please try again';
        }
    }

    // ------------------------------------------------------------------ //
    // TOTP input helpers
    // ------------------------------------------------------------------ //

    _bindTotpInputs(dataAttr) {
        const inputs = document.querySelectorAll(`[data-${this._camelToKebab(dataAttr)}]`);
        inputs.forEach((input, idx) => {
            input.addEventListener('input', () => {
                // Accept only digits
                input.value = input.value.replace(/\D/g, '').slice(0, 1);
                if (input.value.length === 1 && idx < inputs.length - 1) {
                    inputs[idx + 1].focus();
                }
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !input.value && idx > 0) {
                    inputs[idx - 1].focus();
                }
            });
            input.addEventListener('paste', (e) => {
                e.preventDefault();
                const paste = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g, '').slice(0, 6);
                for (let i = 0; i < paste.length && i + idx < inputs.length; i++) {
                    inputs[idx + i].value = paste[i];
                }
                const nextIdx = Math.min(idx + paste.length, inputs.length - 1);
                inputs[nextIdx].focus();
            });
        });
    }

    _collectTotpCode(dataAttr) {
        const inputs = document.querySelectorAll(`[data-${this._camelToKebab(dataAttr)}]`);
        return Array.from(inputs).map(i => i.value).join('');
    }

    _clearTotpInputs(dataAttr) {
        const inputs = document.querySelectorAll(`[data-${this._camelToKebab(dataAttr)}]`);
        inputs.forEach(i => { i.value = ''; });
        if (inputs.length > 0) inputs[0].focus();
    }

    /** Convert camelCase data attribute name to kebab-case for querySelector. */
    _camelToKebab(str) {
        return str.replace(/([A-Z])/g, '-$1').toLowerCase();
    }

    // ------------------------------------------------------------------ //
    // App tokens (third-party app authorization) — Connected Apps card
    //
    // All DOM is built with createElement + textContent — no innerHTML —
    // so token names and metadata cannot be interpreted as HTML even if
    // a future endpoint forgets to sanitize.
    // ------------------------------------------------------------------ //

    _appTokensClear(container) {
        while (container.firstChild) container.removeChild(container.firstChild);
    }

    async _loadAppTokens() {
        const container = document.getElementById('appTokensContent');
        if (!container) return;
        const token = window.authManager && window.authManager.getToken && window.authManager.getToken();
        if (!token) {
            this._appTokensClear(container);
            const msg = document.createElement('div');
            msg.className = 'settings-empty';
            msg.textContent = 'Sign in to manage connected apps.';
            container.appendChild(msg);
            return;
        }
        let res = null;
        try {
            res = await window.apiClient.listAppTokens(token);
        } catch {
            res = null;
        }
        this._activeTokens = (res && Array.isArray(res.active)) ? res.active : [];
        this._revokedTokens = (res && Array.isArray(res.revoked)) ? res.revoked : [];
        if (this._appTokensView !== 'revealing') {
            this._appTokensView = 'list';
        }
        this._renderAppTokensView();
    }

    _renderAppTokensView() {
        const container = document.getElementById('appTokensContent');
        if (!container) return;
        switch (this._appTokensView) {
            case 'minting':   this._renderMintForm(container); break;
            case 'revealing': this._renderRevealScreen(container); break;
            case 'list':
            default:          this._renderAppTokensList(container); break;
        }
    }

    _fmtDate(iso) {
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
        } catch {
            return String(iso);
        }
    }

    _renderAppTokensList(container) {
        this._appTokensClear(container);

        const intro = document.createElement('p');
        intro.className = 'app-tokens-intro';
        intro.textContent = 'Authorize third-party apps (e.g. GRUVAX kiosk) to read your data. Each app gets a unique token you can revoke at any time.';
        container.appendChild(intro);

        const activeWrap = document.createElement('div');
        activeWrap.className = 'app-tokens-active';
        if (!this._activeTokens.length) {
            const empty = document.createElement('div');
            empty.className = 'app-tokens-empty';
            empty.textContent = 'No connected apps yet.';
            activeWrap.appendChild(empty);
        } else {
            for (const t of this._activeTokens) {
                activeWrap.appendChild(this._buildActiveTokenRow(t));
            }
        }
        container.appendChild(activeWrap);

        if (this._revokedTokens.length) {
            const header = document.createElement('div');
            header.className = 'app-tokens-revoked-header';
            header.textContent = 'Revoked (audit trail)';
            container.appendChild(header);

            const revokedList = document.createElement('div');
            revokedList.className = 'app-tokens-revoked-list';
            for (const t of this._revokedTokens) {
                const row = document.createElement('div');
                row.className = 'app-token-revoked-row';

                const name = document.createElement('span');
                name.className = 'app-token-name app-token-name-revoked';
                name.textContent = t.name || '';
                row.appendChild(name);

                const meta = document.createElement('span');
                meta.className = 'app-token-meta';
                meta.textContent = `Revoked: ${this._fmtDate(t.revoked_at)}`;
                row.appendChild(meta);

                revokedList.appendChild(row);
            }
            container.appendChild(revokedList);
        }

        const mintBtn = document.createElement('button');
        mintBtn.id = 'appTokenMintBtn';
        mintBtn.type = 'button';
        mintBtn.className = 'btn-primary mt-3';
        const mintIcon = document.createElement('span');
        mintIcon.className = 'material-symbols-outlined mr-1';
        mintIcon.style.fontSize = '18px';
        mintIcon.textContent = 'add';
        mintBtn.appendChild(mintIcon);
        mintBtn.appendChild(document.createTextNode('Connect an app'));
        mintBtn.addEventListener('click', () => this._handleStartMint());
        container.appendChild(mintBtn);
    }

    _buildActiveTokenRow(t) {
        const row = document.createElement('div');
        row.className = 'app-token-row';
        row.setAttribute('data-token-id', t.id || '');

        const mainCol = document.createElement('div');
        mainCol.className = 'app-token-row-main';

        const name = document.createElement('div');
        name.className = 'app-token-name';
        name.textContent = t.name || '';
        mainCol.appendChild(name);

        const meta = document.createElement('div');
        meta.className = 'app-token-meta';
        const scopeSpan = document.createElement('span');
        scopeSpan.textContent = `Scope: ${(t.scopes || []).join(', ')}`;
        const createdSpan = document.createElement('span');
        createdSpan.textContent = `Created: ${this._fmtDate(t.created_at)}`;
        const usedSpan = document.createElement('span');
        usedSpan.textContent = `Last used: ${this._fmtDate(t.last_used_at)}`;
        meta.appendChild(scopeSpan);
        meta.appendChild(createdSpan);
        meta.appendChild(usedSpan);
        mainCol.appendChild(meta);

        row.appendChild(mainCol);

        const revokeBtn = document.createElement('button');
        revokeBtn.type = 'button';
        revokeBtn.className = 'btn-secondary app-token-revoke';
        revokeBtn.textContent = 'Revoke';
        revokeBtn.addEventListener('click', () => this._handleRevoke(t.id, t.name));
        row.appendChild(revokeBtn);

        return row;
    }

    _renderMintForm(container) {
        this._appTokensClear(container);

        const form = document.createElement('div');
        form.className = 'app-token-mint-form';

        // Name field
        const nameWrap = document.createElement('div');
        nameWrap.className = 'mb-3';
        const nameLabel = document.createElement('label');
        nameLabel.className = 'settings-label';
        nameLabel.htmlFor = 'appTokenName';
        nameLabel.textContent = 'App name';
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.id = 'appTokenName';
        nameInput.className = 'form-input-dark';
        nameInput.maxLength = 255;
        nameInput.placeholder = 'e.g. GRUVAX kiosk';
        nameInput.autocomplete = 'off';
        nameWrap.appendChild(nameLabel);
        nameWrap.appendChild(nameInput);
        form.appendChild(nameWrap);

        // Scopes
        const scopesWrap = document.createElement('div');
        scopesWrap.className = 'mb-3';
        const scopesLabel = document.createElement('label');
        scopesLabel.className = 'settings-label';
        scopesLabel.textContent = 'Permissions';
        scopesWrap.appendChild(scopesLabel);

        const scopeRow = document.createElement('div');
        scopeRow.className = 'app-token-scope-row';
        const scopeChk = document.createElement('input');
        scopeChk.type = 'checkbox';
        scopeChk.id = 'appTokenScope_collectionRead';
        scopeChk.checked = true;
        const scopeChkLabel = document.createElement('label');
        scopeChkLabel.className = 'settings-label-inline';
        scopeChkLabel.htmlFor = 'appTokenScope_collectionRead';
        const scopeBold = document.createElement('strong');
        scopeBold.textContent = 'collection:read';
        const scopeDesc = document.createElement('span');
        scopeDesc.className = 'app-token-scope-desc';
        scopeDesc.textContent = 'Read your collection, stats, and timeline';
        scopeChkLabel.appendChild(scopeBold);
        scopeChkLabel.appendChild(document.createTextNode(' '));
        scopeChkLabel.appendChild(scopeDesc);
        scopeRow.appendChild(scopeChk);
        scopeRow.appendChild(scopeChkLabel);
        scopesWrap.appendChild(scopeRow);
        form.appendChild(scopesWrap);

        // Error region
        const err = document.createElement('div');
        err.id = 'appTokenMintError';
        err.className = 'mb-2 min-h-[1.2rem] text-sm text-accent-red';
        form.appendChild(err);

        // Buttons
        const actions = document.createElement('div');
        actions.className = 'app-token-mint-actions';
        const cancelBtn = document.createElement('button');
        cancelBtn.id = 'appTokenCancelMint';
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn-secondary';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => this._handleCancelMint());
        const submitBtn = document.createElement('button');
        submitBtn.id = 'appTokenSubmitMint';
        submitBtn.type = 'button';
        submitBtn.className = 'btn-primary';
        const submitIcon = document.createElement('span');
        submitIcon.className = 'material-symbols-outlined mr-1';
        submitIcon.style.fontSize = '18px';
        submitIcon.textContent = 'vpn_key';
        submitBtn.appendChild(submitIcon);
        submitBtn.appendChild(document.createTextNode('Mint token'));
        submitBtn.addEventListener('click', () => this._handleSubmitMint());
        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        form.appendChild(actions);

        container.appendChild(form);
        nameInput.focus();
    }

    _renderRevealScreen(container) {
        this._appTokensClear(container);

        const wrap = document.createElement('div');
        wrap.className = 'app-token-reveal';

        const warn = document.createElement('div');
        warn.className = 'app-token-reveal-warning';
        const warnIcon = document.createElement('span');
        warnIcon.className = 'material-symbols-outlined';
        warnIcon.style.fontSize = '20px';
        warnIcon.textContent = 'warning';
        const warnStrong = document.createElement('strong');
        warnStrong.textContent = 'This is the only time you will see this token.';
        warn.appendChild(warnIcon);
        warn.appendChild(warnStrong);
        warn.appendChild(document.createTextNode(' Copy it now and store it somewhere safe — it cannot be recovered.'));
        wrap.appendChild(warn);

        const meta = this._mintedTokenMeta || { name: '', scopes: [] };

        const metaBlock = document.createElement('div');
        metaBlock.className = 'app-token-reveal-meta';
        const appDiv = document.createElement('div');
        const appLbl = document.createElement('span');
        appLbl.className = 'settings-label';
        appLbl.textContent = 'App:';
        appDiv.appendChild(appLbl);
        appDiv.appendChild(document.createTextNode(' ' + (meta.name || '')));
        const permDiv = document.createElement('div');
        const permLbl = document.createElement('span');
        permLbl.className = 'settings-label';
        permLbl.textContent = 'Permissions:';
        permDiv.appendChild(permLbl);
        permDiv.appendChild(document.createTextNode(' ' + (meta.scopes || []).join(', ')));
        metaBlock.appendChild(appDiv);
        metaBlock.appendChild(permDiv);
        wrap.appendChild(metaBlock);

        const tokenLabel = document.createElement('label');
        tokenLabel.className = 'settings-label';
        tokenLabel.textContent = 'Token';
        wrap.appendChild(tokenLabel);

        const pre = document.createElement('pre');
        pre.id = 'appTokenPlaintext';
        pre.className = 'app-token-plaintext';
        // textContent is the only safe sink — the plaintext is opaque random data,
        // but even so, never interpolate it as HTML.
        pre.textContent = this._mintedPlaintext || '';
        wrap.appendChild(pre);

        const actions = document.createElement('div');
        actions.className = 'app-token-reveal-actions';
        const copyBtn = document.createElement('button');
        copyBtn.id = 'appTokenCopy';
        copyBtn.type = 'button';
        copyBtn.className = 'btn-secondary';
        const copyIcon = document.createElement('span');
        copyIcon.className = 'material-symbols-outlined mr-1';
        copyIcon.style.fontSize = '18px';
        copyIcon.textContent = 'content_copy';
        copyBtn.appendChild(copyIcon);
        copyBtn.appendChild(document.createTextNode('Copy'));
        copyBtn.addEventListener('click', () => this._handleCopyToken());
        const doneBtn = document.createElement('button');
        doneBtn.id = 'appTokenDoneReveal';
        doneBtn.type = 'button';
        doneBtn.className = 'btn-primary';
        doneBtn.textContent = 'Done';
        doneBtn.addEventListener('click', () => this._handleDoneReveal());
        actions.appendChild(copyBtn);
        actions.appendChild(doneBtn);
        wrap.appendChild(actions);

        const note = document.createElement('div');
        note.id = 'appTokenCopiedNote';
        note.className = 'mb-2 min-h-[1.2rem] text-sm text-accent-green hidden';
        note.textContent = 'Copied to clipboard';
        wrap.appendChild(note);

        container.appendChild(wrap);
    }

    _handleStartMint() {
        this._appTokensView = 'minting';
        this._renderAppTokensView();
    }

    _handleCancelMint() {
        this._appTokensView = 'list';
        this._renderAppTokensView();
    }

    async _handleSubmitMint() {
        const errorEl = document.getElementById('appTokenMintError');
        if (errorEl) errorEl.textContent = '';

        const nameEl = document.getElementById('appTokenName');
        const collectionReadEl = document.getElementById('appTokenScope_collectionRead');
        const name = nameEl ? nameEl.value.trim() : '';
        if (!name) {
            if (errorEl) errorEl.textContent = 'App name is required';
            return;
        }

        const scopes = [];
        if (collectionReadEl && collectionReadEl.checked) scopes.push('collection:read');
        if (scopes.length === 0) {
            if (errorEl) errorEl.textContent = 'Select at least one permission';
            return;
        }

        const token = window.authManager && window.authManager.getToken && window.authManager.getToken();
        if (!token) {
            if (errorEl) errorEl.textContent = 'You are not signed in';
            return;
        }

        const res = await window.apiClient.mintAppToken(token, name, scopes);
        if (!res || !res.ok || !res.body || !res.body.token) {
            const detail = (res && res.body && res.body.detail) ? res.body.detail : 'Failed to mint token';
            if (errorEl) errorEl.textContent = detail;
            return;
        }

        this._mintedPlaintext = res.body.token;
        this._mintedTokenMeta = { name: res.body.name, scopes: res.body.scopes };
        this._appTokensView = 'revealing';
        this._renderAppTokensView();
    }

    async _handleCopyToken() {
        if (!this._mintedPlaintext) return;
        try {
            await navigator.clipboard.writeText(this._mintedPlaintext);
            const note = document.getElementById('appTokenCopiedNote');
            if (note) {
                note.classList.remove('hidden');
                setTimeout(() => note.classList.add('hidden'), 2000);
            }
        } catch {
            // Clipboard write may be unavailable in some browsers/contexts.
        }
    }

    _handleDoneReveal() {
        this._mintedPlaintext = null;
        this._mintedTokenMeta = null;
        const plaintextEl = document.getElementById('appTokenPlaintext');
        if (plaintextEl) plaintextEl.textContent = '';
        this._appTokensView = 'list';
        this._loadAppTokens();
    }

    async _handleRevoke(tokenId, tokenName) {
        if (!tokenId) return;
        const confirmed = window.confirm(`Revoke the token "${tokenName}"?\n\nThis cannot be undone. Any app using it will lose access immediately.`);
        if (!confirmed) return;

        const token = window.authManager && window.authManager.getToken && window.authManager.getToken();
        if (!token) return;

        const ok = await window.apiClient.revokeAppToken(token, tokenId);
        if (!ok) {
            window.alert('Failed to revoke token. It may have already been revoked.');
        }
        this._loadAppTokens();
    }
}

window.settingsPane = new SettingsPane();
