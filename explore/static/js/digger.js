/**
 * Digger pane controller — AI-powered record-hunting assistant.
 *
 * Shows an onboarding card when Digger is not enabled for the user,
 * otherwise loads and renders the user's digger wantlist as a table.
 */

const DIGGER_TIERS = ['must', 'nice', 'eventually'];
const DIGGER_CONDITIONS = ['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P'];
const DIGGER_SLEEVE_CONDITIONS = ['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P', 'generic', 'no_cover'];

// Human-readable labels for the four optimizer bundle variants.
const DIGGER_BUNDLE_LABELS = {
    cheapest: 'Cheapest',
    most_coverage: 'Most Coverage',
    best_quality: 'Best Quality',
    fewest_sellers: 'Fewest Sellers',
};

// Human-readable labels for a report's change flag.
const DIGGER_CHANGE_FLAG_LABELS = {
    first_run: 'first run',
    significant: 'significant',
    none: 'no change',
};

class DiggerPane {
    constructor() {
        this._settings = null;
        this._items = [];
        this._isLoading = false;

        // T4 — bulk-actions / filter / selection state.
        this._selected = new Set();          // selected release_ids
        this._tierFilter = 'all';            // 'all' | 'must' | 'nice' | 'eventually'
        this._hideNoListings = false;        // hide items with active_listings === 0
        this._bulkApplying = false;          // in-flight guard for bulk-tier Apply

        // M2 — reports view state.
        this._view = 'wantlist';             // 'wantlist' | 'reports' | 'report' | 'recommend' | 'chat'
        this._reports = [];                  // inbox summaries
        this._currentReport = null;          // full report being viewed
        this._recommending = false;          // in-flight guard for Run recommendation

        // M3 — agent chat sub-view state.
        this._chatSessionId = null;          // current agent session (null = new conversation)
        this._chatBusy = false;              // in-flight guard for a streaming turn
        this._chatMessages = null;           // <ul> the message bubbles are appended to

        this._loading = document.getElementById('diggerLoading');
        this._body = document.getElementById('diggerBody');
        this._headerActions = document.getElementById('diggerHeaderActions');
    }

    /**
     * Entry point — called by ExploreApp._switchPane('digger').
     * Loads settings and branches into onboarding or wantlist table.
     */
    async init() {
        const token = window.authManager.getToken();
        if (!token) return;

        if (this._isLoading) return;
        this._isLoading = true;

        if (this._loading) this._loading.classList.add('active');

        try {
            const res = await window.apiClient.getDiggerSettings(token);

            if (res.status === 404 || (res.ok && res.body && res.body.enabled === false)) {
                // Digger not enabled — store whatever we got and show onboarding
                this._settings = res.body || null;
                this._renderOnboarding();
            } else if (res.ok && res.body) {
                // Digger enabled — render the view navigation and load the wantlist.
                this._settings = res.body;
                this._view = 'wantlist';
                this._renderHeaderActions();
                await this._loadWantlist(token);
            } else {
                // Unexpected error
                this._renderError('Could not load Digger settings. Please try again later.');
            }
        } finally {
            this._isLoading = false;
            if (this._loading) this._loading.classList.remove('active');
        }
    }

    // ------------------------------------------------------------------ //
    // Wantlist loading
    // ------------------------------------------------------------------ //

    async _loadWantlist(token) {
        const res = await window.apiClient.getDiggerWantlist(token);
        if (res.ok && res.body) {
            this._items = res.body.items || [];
            this._renderContent();
        } else {
            // Distinguish a failed load from a genuinely empty wantlist.
            this._renderError('Could not load your Digger wantlist. Please try again later.');
        }
    }

    // ------------------------------------------------------------------ //
    // Rendering
    // ------------------------------------------------------------------ //

    _renderOnboarding() {
        // No view navigation while Digger is disabled.
        if (this._headerActions) this._headerActions.textContent = '';

        if (!this._body) return;
        this._body.textContent = '';

        const card = document.createElement('div');
        card.className = 'digger-onboarding settings-card';

        const header = document.createElement('div');
        header.className = 'settings-card-header';

        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined';
        icon.textContent = 'travel_explore';
        header.appendChild(icon);

        const title = document.createElement('h3');
        title.textContent = 'Digger';
        header.appendChild(title);

        card.appendChild(header);

        const body = document.createElement('div');
        body.className = 'settings-card-body';

        const desc = document.createElement('p');
        desc.className = 'text-text-mid text-sm mb-3';
        desc.textContent =
            'Digger is your AI-powered record-hunting assistant. ' +
            'Enable it to automatically track new listings for your wantlist items, ' +
            'with smart condition and price filtering.';
        body.appendChild(desc);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-primary';
        btn.textContent = 'Open Digger Settings';
        btn.addEventListener('click', () => {
            if (window.exploreApp) {
                window.exploreApp._previousPane = 'digger';
                window.exploreApp._switchPane('settings');
            }
        });
        body.appendChild(btn);

        card.appendChild(body);
        this._body.appendChild(card);
    }

    _renderContent() {
        if (!this._body) return;
        this._body.textContent = '';

        if (!this._items || this._items.length === 0) {
            this._renderEmpty();
            return;
        }

        // Top-to-bottom: stats banner → controls (filters + bulk bar) → table.
        this._renderStatsBanner();
        this._renderControls();
        this._renderTable();
    }

    /**
     * Re-fetch the wantlist and fully re-render (stats + controls + table).
     * Reuses _loadWantlist, which sets _items and calls _renderContent.
     */
    async refresh() {
        const token = window.authManager.getToken();
        if (!token) return;
        await this._loadWantlist(token);
    }

    // ------------------------------------------------------------------ //
    // Stats banner
    // ------------------------------------------------------------------ //

    /**
     * Render the stats banner. Computed from ALL items (never the filtered set).
     *
     * NOTE: This banner reflects state at the last FULL render (init / filter
     * change / bulk refresh). Per-row tier edits (T3) intentionally do NOT update
     * the banner live — those controls are kept decoupled from the banner.
     */
    _renderStatsBanner() {
        const counts = { must: 0, nice: 0, eventually: 0 };
        let mustAvailable = 0;
        for (const item of this._items) {
            if (counts[item.tier] != null) counts[item.tier] += 1;
            if (item.tier === 'must' && item.active_listings > 0) mustAvailable += 1;
        }

        const row = document.createElement('div');
        row.className = 'stats-row digger-stats';

        row.appendChild(this._buildStatCard('Must', String(counts.must)));
        row.appendChild(this._buildStatCard('Nice', String(counts.nice)));
        row.appendChild(this._buildStatCard('Eventually', String(counts.eventually)));
        row.appendChild(this._buildStatCard('Must available', `${mustAvailable} / ${counts.must}`));

        this._body.appendChild(row);
    }

