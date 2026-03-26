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
    async expand(nodeId, type, category, limit = 50, offset = 0, beforeYear = null) {
        const params = new URLSearchParams({
            node_id: nodeId,
            type,
            category,
            limit: String(limit),
            offset: String(offset),
        });
        if (beforeYear !== null) {
            params.set('before_year', String(beforeYear));
        }
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
     * Get min/max release year for the slider bounds.
     * @returns {Promise<{min_year: number|null, max_year: number|null}>}
     */
    async getYearRange() {
        const response = await fetch('/api/explore/year-range');
        if (!response.ok) return { min_year: null, max_year: null };
        return response.json();
    }

    /**
     * Get genre/style first-appearance years up to a given year.
     * @param {number} beforeYear - Upper year bound
     * @returns {Promise<{genres: Array, styles: Array}>}
     */
    async getGenreEmergence(beforeYear) {
        const params = new URLSearchParams({ before_year: String(beforeYear) });
        const response = await fetch(`/api/explore/genre-emergence?${params}`);
        if (!response.ok) return { genres: [], styles: [] };
        return response.json();
    }

    /**
     * Save a graph snapshot.
     * @param {Array<{id: string, type: string}>} nodes - Node list
     * @param {{id: string, type: string}} center - Center node
     * @returns {Promise<Object|null>} Snapshot response with token and url
     */
    async saveSnapshot(nodes, center, token) {
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const response = await fetch('/api/snapshot', {
            method: 'POST',
            headers,
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

    /**
     * Find shortest path between two named entities.
     * @param {string} fromName - Source entity name
     * @param {string} fromType - Source entity type (artist, genre, label, style)
     * @param {string} toName - Target entity name
     * @param {string} toType - Target entity type
     * @param {number} maxDepth - Max traversal depth (1-15, default 10)
     * @returns {Promise<{found: boolean, length: number|null, path: Array}|{notFound: boolean, error: string}|null>}
     */
    async findPath(fromName, fromType, toName, toType, maxDepth = 10) {
        const params = new URLSearchParams({
            from_name: fromName,
            from_type: fromType,
            to_name: toName,
            to_type: toType,
            max_depth: String(maxDepth),
        });
        const response = await fetch(`/api/path?${params}`);
        if (response.status === 404) {
            const data = await response.json();
            return { notFound: true, error: data.error || 'Entity not found' };
        }
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Full-text search across all entity types.
     * @param {string} q - Search query (min 3 chars)
     * @param {string[]} types - Entity types to search (artist, label, master, release)
     * @param {string[]} genres - Genre filter
     * @param {number|null} yearMin - Minimum release year
     * @param {number|null} yearMax - Maximum release year
     * @param {number} limit - Results per page
     * @param {number} offset - Pagination offset
     * @returns {Promise<Object|null>} Search results with facets and pagination
     */
    async search(q, types = [], genres = [], yearMin = null, yearMax = null, limit = 20, offset = 0) {
        const params = new URLSearchParams({ q, limit: String(limit), offset: String(offset) });
        if (types.length) params.set('types', types.join(','));
        if (genres.length) params.set('genres', genres.join(','));
        if (yearMin != null) params.set('year_min', String(yearMin));
        if (yearMax != null) params.set('year_max', String(yearMax));
        const response = await fetch(`/api/search?${params}`);
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

    async resetRequest(email) {
        const response = await fetch('/api/auth/reset-request', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ email }),
        });
        return response;
    }

    async resetConfirm(token, newPassword) {
        const response = await fetch('/api/auth/reset-confirm', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ token, new_password: newPassword }),
        });
        return response;
    }

    async twoFactorSetup(token) {
        const response = await fetch('/api/auth/2fa/setup', {
            method: 'POST', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'},
        });
        return response;
    }

    async twoFactorConfirm(token, code) {
        const response = await fetch('/api/auth/2fa/confirm', {
            method: 'POST', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'},
            body: JSON.stringify({ code }),
        });
        return response;
    }

    async twoFactorVerify(challengeToken, code) {
        const response = await fetch('/api/auth/2fa/verify', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ challenge_token: challengeToken, code }),
        });
        return response;
    }

    async twoFactorRecovery(challengeToken, code) {
        const response = await fetch('/api/auth/2fa/recovery', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ challenge_token: challengeToken, code }),
        });
        return response;
    }

    async twoFactorDisable(token, code, password) {
        const response = await fetch('/api/auth/2fa/disable', {
            method: 'POST', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'},
            body: JSON.stringify({ code, password }),
        });
        return response;
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

    // --- Collection gap analysis ---

    async getCollectionFormats(token) {
        if (!token) return null;
        const response = await fetch('/api/collection/formats', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getCollectionGaps(token, entityType, entityId, options = {}) {
        if (!token) return null;
        const params = new URLSearchParams({
            limit: String(options.limit || 50),
            offset: String(options.offset || 0),
        });
        if (options.excludeWantlist) params.set('exclude_wantlist', 'true');
        if (options.formats?.length) {
            options.formats.forEach(f => params.append('formats', f));
        }
        const response = await fetch(`/api/collection/gaps/${entityType}/${encodeURIComponent(entityId)}?${params}`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
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

    // --- Taste fingerprint ---

    /**
     * Get full taste fingerprint (heatmap, obscurity, drift, blind spots).
     * @param {string} token - JWT auth token
     * @returns {Promise<Object|null>} Fingerprint data or null on error/422
     */
    async getTasteFingerprint(token) {
        if (!token) return null;
        const response = await fetch('/api/user/taste/fingerprint', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Download SVG taste card.
     * @param {string} token - JWT auth token
     * @returns {Promise<Blob|null>} SVG blob or null on error
     */
    async getTasteCard(token) {
        if (!token) return null;
        const response = await fetch('/api/user/taste/card', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.blob();
    }
    // --- Collaborators ---

    /**
     * Get collaborators for an artist.
     * @param {string} artistId - Artist ID
     * @param {number} limit - Max collaborators to return
     * @returns {Promise<Object|null>} Collaborator data or null on error
     */
    async getCollaborators(artistId, limit = 20) {
        const params = new URLSearchParams({ limit: String(limit) });
        const response = await fetch(`/api/collaborators/${encodeURIComponent(artistId)}?${params}`);
        if (!response.ok) return null;
        return response.json();
    }

    // --- Genre Tree ---

    /**
     * Get the full genre/style hierarchy.
     * @returns {Promise<Object|null>} Genre tree data or null on error
     */
    async getGenreTree() {
        const response = await fetch('/api/genre-tree');
        if (!response.ok) return null;
        return response.json();
    }

    // --- Insights ---

    async getInsightsTopArtists(limit = 10) {
        const params = new URLSearchParams({ limit: String(limit) });
        const response = await fetch(`/api/insights/top-artists?${params}`);
        if (!response.ok) return null;
        return response.json();
    }

    async getInsightsGenreTrends(genre) {
        const params = new URLSearchParams({ genre });
        const response = await fetch(`/api/insights/genre-trends?${params}`);
        if (!response.ok) return null;
        return response.json();
    }

    async getInsightsThisMonth() {
        const response = await fetch('/api/insights/this-month');
        if (!response.ok) return null;
        return response.json();
    }

    async getInsightsDataCompleteness() {
        const response = await fetch('/api/insights/data-completeness');
        if (!response.ok) return null;
        return response.json();
    }

    async getInsightsStatus() {
        const response = await fetch('/api/insights/status');
        if (!response.ok) return null;
        return response.json();
    }
    // --- NLQ (Natural Language Query) ---

    /**
     * Check if NLQ feature is enabled.
     * @returns {Promise<{enabled: boolean}>} NLQ status
     */
    async checkNlqStatus() {
        try {
            const response = await fetch('/api/nlq/status');
            if (!response.ok) return { enabled: false };
            return response.json();
        } catch {
            return { enabled: false };
        }
    }

    /**
     * Send a natural language query (non-streaming).
     * @param {string} query - Natural language question
     * @param {Object|null} context - Optional context (current_entity_id, current_entity_type)
     * @returns {Promise<Object|null>} Query result or null on failure
     */
    async askNlq(query, context = null) {
        try {
            const body = { query };
            if (context) body.context = context;
            const response = await fetch('/api/nlq/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!response.ok) return null;
            return response.json();
        } catch {
            return null;
        }
    }

    /**
     * Send a natural language query with SSE streaming.
     * @param {string} query - Natural language question
     * @param {Object|null} context - Optional context
     * @param {Function} onStatus - Called with status events
     * @param {Function} onResult - Called with the final result
     * @param {Function} onError - Called on error
     */
    askNlqStream(query, context = null, onStatus, onResult, onError) {
        const body = { query };
        if (context) body.context = context;
        fetch('/api/nlq/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify(body),
        }).then(response => {
            if (!response.ok) {
                if (onError) onError(response.status);
                return;
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            function processChunk() {
                reader.read().then(({ done, value }) => {
                    if (done) return;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';
                    let eventType = null;
                    for (const line of lines) {
                        if (line.startsWith('event: ')) {
                            eventType = line.slice(7).trim();
                        } else if (line.startsWith('data: ') && eventType) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (eventType === 'status' && onStatus) onStatus(data);
                                if (eventType === 'result' && onResult) onResult(data);
                            } catch { /* ignore parse errors */ }
                            eventType = null;
                        }
                    }
                    processChunk();
                });
            }
            processChunk();
        }).catch(err => {
            if (onError) onError(err);
        });
    }
}

// Global instance
window.apiClient = new ApiClient();
