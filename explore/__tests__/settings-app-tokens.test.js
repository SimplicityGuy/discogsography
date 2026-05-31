/**
 * Tests for the App Tokens (Connected Apps) settings card in settings.js.
 *
 * Uses fake timers per project memory (leaked-timer flake) for the
 * setTimeout in _handleCopyToken.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { loadScript } from './helpers.js';

globalThis.QRCode = vi.fn();
QRCode.CorrectLevel = { M: 1 };

function setupDOM() {
    document.body.textContent = '';
    // Bare minimum elements settings.js touches during init()
    for (const id of [
        'settingsEmail', 'settingsCreatedAt', 'settingsDiscogsStatus',
        'settingsCurrentPassword', 'settingsNewPassword', 'settingsConfirmPassword',
        'passwordChangeError', 'passwordChangeSuccess', 'changePasswordBtn',
        'twoFactorContent', 'settingsAppTokensCard',
    ]) {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    }
    // The container the app-tokens card renders into
    const container = document.createElement('div');
    container.id = 'appTokensContent';
    document.body.appendChild(container);
    return container;
}

function setupMocks(opts = {}) {
    window.authManager = {
        getUser: vi.fn().mockReturnValue({ id: 1, email: 'u@test.com', totp_enabled: false }),
        getDiscogsStatus: vi.fn().mockReturnValue(null),
        getToken: vi.fn().mockReturnValue(opts.signedOut ? null : 'test-token'),
        updateTotpEnabled: vi.fn(),
    };
    window.apiClient = {
        // Stubs for parts of settings.js init() that we don't care about
        changePassword: vi.fn().mockResolvedValue({ ok: true }),
        twoFactorSetup: vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }),
        twoFactorConfirm: vi.fn(),
        twoFactorVerify: vi.fn(),
        twoFactorRecovery: vi.fn(),
        twoFactorDisable: vi.fn(),
        // The actual app token surface
        listAppTokens: vi.fn().mockResolvedValue(opts.listResponse ?? { active: [], revoked: [] }),
        mintAppToken: vi.fn().mockResolvedValue({
            ok: true,
            status: 201,
            body: { id: 'tok-1', name: 'kiosk', scopes: ['collection:read'], token: 'dscg_secret_plaintext_value', created_at: '2026-05-26T00:00:00Z' },
        }),
        revokeAppToken: vi.fn().mockResolvedValue(true),
    };
}

async function flush() {
    // Allow microtask queue to drain so awaits in init() complete before assertions.
    await new Promise(resolve => setTimeout(resolve, 0));
}

describe('SettingsPane — App Tokens card', () => {
    let container;

    beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        container = setupDOM();
        setupMocks();
        loadScript('settings.js');
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    describe('list view', () => {
        it('renders empty state when no active tokens', async () => {
            window.settingsPane.init();
            await flush();

            expect(window.apiClient.listAppTokens).toHaveBeenCalledWith('test-token');
            expect(container.textContent).toContain('No connected apps yet');
            const mintBtn = container.querySelector('#appTokenMintBtn');
            expect(mintBtn).toBeTruthy();
        });

        it('renders active tokens with name, scope, and revoke button', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{
                    id: 'tok-a', name: 'GRUVAX kiosk', scopes: ['collection:read'],
                    created_at: '2026-05-26T00:00:00Z', last_used_at: null,
                }],
                revoked: [],
            });
            window.settingsPane.init();
            await flush();

            expect(container.textContent).toContain('GRUVAX kiosk');
            expect(container.textContent).toContain('collection:read');
            expect(container.querySelector('[data-token-id="tok-a"]')).toBeTruthy();
            expect(container.querySelector('.app-token-revoke')).toBeTruthy();
        });

        it('renders revoked tokens in a separate audit trail section', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [],
                revoked: [{ id: 'tok-b', name: 'old-kiosk', revoked_at: '2026-05-25T00:00:00Z' }],
            });
            window.settingsPane.init();
            await flush();

            expect(container.textContent).toContain('Revoked (audit trail)');
            expect(container.textContent).toContain('old-kiosk');
        });

        it('renders sign-in prompt when not authenticated', async () => {
            setupMocks({ signedOut: true });
            window.settingsPane.init();
            await flush();

            expect(container.textContent).toContain('Sign in to manage');
            expect(window.apiClient.listAppTokens).not.toHaveBeenCalled();
        });

        it('escapes token names safely — XSS-impossible via textContent', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{ id: 'tok-x', name: '<script>alert(1)</script>', scopes: ['collection:read'], created_at: null, last_used_at: null }],
                revoked: [],
            });
            window.settingsPane.init();
            await flush();

            // The literal text appears, but as text — never as DOM
            const nameEl = container.querySelector('.app-token-name');
            expect(nameEl.textContent).toBe('<script>alert(1)</script>');
            expect(container.querySelector('script')).toBeNull();
        });
    });

    describe('mint flow', () => {
        it('switches to mint form when Connect button is clicked', async () => {
            window.settingsPane.init();
            await flush();

            container.querySelector('#appTokenMintBtn').click();

            expect(container.querySelector('#appTokenName')).toBeTruthy();
            expect(container.querySelector('#appTokenScope_collectionRead')).toBeTruthy();
            expect(container.querySelector('#appTokenSubmitMint')).toBeTruthy();
        });

        it('rejects empty name with inline error', async () => {
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();

            container.querySelector('#appTokenName').value = '';
            container.querySelector('#appTokenSubmitMint').click();
            await flush();

            expect(container.querySelector('#appTokenMintError').textContent).toContain('App name is required');
            expect(window.apiClient.mintAppToken).not.toHaveBeenCalled();
        });

        it('calls mintAppToken and switches to reveal view on success', async () => {
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();

            container.querySelector('#appTokenName').value = 'GRUVAX kiosk';
            container.querySelector('#appTokenSubmitMint').click();
            await flush();

            expect(window.apiClient.mintAppToken).toHaveBeenCalledWith('test-token', 'GRUVAX kiosk', ['collection:read']);
            const plaintextEl = container.querySelector('#appTokenPlaintext');
            expect(plaintextEl).toBeTruthy();
            expect(plaintextEl.textContent).toBe('dscg_secret_plaintext_value');
            expect(container.textContent).toContain('only time you will see this token');
        });

        it('shows API error detail inline when mint fails', async () => {
            window.apiClient.mintAppToken.mockResolvedValue({
                ok: false, status: 400, body: { detail: 'Unknown scope(s): foo' },
            });
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();
            container.querySelector('#appTokenName').value = 'kiosk';
            container.querySelector('#appTokenSubmitMint').click();
            await flush();

            expect(container.querySelector('#appTokenMintError').textContent).toContain('Unknown scope');
            // Stayed on the mint form, not the reveal screen
            expect(container.querySelector('#appTokenPlaintext')).toBeNull();
        });

        it('rejects when no permission scope is checked', async () => {
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();
            container.querySelector('#appTokenName').value = 'kiosk';
            container.querySelector('#appTokenScope_collectionRead').checked = false;
            container.querySelector('#appTokenSubmitMint').click();
            await flush();

            expect(container.querySelector('#appTokenMintError').textContent).toContain('Select at least one permission');
            expect(window.apiClient.mintAppToken).not.toHaveBeenCalled();
        });

        it('shows "not signed in" error if token disappears between form open and submit', async () => {
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();
            container.querySelector('#appTokenName').value = 'kiosk';

            // Simulate sign-out after the form is open
            window.authManager.getToken = vi.fn().mockReturnValue(null);
            container.querySelector('#appTokenSubmitMint').click();
            await flush();

            expect(container.querySelector('#appTokenMintError').textContent).toContain('not signed in');
            expect(window.apiClient.mintAppToken).not.toHaveBeenCalled();
        });

        it('Cancel returns to list without minting', async () => {
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();
            container.querySelector('#appTokenCancelMint').click();
            await flush();

            expect(container.querySelector('#appTokenName')).toBeNull();
            expect(container.querySelector('#appTokenMintBtn')).toBeTruthy();
            expect(window.apiClient.mintAppToken).not.toHaveBeenCalled();
        });
    });

    describe('reveal screen', () => {
        async function reachRevealScreen() {
            window.settingsPane.init();
            await flush();
            container.querySelector('#appTokenMintBtn').click();
            container.querySelector('#appTokenName').value = 'kiosk';
            container.querySelector('#appTokenSubmitMint').click();
            await flush();
        }

        it('Done clears the plaintext from DOM and reloads list', async () => {
            await reachRevealScreen();
            expect(container.querySelector('#appTokenPlaintext').textContent).toBe('dscg_secret_plaintext_value');

            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{ id: 'tok-1', name: 'kiosk', scopes: ['collection:read'], created_at: null, last_used_at: null }],
                revoked: [],
            });
            container.querySelector('#appTokenDoneReveal').click();
            await flush();

            // Plaintext element gone (back on list view); name appears as a row instead.
            expect(container.querySelector('#appTokenPlaintext')).toBeNull();
            expect(container.textContent).toContain('kiosk');
            expect(container.querySelector('[data-token-id="tok-1"]')).toBeTruthy();
        });

        it('Copy button writes plaintext to clipboard', async () => {
            const writeText = vi.fn().mockResolvedValue(undefined);
            Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

            await reachRevealScreen();
            container.querySelector('#appTokenCopy').click();
            await flush();

            expect(writeText).toHaveBeenCalledWith('dscg_secret_plaintext_value');
        });

        it('Copy shows then hides the "Copied" note after 2s', async () => {
            const writeText = vi.fn().mockResolvedValue(undefined);
            Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

            await reachRevealScreen();
            container.querySelector('#appTokenCopy').click();
            // Resolve the writeText promise + scheduling
            await flush();

            const note = container.querySelector('#appTokenCopiedNote');
            expect(note).toBeTruthy();
            expect(note.classList.contains('hidden')).toBe(false);

            // Advance fake timers by 2s → the setTimeout callback re-adds 'hidden'
            vi.advanceTimersByTime(2000);
            expect(note.classList.contains('hidden')).toBe(true);
        });

        it('Copy silently swallows a clipboard write rejection', async () => {
            const writeText = vi.fn().mockRejectedValue(new Error('clipboard unavailable'));
            Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

            await reachRevealScreen();
            // Must not throw, must not exit reveal view
            container.querySelector('#appTokenCopy').click();
            await flush();

            expect(writeText).toHaveBeenCalled();
            // Still on the reveal screen
            expect(container.querySelector('#appTokenPlaintext')).toBeTruthy();
        });
    });

    describe('revoke flow', () => {
        it('confirms then calls revokeAppToken', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{ id: 'tok-a', name: 'kiosk', scopes: ['collection:read'], created_at: null, last_used_at: null }],
                revoked: [],
            });
            window.confirm = vi.fn().mockReturnValue(true);
            window.settingsPane.init();
            await flush();

            container.querySelector('.app-token-revoke').click();
            await flush();

            expect(window.confirm).toHaveBeenCalled();
            expect(window.apiClient.revokeAppToken).toHaveBeenCalledWith('test-token', 'tok-a');
        });

        it('does NOT call API when user cancels the confirm dialog', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{ id: 'tok-a', name: 'kiosk', scopes: ['collection:read'], created_at: null, last_used_at: null }],
                revoked: [],
            });
            window.confirm = vi.fn().mockReturnValue(false);
            window.settingsPane.init();
            await flush();

            container.querySelector('.app-token-revoke').click();
            await flush();

            expect(window.apiClient.revokeAppToken).not.toHaveBeenCalled();
        });

        it('alerts the user when the revoke API call fails', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{ id: 'tok-a', name: 'kiosk', scopes: ['collection:read'], created_at: null, last_used_at: null }],
                revoked: [],
            });
            window.apiClient.revokeAppToken.mockResolvedValue(false);
            window.confirm = vi.fn().mockReturnValue(true);
            const alertSpy = vi.fn();
            window.alert = alertSpy;

            window.settingsPane.init();
            await flush();
            container.querySelector('.app-token-revoke').click();
            await flush();

            expect(alertSpy).toHaveBeenCalled();
            // Subsequent _loadAppTokens still runs
            expect(window.apiClient.listAppTokens).toHaveBeenCalledTimes(2);
        });

        it('is a no-op when the token row has no id', async () => {
            window.confirm = vi.fn();
            // Reach the revoke handler with an empty id directly
            window.settingsPane._handleRevoke('', 'kiosk');
            await flush();
            expect(window.confirm).not.toHaveBeenCalled();
            expect(window.apiClient.revokeAppToken).not.toHaveBeenCalled();
        });

        it('is a no-op when user is signed out at revoke time', async () => {
            // Sign user out between list-load and revoke-click
            window.apiClient.listAppTokens.mockResolvedValue({
                active: [{ id: 'tok-a', name: 'kiosk', scopes: ['collection:read'], created_at: null, last_used_at: null }],
                revoked: [],
            });
            window.confirm = vi.fn().mockReturnValue(true);
            window.settingsPane.init();
            await flush();

            // After list loads, simulate sign-out
            window.authManager.getToken = vi.fn().mockReturnValue(null);
            container.querySelector('.app-token-revoke').click();
            await flush();

            expect(window.apiClient.revokeAppToken).not.toHaveBeenCalled();
        });
    });

    describe('listAppTokens error handling', () => {
        it('falls back to empty arrays when listAppTokens throws', async () => {
            window.apiClient.listAppTokens.mockRejectedValue(new Error('network down'));
            window.settingsPane.init();
            await flush();

            // List view still rendered, no thrown error reaches the user
            expect(container.textContent).toContain('No connected apps yet');
        });

        it('falls back to empty arrays when listAppTokens returns malformed shape', async () => {
            window.apiClient.listAppTokens.mockResolvedValue({ not_active: 'oops' });
            window.settingsPane.init();
            await flush();

            expect(container.textContent).toContain('No connected apps yet');
        });
    });
});
