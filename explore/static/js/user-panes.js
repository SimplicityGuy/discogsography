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
        this._tasteCache = null;
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
                stars.appendChild(this._renderStars(f.rating));
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
        this.clearTasteCache();
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
                    this.clearTasteCache();
                    this.loadTasteFingerprint();
                }, 2000);
            } else {
                alert('Sync could not be started. Please try again later.');
            }
        } finally {
            if (btn) { btn.classList.remove('syncing'); btn.disabled = false; }
        }
    }

    // ------------------------------------------------------------------ //
    // Taste fingerprint strip
    // ------------------------------------------------------------------ //

    async loadTasteFingerprint() {
        const token = window.authManager.getToken();
        if (!token) return;
        const discogsStatus = window.authManager.getDiscogsStatus();
        if (!discogsStatus?.connected) return;

        const strip = document.getElementById('tasteStrip');
        if (!strip) return;

        // Use cache if available
        if (this._tasteCache) {
            this._renderTasteStrip(this._tasteCache);
            return;
        }

        // Show loading placeholder
        strip.replaceChildren();
        const loader = document.createElement('div');
        loader.className = 'taste-strip-loading';
        strip.appendChild(loader);

        try {
            const data = await window.apiClient.getTasteFingerprint(token);
            if (!data) {
                // 422 (< 10 items), 503, or error — hide strip
                strip.replaceChildren();
                return;
            }
            this._tasteCache = data;
            this._renderTasteStrip(data);
        } catch {
            strip.replaceChildren();
        }
    }

    clearTasteCache() {
        this._tasteCache = null;
    }

    _renderTasteStrip(data) {
        const strip = document.getElementById('tasteStrip');
        if (!strip) return;
        strip.replaceChildren();

        const container = document.createElement('div');
        container.className = 'taste-strip';

        // Column 1: Fingerprint stats
        const col1 = document.createElement('div');
        col1.className = 'taste-col';
        const h1 = document.createElement('div');
        h1.className = 'taste-col-header';
        h1.textContent = 'Fingerprint';
        col1.appendChild(h1);

        // Obscurity
        col1.appendChild(this._tasteStat(
            'Obscurity',
            data.obscurity?.score != null ? data.obscurity.score.toFixed(2) : '—',
            'purple',
        ));

        // Peak decade
        const peakText = data.peak_decade != null ? `${data.peak_decade}s` : '—';
        col1.appendChild(this._tasteStat('Peak', peakText, 'blue'));

        // Taste drift
        const driftText = this._formatDrift(data.drift);
        col1.appendChild(this._tasteStat('Drift', driftText, 'green'));

        container.appendChild(col1);

        // Column 2: Heatmap
        const col2 = document.createElement('div');
        col2.className = 'taste-col';
        const h2 = document.createElement('div');
        h2.className = 'taste-col-header';
        h2.textContent = 'Heatmap';
        col2.appendChild(h2);

        if (data.heatmap && data.heatmap.length > 0) {
            col2.appendChild(this._renderHeatmapGrid(data.heatmap));
        } else {
            const empty = document.createElement('div');
            empty.className = 'taste-empty';
            empty.textContent = '—';
            col2.appendChild(empty);
        }

        container.appendChild(col2);

        // Column 3: Blind spots + download
        const col3 = document.createElement('div');
        col3.className = 'taste-col';
        const h3 = document.createElement('div');
        h3.className = 'taste-col-header';
        h3.textContent = 'Blind Spots';
        col3.appendChild(h3);

        if (data.blind_spots && data.blind_spots.length > 0) {
            data.blind_spots.forEach(spot => {
                const item = document.createElement('div');
                item.className = 'taste-blindspot-item';
                const name = document.createElement('span');
                name.className = 'taste-blindspot-name';
                name.textContent = spot.genre;
                const count = document.createElement('span');
                count.className = 'taste-blindspot-count';
                count.textContent = `${spot.artist_overlap} artists`;
                item.append(name, count);
                col3.appendChild(item);
            });
        } else {
            const empty = document.createElement('div');
            empty.className = 'taste-empty';
            empty.textContent = 'No blind spots found';
            col3.appendChild(empty);
        }

        // Download button
        const dlBtn = document.createElement('button');
        dlBtn.className = 'taste-download-btn';
        const dlIcon = document.createElement('i');
        dlIcon.className = 'fas fa-download mr-1';
        dlBtn.append(dlIcon, 'Download Taste Card');
        dlBtn.addEventListener('click', () => this._downloadTasteCard(dlBtn));
        col3.appendChild(dlBtn);

        container.appendChild(col3);
        strip.appendChild(container);
    }

    _tasteStat(label, value, colorClass) {
        const row = document.createElement('div');
        row.className = 'taste-stat';
        const labelEl = document.createElement('span');
        labelEl.className = 'taste-stat-label';
        labelEl.textContent = label;
        const valueEl = document.createElement('span');
        valueEl.className = `taste-stat-value ${colorClass}`;
        valueEl.textContent = value;
        row.append(labelEl, valueEl);
        return row;
    }

    _formatDrift(drift) {
        if (!drift || drift.length === 0) return '—';
        const first = drift[0].top_genre;
        const last = drift[drift.length - 1].top_genre;
        if (first === last) return `${first} (consistent)`;
        return `${first} → ${last}`;
    }

    _renderHeatmapGrid(cells) {
        // Group by genre, sort by total count desc, take top 5
        const genreTotals = {};
        let maxCount = 0;
        cells.forEach(c => {
            genreTotals[c.genre] = (genreTotals[c.genre] || 0) + c.count;
            if (c.count > maxCount) maxCount = c.count;
        });
        const topGenres = Object.entries(genreTotals)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(e => e[0]);

        // Collect unique decades, sorted
        const decades = [...new Set(cells.map(c => c.decade))].sort((a, b) => a - b);

        // Build lookup: genre+decade -> count
        const lookup = {};
        cells.forEach(c => { lookup[`${c.genre}-${c.decade}`] = c.count; });

        // CSS grid: first col = genre label, rest = decade columns
        const grid = document.createElement('div');
        grid.className = 'taste-heatmap-grid';
        grid.style.gridTemplateColumns = `60px repeat(${decades.length}, 1fr)`;

        // Header row
        const corner = document.createElement('div');
        grid.appendChild(corner);
        decades.forEach(d => {
            const hdr = document.createElement('div');
            hdr.className = 'taste-heatmap-header';
            hdr.textContent = `${d}s`;
            grid.appendChild(hdr);
        });

        // Data rows
        topGenres.forEach(genre => {
            const label = document.createElement('div');
            label.className = 'taste-heatmap-label';
            label.textContent = genre;
            label.title = genre;
            grid.appendChild(label);

            decades.forEach(decade => {
                const count = lookup[`${genre}-${decade}`] || 0;
                const cell = document.createElement('div');
                cell.className = 'taste-heatmap-cell';
                const opacity = maxCount > 0 ? count / maxCount : 0;
                if (count === 0) {
                    cell.style.background = 'var(--bg-tertiary)';
                } else {
                    cell.style.background = `rgba(107, 70, 193, ${Math.max(0.15, opacity)})`;
                }
                cell.title = `${genre} ${decade}s: ${count}`;
                grid.appendChild(cell);
            });
        });

        return grid;
    }

    async _downloadTasteCard(btn) {
        const token = window.authManager.getToken();
        if (!token) return;

        const resetBtn = () => {
            btn.disabled = false;
            btn.replaceChildren();
            const icon = document.createElement('i');
            icon.className = 'fas fa-download mr-1';
            btn.append(icon, 'Download Taste Card');
        };

        btn.disabled = true;
        btn.textContent = 'Downloading...';

        const blob = await window.apiClient.getTasteCard(token);
        if (!blob) {
            btn.textContent = 'Download failed';
            setTimeout(resetBtn, 2000);
            return;
        }

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'taste-card.svg';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        resetBtn();
    }

    // ------------------------------------------------------------------ //
    // Gap analysis — "What am I missing?"
    // ------------------------------------------------------------------ //

    _gapOffset = 0;
    _gapTotal = 0;
    _gapEntityType = null;
    _gapEntityId = null;
    _gapFormats = [];
    _gapExcludeWantlist = false;
    _gapAvailableFormats = null;

    async loadGapAnalysis(entityType, entityId, reset = false) {
        const token = window.authManager.getToken();
        if (!token) return;

        this._gapEntityType = entityType;
        this._gapEntityId = entityId;
        if (reset) this._gapOffset = 0;

        // Switch to the gaps pane
        const paneLinks = document.querySelectorAll('.nav-link');
        paneLinks.forEach(l => l.classList.remove('active'));
        document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
        const gapsPane = document.getElementById('gapsPane');
        if (gapsPane) gapsPane.classList.add('active');
        const navGaps = document.getElementById('navGaps');
        if (navGaps) {
            navGaps.classList.remove('hidden');
            const link = navGaps.querySelector('.nav-link');
            if (link) link.classList.add('active');
        }

        const loading = document.getElementById('gapsLoading');
        const body = document.getElementById('gapsBody');
        if (loading) loading.classList.add('active');

        try {
            // Load available formats for filter (once)
            if (!this._gapAvailableFormats) {
                const fmtData = await window.apiClient.getCollectionFormats(token);
                this._gapAvailableFormats = fmtData?.formats || [];
            }

            const data = await window.apiClient.getCollectionGaps(token, entityType, entityId, {
                limit: this._pageSize,
                offset: this._gapOffset,
                formats: this._gapFormats,
                excludeWantlist: this._gapExcludeWantlist,
            });
            if (!data) {
                this._renderGapsEmpty(body, 'Failed to load gap analysis.');
                return;
            }
            this._gapTotal = data.pagination?.total || 0;
            this._renderGaps(body, data);
        } finally {
            if (loading) loading.classList.remove('active');
        }
    }

    _renderGaps(container, data) {
        if (!container) return;
        container.replaceChildren();

        // Summary header
        const summary = document.createElement('div');
        summary.className = 'gap-summary';

        const entityInfo = document.createElement('div');
        entityInfo.className = 'gap-entity-info';
        const entityIcon = data.entity?.type === 'artist' ? 'fa-user' : data.entity?.type === 'label' ? 'fa-tag' : 'fa-compact-disc';
        const entityTitle = document.createElement('h4');
        entityTitle.className = 'gap-entity-title';
        const titleIcon = document.createElement('i');
        titleIcon.className = `fas ${entityIcon} mr-2`;
        entityTitle.append(titleIcon, data.entity?.name || 'Unknown');
        entityInfo.appendChild(entityTitle);

        const statsRow = document.createElement('div');
        statsRow.className = 'stats-row gap-stats-row';

        const fields = [
            { label: 'Total', value: data.summary?.total || 0 },
            { label: 'Owned', value: data.summary?.owned || 0 },
            { label: 'Missing', value: data.summary?.missing || 0 },
        ];
        fields.forEach(f => {
            const card = document.createElement('div');
            card.className = 'stat-card';
            const statLabel = document.createElement('div');
            statLabel.className = 'stat-label';
            statLabel.textContent = f.label;
            const statValue = document.createElement('div');
            statValue.className = 'stat-value';
            statValue.textContent = typeof f.value === 'number' ? f.value.toLocaleString() : f.value;
            card.append(statLabel, statValue);
            statsRow.appendChild(card);
        });

        summary.append(entityInfo, statsRow);
        container.appendChild(summary);

        // Filters bar
        const filtersBar = document.createElement('div');
        filtersBar.className = 'gap-filters';

        // Format filter dropdown
        if (this._gapAvailableFormats && this._gapAvailableFormats.length > 0) {
            const formatSelect = document.createElement('select');
            formatSelect.className = 'form-input-dark gap-format-select';
            const defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = 'All formats';
            formatSelect.appendChild(defaultOpt);
            this._gapAvailableFormats.forEach(f => {
                const opt = document.createElement('option');
                opt.value = f;
                opt.textContent = f;
                if (this._gapFormats.includes(f)) opt.selected = true;
                formatSelect.appendChild(opt);
            });
            formatSelect.addEventListener('change', () => {
                const selected = formatSelect.value;
                this._gapFormats = selected ? [selected] : [];
                this._gapOffset = 0;
                this.loadGapAnalysis(this._gapEntityType, this._gapEntityId);
            });
            filtersBar.appendChild(formatSelect);
        }

        // Exclude wantlist toggle
        const wantlistLabel = document.createElement('label');
        wantlistLabel.className = 'gap-filter-toggle';
        const wantlistCheckbox = document.createElement('input');
        wantlistCheckbox.type = 'checkbox';
        wantlistCheckbox.checked = this._gapExcludeWantlist;
        wantlistCheckbox.addEventListener('change', () => {
            this._gapExcludeWantlist = wantlistCheckbox.checked;
            this._gapOffset = 0;
            this.loadGapAnalysis(this._gapEntityType, this._gapEntityId);
        });
        wantlistLabel.append(wantlistCheckbox, ' Hide wantlisted');
        filtersBar.appendChild(wantlistLabel);

        container.appendChild(filtersBar);

        // Results table
        if (!data.results || data.results.length === 0) {
            this._renderGapsEmpty(container, 'No missing releases found. You have them all!');
            return;
        }

        const wrap = this._buildGapTable(
            data.results,
            data.pagination?.total || 0,
            this._gapOffset,
            (page) => {
                this._gapOffset = page * this._pageSize;
                this.loadGapAnalysis(this._gapEntityType, this._gapEntityId);
            },
            data.pagination?.has_more || false,
        );
        container.appendChild(wrap);
    }

    _buildGapTable(releases, total, offset, onPageChange, hasMore) {
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
        const titleCount = document.createElement('span');
        titleCount.className = 'title-count';
        titleCount.textContent = `Showing ${showFrom.toLocaleString()}\u2013${showTo.toLocaleString()} of ${total.toLocaleString()} missing`;
        titleArea.appendChild(titleCount);
        header.appendChild(titleArea);
        wrap.appendChild(header);

        // Table
        const scrollWrap = document.createElement('div');
        scrollWrap.className = 'release-table-scroll';
        const table = document.createElement('table');
        table.className = 'release-table';

        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        ['Title', 'Artist', 'Label', 'Year', 'Formats', 'Genre', 'Status'].forEach(col => {
            const th = document.createElement('th');
            th.textContent = col;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        releases.forEach(r => {
            const tr = document.createElement('tr');

            const tdTitle = document.createElement('td');
            tdTitle.className = 'release-list-title';
            tdTitle.textContent = r.title || '(Unknown title)';

            const tdArtist = document.createElement('td');
            tdArtist.textContent = r.artist || '';

            const tdLabel = document.createElement('td');
            tdLabel.textContent = r.label || '';

            const tdYear = document.createElement('td');
            tdYear.className = 'cell-year';
            tdYear.textContent = r.year || '';

            const tdFormats = document.createElement('td');
            const fmts = r.formats || [];
            if (fmts.length) {
                fmts.forEach(f => {
                    const badge = document.createElement('span');
                    badge.className = 'genre-badge';
                    badge.textContent = f;
                    tdFormats.appendChild(badge);
                });
            }

            const tdGenre = document.createElement('td');
            const genres = r.genres || [];
            if (genres[0]) {
                const badge = document.createElement('span');
                badge.className = 'genre-badge';
                badge.textContent = genres[0];
                tdGenre.appendChild(badge);
            }

            const tdStatus = document.createElement('td');
            if (r.on_wantlist) {
                const badge = document.createElement('span');
                badge.className = 'ownership-badge in-wantlist';
                const icon = document.createElement('i');
                icon.className = 'fas fa-heart mr-1';
                badge.append(icon, 'Wanted');
                tdStatus.appendChild(badge);
            }

            tr.append(tdTitle, tdArtist, tdLabel, tdYear, tdFormats, tdGenre, tdStatus);
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

    _renderGapsEmpty(container, msg) {
        if (!container) return;
        const div = document.createElement('div');
        div.className = 'user-pane-empty';
        const icon = document.createElement('i');
        icon.className = 'fas fa-check-circle fa-3x mb-3';
        const p = document.createElement('p');
        p.textContent = msg;
        div.append(icon, p);
        container.appendChild(div);
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

        const titleIcon = document.createElement('span');
        titleIcon.className = 'title-icon';
        const titleIconI = document.createElement('i');
        titleIconI.className = `fas ${iconClass}`;
        titleIcon.appendChild(titleIconI);

        const titleH5 = document.createElement('h5');
        titleH5.textContent = title;

        const titleCount = document.createElement('span');
        titleCount.className = 'title-count';
        titleCount.textContent = `Showing ${showFrom.toLocaleString()}\u2013${showTo.toLocaleString()} of ${total.toLocaleString()}`;

        titleArea.append(titleIcon, titleH5, titleCount);

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
                const ratingSpan = document.createElement('span');
                ratingSpan.className = 'star-rating';
                ratingSpan.appendChild(this._renderStars(r.rating));
                tdRating.appendChild(ratingSpan);
            } else {
                const dashSpan = document.createElement('span');
                dashSpan.className = 'star-rating-dash';
                dashSpan.textContent = '\u2014';
                tdRating.appendChild(dashSpan);
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

    _renderStars(rating) {
        const frag = document.createDocumentFragment();
        const rounded = Math.round(rating);
        for (let i = 1; i <= 5; i++) {
            const star = document.createElement('i');
            star.className = i <= rounded ? 'fas fa-star' : 'fas fa-star star-empty';
            frag.appendChild(star);
        }
        return frag;
    }

}

// Global instance (created after DOM ready in app.js)
window.UserPanes = UserPanes;