    /**
     * Build a single stat card (label + value).
     * @param {string} label
     * @param {string} value
     * @returns {HTMLDivElement}
     */
    _buildStatCard(label, value) {
        const card = document.createElement('div');
        card.className = 'stat-card';

        const lbl = document.createElement('div');
        lbl.className = 'stat-label';
        lbl.textContent = label;
        card.appendChild(lbl);

        const val = document.createElement('div');
        val.className = 'stat-value';
        val.textContent = value;
        card.appendChild(val);

        return card;
    }

    // ------------------------------------------------------------------ //
    // Controls — filters + bulk-actions bar
    // ------------------------------------------------------------------ //

    _renderControls() {
        const controls = document.createElement('div');
        controls.className = 'digger-controls';

        controls.appendChild(this._renderFilters());
        controls.appendChild(this._renderBulkBar());

        this._body.appendChild(controls);
    }

    /**
     * Build the filters bar (tier filter + hide-no-listings toggle).
     * @returns {HTMLDivElement}
     */
    _renderFilters() {
        const filters = document.createElement('div');
        filters.className = 'gap-filters digger-filters';

        // Tier filter select.
        const tierSelect = document.createElement('select');
        tierSelect.className = 'form-input-dark gap-format-select digger-filter-select';
        tierSelect.setAttribute('aria-label', 'Filter by tier');
        const tierOptions = [
            { value: 'all',        label: 'All tiers' },
            { value: 'must',       label: 'Must' },
            { value: 'nice',       label: 'Nice' },
            { value: 'eventually', label: 'Eventually' },
        ];
        for (const { value, label } of tierOptions) {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = label;
            if (value === this._tierFilter) opt.selected = true;
            tierSelect.appendChild(opt);
        }
        tierSelect.addEventListener('change', () => {
            this._tierFilter = tierSelect.value;
            this._renderTable();
        });
        filters.appendChild(tierSelect);

        // Hide-no-listings toggle.
        const hideLabel = document.createElement('label');
        hideLabel.className = 'gap-filter-toggle digger-filter-toggle';
        const hideCheckbox = document.createElement('input');
        hideCheckbox.type = 'checkbox';
        hideCheckbox.checked = this._hideNoListings;
        hideCheckbox.addEventListener('change', () => {
            this._hideNoListings = hideCheckbox.checked;
            this._renderTable();
        });
        hideLabel.append(hideCheckbox, ' Hide items with no listings');
        filters.appendChild(hideLabel);

        return filters;
    }

    /**
     * Build the bulk-actions bar. Hidden when nothing is selected.
     * @returns {HTMLDivElement}
     */
    _renderBulkBar() {
        const bar = document.createElement('div');
        bar.className = 'digger-bulk-bar';
        this._bulkBar = bar;

        // Selection count.
        const count = document.createElement('span');
        count.className = 'digger-bulk-count';
        this._bulkCount = count;
        bar.appendChild(count);

        // Tier select (bulk target).
        const tierSelect = document.createElement('select');
        tierSelect.className = 'form-input-dark digger-bulk-tier';
        tierSelect.setAttribute('aria-label', 'Bulk tier');
        for (const tier of DIGGER_TIERS) {
            const opt = document.createElement('option');
            opt.value = tier;
            // Title-case label to match the tier filter select (e.g. "Must").
            opt.textContent = tier.charAt(0).toUpperCase() + tier.slice(1);
            tierSelect.appendChild(opt);
        }
        this._bulkTierSelect = tierSelect;
        bar.appendChild(tierSelect);

        // Apply button.
        const applyBtn = document.createElement('button');
        applyBtn.type = 'button';
        applyBtn.className = 'btn-primary digger-bulk-apply';
        applyBtn.textContent = 'Apply';
        applyBtn.addEventListener('click', () => this._applyBulkTier());
        this._bulkApplyBtn = applyBtn;
        bar.appendChild(applyBtn);

        // Clear button.
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'digger-bulk-clear';
        clearBtn.textContent = 'Clear';
        clearBtn.addEventListener('click', () => this._clearSelection());
        bar.appendChild(clearBtn);

        this._updateBulkBar();
        return bar;
    }

    /**
     * Update the bulk bar's visibility and selection count to match _selected.
     */
    _updateBulkBar() {
        if (!this._bulkBar) return;
        const n = this._selected.size;
        if (this._bulkCount) this._bulkCount.textContent = `${n} selected`;
        this._bulkBar.classList.toggle('hidden', n === 0);
    }

    /**
     * Apply the chosen tier to all selected releases, then refresh on success.
     */
    async _applyBulkTier() {
        if (this._bulkApplying) return; // guard against double-submit while a request is in flight
        const token = window.authManager.getToken();
        if (!token) return;
        if (this._selected.size === 0) return;

        const tier = this._bulkTierSelect ? this._bulkTierSelect.value : DIGGER_TIERS[0];
        const ids = Array.from(this._selected);

        this._bulkApplying = true;
        if (this._bulkApplyBtn) this._bulkApplyBtn.disabled = true;
        try {
            const res = await window.apiClient.bulkSetDiggerTier(token, ids, tier);
            if (res && res.ok) {
                // Clear selection and re-fetch so tiers + stats reflect the change.
                this._selected.clear();
                await this.refresh();
            }
            // On failure: keep selection so the user can retry.
        } finally {
            this._bulkApplying = false;
            // On success, refresh() rebuilt the bar (this._bulkApplyBtn now points at the
            // fresh, hidden button); on failure it is the same button we disabled above.
            if (this._bulkApplyBtn) this._bulkApplyBtn.disabled = false;
        }
    }

    /**
     * Toggle selection for all currently visible items.
     * @param {boolean} checked
     */
    _toggleSelectAll(checked) {
        const visible = this._getVisibleItems();
        for (const item of visible) {
            if (checked) {
                this._selected.add(item.release_id);
            } else {
                this._selected.delete(item.release_id);
            }
        }
        // Reflect on the visible row checkboxes without a full re-render.
        const rows = this._body.querySelectorAll('.digger-table tbody tr');
        for (const tr of rows) {
            const cb = tr.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = checked;
        }
        this._syncSelectAllCheckbox();
        this._updateBulkBar();
    }

