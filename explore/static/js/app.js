/**
 * Main application controller.
 * Coordinates pane switching, search, graph, trends, auth, and user panes.
 */
class ExploreApp {
    constructor() {
        this.searchType = 'artist';
        this.currentQuery = '';
        this.activePane = 'explore';

        // Trends comparison state
        this.compareMode = false;
        this.primaryTrendsData = null;

        // Initialize components
        this.autocomplete = new Autocomplete();
        this.graph = new GraphVisualization('graphContainer');
        this.trends = new TrendsChart('trendsChart');
        this.userPanes = new window.UserPanes();

        // Wire up callbacks
        this.autocomplete.onSelect = (name) => this._onSearch(name);
        this.graph.onNodeClick = (nodeId, type) => this._onNodeClick(nodeId, type);
        this.graph.onNodeExpand = (name, type) => this._onNodeExpand(name, type);

        // Auth state changes → update UI
        window.authManager.onChange(() => this._updateAuthUI());

        this._bindEvents();
        this._initAuth().then(() => this._restoreFromUrl());
    }

    // ------------------------------------------------------------------ //
    // Auth initialisation
    // ------------------------------------------------------------------ //

    async _initAuth() {
        const valid = await window.authManager.init();
        this._updateAuthUI();
        return valid;
    }

    _updateAuthUI() {
        const loggedIn = window.authManager.isLoggedIn();
        const user = window.authManager.getUser();
        const discogsStatus = window.authManager.getDiscogsStatus();

        // Toggle auth buttons vs user dropdown
        document.getElementById('authButtons').classList.toggle('hidden', loggedIn);
        document.getElementById('userDropdown').classList.toggle('hidden', !loggedIn);

        // Toggle auth-required nav items
        ['navCollection', 'navWantlist', 'navRecommendations'].forEach(id => {
            document.getElementById(id)?.classList.toggle('hidden', !loggedIn);
        });
        // Hide gaps nav when logged out (shown dynamically by gap analysis)
        if (!loggedIn) {
            document.getElementById('navGaps')?.classList.add('hidden');
        }

        if (loggedIn && user) {
            const emailEl = document.getElementById('userEmailDisplay');
            if (emailEl) emailEl.textContent = user.email || '';
        }

        // Discogs status display
        const statusDisplay = document.getElementById('discogsStatusDisplay');
        const connectBtn = document.getElementById('connectDiscogsBtn');
        const disconnectBtn = document.getElementById('disconnectDiscogsBtn');
        const syncBtn = document.getElementById('syncBtn');

        if (loggedIn && discogsStatus?.connected) {
            if (statusDisplay) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-accent-green text-white discogs-badge';
                const icon = document.createElement('i');
                icon.className = 'fas fa-check mr-1';
                badge.append(icon, discogsStatus.discogs_username || 'Connected');
                statusDisplay.replaceChildren(badge);
            }
            connectBtn?.classList.add('hidden');
            disconnectBtn?.classList.remove('hidden');
            syncBtn?.classList.remove('hidden');
        } else if (loggedIn) {
            if (statusDisplay) {
                statusDisplay.innerHTML = '<span class="badge bg-gray-600 text-text-secondary discogs-badge">Not connected</span>';
            }
            connectBtn?.classList.remove('hidden');
            disconnectBtn?.classList.add('hidden');
            syncBtn?.classList.add('hidden');
        } else {
            if (statusDisplay) {
                statusDisplay.innerHTML = '<span class="badge bg-gray-600 text-text-secondary discogs-badge">Not connected</span>';
            }
            connectBtn?.classList.add('hidden');
            disconnectBtn?.classList.add('hidden');
            syncBtn?.classList.add('hidden');
        }

