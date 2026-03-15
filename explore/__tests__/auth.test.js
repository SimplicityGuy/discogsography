import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript, createMockFetch } from './helpers.js';

describe('AuthManager', () => {
    beforeEach(() => {
        localStorage.clear();
        delete globalThis.window;
        globalThis.window = globalThis;
        loadScript('auth.js');
    });

    describe('initial state', () => {
        it('should start logged out with no stored token', () => {
            expect(window.authManager.isLoggedIn()).toBe(false);
            expect(window.authManager.getToken()).toBeNull();
            expect(window.authManager.getUser()).toBeNull();
            expect(window.authManager.getDiscogsStatus()).toBeNull();
        });

        it('should restore token from localStorage', () => {
            localStorage.setItem('auth_token', 'stored-token');
            // Re-load to pick up stored token
            loadScript('auth.js');

            expect(window.authManager.isLoggedIn()).toBe(true);
            expect(window.authManager.getToken()).toBe('stored-token');
        });
    });

    describe('setToken', () => {
        it('should persist token to localStorage', () => {
            window.authManager.setToken('new-token');

            expect(window.authManager.getToken()).toBe('new-token');
            expect(window.authManager.isLoggedIn()).toBe(true);
            expect(localStorage.getItem('auth_token')).toBe('new-token');
        });

        it('should remove token from localStorage when set to null', () => {
            localStorage.setItem('auth_token', 'old-token');
            window.authManager.setToken(null);

            expect(window.authManager.getToken()).toBeNull();
            expect(window.authManager.isLoggedIn()).toBe(false);
            expect(localStorage.getItem('auth_token')).toBeNull();
        });
    });

    describe('setUser and setDiscogsStatus', () => {
        it('should store and retrieve user object', () => {
            const user = { id: 1, email: 'test@example.com' };
            window.authManager.setUser(user);
            expect(window.authManager.getUser()).toEqual(user);
        });

        it('should store and retrieve Discogs status', () => {
            const status = { connected: true, username: 'dj_test' };
            window.authManager.setDiscogsStatus(status);
            expect(window.authManager.getDiscogsStatus()).toEqual(status);
        });
    });

    describe('clear', () => {
        it('should clear all auth state and localStorage', () => {
            window.authManager.setToken('token');
            window.authManager.setUser({ id: 1 });
            window.authManager.setDiscogsStatus({ connected: true });

            window.authManager.clear();

            expect(window.authManager.getToken()).toBeNull();
            expect(window.authManager.getUser()).toBeNull();
            expect(window.authManager.getDiscogsStatus()).toBeNull();
            expect(window.authManager.isLoggedIn()).toBe(false);
            expect(localStorage.getItem('auth_token')).toBeNull();
        });
    });

    describe('onChange and notify', () => {
        it('should call registered listeners on notify', () => {
            const listener = vi.fn();
            window.authManager.onChange(listener);
            window.authManager.setToken('token');

            window.authManager.notify();

            expect(listener).toHaveBeenCalledWith(true);
        });

        it('should call multiple listeners', () => {
            const listener1 = vi.fn();
            const listener2 = vi.fn();
            window.authManager.onChange(listener1);
            window.authManager.onChange(listener2);

            window.authManager.notify();

            expect(listener1).toHaveBeenCalled();
            expect(listener2).toHaveBeenCalled();
        });

        it('should pass false when logged out', () => {
            const listener = vi.fn();
            window.authManager.onChange(listener);

            window.authManager.notify();

            expect(listener).toHaveBeenCalledWith(false);
        });
    });

    describe('init', () => {
        it('should return false and stay logged out when no token', async () => {
            const result = await window.authManager.init();
            expect(result).toBe(false);
        });

        it('should validate token and set user on success', async () => {
            localStorage.setItem('auth_token', 'valid-token');
            loadScript('auth.js');

            // Mock apiClient on window
            window.apiClient = {
                getMe: vi.fn().mockResolvedValue({ id: 1, email: 'user@test.com' }),
                getDiscogsStatus: vi.fn().mockResolvedValue({ connected: false }),
            };

            const result = await window.authManager.init();

            expect(result).toBe(true);
            expect(window.authManager.getUser()).toEqual({ id: 1, email: 'user@test.com' });
            expect(window.authManager.getDiscogsStatus()).toEqual({ connected: false });
        });

        it('should clear state when token is invalid', async () => {
            localStorage.setItem('auth_token', 'invalid-token');
            loadScript('auth.js');

            window.apiClient = {
                getMe: vi.fn().mockResolvedValue(null),
            };

            const result = await window.authManager.init();

            expect(result).toBe(false);
            expect(window.authManager.isLoggedIn()).toBe(false);
            expect(localStorage.getItem('auth_token')).toBeNull();
        });
    });
});
