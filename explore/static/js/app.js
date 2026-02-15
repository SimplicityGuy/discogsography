/**
 * Main application controller.
 * Coordinates pane switching, search, graph, and trends.
 */
class ExploreApp {
    constructor() {
        this.searchType = 'artist';
        this.currentQuery = '';
        this.activePane = 'explore';

        // Initialize components
        this.autocomplete = new Autocomplete();
        this.graph = new GraphVisualization('graphContainer');
        this.trends = new TrendsChart('trendsChart');

        // Wire up callbacks
        this.autocomplete.onSelect = (name) => this._onSearch(name);
        this.graph.onNodeClick = (nodeId, type) => this._onNodeClick(nodeId, type);
        this.graph.onNodeExpand = (name, type) => this._onNodeExpand(name, type);

        this._bindEvents();
    }

    _bindEvents() {
        // Pane switching
        document.querySelectorAll('[data-pane]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this._switchPane(link.dataset.pane);
            });
        });

        // Search type dropdown
        document.querySelectorAll('[data-type]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                this._setSearchType(item.dataset.type);
            });
        });

        // Close info panel
        document.getElementById('closePanelBtn').addEventListener('click', () => {
            document.getElementById('infoPanel').classList.remove('open');
        });
    }

    _switchPane(pane) {
        this.activePane = pane;

        // Update nav links
        document.querySelectorAll('[data-pane]').forEach(link => {
            link.classList.toggle('active', link.dataset.pane === pane);
        });

        // Show/hide panes
        document.querySelectorAll('.pane').forEach(el => {
            el.classList.remove('active');
        });
        document.getElementById(pane + 'Pane').classList.add('active');

        // If switching to trends and we have a query, load trends
        if (pane === 'trends' && this.currentQuery) {
            this._loadTrends(this.currentQuery, this.searchType);
        }
    }

    _setSearchType(type) {
        this.searchType = type;

        // Update button text
        const btn = document.getElementById('searchTypeBtn');
        btn.textContent = type.charAt(0).toUpperCase() + type.slice(1);

        // Update dropdown active state
        document.querySelectorAll('[data-type]').forEach(item => {
            item.classList.toggle('active', item.dataset.type === type);
        });

        // Re-trigger autocomplete if there's input
        const input = document.getElementById('searchInput');
        if (input.value.trim().length >= 2) {
            this.autocomplete._search(input.value.trim());
        }
    }

    async _onSearch(name) {
        this.currentQuery = name;

        if (this.activePane === 'explore') {
            await this._loadExplore(name, this.searchType);
        } else {
            await this._loadTrends(name, this.searchType);
        }
    }

    async _loadExplore(name, type) {
        const loading = document.getElementById('graphLoading');
        loading.classList.add('active');
        try {
            const data = await window.apiClient.explore(name, type);
            if (data) {
                // Wait for all category expansions to complete before hiding loader
                await new Promise((resolve) => {
                    this.graph.onExpandsComplete = () => {
                        this.graph.onExpandsComplete = null;
                        resolve();
                    };
                    this.graph.setExploreData(data);
                    // If no expansions were needed, resolve immediately
                    if (this.graph._pendingExpands <= 0) {
                        this.graph.onExpandsComplete = null;
                        resolve();
                    }
                });
            }
        } finally {
            loading.classList.remove('active');
        }
    }

    async _loadTrends(name, type) {
        const loading = document.getElementById('trendsLoading');
        loading.classList.add('active');
        try {
            const data = await window.apiClient.getTrends(name, type);
            if (data) {
                this.trends.render(data);
            }
        } finally {
            loading.classList.remove('active');
        }
    }

    async _onNodeClick(nodeId, type) {
        const panel = document.getElementById('infoPanel');
        const body = document.getElementById('infoPanelBody');
        const title = document.getElementById('infoPanelTitle');

        body.innerHTML = '<p class="text-muted">Loading...</p>';
        panel.classList.add('open');

        const details = await window.apiClient.getNodeDetails(nodeId, type);
        if (!details) {
            body.innerHTML = '<p class="text-muted">No details available</p>';
            return;
        }

        title.textContent = details.name || nodeId;
        body.innerHTML = this._renderDetails(details, type);

        // Wire up the explore button if present
        const exploreBtn = body.querySelector('.explore-node-btn');
        if (exploreBtn) {
            exploreBtn.addEventListener('click', () => {
                const exploreName = exploreBtn.dataset.name;
                const exploreType = exploreBtn.dataset.type;
                this._onNodeExpand(exploreName, exploreType);
                panel.classList.remove('open');
            });
        }
    }

    async _onNodeExpand(name, type) {
        // Only artist, genre, label are explorable
        const explorableTypes = ['artist', 'genre', 'label'];
        if (!explorableTypes.includes(type)) return;

        // Update search type to match
        this._setSearchType(type);
        this.currentQuery = name;

        // Update search input
        document.getElementById('searchInput').value = name;

        // Load explore data for this node
        await this._loadExplore(name, type);
    }

    _renderDetails(details, type) {
        let html = '';

        // Explore button for navigable types
        const explorableTypes = ['artist', 'genre', 'label'];
        if (explorableTypes.includes(type)) {
            html += `<button class="btn btn-sm btn-outline-primary w-100 mb-3 explore-node-btn" data-name="${this._escapeAttr(details.name)}" data-type="${type}"><i class="fas fa-project-diagram me-1"></i>Explore ${details.name}</button>`;
        }

        if (type === 'artist') {
            html += this._detailStat('Releases', details.release_count || 0);
            if (details.genres && details.genres.length) {
                html += this._detailTags('Genres', details.genres);
            }
            if (details.styles && details.styles.length) {
                html += this._detailTags('Styles', details.styles);
            }
            if (details.groups && details.groups.length) {
                html += this._detailTags('Groups', details.groups);
            }
        } else if (type === 'release') {
            if (details.year) html += this._detailStat('Year', details.year);
            if (details.country) html += this._detailStat('Country', details.country);
            if (details.artists && details.artists.length) {
                html += this._detailTags('Artists', details.artists);
            }
            if (details.labels && details.labels.length) {
                html += this._detailTags('Labels', details.labels);
            }
            if (details.genres && details.genres.length) {
                html += this._detailTags('Genres', details.genres);
            }
            if (details.styles && details.styles.length) {
                html += this._detailTags('Styles', details.styles);
            }
        } else if (type === 'label') {
            html += this._detailStat('Releases', details.release_count || 0);
        } else if (type === 'genre' || type === 'style') {
            html += this._detailStat('Artists', details.artist_count || 0);
        }

        return html || '<p class="text-muted">No additional details</p>';
    }

    _detailStat(label, value) {
        return `<div class="detail-stat"><span class="label">${label}</span><span class="value">${label === 'Year' ? value : (typeof value === 'number' ? value.toLocaleString() : value)}</span></div>`;
    }

    _detailTags(label, tags) {
        const tagsHtml = tags.map(t => `<span class="detail-tag">${this._escapeHtml(t)}</span>`).join('');
        return `<div class="detail-section"><h6>${label}</h6><div class="detail-tags">${tagsHtml}</div></div>`;
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _escapeAttr(text) {
        return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.exploreApp = new ExploreApp();
});
