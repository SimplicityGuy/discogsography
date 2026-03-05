/**
 * UserPanes — manages Collection, Wantlist, Recommendations panes
 * and the Discogs OAuth connect flow.
 *
 * Depends on: window.apiClient (api-client.js), window.authManager (auth.js)
 */
class UserPanes {
    constructor() {
        this._collectionOffset = 0;
        this._wantlistOffset = 0;
        this._pageSize = 50;
        this._collectionTotal = 0;
        this._wantlistTotal = 0;
        this._discogsOAuthState = null;
    }

    // ------------------------------------------------------------------ //
    // Collection pane
    // ------------------------------------------------------------------ //

    async loadCollection(reset = false) {
        const token = window.authManager.getToken();
        if (!token) return;
        if (reset) this._collectionOffset = 0;

        const loading = document.getElementById('collectionLoading');
        const body = document.getElementById('collectionBody');
        if (loading) loading.classList.add('active');

        try {
            const data = await window.apiClient.getUserCollection(token, this._pageSize, this._collectionOffset);
            if (!data) {
                this._renderCollectionEmpty(body, 'Failed to load collection.');
                return;
            }
            this._collectionTotal = data.total;
            this._renderCollectionList(body, data);
        } finally {
            if (loading) loading.classList.remove('active');
        }
    }

    _renderCollectionList(container, data) {
        if (!container) return;
        container.innerHTML = '';

        if (!data.releases || data.releases.length === 0) {
            this._renderCollectionEmpty(container, 'Your collection is empty. Sync your Discogs collection first.');
            return;
        }

        // Stats banner
        const statsBar = document.createElement('p');
        statsBar.className = 'text-text-secondary text-sm mb-2';
        statsBar.textContent = `Showing ${this._collectionOffset + 1}–${this._collectionOffset + data.releases.length} of ${data.total.toLocaleString()} releases`;
        container.appendChild(statsBar);

        const ul = document.createElement('ul');
        ul.className = 'release-list';
        data.releases.forEach(r => {
            const li = document.createElement('li');
            li.className = 'release-list-item';

            const info = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'release-list-title';
            title.textContent = r.title || '(Unknown title)';
            const meta = document.createElement('div');
            meta.className = 'release-list-meta';
            meta.textContent = [r.artist, r.label].filter(Boolean).join(' · ');
            info.append(title, meta);

            const year = document.createElement('div');
            year.className = 'release-list-year';
            year.textContent = r.year || '';

            li.append(info, year);
            ul.appendChild(li);
        });
        container.appendChild(ul);

        // Pagination
        if (data.total > this._pageSize) {
            const pag = this._buildPagination(
                this._collectionOffset,
                data.total,
                () => {
                    this._collectionOffset = Math.max(0, this._collectionOffset - this._pageSize);
                    this.loadCollection();
                },
                () => {
                    this._collectionOffset += this._pageSize;
                    this.loadCollection();
                },
                data.has_more,
            );
            container.appendChild(pag);
        }
    }

    _renderCollectionEmpty(container, msg) {
        if (!container) return;
        const div = document.createElement('div');
        div.className = 'user-pane-empty';
        const icon = document.createElement('i');
        icon.className = 'fas fa-record-vinyl fa-3x mb-3';
        const p = document.createElement('p');
        p.textContent = msg;
        div.append(icon, p);
        container.appendChild(div);
    }

    // ------------------------------------------------------------------ //
    // Wantlist pane
    // ------------------------------------------------------------------ //

    async loadWantlist(reset = false) {
        const token = window.authManager.getToken();
        if (!token) return;
        if (reset) this._wantlistOffset = 0;

        const loading = document.getElementById('wantlistLoading');
        const body = document.getElementById('wantlistBody');
        if (loading) loading.classList.add('active');

        try {
            const data = await window.apiClient.getUserWantlist(token, this._pageSize, this._wantlistOffset);
            if (!data) {
                this._renderWantlistEmpty(body, 'Failed to load wantlist.');
                return;
            }
            this._wantlistTotal = data.total;
            this._renderWantlistList(body, data);
        } finally {
            if (loading) loading.classList.remove('active');
        }
    }

