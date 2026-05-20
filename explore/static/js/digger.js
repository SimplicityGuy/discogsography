/**
 * Digger pane controller — AI-powered record-hunting assistant.
 *
 * Shows an onboarding card when Digger is not enabled for the user,
 * otherwise loads and renders the user's digger wantlist as a table.
 */

const DIGGER_TIERS = ['must', 'nice', 'eventually'];
const DIGGER_CONDITIONS = ['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P'];
const DIGGER_SLEEVE_CONDITIONS = ['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P', 'generic', 'no_cover'];

class DiggerPane {
    constructor() {
        this._settings = null;
        this._items = [];
        this._isLoading = false;

        this._loading = document.getElementById('diggerLoading');
        this._body = document.getElementById('diggerBody');
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
                // Digger enabled — load wantlist
                this._settings = res.body;
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

        this._renderTable();
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

    _renderTable() {
        const wrap = document.createElement('div');
        wrap.className = 'release-table-wrap digger-table-wrap';

        const scroll = document.createElement('div');
        scroll.className = 'release-table-scroll';

        const table = document.createElement('table');
        table.className = 'release-table digger-table';

        // Header
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
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

        // Body
        const tbody = document.createElement('tbody');
        for (const item of this._items) {
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
}

window.diggerPane = new DiggerPane();
