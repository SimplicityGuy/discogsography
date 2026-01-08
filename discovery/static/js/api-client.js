// API Client for Discovery Service

class DiscoveryAPI {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }

    // Generic fetch wrapper with error handling
    async fetchAPI(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers,
                },
            });

            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('API Request Failed:', error);
            throw error;
        }
    }

    // Search for artists, albums, or labels
    async search(query, type = 'all') {
        return this.fetchAPI(`/api/search?q=${encodeURIComponent(query)}&type=${type}`);
    }

    // Get recommendations
    async getRecommendations(artistId, options = {}) {
        const params = new URLSearchParams({
            artist_id: artistId,
            limit: options.limit || 10,
            ...options
        });
        return this.fetchAPI(`/api/recommendations?${params}`);
    }

    // Get graph data for visualization
    async getGraphData(nodeId, options = {}) {
        const params = new URLSearchParams({
            node_id: nodeId,
            depth: options.depth || 2,
            limit: options.limit || 50,
            node_types: options.nodeTypes || 'all',
            ...options
        });
        return this.fetchAPI(`/api/graph?${params}`);
    }

    // Get analytics data
    async getAnalytics(type, options = {}) {
        const params = new URLSearchParams({
            type: type,
            ...options
        });
        return this.fetchAPI(`/api/analytics?${params}`);
    }

    // Find musical journey between two artists
    async findJourney(startArtistId, endArtistId, options = {}) {
        return this.fetchAPI('/api/journey', {
            method: 'POST',
            body: JSON.stringify({
                start_artist_id: startArtistId,
                end_artist_id: endArtistId,
                max_depth: options.maxDepth || 5,
                ...options
            })
        });
    }

    // Get trend data
    async getTrends(trendType, options = {}) {
        const params = new URLSearchParams({
            type: trendType,
            start_year: options.startYear || 1950,
            end_year: options.endYear || new Date().getFullYear(),
            ...options
        });
        return this.fetchAPI(`/api/trends?${params}`);
    }

    // Get similarity heatmap data
    async getHeatmap(heatmapType, options = {}) {
        const params = new URLSearchParams({
            type: heatmapType,
            top_n: options.topN || 20,
            ...options
        });
        return this.fetchAPI(`/api/heatmap?${params}`);
    }

    // Get artist details
    async getArtistDetails(artistId) {
        return this.fetchAPI(`/api/artists/${artistId}`);
    }

    // Get release details
    async getReleaseDetails(releaseId) {
        return this.fetchAPI(`/api/releases/${releaseId}`);
    }

    // Get label details
    async getLabelDetails(labelId) {
        return this.fetchAPI(`/api/labels/${labelId}`);
    }

    // WebSocket connection for real-time updates
    connectWebSocket(onMessage) {
        const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                onMessage(data);
            } catch (error) {
                console.error('WebSocket message parse error:', error);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            // Attempt to reconnect after 5 seconds
            setTimeout(() => this.connectWebSocket(onMessage), 5000);
        };
    }

    // Close WebSocket connection
    closeWebSocket() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Create global API instance
window.discoveryAPI = new DiscoveryAPI();