    /**
     * Keep the header select-all checkbox in sync with row selection state.
     */
    _syncSelectAllCheckbox() {
        const selectAll = this._body.querySelector('.digger-table thead input[type="checkbox"]');
        if (!selectAll) return;
        const visible = this._getVisibleItems();
        selectAll.checked = visible.length > 0 && visible.every((it) => this._selected.has(it.release_id));
    }

    /**
     * Clear the entire selection, uncheck visible rows, and hide the bulk bar.
     */
    _clearSelection() {
        this._selected.clear();
        const rows = this._body.querySelectorAll('.digger-table tbody tr');
        for (const tr of rows) {
            const cb = tr.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = false;
        }
        this._syncSelectAllCheckbox();
        this._updateBulkBar();
    }

    _renderEmpty() {
        if (!this._body) return;
        this._body.textContent = '';

        const empty = document.createElement('div');
        empty.className = 'user-pane-empty';

        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined icon-3x mb-3';
        icon.textContent = 'travel_explore';
        empty.appendChild(icon);

        const msg = document.createElement('p');
        msg.textContent = 'No wantlist items found. Add records to your Discogs wantlist and sync to get started.';
        empty.appendChild(msg);

        this._body.appendChild(empty);
    }

    _renderError(message) {
        if (!this._body) return;
        this._body.textContent = '';

        const empty = document.createElement('div');
        empty.className = 'user-pane-empty';

        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined icon-3x mb-3';
        icon.textContent = 'error_outline';
        empty.appendChild(icon);

        const msg = document.createElement('p');
        msg.textContent = message || 'Could not load Digger. Please try again later.';
        empty.appendChild(msg);

        this._body.appendChild(empty);
    }

    /**
     * Items currently visible given the active filters.
     * @returns {Array<Object>}
     */
    _getVisibleItems() {
        return this._items.filter((item) => {
            if (this._tierFilter !== 'all' && item.tier !== this._tierFilter) return false;
            if (this._hideNoListings && !(item.active_listings > 0)) return false;
            return true;
        });
    }

    /**
     * Render (or re-render) just the table rows for the currently visible items.
     * Removes any existing table wrap first so filter changes don't stack tables.
     */
    _renderTable() {
        // Drop any prior table (filter re-render) without touching banner/controls.
        const existing = this._body.querySelector('.digger-table-wrap');
        if (existing) existing.remove();

        const wrap = document.createElement('div');
        wrap.className = 'release-table-wrap digger-table-wrap';

        const scroll = document.createElement('div');
        scroll.className = 'release-table-scroll';

        const table = document.createElement('table');
        table.className = 'release-table digger-table';

        // Header
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');

        // Leading select-all column.
        const thSelect = document.createElement('th');
        thSelect.className = 'col-select';
        const selectAll = document.createElement('input');
        selectAll.type = 'checkbox';
        selectAll.setAttribute('aria-label', 'Select all');
        const visibleNow = this._getVisibleItems();
        selectAll.checked = visibleNow.length > 0 && visibleNow.every((it) => this._selected.has(it.release_id));
        selectAll.addEventListener('change', () => this._toggleSelectAll(selectAll.checked));
        thSelect.appendChild(selectAll);
        headerRow.appendChild(thSelect);

        const columns = [
            { label: 'Artist',          cls: 'col-artist' },
            { label: 'Title',           cls: 'col-title' },
            { label: 'Year',            cls: 'col-year' },
            { label: 'Tier',            cls: 'col-tier' },
            { label: 'Media',           cls: 'col-media' },
            { label: 'Sleeve',          cls: 'col-sleeve' },
            { label: 'Max price',       cls: 'col-price' },
            { label: 'Active listings', cls: 'col-listings' },
            { label: 'Last scraped',    cls: 'col-scraped' },
        ];
        for (const { label, cls } of columns) {
            const th = document.createElement('th');
            th.className = cls;
            th.textContent = label;
            headerRow.appendChild(th);
        }
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Body — only visible items.
        const tbody = document.createElement('tbody');
        for (const item of visibleNow) {
            tbody.appendChild(this._buildRow(item));
        }
        table.appendChild(tbody);

        scroll.appendChild(table);
        wrap.appendChild(scroll);
        this._body.appendChild(wrap);
    }

