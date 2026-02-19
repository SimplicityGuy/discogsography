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
}

// Global instance
window.apiClient = new ApiClient();
