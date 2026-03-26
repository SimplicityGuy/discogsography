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

    /**
     * Initialise: if token in storage, validate it by calling /api/auth/me.
     * Returns true if the session is valid.
     */
    async init() {
        if (!this._token) return false;
        const user = await window.apiClient.getMe(this._token);
        if (!user) {
            this.clear();
            return false;
        }
        this._user = user;
        const discogsStatus = await window.apiClient.getDiscogsStatus(this._token);
        this._discogsStatus = discogsStatus;
        return true;
    }
}

// Global singleton
window.authManager = new AuthManager();
