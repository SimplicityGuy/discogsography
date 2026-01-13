// Main Discovery Playground Application

class DiscoveryPlayground {
    constructor() {
        this.currentView = 'graph';
        this.currentData = null;
        this.visualizations = {
            graph: null,
            journey: null,
            trends: null,
            heatmap: null
        };

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.initializeVisualizations();

        // Connect WebSocket for real-time updates
        discoveryAPI.connectWebSocket(this.handleWebSocketMessage.bind(this));

        // Load initial data
        this.switchView('graph');
    }

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('[data-view]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const view = e.currentTarget.dataset.view;
                this.switchView(view);
            });
        });

        // Search
        const searchInput = document.getElementById('searchInput');
        let searchTimeout;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.performSearch(e.target.value);
            }, 300);
        });

        // Controls
        document.getElementById('exploreBtn').addEventListener('click', () => {
            this.explore();
        });

        document.getElementById('resetBtn').addEventListener('click', () => {
            this.resetView();
        });

        // Sliders
        document.getElementById('depthSlider').addEventListener('input', (e) => {
            document.getElementById('depthValue').textContent = e.target.value;
        });

        document.getElementById('nodeLimit').addEventListener('input', (e) => {
            document.getElementById('nodeLimitValue').textContent = e.target.value;
        });

        document.getElementById('topArtists').addEventListener('input', (e) => {
            document.getElementById('topArtistsValue').textContent = e.target.value;
        });

        // Journey Builder
        document.getElementById('findJourneyBtn').addEventListener('click', () => {
            this.findMusicJourney();
        });

        // Zoom controls
        document.getElementById('zoomInBtn').addEventListener('click', () => {
            this.zoom(1.2);
        });

        document.getElementById('zoomOutBtn').addEventListener('click', () => {
            this.zoom(0.8);
        });

        document.getElementById('fullscreenBtn').addEventListener('click', () => {
            this.toggleFullscreen();
        });
    }

    initializeVisualizations() {
        // Initialize visualization modules
        if (typeof GraphVisualization !== 'undefined') {
            this.visualizations.graph = new GraphVisualization('graphSvg');
        }
        if (typeof JourneyBuilder !== 'undefined') {
            this.visualizations.journey = new JourneyBuilder('journeyPath');
        }
        if (typeof TrendAnalysis !== 'undefined') {
            this.visualizations.trends = new TrendAnalysis('trendsChart');
        }
        if (typeof HeatmapVisualization !== 'undefined') {
            this.visualizations.heatmap = new HeatmapVisualization('heatmapChart');
        }
    }

    switchView(view) {
        this.currentView = view;

        // Update navigation
        document.querySelectorAll('[data-view]').forEach(link => {
            link.classList.toggle('active', link.dataset.view === view);
        });

        // Hide all views
        document.querySelectorAll('.view-container').forEach(container => {
            container.style.display = 'none';
        });
        document.querySelectorAll('.view-controls').forEach(controls => {
            controls.style.display = 'none';
        });

        // Show current view
        const viewContainer = document.getElementById(`${view}View`);
        const viewControls = document.getElementById(`${view}Controls`);

        if (viewContainer) viewContainer.style.display = 'block';
        if (viewControls) viewControls.style.display = 'block';

        // Update title
        const titles = {
            graph: '<i class="fas fa-project-diagram"></i> Graph Explorer',
            journey: '<i class="fas fa-route"></i> Music Journey',
            trends: '<i class="fas fa-chart-line"></i> Trend Analysis',
            heatmap: '<i class="fas fa-th"></i> Similarity Heatmap'
        };
        document.getElementById('viewTitle').innerHTML = titles[view] || view;

        // Load default data for the view
        this.loadDefaultData();
    }

    async performSearch(query) {
        if (!query || query.length < 2) return;

        this.showLoading(true);

        try {
            const results = await discoveryAPI.search(query);
            this.displaySearchResults(results);
        } catch (error) {
            this.showError('Search failed: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    displaySearchResults(results) {
        // Update current data
        this.currentData = results;

        // Display based on current view
        switch (this.currentView) {
            case 'graph':
                if (this.visualizations.graph && results.artists?.length > 0) {
                    this.loadGraphData(results.artists[0].id);
                }
                break;
            case 'journey':
                // Update journey inputs with search results
                if (results.artists?.length > 0) {
                    const startInput = document.getElementById('startArtist');
                    if (!startInput.value) {
                        startInput.value = results.artists[0].name;
                        startInput.dataset.artistId = results.artists[0].id;
                    }
                }
                break;
        }

        // Update info panel
        this.updateInfoPanel(results);
    }

    async explore() {
        switch (this.currentView) {
            case 'graph':
                await this.exploreGraph();
                break;
            case 'trends':
                await this.exploreTrends();
                break;
            case 'heatmap':
                await this.exploreHeatmap();
                break;
        }
    }

    async exploreGraph() {
        const searchValue = document.getElementById('searchInput').value;
        if (!searchValue) {
            this.showNotification('Please enter an artist name to explore', 'warning');
            return;
        }

        this.showLoading(true);

        try {
            // Search for the artist first
            const searchResults = await discoveryAPI.search(searchValue, 'artist');
            if (searchResults.artists?.length > 0) {
                const artistId = searchResults.artists[0].id;
                await this.loadGraphData(artistId);
            } else {
                this.showNotification('No artists found', 'warning');
            }
        } catch (error) {
            this.showError('Failed to explore graph: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    async loadGraphData(nodeId) {
        const depth = parseInt(document.getElementById('depthSlider').value);
        const limit = parseInt(document.getElementById('nodeLimit').value);

        try {
            const graphData = await discoveryAPI.getGraphData(nodeId, { depth, limit });

            if (this.visualizations.graph) {
                this.visualizations.graph.render(graphData);

                // Set up node click handler
                this.visualizations.graph.onNodeClick = (node) => {
                    this.handleNodeClick(node);
                };
            }
        } catch (error) {
            this.showError('Failed to load graph data: ' + error.message);
        }
    }

    async exploreTrends() {
        const trendType = document.getElementById('trendType').value;
        const startYear = document.getElementById('yearStart').value || 1950;
        const endYear = document.getElementById('yearEnd').value || new Date().getFullYear();

        this.showLoading(true);

        try {
            const trendData = await discoveryAPI.getTrends(trendType, { startYear, endYear });

            if (this.visualizations.trends) {
                this.visualizations.trends.render(trendData);
            }
        } catch (error) {
            this.showError('Failed to load trend data: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    async exploreHeatmap() {
        const heatmapType = document.getElementById('heatmapType').value;
        const topN = parseInt(document.getElementById('topArtists').value);

        this.showLoading(true);

        try {
            const heatmapData = await discoveryAPI.getHeatmap(heatmapType, { topN });

            if (this.visualizations.heatmap) {
                this.visualizations.heatmap.render(heatmapData);
            }
        } catch (error) {
            this.showError('Failed to load heatmap data: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    async findMusicJourney() {
        const startArtist = document.getElementById('startArtist');
        const endArtist = document.getElementById('endArtist');

        // Check if we have values
        if (!startArtist.value || !endArtist.value) {
            this.showNotification('Please enter both start and end artists', 'warning');
            return;
        }

        this.showLoading(true);

        try {
            // If artist IDs are not set, search for them first
            if (!startArtist.dataset.artistId) {
                const results = await discoveryAPI.search(startArtist.value, 'artist', 1);
                if (results.items?.artists?.length > 0) {
                    startArtist.dataset.artistId = results.items.artists[0].id;
                    startArtist.value = results.items.artists[0].name; // Use exact match
                } else {
                    this.showNotification(`Could not find artist: ${startArtist.value}`, 'warning');
                    this.showLoading(false);
                    return;
                }
            }

            if (!endArtist.dataset.artistId) {
                const results = await discoveryAPI.search(endArtist.value, 'artist', 1);
                if (results.items?.artists?.length > 0) {
                    endArtist.dataset.artistId = results.items.artists[0].id;
                    endArtist.value = results.items.artists[0].name; // Use exact match
                } else {
                    this.showNotification(`Could not find artist: ${endArtist.value}`, 'warning');
                    this.showLoading(false);
                    return;
                }
            }

            const journey = await discoveryAPI.findJourney(
                startArtist.dataset.artistId,
                endArtist.dataset.artistId
            );

            if (this.visualizations.journey) {
                this.visualizations.journey.render(journey);
            }
        } catch (error) {
            this.showError('Failed to find music journey: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    handleNodeClick(node) {
        // Load node details
        this.loadNodeDetails(node);

        // Update search input
        document.getElementById('searchInput').value = node.name || node.label || '';
    }

    async loadNodeDetails(node) {
        try {
            let details;
            switch (node.type) {
                case 'artist':
                    details = await discoveryAPI.getArtistDetails(node.id);
                    break;
                case 'release':
                    details = await discoveryAPI.getReleaseDetails(node.id);
                    break;
                case 'label':
                    details = await discoveryAPI.getLabelDetails(node.id);
                    break;
                default:
                    details = node;
            }

            this.updateInfoPanel(details);
        } catch (error) {
            console.error('Failed to load node details:', error);
        }
    }

    updateInfoPanel(data) {
        const infoPanel = document.getElementById('infoPanel');

        if (!data || typeof data !== 'object') {
            infoPanel.innerHTML = '<p class="text-muted">No information available</p>';
            return;
        }

        let html = '';

        // Handle search results
        if (data.artists || data.releases || data.labels) {
            html = '<h6>Search Results</h6>';

            if (data.artists?.length > 0) {
                html += '<div class="info-item"><div class="info-label">Artists</div>';
                data.artists.slice(0, 5).forEach(artist => {
                    html += `<div class="info-value">• ${artist.name}</div>`;
                });
                html += '</div>';
            }

            if (data.releases?.length > 0) {
                html += '<div class="info-item"><div class="info-label">Releases</div>';
                data.releases.slice(0, 5).forEach(release => {
                    html += `<div class="info-value">• ${release.title}</div>`;
                });
                html += '</div>';
            }
        }
        // Handle single entity details
        else {
            const fields = [
                { key: 'name', label: 'Name' },
                { key: 'title', label: 'Title' },
                { key: 'real_name', label: 'Real Name' },
                { key: 'profile', label: 'Profile' },
                { key: 'year', label: 'Year' },
                { key: 'genres', label: 'Genres' },
                { key: 'styles', label: 'Styles' },
                { key: 'country', label: 'Country' },
                { key: 'members', label: 'Members' },
                { key: 'aliases', label: 'Aliases' }
            ];

            fields.forEach(field => {
                if (data[field.key]) {
                    html += '<div class="info-item">';
                    html += `<div class="info-label">${field.label}</div>`;

                    if (Array.isArray(data[field.key])) {
                        html += `<div class="info-value">${data[field.key].join(', ')}</div>`;
                    } else {
                        html += `<div class="info-value">${data[field.key]}</div>`;
                    }

                    html += '</div>';
                }
            });
        }

        infoPanel.innerHTML = html || '<p class="text-muted">No details available</p>';
    }

    resetView() {
        // Clear search
        document.getElementById('searchInput').value = '';

        // Reset controls to defaults
        document.getElementById('depthSlider').value = 2;
        document.getElementById('depthValue').textContent = '2';
        document.getElementById('nodeLimit').value = 50;
        document.getElementById('nodeLimitValue').textContent = '50';

        // Reset visualizations
        Object.values(this.visualizations).forEach(viz => {
            if (viz && typeof viz.reset === 'function') {
                viz.reset();
            }
        });

        // Clear info panel
        document.getElementById('infoPanel').innerHTML = '<p class="text-muted">Select an item to view details</p>';

        // Load default data
        this.loadDefaultData();
    }

    async loadDefaultData() {
        // Load some interesting default data based on current view
        switch (this.currentView) {
            case 'graph':
                // Could load a featured artist graph
                break;
            case 'trends':
                // Load default trend data
                await this.exploreTrends();
                break;
            case 'heatmap':
                // Load default heatmap
                await this.exploreHeatmap();
                break;
        }
    }

    zoom(factor) {
        const viz = this.visualizations[this.currentView];
        if (viz && typeof viz.zoom === 'function') {
            viz.zoom(factor);
        }
    }

    toggleFullscreen() {
        const container = document.getElementById('visualizationContainer');
        container.classList.toggle('fullscreen');

        // Update button icon
        const btn = document.getElementById('fullscreenBtn');
        const icon = btn.querySelector('i');
        icon.classList.toggle('fa-expand');
        icon.classList.toggle('fa-compress');

        // Trigger resize for visualizations
        window.dispatchEvent(new Event('resize'));
    }

    showLoading(show) {
        const overlay = document.getElementById('loadingOverlay');
        overlay.style.display = show ? 'flex' : 'none';
    }

    showNotification(message, type = 'info') {
        const toast = document.getElementById('notificationToast');
        const toastMessage = document.getElementById('toastMessage');

        toastMessage.textContent = message;

        // Update toast styling based on type
        const header = toast.querySelector('.toast-header i');
        header.className = `fas fa-${type === 'error' ? 'exclamation-circle text-danger' :
                                     type === 'warning' ? 'exclamation-triangle text-warning' :
                                     'info-circle text-primary'} me-2`;

        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
    }

    showError(message) {
        this.showNotification(message, 'error');
    }

    handleWebSocketMessage(data) {
        // Handle real-time updates
        console.log('WebSocket message:', data);

        // Could update visualizations with new data
        if (data.type === 'update' && data.view === this.currentView) {
            // Refresh current view with new data
        }
    }
}

// Initialize playground when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.playground = new DiscoveryPlayground();
});
