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

        const wrap = this._buildReleaseTable(
            'My Collection',
            'fa-record-vinyl',
            data.releases,
            data.total,
            this._collectionOffset,
            'collectionRefreshBtn',
            (page) => {
                this._collectionOffset = page * this._pageSize;
                this.loadCollection();
            },
            data.has_more,
        );
        container.appendChild(wrap);
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

        const wrap = this._buildReleaseTable(
            'My Wantlist',
            'fa-heart',
            data.releases,
            data.total,
            this._wantlistOffset,
            'wantlistRefreshBtn',
            (page) => {
                this._wantlistOffset = page * this._pageSize;
                this.loadWantlist();
            },
            data.has_more,
        );
        container.appendChild(wrap);
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

        const total = stats.total_releases ?? stats.total ?? 0;
        const artists = stats.unique_artists ?? stats.artists ?? 0;
        const labels = stats.unique_labels ?? stats.labels ?? 0;
        const avgRating = stats.average_rating != null ? Number(stats.average_rating) : null;

        const fields = [
            { label: 'Total Items', value: typeof total === 'number' ? total.toLocaleString() : total },
            { label: 'Artists', value: typeof artists === 'number' ? artists.toLocaleString() : artists },
            { label: 'Labels', value: typeof labels === 'number' ? labels.toLocaleString() : labels },
            { label: 'Avg Rating', value: avgRating != null ? avgRating.toFixed(1) : '—', rating: avgRating },
        ];

        el.innerHTML = '';
        el.className = 'stats-row';
        fields.forEach(f => {
            const card = document.createElement('div');
            card.className = 'stat-card';
            const statLabel = document.createElement('div');
            statLabel.className = 'stat-label';
            statLabel.textContent = f.label;
            const statValue = document.createElement('div');
            statValue.className = 'stat-value';
            statValue.textContent = f.value;
            if (f.rating != null) {
                const stars = document.createElement('span');
                stars.className = 'stat-stars';
                stars.innerHTML = this._renderStarsHTML(f.rating);
                statValue.appendChild(stars);
            }
            card.append(statLabel, statValue);
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

    // ------------------------------------------------------------------ //
    // Shared table builder
    // ------------------------------------------------------------------ //

    _buildReleaseTable(title, iconClass, releases, total, offset, refreshBtnId, onPageChange, hasMore) {
        const currentPage = Math.floor(offset / this._pageSize);
        const totalPages = Math.ceil(total / this._pageSize);
        const showFrom = offset + 1;
        const showTo = offset + releases.length;

        const wrap = document.createElement('div');
        wrap.className = 'release-table-wrap';

        // Header
        const header = document.createElement('div');
        header.className = 'release-table-header';

        const titleArea = document.createElement('div');
        titleArea.className = 'release-table-title';
        titleArea.innerHTML = `<span class="title-icon"><i class="fas ${iconClass}"></i></span>`
            + `<h5>${this._escapeHTML(title)}</h5>`
            + `<span class="title-count">Showing ${showFrom.toLocaleString()}–${showTo.toLocaleString()} of ${total.toLocaleString()}</span>`;

        const actions = document.createElement('div');
        actions.className = 'release-table-actions';

        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'btn-refresh btn-sync';
        refreshBtn.id = refreshBtnId;
        refreshBtn.innerHTML = '<i class="fas fa-redo"></i> Refresh';

        actions.appendChild(refreshBtn);
        header.append(titleArea, actions);
        wrap.appendChild(header);

        // Scrollable table area
        const scrollWrap = document.createElement('div');
        scrollWrap.className = 'release-table-scroll';

        const table = document.createElement('table');
        table.className = 'release-table';

        // thead
        const thead = document.createElement('thead');
        thead.innerHTML = `<tr>
            <th class="col-artist sortable">Artist <i class="fas fa-sort-down" style="font-size:0.6rem;opacity:0.5"></i></th>
            <th class="col-title sortable">Release Title <i class="fas fa-sort-down" style="font-size:0.6rem;opacity:0.5"></i></th>
            <th class="col-label">Label</th>
            <th class="col-year">Year</th>
            <th class="col-genre">Genre / Style</th>
            <th class="col-rating">Rating</th>
        </tr>`;
        table.appendChild(thead);

        // tbody
        const tbody = document.createElement('tbody');
        releases.forEach(r => {
            const tr = document.createElement('tr');

            const tdArtist = document.createElement('td');
            tdArtist.textContent = r.artist || '—';

            const tdTitle = document.createElement('td');
            tdTitle.className = 'release-list-title';
            tdTitle.textContent = r.title || '(Unknown title)';

            const tdLabel = document.createElement('td');
            tdLabel.textContent = r.label || '';

            const tdYear = document.createElement('td');
            tdYear.className = 'cell-year';
            tdYear.textContent = r.year || '';

            const tdGenre = document.createElement('td');
            const genres = r.genres || [];
            const styles = r.styles || [];
            // Show first genre, or first style if no genre
            const tag = genres[0] || styles[0];
            if (tag) {
                const badge = document.createElement('span');
                badge.className = genres[0] ? 'genre-badge' : 'genre-badge style-badge';
                badge.textContent = tag;
                tdGenre.appendChild(badge);
            }

            const tdRating = document.createElement('td');
            if (r.rating && r.rating > 0) {
                tdRating.innerHTML = `<span class="star-rating">${this._renderStarsHTML(r.rating)}</span>`;
            } else {
                tdRating.innerHTML = '<span class="star-rating-dash">—</span>';
            }

            tr.append(tdArtist, tdTitle, tdLabel, tdYear, tdGenre, tdRating);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        scrollWrap.appendChild(table);
        wrap.appendChild(scrollWrap);

        // Pagination
        if (total > this._pageSize) {
            const pag = this._buildPagination(currentPage, totalPages, onPageChange);
            wrap.appendChild(pag);
        }

        return wrap;
    }

    _buildPagination(currentPage, totalPages, onPageChange) {
        const div = document.createElement('div');
        div.className = 'pane-pagination';

        const info = document.createElement('span');
        info.className = 'page-info';
        info.textContent = `Page ${currentPage + 1} of ${totalPages}`;

        const buttons = document.createElement('div');
        buttons.className = 'page-buttons';

        // Previous arrow
        const prevBtn = document.createElement('button');
        prevBtn.className = 'page-btn';
        prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';
        prevBtn.disabled = currentPage === 0;
        prevBtn.addEventListener('click', () => onPageChange(currentPage - 1));
        buttons.appendChild(prevBtn);

        // Page numbers
        const pages = this._getPageNumbers(currentPage, totalPages);
        pages.forEach(p => {
            if (p === '...') {
                const ellipsis = document.createElement('span');
                ellipsis.className = 'page-ellipsis';
                ellipsis.textContent = '...';
                buttons.appendChild(ellipsis);
            } else {
                const btn = document.createElement('button');
                btn.className = 'page-btn' + (p === currentPage ? ' active' : '');
                btn.textContent = p + 1;
                btn.addEventListener('click', () => onPageChange(p));
                buttons.appendChild(btn);
            }
        });

        // Next arrow
        const nextBtn = document.createElement('button');
        nextBtn.className = 'page-btn';
        nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';
        nextBtn.disabled = currentPage >= totalPages - 1;
        nextBtn.addEventListener('click', () => onPageChange(currentPage + 1));
        buttons.appendChild(nextBtn);

        div.append(info, buttons);
        return div;
    }

    _getPageNumbers(current, total) {
        if (total <= 5) return Array.from({ length: total }, (_, i) => i);
        const pages = [];
        pages.push(0);
        if (current > 2) pages.push('...');
        for (let i = Math.max(1, current - 1); i <= Math.min(total - 2, current + 1); i++) {
            pages.push(i);
        }
        if (current < total - 3) pages.push('...');
        pages.push(total - 1);
        return pages;
    }

    _renderStarsHTML(rating) {
        const rounded = Math.round(rating);
        let html = '';
        for (let i = 1; i <= 5; i++) {
            if (i <= rounded) {
                html += '<i class="fas fa-star"></i>';
            } else {
                html += '<i class="fas fa-star star-empty"></i>';
            }
        }
        return html;
    }

    _escapeHTML(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

// Global instance (created after DOM ready in app.js)
window.UserPanes = UserPanes;
