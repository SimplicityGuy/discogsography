import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

// Mock QRCode global
globalThis.QRCode = vi.fn();
QRCode.CorrectLevel = { M: 1 };

function setupSettingsDOM() {
    document.body.textContent = '';

    // Profile elements
    for (const id of ['settingsEmail', 'settingsCreatedAt', 'settingsDiscogsStatus']) {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    }

    // Password form
    for (const id of ['settingsCurrentPassword', 'settingsNewPassword', 'settingsConfirmPassword']) {
        const inp = document.createElement('input');
        inp.id = id;
        inp.type = 'password';
        document.body.appendChild(inp);
    }

    // Password messages
    for (const id of ['passwordChangeError', 'passwordChangeSuccess']) {
        const el = document.createElement('div');
        el.id = id;
        el.classList.add('hidden');
        document.body.appendChild(el);
    }

    // Change password button
    const btn = document.createElement('button');
    btn.id = 'changePasswordBtn';
    document.body.appendChild(btn);

    // 2FA container
    const twoFa = document.createElement('div');
    twoFa.id = 'twoFactorContent';
    document.body.appendChild(twoFa);
}

function setupMocks() {
    window.authManager = {
        getUser: vi.fn().mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: false }),
        getDiscogsStatus: vi.fn().mockReturnValue(null),
        getToken: vi.fn().mockReturnValue('test-token'),
        updateTotpEnabled: vi.fn(),
    };

    window.apiClient = {
        changePassword: vi.fn().mockResolvedValue({ ok: true }),
        // Real /api/auth/2fa/setup returns secret, otpauth_uri, AND recovery_codes.
        twoFactorSetup: vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                secret: 'JBSWY3DPEHPK3PXP',
                otpauth_uri: 'otpauth://totp/test',
                recovery_codes: ['code1', 'code2', 'code3', 'code4'],
            }),
        }),
        // Real /api/auth/2fa/confirm returns only {message} — no codes.
        twoFactorConfirm: vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ message: '2FA has been enabled' }),
        }),
        twoFactorDisable: vi.fn().mockResolvedValue({ ok: true }),
    };
}