    /**
     * Build a single table row for a wantlist item.
     * @param {Object} item - Wantlist item from API
     * @returns {HTMLTableRowElement}
     */
    _buildRow(item) {
        const tr = document.createElement('tr');
        tr.dataset.releaseId = String(item.release_id);

        // Row-selection checkbox (leading column)
        const tdSelect = document.createElement('td');
        tdSelect.className = 'col-select';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = this._selected.has(item.release_id);
        checkbox.setAttribute('aria-label', 'Select row');
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) {
                this._selected.add(item.release_id);
            } else {
                this._selected.delete(item.release_id);
            }
            // Single-checkbox toggle: update the bulk bar only — no full re-render.
            this._updateBulkBar();
            this._syncSelectAllCheckbox();
        });
        tdSelect.appendChild(checkbox);
        tr.appendChild(tdSelect);

        // Artist (plain text)
        const tdArtist = document.createElement('td');
        tdArtist.textContent = item.artist || '—';
        tr.appendChild(tdArtist);

        // Title (plain text)
        const tdTitle = document.createElement('td');
        tdTitle.textContent = item.title || '—';
        tr.appendChild(tdTitle);

        // Year (plain text)
        const tdYear = document.createElement('td');
        tdYear.textContent = item.year != null ? String(item.year) : '—';
        tr.appendChild(tdYear);

        // Tier (segmented toggle)
        const tdTier = document.createElement('td');
        tdTier.appendChild(this._buildTierToggle(item));
        tr.appendChild(tdTier);

        // Media condition (select)
        const tdMedia = document.createElement('td');
        tdMedia.appendChild(this._buildConditionSelect(item, 'media'));
        tr.appendChild(tdMedia);

        // Sleeve condition (select)
        const tdSleeve = document.createElement('td');
        tdSleeve.appendChild(this._buildConditionSelect(item, 'sleeve'));
        tr.appendChild(tdSleeve);

        // Max price (number input, dollars)
        const tdPrice = document.createElement('td');
        tdPrice.appendChild(this._buildMaxPriceInput(item));
        tr.appendChild(tdPrice);

        // Active listings (plain text)
        const tdListings = document.createElement('td');
        tdListings.textContent = item.active_listings != null ? String(item.active_listings) : '0';
        tr.appendChild(tdListings);

        // Last scraped (plain text)
        const tdScraped = document.createElement('td');
        tdScraped.textContent = this._formatScrapedAt(item.last_scraped_at);
        tr.appendChild(tdScraped);

        return tr;
    }

    /**
     * Build a segmented tier toggle for a row item.
     * @param {Object} item
     * @returns {HTMLDivElement}
     */
    _buildTierToggle(item) {
        const group = document.createElement('div');
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', 'Tier');
        group.className = 'digger-tier-group';

        for (const tier of DIGGER_TIERS) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'search-chip digger-tier-btn';
            btn.textContent = tier;
            btn.dataset.tier = tier;

            const isActive = item.tier === tier;
            btn.setAttribute('aria-pressed', String(isActive));
            if (isActive) btn.classList.add('active');

            btn.addEventListener('click', async () => {
                if (btn.getAttribute('aria-pressed') === 'true') return; // already active

                const token = window.authManager.getToken();
                if (!token) return;

                const res = await window.apiClient.setDiggerPriority(token, item.release_id, { tier });

                if (res.ok) {
                    // Update in-memory state
                    item.tier = tier;
                    // Update all buttons in the group
                    const allBtns = group.querySelectorAll('.digger-tier-btn');
                    for (const b of allBtns) {
                        const pressed = b.dataset.tier === tier;
                        b.setAttribute('aria-pressed', String(pressed));
                        b.classList.toggle('active', pressed);
                    }
                }
                // On failure: leave buttons as-is (no visual change committed)
            });

            group.appendChild(btn);
        }

        return group;
    }

    /**
     * Build a condition <select> for media or sleeve.
     * @param {Object} item
     * @param {'media'|'sleeve'} type
     * @returns {HTMLSelectElement}
     */
    _buildConditionSelect(item, type) {
        const isMedia = type === 'media';
        const options = isMedia ? DIGGER_CONDITIONS : DIGGER_SLEEVE_CONDITIONS;
        const currentValue = isMedia ? item.min_media_condition : item.min_sleeve_condition;

        const sel = document.createElement('select');
        sel.className = 'form-input-dark digger-cell-control';

        for (const val of options) {
            const opt = document.createElement('option');
            opt.value = val;
            opt.textContent = val;
            if (val === currentValue) opt.selected = true;
            sel.appendChild(opt);
        }

        sel.addEventListener('change', async () => {
            const token = window.authManager.getToken();
            if (!token) return;

            const value = sel.value;
            const patch = isMedia
                ? { min_media_condition: value }
                : { min_sleeve_condition: value };

            const res = await window.apiClient.setDiggerPriority(token, item.release_id, patch);

            if (res.ok) {
                // Update in-memory state
                if (isMedia) {
                    item.min_media_condition = value;
                } else {
                    item.min_sleeve_condition = value;
                }
            } else {
                // Revert the control to the item's unchanged value
                sel.value = isMedia ? item.min_media_condition : item.min_sleeve_condition;
            }
        });

        return sel;
    }

    /**
     * Build a max-price number input (displays dollars, stores cents).
     * @param {Object} item
     * @returns {HTMLInputElement}
     */
    _buildMaxPriceInput(item) {
        const input = document.createElement('input');
        input.type = 'number';
        input.min = '0';
        input.step = '0.01';
        input.className = 'form-input-dark digger-cell-control';

        input.value = item.max_price_cents != null ? String(item.max_price_cents / 100) : '';

        input.addEventListener('change', async () => {
            const token = window.authManager.getToken();
            if (!token) return;

            // Note: <input type="number"> sanitizes non-numeric text to '' (per the HTML
            // spec, in browsers and jsdom alike), so `raw` is always either '' or a valid
            // number string — NaN cannot reach the API here.
            const raw = input.value.trim();
            const max_price_cents = raw === '' ? null : Math.round(Number(raw) * 100);

            const res = await window.apiClient.setDiggerPriority(token, item.release_id, { max_price_cents });

            if (res.ok) {
                item.max_price_cents = max_price_cents;
            } else {
                // Revert to the item's unchanged value
                input.value = item.max_price_cents != null ? String(item.max_price_cents / 100) : '';
            }
        });

        return input;
    }

    // ------------------------------------------------------------------ //
    // Utilities
    // ------------------------------------------------------------------ //

    /**
     * Format last_scraped_at ISO string as a locale date, or "never" if null.
     * @param {string|null} iso
     * @returns {string}
     */
    _formatScrapedAt(iso) {
        if (!iso) return 'never';
        try {
            return new Date(iso).toLocaleDateString();
        } catch {
            return 'never';
        }
    }

    // ------------------------------------------------------------------ //
    // Reports — bundle rendering helpers
    // ------------------------------------------------------------------ //

    /**
     * Format an integer cents amount as a localized currency string.
     * Money flows through the optimizer in cents; the UI displays currency.
     * @param {number} cents
     * @param {string} [currency='USD'] - ISO-4217 currency code
     * @returns {string}
     */
    _formatCents(cents, currency = 'USD') {
        const amount = (Number(cents) || 0) / 100;
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency',
                currency,
                currencyDisplay: 'symbol',
            }).format(amount);
        } catch {
            // Invalid currency code — fall back to a plain decimal.
            return `${currency} ${amount.toFixed(2)}`;
        }
    }

    /**
     * Build a single bundle card showing totals, coverage, and an expandable
     * per-seller breakdown.
     * @param {Object} bundle - Optimizer Bundle (cents-denominated)
     * @param {string} currency - ISO-4217 currency code for display
     * @returns {HTMLDivElement}
     */
    _buildBundleCard(bundle, currency) {
        const card = document.createElement('div');
        card.className = `digger-bundle-card digger-bundle-${bundle.name}`;
        card.dataset.bundleName = bundle.name;

        // Header — name label + optional greedy-solver badge.
        const header = document.createElement('header');
        header.className = 'digger-bundle-header';

        const title = document.createElement('h4');
        title.className = 'digger-bundle-name';
        title.textContent = DIGGER_BUNDLE_LABELS[bundle.name] || bundle.name;
        header.appendChild(title);

        if (bundle.solver === 'greedy') {
            const badge = document.createElement('span');
            badge.className = 'badge digger-solver-greedy';
            badge.textContent = 'greedy';
            badge.title = 'Computed with the greedy fallback solver';
            header.appendChild(badge);
        }
        card.appendChild(header);

        // Grand total.
        const total = document.createElement('div');
        total.className = 'digger-bundle-total';
        total.textContent = this._formatCents(bundle.grand_total_cents, currency);
        card.appendChild(total);

        // Item + shipping breakdown.
        const breakdown = document.createElement('div');
        breakdown.className = 'digger-bundle-breakdown';
        breakdown.textContent =
            `${this._formatCents(bundle.total_item_cost_cents, currency)} items` +
            ` + ${this._formatCents(bundle.total_shipping_cents, currency)} shipping`;
        card.appendChild(breakdown);

        // Coverage counts.
        const cov = bundle.coverage || { must: 0, nice: 0, eventually: 0 };
        const coverage = document.createElement('div');
        coverage.className = 'digger-bundle-coverage';
        coverage.textContent = `${cov.must} must · ${cov.nice} nice · ${cov.eventually} eventually`;
        card.appendChild(coverage);

        // Seller count.
        const orders = bundle.seller_orders || [];
        const sellers = document.createElement('div');
        sellers.className = 'digger-bundle-sellers';
        sellers.textContent = `${orders.length} seller${orders.length === 1 ? '' : 's'}`;
        card.appendChild(sellers);

        // Reasoning hint.
        if (bundle.reasoning_hint) {
            const hint = document.createElement('p');
            hint.className = 'digger-bundle-hint';
            hint.textContent = bundle.reasoning_hint;
            card.appendChild(hint);
        }

        // Expandable per-seller breakdown (only when there are orders).
        if (orders.length > 0) {
            card.appendChild(this._buildSellerBreakdown(bundle, currency));
        }

        return card;
    }

    /**
     * Build the collapsible per-seller order breakdown for a bundle card.
     * @param {Object} bundle
     * @param {string} currency
     * @returns {HTMLDetailsElement}
     */
    _buildSellerBreakdown(bundle, currency) {
        const details = document.createElement('details');
        details.className = 'digger-bundle-details';

        const summary = document.createElement('summary');
        summary.textContent = 'Seller breakdown';
        details.appendChild(summary);

        for (const order of bundle.seller_orders || []) {
            const block = document.createElement('div');
            block.className = 'digger-seller-order';

            const head = document.createElement('div');
            head.className = 'digger-seller-order-head';
            head.textContent =
                `Seller ${order.seller_id} — ` +
                `${this._formatCents(order.subtotal_item_cents, currency)} items` +
                ` + ${this._formatCents(order.shipping_cents, currency)} shipping`;
            block.appendChild(head);

            const list = document.createElement('ul');
            list.className = 'digger-listing-list';
            for (const line of order.listings || []) {
                const li = document.createElement('li');
                li.textContent =
                    `Release ${line.release_id} — ` +
                    `${line.media_condition}/${line.sleeve_condition} — ` +
                    `${this._formatCents(line.price_cents, currency)}`;
                list.appendChild(li);
            }
            block.appendChild(list);
            details.appendChild(block);
        }

        return details;
    }

    /**
     * Build the "Watching" section listing releases with no qualifying listing.
     * Returns null when there is nothing to watch.
     * @param {number[]} releaseIds
     * @returns {HTMLElement|null}
     */
    _buildWatchingList(releaseIds) {
        if (!releaseIds || releaseIds.length === 0) return null;

        const section = document.createElement('section');
        section.className = 'digger-watching-list';

        const heading = document.createElement('h4');
        heading.textContent = 'Watching — no qualifying listings yet';
        section.appendChild(heading);

        const list = document.createElement('ul');
        for (const id of releaseIds) {
            const li = document.createElement('li');
            const link = document.createElement('a');
            link.href = `https://www.discogs.com/release/${id}`;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = `release ${id}`;
            li.appendChild(link);
            list.appendChild(li);
        }
        section.appendChild(list);

        return section;
    }

    // ------------------------------------------------------------------ //
    // Reports — header navigation
    // ------------------------------------------------------------------ //

    /**
     * Render the in-pane view navigation (Wantlist / Reports) into the header.
     * Only shown when Digger is enabled.
     */
    _renderHeaderActions() {
        if (!this._headerActions) return;
        this._headerActions.textContent = '';

        this._headerActions.appendChild(this._buildNavButton('Wantlist', 'wantlist'));
        this._headerActions.appendChild(this._buildNavButton('Reports', 'reports'));
        this._headerActions.appendChild(this._buildNavButton('Chat', 'chat'));

        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.className = 'btn-primary digger-run-btn';
        runBtn.textContent = 'Run recommendation';
        runBtn.addEventListener('click', () => this._runRecommendation());
        this._runBtn = runBtn;
        this._headerActions.appendChild(runBtn);

        this._updateNavActiveState();
    }

    /**
     * Build a single header navigation button.
     * @param {string} label
     * @param {'wantlist'|'reports'|'chat'} view
     * @returns {HTMLButtonElement}
     */
    _buildNavButton(label, view) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'digger-nav-btn';
        btn.dataset.view = view;
        btn.textContent = label;
        btn.addEventListener('click', () => {
            if (view === 'wantlist') {
                this._showWantlist();
            } else if (view === 'reports') {
                this._showReports();
            } else if (view === 'chat') {
                this._showChat();
            }
        });
        return btn;
    }

    /**
     * Reflect the current view on the navigation buttons. The report viewer is
     * part of the Reports section, so it keeps the Reports button active.
     */
    _updateNavActiveState() {
        if (!this._headerActions) return;
        const navBtns = this._headerActions.querySelectorAll('.digger-nav-btn');
        for (const btn of navBtns) {
            const view = btn.dataset.view;
            const isActive =
                (view === 'wantlist' && this._view === 'wantlist') ||
                (view === 'reports' && (this._view === 'reports' || this._view === 'report')) ||
                (view === 'chat' && this._view === 'chat');
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-pressed', String(isActive));
        }
    }

    /**
     * Switch back to the wantlist view and reload it.
     */
    async _showWantlist() {
        this._view = 'wantlist';
        this._updateNavActiveState();
        const token = window.authManager.getToken();
        if (!token) return;
        await this._loadWantlist(token);
    }

    // ------------------------------------------------------------------ //
    // Reports — inbox
    // ------------------------------------------------------------------ //

    /**
     * Switch to the reports inbox, fetching the latest summaries.
     */
    async _showReports() {
        this._view = 'reports';
        this._updateNavActiveState();
        const token = window.authManager.getToken();
        if (!token) return;

        const res = await window.apiClient.getDiggerReports(token);
        if (res.ok && res.body) {
            this._reports = res.body.items || [];
            this._renderReportsList();
        } else {
            this._renderError('Could not load your Digger reports. Please try again later.');
        }
    }

    /**
     * Render the reports inbox list (or an empty state).
     */
    _renderReportsList() {
        if (!this._body) return;
        this._body.textContent = '';

        if (!this._reports || this._reports.length === 0) {
            this._renderReportsEmpty();
            return;
        }

        const list = document.createElement('ul');
        list.className = 'digger-reports';
        for (const item of this._reports) {
            list.appendChild(this._buildReportListItem(item));
        }
        this._body.appendChild(list);
    }

    /**
     * Render the empty-inbox placeholder.
     */
    _renderReportsEmpty() {
        const empty = document.createElement('div');
        empty.className = 'user-pane-empty';

        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined icon-3x mb-3';
        icon.textContent = 'inbox';
        empty.appendChild(icon);

        const msg = document.createElement('p');
        msg.textContent = 'No reports yet — run a recommendation to generate your first one.';
        empty.appendChild(msg);

        this._body.appendChild(empty);
    }

    /**
     * Build a single inbox list item.
     * @param {Object} item - Report summary
     * @returns {HTMLLIElement}
     */
    _buildReportListItem(item) {
        const li = document.createElement('li');
        li.className = `digger-report-item ${item.read_at ? 'read' : 'unread'}`;
        li.dataset.reportId = item.report_id;

        const link = document.createElement('button');
        link.type = 'button';
        link.className = 'digger-report-link';
        link.addEventListener('click', () => this._openReport(item.report_id));

        const title = document.createElement('div');
        title.className = 'digger-report-title';
        title.textContent = item.title;
        link.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'digger-report-meta';

        const when = document.createElement('span');
        when.className = 'digger-report-when';
        when.textContent = this._formatDateTime(item.generated_at);
        meta.appendChild(when);

        const flag = document.createElement('span');
        flag.className = `digger-flag digger-flag-${item.change_flag}`;
        flag.textContent = this._changeFlagLabel(item.change_flag);
        meta.appendChild(flag);

        link.appendChild(meta);
        li.appendChild(link);
        return li;
    }

    /**
     * Human-readable label for a change flag.
     * @param {string} flag
     * @returns {string}
     */
    _changeFlagLabel(flag) {
        return DIGGER_CHANGE_FLAG_LABELS[flag] || (flag || '').replace(/_/g, ' ');
    }

    /**
     * Format an ISO timestamp as a locale date-time string, or '' on failure.
     * @param {string|null} iso
     * @returns {string}
     */
    _formatDateTime(iso) {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleString();
        } catch {
            return '';
        }
    }

    // ------------------------------------------------------------------ //
    // Reports — viewer
    // ------------------------------------------------------------------ //

    /**
     * Open a full report: fetch it, render the viewer, and mark it read.
     * @param {string} reportId
     */
    async _openReport(reportId) {
        this._view = 'report';
        this._updateNavActiveState();
        const token = window.authManager.getToken();
        if (!token) return;

        const res = await window.apiClient.getDiggerReport(token, reportId);
        if (!res.ok || !res.body) {
            this._renderError('Could not load this report. Please try again later.');
            return;
        }

        this._currentReport = res.body;
        this._renderReportViewer(this._currentReport);

        // Mark unread reports read (fire-and-forget); reflect locally so the
        // inbox shows the updated state on return.
        if (!this._currentReport.read_at) {
            window.apiClient
                .markDiggerReportRead(token, reportId)
                .then(() => {
                    const summary = this._reports.find((r) => r.report_id === reportId);
                    if (summary) summary.read_at = new Date().toISOString();
                })
                .catch(() => { /* read state is non-critical */ });
        }
    }

    /**
     * Render the report viewer (4 bundle cards + watching list).
     * @param {Object} report - Full report payload
     */
    _renderReportViewer(report) {
        const currency =
            (report.summary && report.summary.currency) ||
            (this._settings && this._settings.currency) ||
            'USD';
        this._renderBundlesView({
            title: report.title,
            generatedAt: report.generated_at,
            shippingConfidence: report.shipping_confidence,
            bundles: report.bundles || [],
            watching: report.watching || [],
            currency,
            onBack: () => this._showReports(),
        });
    }

    /**
     * Shared renderer for a set of bundles + watching list. Used by both the
     * stored-report viewer and the interactive recommendation result.
     * @param {Object} opts
     */
    _renderBundlesView(opts) {
        if (!this._body) return;
        this._body.textContent = '';

        const viewer = document.createElement('div');
        viewer.className = 'digger-report-viewer';

        if (opts.onBack) {
            const back = document.createElement('button');
            back.type = 'button';
            back.className = 'digger-back-btn';
            back.textContent = opts.backLabel || '← Back to reports';
            back.addEventListener('click', () => opts.onBack());
            viewer.appendChild(back);
        }

        const header = document.createElement('div');
        header.className = 'digger-report-viewer-header';

        const heading = document.createElement('h3');
        heading.textContent = opts.title;
        header.appendChild(heading);

        const meta = document.createElement('div');
        meta.className = 'digger-report-meta';
        if (opts.generatedAt) {
            const when = document.createElement('span');
            when.textContent = this._formatDateTime(opts.generatedAt);
            meta.appendChild(when);
        }
        if (opts.shippingConfidence) {
            const conf = document.createElement('span');
            conf.className = `badge digger-confidence-${opts.shippingConfidence}`;
            conf.textContent = `${opts.shippingConfidence} shipping confidence`;
            meta.appendChild(conf);
        }
        header.appendChild(meta);
        viewer.appendChild(header);

        const grid = document.createElement('div');
        grid.className = 'digger-bundles-grid';
        for (const bundle of opts.bundles || []) {
            grid.appendChild(this._buildBundleCard(bundle, opts.currency));
        }
        viewer.appendChild(grid);

        const watching = this._buildWatchingList(opts.watching);
        if (watching) viewer.appendChild(watching);

        this._body.appendChild(viewer);
    }

    // ------------------------------------------------------------------ //
    // Reports — interactive "Run recommendation" (SSE)
    // ------------------------------------------------------------------ //

    /**
     * Run an interactive recommendation, streaming refresh progress then the
     * resulting bundles. Guards against concurrent runs.
     */
    async _runRecommendation() {
        if (this._recommending) return; // in-flight guard
        const token = window.authManager.getToken();
        if (!token) return;

        this._recommending = true;
        if (this._runBtn) this._runBtn.disabled = true;
        this._view = 'recommend';
        this._updateNavActiveState();
        this._renderRecommendProgress('Starting recommendation…');

        let staleCount = 0;
        window.apiClient.runDiggerRecommend(token, {}, {
            onRefreshStarted: (data) => {
                staleCount = (data && data.stale_count) || 0;
                this._renderRecommendProgress(
                    staleCount === 0 ? 'Computing bundles…' : `Refreshing ${staleCount} stale listings…`,
                );
            },
            onRefreshProgress: (data) => {
                const remaining = data && data.remaining != null ? data.remaining : staleCount;
                const done = Math.max(0, staleCount - remaining);
                this._renderRecommendProgress(`Refreshing listings… ${done}/${staleCount}`);
            },
            onResult: (data) => {
                this._renderRecommendResult(data || {});
            },
            onError: (err) => {
                const reason = (err && (err.reason || err.detail)) || 'Something went wrong.';
                this._renderError(`Recommendation failed: ${reason}`);
                this._finishRecommendation();
            },
            onDone: () => {
                this._finishRecommendation();
            },
        });
    }

    /**
     * Clear the in-flight guard and re-enable the run button.
     */
    _finishRecommendation() {
        this._recommending = false;
        if (this._runBtn) this._runBtn.disabled = false;
    }

    /**
     * Render a spinner + status line while a recommendation is in progress.
     * @param {string} message
     */
    _renderRecommendProgress(message) {
        if (!this._body) return;
        this._body.textContent = '';

        const wrap = document.createElement('div');
        wrap.className = 'digger-recommend-progress';

        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        spinner.setAttribute('role', 'status');
        wrap.appendChild(spinner);

        const status = document.createElement('p');
        status.className = 'digger-recommend-status';
        status.textContent = message;
        wrap.appendChild(status);

        this._body.appendChild(wrap);
    }

    /**
     * Render the interactive recommendation result (same layout as the report
     * viewer), with a back control returning to the wantlist.
     * @param {Object} out - OptimizerOutput payload
     */
    _renderRecommendResult(out) {
        const currency = (this._settings && this._settings.currency) || 'USD';
        this._renderBundlesView({
            title: 'New recommendation',
            generatedAt: null,
            shippingConfidence: out.shipping_confidence,
            bundles: out.bundles || [],
            watching: out.watching || [],
            currency,
            onBack: () => this._showWantlist(),
            backLabel: '← Back to wantlist',
        });
    }

    // ------------------------------------------------------------------ //
    // Chat — interactive agent conversation (SSE)
    // ------------------------------------------------------------------ //

    /**
     * Switch to the chat view and render the message list + composer.
     */
    async _showChat() {
        this._view = 'chat';
        this._updateNavActiveState();
        this._renderChatView();
    }

    /**
     * Render the chat sub-view: a scrolling message list above a composer.
     */
    _renderChatView() {
        if (!this._body) return;
        this._body.textContent = '';

        const chat = document.createElement('div');
        chat.className = 'digger-chat';

        const main = document.createElement('div');
        main.className = 'digger-chat-main';

        const messages = document.createElement('ul');
        messages.className = 'digger-chat-messages';
        this._chatMessages = messages;
        main.appendChild(messages);

        const composer = document.createElement('div');
        composer.className = 'digger-chat-composer';

        const input = document.createElement('textarea');
        input.className = 'digger-chat-input';
        input.placeholder = 'Ask Digger…';
        input.rows = 2;
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._sendChatMessage();
            }
        });
        this._chatInput = input;
        composer.appendChild(input);

        const send = document.createElement('button');
        send.type = 'button';
        send.className = 'btn-primary digger-chat-send';
        send.textContent = 'Send';
        send.addEventListener('click', () => this._sendChatMessage());
        this._chatSendBtn = send;
        composer.appendChild(send);

        main.appendChild(composer);
        chat.appendChild(main);
        this._body.appendChild(chat);
    }

    /**
     * Send the composer draft as one agent turn, streaming the reply into the
     * message list. Guards against empty drafts and concurrent turns.
     */
    async _sendChatMessage() {
        if (this._chatBusy) return;
        const draft = ((this._chatInput && this._chatInput.value) || '').trim();
        if (!draft) return;
        const token = window.authManager.getToken();
        if (!token) return;

        this._chatBusy = true;
        if (this._chatSendBtn) this._chatSendBtn.disabled = true;
        if (this._chatInput) this._chatInput.value = '';

        this._appendChatUserMessage(draft);
        const assistantText = this._appendChatAssistantShell();

        window.apiClient.streamDiggerAgent(
            token,
            { user_message: draft, session_id: this._chatSessionId },
            {
                onText: (data) => {
                    assistantText.textContent += (data && data.delta) || '';
                    this._scrollChatToEnd();
                },
                onToolCall: (data) => this._appendChatToolCall(data),
                onToolResult: (data) => this._appendChatToolResult(data),
                onBundleCard: (data) => this._appendChatBundleCard(data),
                onProposalCard: (data) => this._appendChatProposalCard(data),
                onDone: (data) => {
                    if (data && data.session_id) this._chatSessionId = data.session_id;
                    this._finishChat();
                },
                onError: (err) => {
                    this._appendChatError((err && (err.reason || err.detail)) || 'Something went wrong.');
                    this._finishChat();
                },
            },
        );
    }

    /**
     * Clear the in-flight guard and re-enable the composer.
     */
    _finishChat() {
        this._chatBusy = false;
        if (this._chatSendBtn) this._chatSendBtn.disabled = false;
    }

    /**
     * Append an empty chat bubble <li> with the given role class and return it.
     * @param {string} roleClass
     * @returns {HTMLLIElement}
     */
    _appendChatMessageItem(roleClass) {
        const li = document.createElement('li');
        li.className = `digger-chat-msg ${roleClass}`;
        if (this._chatMessages) this._chatMessages.appendChild(li);
        return li;
    }

    _appendChatUserMessage(text) {
        const li = this._appendChatMessageItem('digger-chat-msg-user');
        const div = document.createElement('div');
        div.className = 'digger-chat-text';
        div.textContent = text;
        li.appendChild(div);
    }

    /**
     * Append an empty assistant bubble and return its text node for streaming.
     * @returns {HTMLDivElement}
     */
    _appendChatAssistantShell() {
        const li = this._appendChatMessageItem('digger-chat-msg-assistant');
        const div = document.createElement('div');
        div.className = 'digger-chat-text';
        li.appendChild(div);
        return div;
    }

    _appendChatToolCall(data) {
        const li = this._appendChatMessageItem('digger-chat-msg-tool');
        const pill = document.createElement('div');
        pill.className = 'digger-tool-pill';
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined';
        icon.textContent = 'build';
        pill.appendChild(icon);
        const label = document.createElement('span');
        label.textContent = (data && data.name) || 'tool';
        pill.appendChild(label);
        li.appendChild(pill);
        this._scrollChatToEnd();
    }

    _appendChatToolResult(data) {
        const li = this._appendChatMessageItem('digger-chat-msg-tool');
        const details = document.createElement('details');
        details.className = 'digger-tool-result';
        const summary = document.createElement('summary');
        summary.textContent = `${(data && data.name) || 'tool'} result`;
        details.appendChild(summary);
        const pre = document.createElement('pre');
        pre.textContent = JSON.stringify((data && data.output) ?? {}, null, 2);
        details.appendChild(pre);
        li.appendChild(details);
        this._scrollChatToEnd();
    }

    _appendChatBundleCard(data) {
        const li = this._appendChatMessageItem('digger-chat-msg-assistant');
        const currency = (this._settings && this._settings.currency) || 'USD';
        li.appendChild(this._buildBundleCard((data && data.bundle) || {}, currency));
        this._scrollChatToEnd();
    }

    _appendChatError(message) {
        const li = this._appendChatMessageItem('digger-chat-msg-error');
        li.textContent = message;
        this._scrollChatToEnd();
    }

    /**
     * Append a proposal card placeholder, then fill it with the fetched proposal.
     * The stream only carries {proposal_id, count}; the full payload is fetched
     * from the proposals endpoint so the card can show the tier changes.
     */
    _appendChatProposalCard(data) {
        const proposal = (data && data.proposal) || {};
        const li = this._appendChatMessageItem('digger-chat-msg-assistant');
        this._populateProposalCard(li, proposal.proposal_id);
        this._scrollChatToEnd();
    }

    async _populateProposalCard(container, proposalId) {
        const token = window.authManager.getToken();
        if (!token || !proposalId) return;
        const res = await window.apiClient.getDiggerProposals(token);
        const items = (res && res.ok && res.body && res.body.items) || [];
        const proposal = items.find((p) => p.proposal_id === proposalId);
        if (!proposal) {
            const note = document.createElement('div');
            note.className = 'digger-proposal-card';
            note.textContent = 'Proposal no longer available.';
            container.appendChild(note);
            return;
        }
        container.appendChild(this._buildProposalCard(proposal));
        this._scrollChatToEnd();
    }

    /**
     * Build a tier-change proposal card with Approve / Reject actions.
     * @param {Object} proposal - { proposal_id, payload: [{release_id,current_tier,proposed_tier,reason}] }
     * @returns {HTMLDivElement}
     */
    _buildProposalCard(proposal) {
        const card = document.createElement('div');
        card.className = 'digger-proposal-card';
        card.dataset.proposalId = proposal.proposal_id;

        const heading = document.createElement('h4');
        heading.textContent = 'Tier-change proposal';
        card.appendChild(heading);

        const list = document.createElement('ul');
        list.className = 'digger-proposal-changes';
        for (const change of proposal.payload || []) {
            const item = document.createElement('li');
            const desc = document.createElement('div');
            desc.textContent = `release ${change.release_id}: ${change.current_tier} → ${change.proposed_tier}`;
            item.appendChild(desc);
            if (change.reason) {
                const reason = document.createElement('div');
                reason.className = 'digger-proposal-reason';
                reason.textContent = change.reason;
                item.appendChild(reason);
            }
            list.appendChild(item);
        }
        card.appendChild(list);

        const actions = document.createElement('div');
        actions.className = 'digger-proposal-actions';

        const approveBtn = document.createElement('button');
        approveBtn.type = 'button';
        approveBtn.className = 'btn-primary';
        approveBtn.textContent = 'Approve';
        actions.appendChild(approveBtn);

        const rejectBtn = document.createElement('button');
        rejectBtn.type = 'button';
        rejectBtn.className = 'btn-secondary';
        rejectBtn.textContent = 'Reject';
        actions.appendChild(rejectBtn);

        card.appendChild(actions);

        const status = document.createElement('div');
        status.className = 'digger-proposal-status';
        card.appendChild(status);

        const setBusy = (busy) => {
            approveBtn.disabled = busy;
            rejectBtn.disabled = busy;
        };

        approveBtn.addEventListener('click', async () => {
            const token = window.authManager.getToken();
            if (!token) return;
            setBusy(true);
            const res = await window.apiClient.approveDiggerProposal(token, proposal.proposal_id);
            if (res && res.ok) {
                const applied = (res.body && res.body.applied) || 0;
                actions.remove();
                status.textContent = `Applied ${applied} change${applied === 1 ? '' : 's'}`;
                card.classList.add('approved');
            } else {
                setBusy(false);
                status.textContent = 'Could not approve. Please try again.';
            }
        });

        rejectBtn.addEventListener('click', async () => {
            const token = window.authManager.getToken();
            if (!token) return;
            setBusy(true);
            const res = await window.apiClient.rejectDiggerProposal(token, proposal.proposal_id);
            if (res && res.ok) {
                actions.remove();
                status.textContent = 'Rejected';
                card.classList.add('rejected');
            } else {
                setBusy(false);
                status.textContent = 'Could not reject. Please try again.';
            }
        });

        return card;
    }

    /**
     * Keep the newest message in view as content streams in.
     */
    _scrollChatToEnd() {
        if (this._chatMessages) this._chatMessages.scrollTop = this._chatMessages.scrollHeight;
    }
}

window.diggerPane = new DiggerPane();