        // If we just logged out and were on a personal pane, switch to explore
        if (!loggedIn && ['collection', 'wantlist', 'recommendations'].includes(this.activePane)) {
            this._switchPane('explore');
        }
    }

    // ------------------------------------------------------------------ //
    // Event binding
    // ------------------------------------------------------------------ //

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

        // Trends comparison controls
        document.getElementById('compareBtn').addEventListener('click', () => this._enableCompareMode());
        document.getElementById('clearCompareBtn').addEventListener('click', () => this._clearComparison());

        // Share button
        document.getElementById('shareBtn').addEventListener('click', () => this._shareSnapshot());

        // Login form
        document.getElementById('loginSubmitBtn')?.addEventListener('click', () => this._handleLogin());
        document.getElementById('loginPassword')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._handleLogin();
        });

        // Register form
        document.getElementById('registerSubmitBtn')?.addEventListener('click', () => this._handleRegister());
        document.getElementById('registerPassword')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._handleRegister();
        });

        // Logout
        document.getElementById('logoutBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this._handleLogout();
        });

        // Discogs OAuth
        document.getElementById('connectDiscogsBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.userPanes.startDiscogsOAuth();
        });
        document.getElementById('disconnectDiscogsBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.userPanes.disconnectDiscogs();
        });
        document.getElementById('discogsVerifierSubmit')?.addEventListener('click', () => {
            this.userPanes.submitDiscogsVerifier();
        });
        document.getElementById('discogsVerifierInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.userPanes.submitDiscogsVerifier();
        });

        // Sync
        document.getElementById('syncBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.userPanes.triggerSync();
        });

        // Collection / wantlist / recommendations refresh (delegated — buttons are rendered dynamically)
        document.getElementById('collectionPane')?.addEventListener('click', (e) => {
            if (e.target.closest('#collectionRefreshBtn')) {
                this.userPanes.loadCollection(true);
                this.userPanes.loadCollectionStats();
            }
        });
        document.getElementById('wantlistPane')?.addEventListener('click', (e) => {
            if (e.target.closest('#wantlistRefreshBtn')) {
                this.userPanes.loadWantlist(true);
            }
        });
        document.getElementById('recommendationsRefreshBtn')?.addEventListener('click', () => {
            this.userPanes.loadRecommendations();
        });

        // Login button opens modal and clears errors
        document.getElementById('navLoginBtn')?.addEventListener('click', () => {
            if (window.Alpine) Alpine.store('modals').authOpen = true;
            document.getElementById('loginError').textContent = '';
            document.getElementById('registerError').textContent = '';
            document.getElementById('registerSuccess')?.classList.add('hidden');
        });
    }

    // ------------------------------------------------------------------ //
    // Auth handlers
    // ------------------------------------------------------------------ //

    async _handleLogin() {
        const email = document.getElementById('loginEmail')?.value.trim();
        const password = document.getElementById('loginPassword')?.value;
        const errorEl = document.getElementById('loginError');
        const submitBtn = document.getElementById('loginSubmitBtn');

        if (!email || !password) {
            if (errorEl) errorEl.textContent = 'Please enter your email and password.';
            return;
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i>Logging in...';
        if (errorEl) errorEl.textContent = '';

        try {
            const result = await window.apiClient.login(email, password);
            if (!result || !result.access_token) {
                if (errorEl) errorEl.textContent = 'Invalid email or password.';
                return;
            }

            window.authManager.setToken(result.access_token);
            const user = await window.apiClient.getMe(result.access_token);
            window.authManager.setUser(user);
            const discogsStatus = await window.apiClient.getDiscogsStatus(result.access_token);
            window.authManager.setDiscogsStatus(discogsStatus);
            window.authManager.notify();

            // Close modal
            Alpine.store('modals').authOpen = false;
            document.getElementById('loginEmail').value = '';
            document.getElementById('loginPassword').value = '';
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-sign-in-alt mr-1"></i>Login';
        }
    }

    async _handleRegister() {
        const email = document.getElementById('registerEmail')?.value.trim();
        const password = document.getElementById('registerPassword')?.value;
        const errorEl = document.getElementById('registerError');
        const successEl = document.getElementById('registerSuccess');
        const submitBtn = document.getElementById('registerSubmitBtn');

        if (!email || !password) {
            if (errorEl) errorEl.textContent = 'Please enter your email and password.';
            return;
        }
        if (password.length < 8) {
            if (errorEl) errorEl.textContent = 'Password must be at least 8 characters.';
            return;
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i>Creating account...';
        if (errorEl) errorEl.textContent = '';
        if (successEl) successEl.classList.add('hidden');

        try {
            const ok = await window.apiClient.register(email, password);
            if (ok) {
                if (successEl) successEl.classList.remove('hidden');
                document.getElementById('registerEmail').value = '';
                document.getElementById('registerPassword').value = '';
                // Switch to login tab
                document.getElementById('login-tab')?.click();
            } else {
                if (errorEl) errorEl.textContent = 'Registration failed. Please try again.';
            }
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-user-plus mr-1"></i>Create Account';
        }
    }

    async _handleLogout() {
        const token = window.authManager.getToken();
        await window.apiClient.logout(token);
        window.authManager.clear();
        window.authManager.notify();
    }

    // ------------------------------------------------------------------ //
    // Pane management
    // ------------------------------------------------------------------ //

    _switchPane(pane) {
        this.activePane = pane;

        // Update nav links
        document.querySelectorAll('[data-pane]').forEach(link => {
            link.classList.toggle('active', link.dataset.pane === pane);
        });

        // Show/hide panes
        document.querySelectorAll('.pane').forEach(el => el.classList.remove('active'));
        const target = document.getElementById(pane + 'Pane');
        if (target) target.classList.add('active');

        // Lazy-load user panes on first visit
        if (pane === 'trends' && this.currentQuery) {
            this._loadTrends(this.currentQuery, this.searchType);
        } else if (pane === 'collection' && window.authManager.isLoggedIn()) {
            this.userPanes.loadCollection(true);
            this.userPanes.loadCollectionStats();
        } else if (pane === 'wantlist' && window.authManager.isLoggedIn()) {
            this.userPanes.loadWantlist(true);
        } else if (pane === 'recommendations' && window.authManager.isLoggedIn()) {
            this.userPanes.loadRecommendations();
        }
    }

    _setSearchType(type) {
        this.searchType = type;
        const btn = document.getElementById('searchTypeBtn');
        if (btn) btn.textContent = type.charAt(0).toUpperCase() + type.slice(1);

        document.querySelectorAll('[data-type]').forEach(item => {
            item.classList.toggle('active', item.dataset.type === type);
        });

        const input = document.getElementById('searchInput');
        if (input?.value.trim().length >= 2) {
            this.autocomplete._search(input.value.trim());
        }
    }

    // ------------------------------------------------------------------ //
    // Search & graph
    // ------------------------------------------------------------------ //

    async _onSearch(name) {
        this.currentQuery = name;
        this._pushState(name, this.searchType);

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
                await new Promise((resolve) => {
                    this.graph.onExpandsComplete = () => {
                        this.graph.onExpandsComplete = null;
                        resolve();
                    };
                    this.graph.setExploreData(data);
                    if (this.graph._pendingExpands <= 0) {
                        this.graph.onExpandsComplete = null;
                        resolve();
                    }
                });
                // Decorate release nodes with ownership badges if logged in
                await this._decorateOwnership();
            }
        } finally {
            loading.classList.remove('active');
        }
    }

    async _decorateOwnership() {
        if (!window.authManager.isLoggedIn()) return;
        const token = window.authManager.getToken();
        const releaseNodes = (this.graph.nodes || []).filter(n => n.type === 'release' && !n.isCategory);
        if (releaseNodes.length === 0) return;

        const ids = releaseNodes.map(n => n.nodeId || n.name).slice(0, 100);
        const result = await window.apiClient.getUserStatus(ids, token);
        if (!result || !result.status) return;

        // Update info panel if it's showing a release node that has status
        const title = document.getElementById('infoPanelTitle')?.textContent;
        if (title) {
            const matchId = ids.find(id => id === title);
            if (matchId && result.status[matchId]) {
                this._addOwnershipBadges(matchId, result.status[matchId]);
            }
        }
    }

    _addOwnershipBadges(releaseId, statusObj) {
        const body = document.getElementById('infoPanelBody');
        if (!body) return;

        // Remove existing badges
        body.querySelectorAll('.ownership-badge').forEach(b => b.remove());

        const container = document.createElement('div');
        container.className = 'mb-2';

        if (statusObj.in_collection) {
            const badge = document.createElement('span');
            badge.className = 'ownership-badge in-collection';
            badge.innerHTML = '<i class="fas fa-check mr-1"></i>In Collection';
            container.appendChild(badge);
        }
        if (statusObj.in_wantlist) {
            const badge = document.createElement('span');
            badge.className = 'ownership-badge in-wantlist';
            badge.innerHTML = '<i class="fas fa-heart mr-1"></i>In Wantlist';
            container.appendChild(badge);
        }

        if (container.children.length > 0) {
            body.insertBefore(container, body.firstChild);
        }
    }

    async _loadTrends(name, type) {
        const loading = document.getElementById('trendsLoading');
        loading.classList.add('active');
        try {
            const data = await window.apiClient.getTrends(name, type);
            if (data) {
                if (this.compareMode && this.primaryTrendsData) {
                    this.trends.addComparison(data);
                    document.getElementById('compareBadge').textContent = `vs ${data.name}`;
                    document.getElementById('compareInfo').classList.remove('hidden');
                    document.getElementById('compareHint').classList.add('hidden');
                    this.compareMode = false;
                } else {
                    this.primaryTrendsData = data;
                    this.trends.render(data);
                    document.getElementById('compareBtn').classList.remove('hidden');
                    document.getElementById('compareHint').classList.add('hidden');
                    document.getElementById('compareInfo').classList.add('hidden');
                    this.compareMode = false;
                }
            }
        } finally {
            loading.classList.remove('active');
        }
    }

    _enableCompareMode() {
        if (!this.primaryTrendsData) return;
        this.compareMode = true;
        document.getElementById('compareBtn').classList.add('hidden');
        document.getElementById('compareHint').classList.remove('hidden');
    }

    _clearComparison() {
        this.compareMode = false;
        this.trends.clearComparison();
        document.getElementById('compareBtn').classList.remove('hidden');
        document.getElementById('compareHint').classList.add('hidden');
        document.getElementById('compareInfo').classList.add('hidden');
    }

    _pushState(name, type) {
        const params = new URLSearchParams({ name, type });
        history.pushState({ name, type }, '', `?${params}`);
    }

    async _restoreFromUrl() {
        const params = new URLSearchParams(window.location.search);
        const snapshotToken = params.get('snapshot');
        if (snapshotToken) {
            await this._loadSnapshot(snapshotToken);
            return;
        }
        const name = params.get('name');
        const type = params.get('type');
        if (name && type) {
            this._setSearchType(type);
            document.getElementById('searchInput').value = name;
            this._onSearch(name);
        }
    }

    async _loadSnapshot(token) {
        const loading = document.getElementById('graphLoading');
        loading.classList.add('active');
        try {
            const data = await window.apiClient.restoreSnapshot(token);
            if (data) this.graph.restoreSnapshot(data.nodes, data.center);
        } finally {
            loading.classList.remove('active');
        }
    }

    async _shareSnapshot() {
        const nodes = this.graph.nodes
            .filter(n => !n.isCategory)
            .map(n => ({ id: n.nodeId || n.name, type: n.type }));
        const centerName = this.graph.centerName;
        const centerType = this.graph.centerType;
        if (!centerName || nodes.length === 0) return;

        const result = await window.apiClient.saveSnapshot(nodes, { id: centerName, type: centerType });
        if (!result) return;

        const url = `${window.location.origin}/?snapshot=${result.token}`;
        try {
            await navigator.clipboard.writeText(url);
        } catch {
            prompt('Copy this link:', url);
            return;
        }
        this._showToast('Link copied!');
    }

    _showToast(message) {
        const toast = document.getElementById('shareToast');
        const toastMsg = document.getElementById('shareToastMsg');
        if (toastMsg) toastMsg.textContent = message;
        toast?.classList.add('show');
        setTimeout(() => toast?.classList.remove('show'), 2500);
    }

    async _onNodeClick(nodeId, type) {
        const panel = document.getElementById('infoPanel');
        const body = document.getElementById('infoPanelBody');
        const title = document.getElementById('infoPanelTitle');

        body.innerHTML = '<p class="text-text-secondary">Loading...</p>';
        panel.classList.add('open');

        const details = await window.apiClient.getNodeDetails(nodeId, type);
        if (!details) {
            body.innerHTML = '<p class="text-text-secondary">No details available</p>';
            return;
        }

        title.textContent = details.name || nodeId;
        body.replaceChildren(...this._renderDetails(details, type));

        // Add ownership badges for release nodes
        if (type === 'release' && window.authManager.isLoggedIn()) {
            const token = window.authManager.getToken();
            const result = await window.apiClient.getUserStatus([nodeId], token);
            if (result?.status?.[nodeId]) {
                this._addOwnershipBadges(nodeId, result.status[nodeId]);
            }
        }

        const exploreBtn = body.querySelector('.explore-node-btn');
        if (exploreBtn) {
            exploreBtn.addEventListener('click', () => {
                this._onNodeExpand(exploreBtn.dataset.name, exploreBtn.dataset.type);
                panel.classList.remove('open');
            });
        }
    }

    async _onNodeExpand(name, type) {
        const explorableTypes = ['artist', 'genre', 'label', 'style'];
        if (!explorableTypes.includes(type)) return;

        this._setSearchType(type);
        this.currentQuery = name;
        document.getElementById('searchInput').value = name;
        await this._loadExplore(name, type);
    }

    _renderDetails(details, type) {
        const nodes = [];

        const explorableTypes = ['artist', 'genre', 'label', 'style'];
        if (explorableTypes.includes(type)) {
            const btn = document.createElement('button');
            btn.className = 'btn-outline-primary btn-sm w-full mb-3 explore-node-btn';
            btn.dataset.name = details.name;
            btn.dataset.type = type;
            const icon = document.createElement('i');
            icon.className = 'fas fa-project-diagram mr-1';
            btn.append(icon, `Explore ${details.name}`);
            nodes.push(btn);
        }

        if (type === 'artist') {
            nodes.push(this._detailStat('Releases', details.release_count || 0));
            if (details.genres?.length) nodes.push(this._detailTags('Genres', details.genres));
            if (details.styles?.length) nodes.push(this._detailTags('Styles', details.styles));
            if (details.groups?.length) nodes.push(this._detailTags('Groups', details.groups));
            if (window.authManager.isLoggedIn()) {
                nodes.push(this._gapAnalysisButton('artist', nodeId, details.name));
            }
        } else if (type === 'release') {
            if (details.year) nodes.push(this._detailStat('Year', details.year));
            if (details.artists?.length) nodes.push(this._detailTags('Artists', details.artists));
            if (details.labels?.length) nodes.push(this._detailTags('Labels', details.labels));
            if (details.genres?.length) nodes.push(this._detailTags('Genres', details.genres));
            if (details.styles?.length) nodes.push(this._detailTags('Styles', details.styles));
        } else if (type === 'label') {
            nodes.push(this._detailStat('Releases', details.release_count || 0));
            if (window.authManager.isLoggedIn()) {
                nodes.push(this._gapAnalysisButton('label', nodeId, details.name));
            }
        } else if (type === 'genre' || type === 'style') {
            nodes.push(this._detailStat('Artists', details.artist_count || 0));
        }

        if (nodes.length === 0) {
            const p = document.createElement('p');
            p.className = 'text-text-secondary';
            p.textContent = 'No additional details';
            nodes.push(p);
        }

        return nodes;
    }

    _detailStat(label, value) {
        const div = document.createElement('div');
        div.className = 'detail-stat';
        const labelEl = document.createElement('span');
        labelEl.className = 'label';
        labelEl.textContent = label;
        const valueEl = document.createElement('span');
        valueEl.className = 'value';
        valueEl.textContent = label === 'Year' ? value : (typeof value === 'number' ? value.toLocaleString() : value);
        div.append(labelEl, valueEl);
        return div;
    }

    _gapAnalysisButton(entityType, entityId, entityName) {
        const btn = document.createElement('button');
        btn.className = 'btn-outline-warning btn-sm w-full mt-3 gap-analysis-btn';
        const icon = document.createElement('i');
        icon.className = 'fas fa-search-minus mr-1';
        btn.append(icon, 'What am I missing?');
        btn.addEventListener('click', () => {
            const panel = document.getElementById('infoPanel');
            if (panel) panel.classList.remove('open');
            window.userPanes.loadGapAnalysis(entityType, entityId, true);
        });
        return btn;
    }

    _detailTags(label, tags) {
        const section = document.createElement('div');
        section.className = 'detail-section';
        const heading = document.createElement('h6');
        heading.textContent = label;
        const tagsDiv = document.createElement('div');
        tagsDiv.className = 'detail-tags';
        tags.forEach(t => {
            const span = document.createElement('span');
            span.className = 'detail-tag';
            span.textContent = t;
            tagsDiv.appendChild(span);
        });
        section.append(heading, tagsDiv);
        return section;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.exploreApp = new ExploreApp();
});
