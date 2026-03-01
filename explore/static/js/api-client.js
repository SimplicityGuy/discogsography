/**
 * API client for the Explore service.
 */
class ApiClient {
    /**
     * Autocomplete search.
     * @param {string} query - Search query
     * @param {string} type - Entity type (artist, genre, label, style)
     * @param {number} limit - Max results
     * @returns {Promise<Array>} Search results
     */
    async autocomplete(query, type, limit = 10) {
        const params = new URLSearchParams({ q: query, type, limit: String(limit) });
        const response = await fetch(`/api/autocomplete?${params}`);
        if (!response.ok) return [];
        const data = await response.json();
        return data.results || [];
    }

    /**
     * Explore an entity (center node + categories).
     * @param {string} name - Entity name
     * @param {string} type - Entity type
     * @returns {Promise<Object|null>} Explore data
     */
    async explore(name, type) {
        const params = new URLSearchParams({ name, type });
        const response = await fetch(`/api/explore?${params}`);
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Expand a category to get child nodes (paginated).
     * @param {string} nodeId - Parent entity name
     * @param {string} type - Parent entity type
     * @param {string} category - Category to expand
     * @param {number} limit - Max results per page
     * @param {number} offset - Number of results to skip
     * @returns {Promise<{children: Array, total: number, offset: number, limit: number, has_more: boolean}>}
     */
    async expand(nodeId, type, category, limit = 50, offset = 0) {
        const params = new URLSearchParams({
            node_id: nodeId,
            type,
            category,
            limit: String(limit),
            offset: String(offset),
        });
        const response = await fetch(`/api/expand?${params}`);
        if (!response.ok) return { children: [], total: 0, offset, limit, has_more: false };
        return response.json();
    }

    /**
     * Get full details for a node.
     * @param {string} nodeId - Node ID
     * @param {string} type - Node type
     * @returns {Promise<Object|null>} Node details
     */
    async getNodeDetails(nodeId, type) {
        const params = new URLSearchParams({ type });
        const response = await fetch(`/api/node/${encodeURIComponent(nodeId)}?${params}`);
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Get time-series trends data.
     * @param {string} name - Entity name
     * @param {string} type - Entity type
     * @returns {Promise<Object|null>} Trends data
     */
    async getTrends(name, type) {
        const params = new URLSearchParams({ name, type });
        const response = await fetch(`/api/trends?${params}`);
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Save a graph snapshot.
     * @param {Array<{id: string, type: string}>} nodes - Node list
     * @param {{id: string, type: string}} center - Center node
     * @returns {Promise<Object|null>} Snapshot response with token and url
     */
    async saveSnapshot(nodes, center) {
        const response = await fetch('/api/snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nodes, center }),
        });
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Restore a graph snapshot by token.
     * @param {string} token - Snapshot token
     * @returns {Promise<Object|null>} Snapshot restore response
     */
    async restoreSnapshot(token) {
        const response = await fetch(`/api/snapshot/${encodeURIComponent(token)}`);
        if (!response.ok) return null;
        return response.json();
    }

    // --- Auth ---

    async register(email, password) {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });
        return response.status === 201;
    }

    async login(email, password) {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });
        if (!response.ok) return null;
        return response.json();
    }

    async logout(token) {
        if (!token) return;
        await fetch('/api/auth/logout', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
        });
    }

    async getMe(token) {
        if (!token) return null;
        const response = await fetch('/api/auth/me', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    // --- Discogs OAuth ---

    async authorizeDiscogs(token) {
        if (!token) return null;
        const response = await fetch('/api/oauth/authorize/discogs', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async verifyDiscogs(token, state, oauthVerifier) {
        if (!token) return null;
        const response = await fetch('/api/oauth/verify/discogs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ state, oauth_verifier: oauthVerifier }),
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getDiscogsStatus(token) {
        if (!token) return null;
        const response = await fetch('/api/oauth/status/discogs', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async revokeDiscogs(token) {
        if (!token) return null;
        const response = await fetch('/api/oauth/revoke/discogs', {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    // --- User data ---

    async getUserCollection(token, limit = 50, offset = 0) {
        if (!token) return null;
        const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
        const response = await fetch(`/api/user/collection?${params}`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getUserWantlist(token, limit = 50, offset = 0) {
        if (!token) return null;
        const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
        const response = await fetch(`/api/user/wantlist?${params}`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getUserRecommendations(token, limit = 20) {
        if (!token) return null;
        const params = new URLSearchParams({ limit: String(limit) });
        const response = await fetch(`/api/user/recommendations?${params}`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getUserCollectionStats(token) {
        if (!token) return null;
        const response = await fetch('/api/user/collection/stats', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getUserStatus(ids, token = null) {
        const params = new URLSearchParams({ ids: ids.join(',') });
        const headers = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const response = await fetch(`/api/user/status?${params}`, { headers });
        if (!response.ok) return null;
        return response.json();
    }

    // --- Sync ---

    async triggerSync(token) {
        if (!token) return null;
        const response = await fetch('/api/sync', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getSyncStatus(token) {
        if (!token) return null;
        const response = await fetch('/api/sync/status', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }
}

// Global instance
window.apiClient = new ApiClient();