    _renderWantlistList(container, data) {
        if (!container) return;
        container.innerHTML = '';

        if (!data.releases || data.releases.length === 0) {
            this._renderWantlistEmpty(container, 'Your wantlist is empty. Sync your Discogs wantlist first.');
            return;
        }

        const statsBar = document.createElement('p');
        statsBar.className = 'text-text-secondary text-sm mb-2';
        statsBar.textContent = `Showing ${this._wantlistOffset + 1}–${this._wantlistOffset + data.releases.length} of ${data.total.toLocaleString()} releases`;
        container.appendChild(statsBar);

        const ul = document.createElement('ul');
        ul.className = 'release-list';
        data.releases.forEach(r => {
            const li = document.createElement('li');
            li.className = 'release-list-item';

            const info = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'release-list-title';
            title.textContent = r.title || '(Unknown title)';
            const meta = document.createElement('div');
            meta.className = 'release-list-meta';
            meta.textContent = [r.artist, r.label].filter(Boolean).join(' · ');
            info.append(title, meta);

            const year = document.createElement('div');
            year.className = 'release-list-year';
            year.textContent = r.year || '';

            li.append(info, year);
            ul.appendChild(li);
        });
        container.appendChild(ul);

        if (data.total > this._pageSize) {
            const pag = this._buildPagination(
                this._wantlistOffset,
                data.total,
                () => {
                    this._wantlistOffset = Math.max(0, this._wantlistOffset - this._pageSize);
                    this.loadWantlist();
                },
                () => {
                    this._wantlistOffset += this._pageSize;
                    this.loadWantlist();
                },
                data.has_more,
            );
            container.appendChild(pag);
        }
    }

    _renderWantlistEmpty(container, msg) {
        if (!container) return;
        const div = document.createElement('div');
        div.className = 'user-pane-empty';
        const icon = document.createElement('i');
        icon.className = 'fas fa-heart fa-3x mb-3';
        const p = document.createElement('p');
        p.textContent = msg;
        div.append(icon, p);
        container.appendChild(div);
    }

    // ------------------------------------------------------------------ //
    // Recommendations pane
    // ------------------------------------------------------------------ //

    async loadRecommendations() {
        const token = window.authManager.getToken();
        if (!token) return;

        const loading = document.getElementById('recommendationsLoading');
        const body = document.getElementById('recommendationsBody');
        if (loading) loading.classList.add('active');

        try {
            const data = await window.apiClient.getUserRecommendations(token, 50);
            this._renderRecommendations(body, data);
        } finally {
            if (loading) loading.classList.remove('active');
        }
    }

    _renderRecommendations(container, data) {
        if (!container) return;
        container.innerHTML = '';

        if (!data || !data.recommendations || data.recommendations.length === 0) {
            container.innerHTML = `<div class="user-pane-empty"><i class="fas fa-lightbulb fa-3x mb-3"></i><p>No recommendations yet. Sync your collection to get personalised suggestions.</p></div>`;
            return;
        }

        const intro = document.createElement('p');
        intro.className = 'text-text-secondary text-sm mb-2';
        intro.textContent = `${data.recommendations.length} releases you might like`;
        container.appendChild(intro);

        data.recommendations.forEach(r => {
            const item = document.createElement('div');
            item.className = 'recommendation-item';

            const info = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'release-list-title';
            title.textContent = r.title || '(Unknown title)';
            const meta = document.createElement('div');
            meta.className = 'release-list-meta';
            meta.textContent = [r.artist, r.year].filter(Boolean).join(' · ');
            info.append(title, meta);

            const score = document.createElement('div');
            score.className = 'recommendation-score';
            if (r.score !== undefined) {
                score.textContent = `${Math.round(r.score * 100)}% match`;
            }

            item.append(info, score);
            container.appendChild(item);
        });
    }

    // ------------------------------------------------------------------ //
    // Collection stats
    // ------------------------------------------------------------------ //

    async loadCollectionStats() {
        const token = window.authManager.getToken();
        if (!token) return;
        const stats = await window.apiClient.getUserCollectionStats(token);
        this._renderCollectionStats(stats);
    }

    _renderCollectionStats(stats) {
        const el = document.getElementById('collectionStats');
        if (!el || !stats) return;

        const fields = [
            { label: 'Total', value: stats.total_releases ?? stats.total ?? '—' },
            { label: 'Artists', value: stats.unique_artists ?? stats.artists ?? '—' },
            { label: 'Labels', value: stats.unique_labels ?? stats.labels ?? '—' },
            { label: 'Avg Rating', value: stats.average_rating != null ? Number(stats.average_rating).toFixed(1) : '—' },
        ];

        el.innerHTML = '';
        el.className = 'stats-row';
        fields.forEach(f => {
            const card = document.createElement('div');
            card.className = 'stat-card';
            const statValue = document.createElement('div');
            statValue.className = 'stat-value';
            statValue.textContent = typeof f.value === 'number' ? f.value.toLocaleString() : f.value;
            const statLabel = document.createElement('div');
            statLabel.className = 'stat-label';
            statLabel.textContent = f.label;
            card.append(statValue, statLabel);
            el.appendChild(card);
        });
    }