describe('SettingsPane', () => {
    beforeEach(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        setupSettingsDOM();
        setupMocks();
        QRCode.mockClear();
        loadScript('settings.js');
    });

    // ------------------------------------------------------------------ //
    // Constructor
    // ------------------------------------------------------------------ //

    describe('constructor', () => {
        it('should initialize with default state', () => {
            const pane = window.settingsPane;
            expect(pane._initialized).toBe(false);
            expect(pane._twoFaState).toBe('disabled');
            expect(pane._setupData).toBeNull();
            expect(pane._recoveryCodes).toBeNull();
        });
    });

    // ------------------------------------------------------------------ //
    // init
    // ------------------------------------------------------------------ //

    describe('init', () => {
        it('should call _loadProfile and _renderTwoFaState', () => {
            const pane = window.settingsPane;
            const loadSpy = vi.spyOn(pane, '_loadProfile');
            const renderSpy = vi.spyOn(pane, '_renderTwoFaState');

            pane.init();

            expect(loadSpy).toHaveBeenCalled();
            expect(renderSpy).toHaveBeenCalled();
        });

        it('should bind events only once', () => {
            const pane = window.settingsPane;
            const bindSpy = vi.spyOn(pane, '_bindEvents');

            pane.init();
            expect(bindSpy).toHaveBeenCalledTimes(1);
            expect(pane._initialized).toBe(true);

            pane.init();
            expect(bindSpy).toHaveBeenCalledTimes(1);
        });
    });

    // ------------------------------------------------------------------ //
    // _loadProfile
    // ------------------------------------------------------------------ //

    describe('_loadProfile', () => {
        it('should populate email', () => {
            window.settingsPane.init();
            expect(document.getElementById('settingsEmail').textContent).toBe('user@test.com');
        });

        it('should format created_at date', () => {
            window.authManager.getUser.mockReturnValue({
                id: 1, email: 'user@test.com', created_at: '2024-06-15T10:30:00Z', totp_enabled: false,
            });
            window.settingsPane.init();
            const text = document.getElementById('settingsCreatedAt').textContent;
            // Date should contain "June" and "2024" regardless of locale
            expect(text).toContain('2024');
        });

        it('should show empty string when no created_at', () => {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: false });
            window.settingsPane.init();
            expect(document.getElementById('settingsCreatedAt').textContent).toBe('');
        });

        it('should show Discogs connected badge when connected', () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: true, username: 'dj_test' });
            window.settingsPane.init();
            const el = document.getElementById('settingsDiscogsStatus');
            const badge = el.querySelector('.twofa-badge-enabled');
            expect(badge).not.toBeNull();
            expect(badge.textContent).toBe('Connected');
        });

        it('should show Discogs username when available', () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: true, username: 'dj_test' });
            window.settingsPane.init();
            const el = document.getElementById('settingsDiscogsStatus');
            expect(el.textContent).toContain('dj_test');
        });

        it('should show "Not connected" when Discogs not connected', () => {
            window.authManager.getDiscogsStatus.mockReturnValue(null);
            window.settingsPane.init();
            expect(document.getElementById('settingsDiscogsStatus').textContent).toBe('Not connected');
        });

        it('should derive totp_enabled = true as enabled state', () => {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: true });
            window.settingsPane.init();
            expect(window.settingsPane._twoFaState).toBe('enabled');
        });

        it('should derive totp_enabled = false as disabled state', () => {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: false });
            window.settingsPane.init();
            expect(window.settingsPane._twoFaState).toBe('disabled');
        });

        it('should return early when no user', () => {
            window.authManager.getUser.mockReturnValue(null);
            window.settingsPane.init();
            expect(document.getElementById('settingsEmail').textContent).toBe('');
        });
    });

    // ------------------------------------------------------------------ //
    // _handleChangePassword
    // ------------------------------------------------------------------ //

    describe('_handleChangePassword', () => {
        it('should show error when current password is empty', async () => {
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = '';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('Current password is required');
        });

        it('should show error when new password is too short', async () => {
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'oldpass';
            document.getElementById('settingsNewPassword').value = 'short';
            document.getElementById('settingsConfirmPassword').value = 'short';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('New password must be at least 8 characters');
        });

        it('should show error when passwords do not match', async () => {
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'oldpass';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword2';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('Passwords do not match');
        });

        it('should show success and clear form on successful change', async () => {
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'oldpass';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword1';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeSuccess').textContent).toBe('Password changed successfully');
            expect(document.getElementById('settingsCurrentPassword').value).toBe('');
            expect(document.getElementById('settingsNewPassword').value).toBe('');
            expect(document.getElementById('settingsConfirmPassword').value).toBe('');
        });

        it('should show API error detail on failure', async () => {
            window.apiClient.changePassword.mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Incorrect password' }),
            });
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'wrong';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword1';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('Incorrect password');
        });

        it('should show generic error on API failure without detail', async () => {
            window.apiClient.changePassword.mockResolvedValue({
                ok: false,
                json: async () => ({}),
            });
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'wrong';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword1';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('Failed to change password');
        });

        it('should show network error on fetch failure', async () => {
            window.apiClient.changePassword.mockRejectedValue(new Error('Network error'));
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'old';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword1';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('Network error — please try again');
        });

        it('should show error when not authenticated', async () => {
            window.authManager.getToken.mockReturnValue(null);
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'old';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword1';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('passwordChangeError').textContent).toBe('Not authenticated');
        });

        it('should re-enable button after completion', async () => {
            window.settingsPane.init();
            document.getElementById('settingsCurrentPassword').value = 'old';
            document.getElementById('settingsNewPassword').value = 'newpassword1';
            document.getElementById('settingsConfirmPassword').value = 'newpassword1';

            await window.settingsPane._handleChangePassword();

            expect(document.getElementById('changePasswordBtn').disabled).toBe(false);
        });
    });

    // ------------------------------------------------------------------ //
    // 2FA state: disabled
    // ------------------------------------------------------------------ //

    describe('2FA state: disabled', () => {
        it('should render disabled badge and enable button', () => {
            window.settingsPane.init();
            const container = document.getElementById('twoFactorContent');
            const badge = container.querySelector('.twofa-badge-disabled');
            expect(badge).not.toBeNull();
            expect(badge.textContent).toBe('Disabled');
            expect(container.textContent).toContain('Enable 2FA');
        });
    });

    // ------------------------------------------------------------------ //
    // 2FA state: enabled
    // ------------------------------------------------------------------ //

    describe('2FA state: enabled', () => {
        it('should render enabled badge and disable button', () => {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: true });
            window.settingsPane.init();
            const container = document.getElementById('twoFactorContent');
            const badge = container.querySelector('.twofa-badge-enabled');
            expect(badge).not.toBeNull();
            expect(badge.textContent).toBe('Enabled');
            expect(container.textContent).toContain('Disable 2FA');
        });

        it('should transition to disableConfirm on disable button click', () => {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: true });
            window.settingsPane.init();
            const container = document.getElementById('twoFactorContent');
            const disableBtn = container.querySelector('.btn-danger');
            disableBtn.click();

            expect(window.settingsPane._twoFaState).toBe('disableConfirm');
            // Should now show the disable confirm UI
            expect(container.textContent).toContain('Authenticator Code');
        });
    });

    // ------------------------------------------------------------------ //
    // 2FA state: setup
    // ------------------------------------------------------------------ //

    describe('2FA state: setup', () => {
        it('should render QR code, manual secret, and TOTP inputs after _startSetup', async () => {
            window.settingsPane.init();

            await window.settingsPane._startSetup();

            const container = document.getElementById('twoFactorContent');
            expect(QRCode).toHaveBeenCalled();
            expect(container.textContent).toContain('JBSWY3DPEHPK3PXP');
            expect(container.textContent).toContain('Verify & Enable');
            expect(container.textContent).toContain('Cancel');
        });

        it('should show 6 TOTP input fields', async () => {
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            const inputs = document.querySelectorAll('[data-setup-totp]');
            expect(inputs.length).toBe(6);
        });

        it('should cancel setup and return to disabled', async () => {
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            const container = document.getElementById('twoFactorContent');
            const cancelBtn = Array.from(container.querySelectorAll('button')).find(b => b.textContent === 'Cancel');
            cancelBtn.click();

            expect(window.settingsPane._twoFaState).toBe('disabled');
            expect(window.settingsPane._setupData).toBeNull();
        });
    });

    // ------------------------------------------------------------------ //
    // 2FA state: recovery
    // ------------------------------------------------------------------ //

    describe('2FA state: recovery', () => {
        async function setupRecoveryState() {
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            // Fill TOTP inputs
            const inputs = document.querySelectorAll('[data-setup-totp]');
            '123456'.split('').forEach((d, i) => { inputs[i].value = d; });

            await window.settingsPane._confirmSetup();
        }

        it('should render warning, codes grid, and buttons', async () => {
            await setupRecoveryState();
            const container = document.getElementById('twoFactorContent');
            expect(container.textContent).toContain('Save these recovery codes');
            expect(container.textContent).toContain('code1');
            expect(container.textContent).toContain('code4');
            expect(container.textContent).toContain('Copy Codes');
            expect(container.textContent).toContain("I've Saved My Codes");
        });

        it('should call updateTotpEnabled(true) on confirm', async () => {
            await setupRecoveryState();
            expect(window.authManager.updateTotpEnabled).toHaveBeenCalledWith(true);
        });

        it('should transition to enabled when done button is clicked', async () => {
            await setupRecoveryState();
            const container = document.getElementById('twoFactorContent');
            const doneBtn = Array.from(container.querySelectorAll('button')).find(b => b.textContent === "I've Saved My Codes");
            doneBtn.click();

            expect(window.settingsPane._twoFaState).toBe('enabled');
            expect(window.settingsPane._recoveryCodes).toBeNull();
        });

        it('should copy codes when copy button is clicked', async () => {
            const writeTextMock = vi.fn().mockResolvedValue(undefined);
            navigator.clipboard = { writeText: writeTextMock };

            await setupRecoveryState();
            const container = document.getElementById('twoFactorContent');
            const copyBtn = Array.from(container.querySelectorAll('button')).find(b => b.textContent.includes('Copy'));
            copyBtn.click();

            expect(writeTextMock).toHaveBeenCalledWith('code1\ncode2\ncode3\ncode4');
        });
    });

    // ------------------------------------------------------------------ //
    // 2FA state: disableConfirm
    // ------------------------------------------------------------------ //

    describe('2FA state: disableConfirm', () => {
        function enterDisableConfirm() {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: true });
            window.settingsPane.init();
            // Click disable button to enter disableConfirm state
            const disableBtn = document.getElementById('twoFactorContent').querySelector('.btn-danger');
            disableBtn.click();
        }

        it('should render TOTP inputs, password field, and buttons', () => {
            enterDisableConfirm();
            const container = document.getElementById('twoFactorContent');
            expect(container.textContent).toContain('Authenticator Code');
            expect(container.textContent).toContain('Password');
            expect(document.getElementById('disableTotpPassword')).not.toBeNull();
            expect(container.textContent).toContain('Disable 2FA');
            expect(container.textContent).toContain('Cancel');
        });

        it('should cancel and return to enabled state', () => {
            enterDisableConfirm();
            const container = document.getElementById('twoFactorContent');
            const cancelBtn = Array.from(container.querySelectorAll('button')).find(b => b.textContent === 'Cancel');
            cancelBtn.click();

            expect(window.settingsPane._twoFaState).toBe('enabled');
        });

        it('should render 6 disable TOTP inputs', () => {
            enterDisableConfirm();
            const inputs = document.querySelectorAll('[data-disable-totp]');
            expect(inputs.length).toBe(6);
        });
    });

    // ------------------------------------------------------------------ //
    // _startSetup
    // ------------------------------------------------------------------ //

    describe('_startSetup', () => {
        it('should transition to setup state on success', async () => {
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            expect(window.settingsPane._twoFaState).toBe('setup');
            expect(window.settingsPane._setupData).toEqual({
                secret: 'JBSWY3DPEHPK3PXP',
                otpauth_uri: 'otpauth://totp/test',
                recovery_codes: ['code1', 'code2', 'code3', 'code4'],
            });
        });

        it('should show error on API failure', async () => {
            window.apiClient.twoFactorSetup.mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Setup failed' }),
            });
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            const container = document.getElementById('twoFactorContent');
            expect(container.textContent).toContain('Setup failed');
            expect(window.settingsPane._twoFaState).toBe('disabled');
        });

        it('should do nothing when not authenticated', async () => {
            window.authManager.getToken.mockReturnValue(null);
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            expect(window.apiClient.twoFactorSetup).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // _confirmSetup
    // ------------------------------------------------------------------ //

    describe('_confirmSetup', () => {
        async function enterSetupState() {
            window.settingsPane.init();
            await window.settingsPane._startSetup();
        }

        it('should transition to recovery on valid code', async () => {
            await enterSetupState();
            const inputs = document.querySelectorAll('[data-setup-totp]');
            '123456'.split('').forEach((d, i) => { inputs[i].value = d; });

            await window.settingsPane._confirmSetup();

            expect(window.settingsPane._twoFaState).toBe('recovery');
            expect(window.authManager.updateTotpEnabled).toHaveBeenCalledWith(true);
        });

        it('should show error on invalid code format', async () => {
            await enterSetupState();
            // Leave inputs empty

            await window.settingsPane._confirmSetup();

            expect(document.getElementById('setupTotpError').textContent).toBe('Please enter a 6-digit code');
        });

        it('should show API error on failure', async () => {
            window.apiClient.twoFactorConfirm.mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Wrong TOTP code' }),
            });
            await enterSetupState();
            const inputs = document.querySelectorAll('[data-setup-totp]');
            '123456'.split('').forEach((d, i) => { inputs[i].value = d; });

            await window.settingsPane._confirmSetup();

            expect(document.getElementById('setupTotpError').textContent).toBe('Wrong TOTP code');
        });

        it('should show network error on exception', async () => {
            window.apiClient.twoFactorConfirm.mockRejectedValue(new Error('fail'));
            await enterSetupState();
            const inputs = document.querySelectorAll('[data-setup-totp]');
            '123456'.split('').forEach((d, i) => { inputs[i].value = d; });

            await window.settingsPane._confirmSetup();

            expect(document.getElementById('setupTotpError').textContent).toBe('Network error — please try again');
        });
    });

    // ------------------------------------------------------------------ //
    // _handleDisable
    // ------------------------------------------------------------------ //

    describe('_handleDisable', () => {
        function enterDisableConfirm() {
            window.authManager.getUser.mockReturnValue({ id: 1, email: 'user@test.com', totp_enabled: true });
            window.settingsPane.init();
            const disableBtn = document.getElementById('twoFactorContent').querySelector('.btn-danger');
            disableBtn.click();
        }

        it('should transition to disabled on success', async () => {
            enterDisableConfirm();
            const inputs = document.querySelectorAll('[data-disable-totp]');
            '654321'.split('').forEach((d, i) => { inputs[i].value = d; });
            document.getElementById('disableTotpPassword').value = 'mypassword';

            await window.settingsPane._handleDisable();

            expect(window.settingsPane._twoFaState).toBe('disabled');
            expect(window.authManager.updateTotpEnabled).toHaveBeenCalledWith(false);
        });

        it('should show error when password is missing', async () => {
            enterDisableConfirm();
            const inputs = document.querySelectorAll('[data-disable-totp]');
            '654321'.split('').forEach((d, i) => { inputs[i].value = d; });
            document.getElementById('disableTotpPassword').value = '';

            await window.settingsPane._handleDisable();

            expect(document.getElementById('disableTotpError').textContent).toBe('Password is required');
        });

        it('should show error when TOTP code is incomplete', async () => {
            enterDisableConfirm();
            document.getElementById('disableTotpPassword').value = 'mypassword';

            await window.settingsPane._handleDisable();

            expect(document.getElementById('disableTotpError').textContent).toBe('Please enter a 6-digit code');
        });

        it('should show API error on failure', async () => {
            window.apiClient.twoFactorDisable.mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Invalid TOTP code' }),
            });
            enterDisableConfirm();
            const inputs = document.querySelectorAll('[data-disable-totp]');
            '654321'.split('').forEach((d, i) => { inputs[i].value = d; });
            document.getElementById('disableTotpPassword').value = 'pass';

            await window.settingsPane._handleDisable();

            expect(document.getElementById('disableTotpError').textContent).toBe('Invalid TOTP code');
        });

        it('should show network error on exception', async () => {
            window.apiClient.twoFactorDisable.mockRejectedValue(new Error('fail'));
            enterDisableConfirm();
            const inputs = document.querySelectorAll('[data-disable-totp]');
            '654321'.split('').forEach((d, i) => { inputs[i].value = d; });
            document.getElementById('disableTotpPassword').value = 'pass';

            await window.settingsPane._handleDisable();

            expect(document.getElementById('disableTotpError').textContent).toBe('Network error — please try again');
        });
    });

    // ------------------------------------------------------------------ //
    // TOTP helpers
    // ------------------------------------------------------------------ //

    describe('TOTP helpers', () => {
        it('_collectTotpCode should return joined 6-digit string', async () => {
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            const inputs = document.querySelectorAll('[data-setup-totp]');
            '789012'.split('').forEach((d, i) => { inputs[i].value = d; });

            const code = window.settingsPane._collectTotpCode('setupTotp');
            expect(code).toBe('789012');
        });

        it('_clearTotpInputs should clear all inputs', async () => {
            window.settingsPane.init();
            await window.settingsPane._startSetup();

            const inputs = document.querySelectorAll('[data-setup-totp]');
            '123456'.split('').forEach((d, i) => { inputs[i].value = d; });

            window.settingsPane._clearTotpInputs('setupTotp');
            inputs.forEach(inp => expect(inp.value).toBe(''));
        });

        it('_camelToKebab should convert camelCase to kebab-case', () => {
            expect(window.settingsPane._camelToKebab('setupTotp')).toBe('setup-totp');
            expect(window.settingsPane._camelToKebab('disableTotp')).toBe('disable-totp');
            expect(window.settingsPane._camelToKebab('myLongName')).toBe('my-long-name');
        });
    });
});
