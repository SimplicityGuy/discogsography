/**
 * Auth state manager for the Explore frontend.
 * Handles JWT token storage, user state, and auth events.
 */
class AuthManager {
    constructor() {
        this._token = localStorage.getItem('auth_token');
        this._user = null;
        this._discogsStatus = null;
        this._listeners = [];
        this._challengeToken = null;

        // Sync auth state across tabs: a logout (or token change) in one tab
        // only clears that tab's localStorage/memory (see clear()) — without
        // this, a second open tab keeps its stale in-memory token and shows
        // the user as logged in indefinitely (discogsography-ponr).
        if (typeof window !== 'undefined' && window.addEventListener) {
            window.addEventListener('storage', (e) => this._onStorageEvent(e));
        }
    }

    /**
     * Cross-tab sync: react to another tab changing/clearing `auth_token`.
     * @param {StorageEvent} e
     */
    _onStorageEvent(e) {
        if (e.key !== 'auth_token') return;
        if (e.newValue === this._token) return;
        this._token = e.newValue || null;
        if (!this._token) {
            this._user = null;
            this._discogsStatus = null;
        }
        this.notify();
    }

    /** Whether the user is currently logged in. */
    isLoggedIn() {
        return Boolean(this._token);
    }

    /** Current JWT token or null. */
    getToken() {
        return this._token;
    }

    /** Current user object {id, email} or null. */
    getUser() {
        return this._user;
    }

    /** Discogs connection status or null. */
    getDiscogsStatus() {
        return this._discogsStatus;
    }

    /** Persist token and notify listeners. */
    setToken(token) {
        this._token = token;
        if (token) {
            localStorage.setItem('auth_token', token);
        } else {
            localStorage.removeItem('auth_token');
        }
    }

    /** Store user info. */
    setUser(user) {
        this._user = user;
    }

    /** Store Discogs status. */
    setDiscogsStatus(status) {
        this._discogsStatus = status;
    }

    setChallengeToken(token) { this._challengeToken = token; }
    getChallengeToken() { return this._challengeToken; }
    clearChallenge() { this._challengeToken = null; }

    /** Clear all auth state (logout). */
    clear() {
        this._token = null;
        this._user = null;
        this._discogsStatus = null;
        localStorage.removeItem('auth_token');
    }

    /** Register a listener for auth state changes. Callback receives (isLoggedIn). */
    onChange(callback) {
        this._listeners.push(callback);
    }

    /** Notify all listeners of state change. */
    notify() {
        this._listeners.forEach(cb => cb(this.isLoggedIn()));
    }

    /** Update totp_enabled flag without re-fetching from API. */
    updateTotpEnabled(enabled) {
        if (this._user) {
            this._user.totp_enabled = enabled;
        }
    }

    /**
     * Initialise: if token in storage, validate it by calling /api/auth/me.
     * Returns true if the session is valid.
     */
    async init() {
        if (!this._token) return false;
        try {
            const user = await window.apiClient.getMe(this._token);
            if (!user) {
                this.clear();
                return false;
            }
            this._user = user;
            const discogsStatus = await window.apiClient.getDiscogsStatus(this._token);
            this._discogsStatus = discogsStatus;
            return true;
        } catch {
            // A network-level fetch rejection (server unreachable, offline,
            // DNS/CORS, server restart) — api-client only converts HTTP error
            // statuses to null, so this is the ONLY place such a rejection
            // would otherwise escape init() uncaught, aborting page-load auth
            // restore (discogsography-ponr). Treat it like an invalid session
            // rather than letting the caller's page-load chain reject.
            this.clear();
            return false;
        }
    }
}

// Global singleton
window.authManager = new AuthManager();