    // ------------------------------------------------------------------ //
    // Discogs OAuth flow
    // ------------------------------------------------------------------ //

    async startDiscogsOAuth() {
        const token = window.authManager.getToken();
        if (!token) return;

        const data = await window.apiClient.authorizeDiscogs(token);
        if (!data || !data.authorize_url) {
            alert('Could not start Discogs authorization. Please try again.');
            return;
        }

        this._discogsOAuthState = data.state;

        // Open Discogs auth page in a new tab
        window.open(data.authorize_url, '_blank', 'noopener,noreferrer');

        // Show verifier modal
        Alpine.store('modals').discogsOpen = true;
    }

    async submitDiscogsVerifier() {
        const token = window.authManager.getToken();
        const verifier = document.getElementById('discogsVerifierInput')?.value?.trim();
        const errorEl = document.getElementById('discogsVerifierError');

        if (!verifier) {
            if (errorEl) { errorEl.textContent = 'Please enter the verification code.'; errorEl.classList.remove('hidden'); }
            return;
        }
        if (!this._discogsOAuthState) {
            if (errorEl) { errorEl.textContent = 'Session expired. Please start again.'; errorEl.classList.remove('hidden'); }
            return;
        }

        const submitBtn = document.getElementById('discogsVerifierSubmit');
        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Connecting...'; }

        const result = await window.apiClient.verifyDiscogs(token, this._discogsOAuthState, verifier);
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Connect'; }

        if (!result || !result.connected) {
            if (errorEl) { errorEl.textContent = 'Verification failed. Please check the code and try again.'; errorEl.classList.remove('hidden'); }
            return;
        }

        // Update auth manager with new Discogs status
        const status = await window.apiClient.getDiscogsStatus(token);
        window.authManager.setDiscogsStatus(status);

        // Close modal and notify
        Alpine.store('modals').discogsOpen = false;
        this._discogsOAuthState = null;
        document.getElementById('discogsVerifierInput').value = '';
        if (errorEl) errorEl.classList.add('hidden');

        window.authManager.notify();
    }

    async disconnectDiscogs() {
        const token = window.authManager.getToken();
        if (!token) return;
        if (!confirm('Disconnect your Discogs account?')) return;

        await window.apiClient.revokeDiscogs(token);
        window.authManager.setDiscogsStatus({ connected: false });
        window.authManager.notify();
    }

    // ------------------------------------------------------------------ //
    // Sync
    // ------------------------------------------------------------------ //

    async triggerSync() {
        const token = window.authManager.getToken();
        if (!token) return;

        const btn = document.getElementById('syncBtn');
        if (btn) { btn.classList.add('syncing'); btn.disabled = true; }

        try {
            const result = await window.apiClient.triggerSync(token);
            if (result) {
                // Reload panes after a short delay to allow sync to start
                setTimeout(() => {
                    this.loadCollection(true);
                    this.loadWantlist(true);
                }, 2000);
            } else {
                alert('Sync could not be started. Please try again later.');
            }
        } finally {
            if (btn) { btn.classList.remove('syncing'); btn.disabled = false; }
        }
    }

    // ------------------------------------------------------------------ //
    // Helpers
    // ------------------------------------------------------------------ //

    _buildPagination(offset, total, onPrev, onNext, hasMore) {
        const page = Math.floor(offset / this._pageSize) + 1;
        const totalPages = Math.ceil(total / this._pageSize);

        const div = document.createElement('div');
        div.className = 'pane-pagination';

        const prevBtn = document.createElement('button');
        prevBtn.className = 'btn-outline-secondary btn-sm';
        prevBtn.textContent = 'Previous';
        prevBtn.disabled = offset === 0;
        prevBtn.addEventListener('click', onPrev);

        const pageInfo = document.createElement('span');
        pageInfo.className = 'text-text-secondary text-sm';
        pageInfo.textContent = `Page ${page} of ${totalPages}`;

        const nextBtn = document.createElement('button');
        nextBtn.className = 'btn-outline-secondary btn-sm';
        nextBtn.textContent = 'Next';
        nextBtn.disabled = !hasMore;
        nextBtn.addEventListener('click', onNext);

        div.append(prevBtn, pageInfo, nextBtn);
        return div;
    }
}

// Global instance (created after DOM ready in app.js)
window.UserPanes = UserPanes;
