/**
 * Digger pane controller — AI-powered record-hunting assistant.
 *
 * Shows an onboarding card when Digger is not enabled for the user,
 * otherwise loads and renders the user's digger wantlist as a table.
 */
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
            { label: 'Artist', cls: 'col-artist' },
            { label: 'Title', cls: 'col-title' },
            { label: 'Year', cls: 'col-year' },
            { label: 'Tier', cls: 'col-tier' },
            { label: 'Active listings', cls: 'col-listings' },
            { label: 'Last scraped', cls: 'col-scraped' },
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
     * Kept as a separate helper so T3 can extend it.
     * @param {Object} item - Wantlist item from API
     * @returns {HTMLTableRowElement}
     */
    _buildRow(item) {
        const tr = document.createElement('tr');
        tr.dataset.releaseId = String(item.release_id);

        const cells = [
            item.artist || '—',
            item.title  || '—',
            item.year   != null ? String(item.year) : '—',
            item.tier   || '—',
            item.active_listings != null ? String(item.active_listings) : '0',
            this._formatScrapedAt(item.last_scraped_at),
        ];

        for (const text of cells) {
            const td = document.createElement('td');
            td.textContent = text;
            tr.appendChild(td);
        }

        return tr;
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
