'use strict';

const DLQ_NAMES = [
    'graphinator-artists-dlq', 'graphinator-labels-dlq',
    'graphinator-masters-dlq', 'graphinator-releases-dlq',
    'tableinator-artists-dlq', 'tableinator-labels-dlq',
    'tableinator-masters-dlq', 'tableinator-releases-dlq',
];

// Helper: create a table row with a single "no data" cell spanning colSpan columns
function _emptyRow(colSpan, message) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = colSpan;
    td.className = 'py-3 text-center t-muted';
    td.textContent = message;
    tr.appendChild(td);
    return tr;
}

class AdminDashboard {
    constructor() {
        this.token = localStorage.getItem('admin_token');
        this.refreshInterval = null;
        this.activeTab = 'extractions';
        this.initTheme();
        this.bindEvents();
        if (this.token) {
            this.showPanel();
        } else {
            this.showLogin();
        }
    }

    // ─── Theme toggle ────────────────────────────────────────────────────────

    initTheme() {
        const btn = document.getElementById('theme-toggle');
        const autoIcon = document.getElementById('theme-icon-auto');
        const sunIcon = document.getElementById('theme-icon-sun');
        const moonIcon = document.getElementById('theme-icon-moon');
        if (!btn || !autoIcon || !sunIcon || !moonIcon) return;

        const getMode = () => localStorage.getItem('theme') || 'auto';

        const applyMode = (mode) => {
            if (mode === 'auto') {
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                document.documentElement.classList.toggle('dark', prefersDark);
            } else {
                document.documentElement.classList.toggle('dark', mode === 'dark');
            }
        };

        const updateIcons = () => {
            const mode = getMode();
            autoIcon.classList.toggle('hidden', mode !== 'auto');
            sunIcon.classList.toggle('hidden', mode !== 'light');
            moonIcon.classList.toggle('hidden', mode !== 'dark');
        };

        applyMode(getMode());
        updateIcons();

        const cycle = { auto: 'light', light: 'dark', dark: 'auto' };

        btn.addEventListener('click', () => {
            const next = cycle[getMode()];
            if (next === 'auto') {
                localStorage.removeItem('theme');
            } else {
                localStorage.setItem('theme', next);
            }
            applyMode(next);
            updateIcons();
        });

        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (getMode() === 'auto') {
                document.documentElement.classList.toggle('dark', e.matches);
                updateIcons();
            }
        });
    }

    // ─── Event binding ───────────────────────────────────────────────────────

    bindEvents() {
        const loginBtn = document.getElementById('login-btn');
        if (loginBtn) {
            loginBtn.addEventListener('click', () => this.login());
        }

        const passwordInput = document.getElementById('login-password');
        if (passwordInput) {
            passwordInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') this.login();
            });
        }

        const emailInput = document.getElementById('login-email');
        if (emailInput) {
            emailInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') this.login();
            });
        }

        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => this.logout());
        }

        const triggerBtn = document.getElementById('trigger-btn');
        if (triggerBtn) {
            triggerBtn.addEventListener('click', () => this.triggerExtraction());
        }

        // Tab navigation
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });

        // Collapsible sections
        document.querySelectorAll('.collapsible-header').forEach(header => {
            header.addEventListener('click', () => {
                const targetId = header.dataset.target;
                const body = document.getElementById(targetId);
                const chevron = header.querySelector('.collapsible-chevron');
                if (!body) return;
                body.classList.toggle('collapsed');
                if (chevron) {
                    chevron.textContent = body.classList.contains('collapsed') ? 'chevron_right' : 'expand_more';
                }
            });
        });

        // Manual refresh buttons
        const usersRefreshBtn = document.getElementById('users-refresh-btn');
        if (usersRefreshBtn) {
            usersRefreshBtn.addEventListener('click', () => {
                this.fetchUserStats();
                this.fetchSyncActivity();
            });
        }

        const storageRefreshBtn = document.getElementById('storage-refresh-btn');
        if (storageRefreshBtn) {
            storageRefreshBtn.addEventListener('click', () => this.fetchStorage());
        }
    }

    // ─── Tab switching ───────────────────────────────────────────────────────

    switchTab(tabName) {
        this.activeTab = tabName;

        // Update button active states
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Show/hide panels
        const panels = ['extractions', 'dlq', 'users', 'storage'];
        panels.forEach(name => {
            const el = document.getElementById(`tab-${name}`);
            if (el) el.style.display = name === tabName ? 'block' : 'none';
        });

        // Fetch data when switching to a tab that needs it
        if (tabName === 'users') {
            this.fetchUserStats();
            this.fetchSyncActivity();
        } else if (tabName === 'storage') {
            this.fetchStorage();
        }
    }

    // ─── View switching ──────────────────────────────────────────────────────

    showLogin() {
        document.getElementById('admin-view').style.display = 'none';
        document.getElementById('login-view').style.display = 'flex';
        this.stopAutoRefresh();
    }

    showPanel() {
        document.getElementById('login-view').style.display = 'none';
        document.getElementById('admin-view').style.display = 'block';
        this.renderDlqList();
        this.loadExtractions();
        this.startAutoRefresh();

        // Show email if stored
        const email = localStorage.getItem('admin_email');
        const emailEl = document.getElementById('admin-email');
        if (emailEl && email) {
            emailEl.textContent = email;
        }
    }

    // ─── Auth ────────────────────────────────────────────────────────────────

    async login() {
        const email = document.getElementById('login-email').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');
        const loginBtn = document.getElementById('login-btn');

        if (!email || !password) {
            errorEl.textContent = 'Email and password are required';
            errorEl.style.display = 'block';
            return;
        }

        loginBtn.disabled = true;
        errorEl.style.display = 'none';

        try {
            const response = await fetch('/admin/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password }),
            });

            if (response.ok) {
                const data = await response.json();
                this.token = data.token;
                localStorage.setItem('admin_token', data.token);
                localStorage.setItem('admin_email', email);
                this.showPanel();
            } else {
                const err = await response.json().catch(() => ({}));
                errorEl.textContent = err.detail || 'Invalid credentials';
                errorEl.style.display = 'block';
            }
        } catch {
            errorEl.textContent = 'Connection error. Please try again.';
            errorEl.style.display = 'block';
        } finally {
            loginBtn.disabled = false;
        }
    }

    async logout() {
        try {
            await this.authFetch('/admin/api/logout', { method: 'POST' });
        } catch {
            // Ignore errors on logout
        }
        this.token = null;
        localStorage.removeItem('admin_token');
        localStorage.removeItem('admin_email');
        this.showLogin();
    }

    async authFetch(url, options = {}) {
        const headers = { ...options.headers };
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        const response = await fetch(url, { ...options, headers });
        if (response.status === 401) {
            this.token = null;
            localStorage.removeItem('admin_token');
            this.showLogin();
        }
        return response;
    }

    // ─── Extractions ─────────────────────────────────────────────────────────

    async loadExtractions() {
        try {
            const response = await this.authFetch('/admin/api/extractions');
            if (!response.ok) return;

            const data = await response.json();
            const extractions = data.extractions || [];
            const historyBody = document.getElementById('history-body');
            const emptyMsg = document.getElementById('history-empty');

            if (extractions.length === 0) {
                historyBody.replaceChildren();
                emptyMsg.style.display = 'block';
                return;
            }

            emptyMsg.style.display = 'none';

            const rows = extractions.map(e => {
                const tr = document.createElement('tr');
                tr.className = 'border-b b-row';

                const tdDate = document.createElement('td');
                tdDate.className = 'py-2.5 pr-4 mono t-mid';
                tdDate.textContent = e.started_at ? new Date(e.started_at).toLocaleString() : '\u2014';

                const tdStatus = document.createElement('td');
                tdStatus.className = 'py-2.5 pr-4';
                const badge = document.createElement('span');
                badge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${this._statusBadgeClass(e.status)}`;
                badge.textContent = e.status;
                tdStatus.appendChild(badge);

                const tdDuration = document.createElement('td');
                tdDuration.className = 'py-2.5 pr-4 mono t-mid';
                tdDuration.textContent = e.duration || '\u2014';

                const tdRecords = document.createElement('td');
                tdRecords.className = 'py-2.5 pr-4 mono t-mid text-right';
                tdRecords.textContent = e.records != null ? Number(e.records).toLocaleString() : '\u2014';

                const tdError = document.createElement('td');
                tdError.className = 'py-2.5 mono t-muted text-xs truncate max-w-[200px]';
                tdError.textContent = e.error || '\u2014';
                if (e.error) tdError.title = e.error;

                tr.append(tdDate, tdStatus, tdDuration, tdRecords, tdError);
                return tr;
            });

            historyBody.replaceChildren(...rows);

            // Update current status badge
            const latest = extractions[0];
            if (latest) {
                const statusEl = document.getElementById('extraction-status');
                if (statusEl) {
                    statusEl.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${this._statusBadgeClass(latest.status)}`;
                    statusEl.textContent = latest.status;
                }
            }
        } catch {
            // Silently fail — will retry on next auto-refresh
        }
    }

    async triggerExtraction() {
        const triggerBtn = document.getElementById('trigger-btn');
        const spinner = document.getElementById('trigger-spinner');

        triggerBtn.disabled = true;
        spinner.style.display = 'inline-block';

        try {
            const response = await this.authFetch('/admin/api/extractions/trigger', {
                method: 'POST',
            });

            if (response.ok) {
                this.showToast('Extraction triggered successfully', 'success');
                await this.loadExtractions();
            } else {
                const err = await response.json().catch(() => ({}));
                this.showToast(err.detail || 'Failed to trigger extraction', 'error');
            }
        } catch {
            this.showToast('Connection error', 'error');
        } finally {
            triggerBtn.disabled = false;
            spinner.style.display = 'none';
        }
    }

    // ─── DLQ Management ──────────────────────────────────────────────────────

    renderDlqList() {
        const container = document.getElementById('dlq-list');
        if (!container) return;

        const items = DLQ_NAMES.map(queue => {
            const parts = queue.replace('-dlq', '').split('-');
            const service = parts[0];
            const type = parts[1];

            const row = document.createElement('div');
            row.className = 'flex items-center justify-between py-2.5 border-b b-row';

            const left = document.createElement('div');
            left.className = 'flex items-center gap-3';

            const icon = document.createElement('span');
            icon.className = 'material-symbols-outlined text-sm t-muted';
            icon.textContent = 'mail';

            const name = document.createElement('span');
            name.className = 'text-xs mono t-mid';
            name.textContent = queue;

            const serviceBadge = document.createElement('span');
            serviceBadge.className = 'text-[10px] px-1.5 py-0.5 rounded t-muted bg-inner border b-theme uppercase font-bold';
            serviceBadge.textContent = service;

            const typeBadge = document.createElement('span');
            typeBadge.className = 'text-[10px] px-1.5 py-0.5 rounded t-muted bg-inner border b-theme uppercase font-bold';
            typeBadge.textContent = type;

            left.append(icon, name, serviceBadge, typeBadge);

            const purgeBtn = document.createElement('button');
            purgeBtn.className = 'text-[10px] px-3 py-1 rounded font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors flex items-center gap-1';
            purgeBtn.addEventListener('click', () => this.purgeDlq(queue));

            const deleteIcon = document.createElement('span');
            deleteIcon.className = 'material-symbols-outlined';
            deleteIcon.style.fontSize = '12px';
            deleteIcon.textContent = 'delete';

            purgeBtn.append(deleteIcon, document.createTextNode(' Purge'));

            row.append(left, purgeBtn);
            return row;
        });

        container.replaceChildren(...items);
    }

    async purgeDlq(queue) {
        if (!confirm(`Are you sure you want to purge ${queue}?\n\nThis will permanently delete all messages in this dead letter queue.`)) {
            return;
        }

        try {
            const response = await this.authFetch(`/admin/api/dlq/purge/${queue}`, {
                method: 'POST',
            });

            if (response.ok) {
                const data = await response.json().catch(() => ({}));
                const count = data.purged != null ? data.purged : 0;
                this.showToast(`Purged ${count} message(s) from ${queue}`, 'success');
            } else {
                const err = await response.json().catch(() => ({}));
                this.showToast(err.detail || `Failed to purge ${queue}`, 'error');
            }
        } catch {
            this.showToast('Connection error', 'error');
        }
    }

    // ─── User Activity ────────────────────────────────────────────────────────

    async fetchUserStats() {
        const loadingEl = document.getElementById('users-loading');
        const errorEl = document.getElementById('users-error');
        const errorMsgEl = document.getElementById('users-error-msg');
        if (loadingEl) loadingEl.style.display = 'inline';
        if (errorEl) errorEl.style.display = 'none';

        try {
            const response = await this.authFetch('/admin/api/users/stats');
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                this._showInlineError(errorEl, errorMsgEl, err.detail || `Error ${response.status}`);
                return;
            }

            const data = await response.json();

            this._setText('stat-total-users', data.total_users != null ? Number(data.total_users).toLocaleString() : '—');
            this._setText('stat-active-7d', data.active_7d != null ? Number(data.active_7d).toLocaleString() : '—');
            this._setText('stat-active-30d', data.active_30d != null ? Number(data.active_30d).toLocaleString() : '—');
            this._setText('stat-oauth-rate', data.oauth_rate != null ? `${data.oauth_rate.toFixed(1)}%` : '—');

            // Render daily registrations table
            const tbody = document.getElementById('registrations-body');
            if (tbody) {
                const rows = data.daily_registrations || [];
                if (rows.length === 0) {
                    tbody.replaceChildren(_emptyRow(3, 'No registration data available'));
                } else {
                    tbody.replaceChildren(...rows.map(row => {
                        const tr = document.createElement('tr');
                        tr.className = 'border-b b-row';

                        const tdDate = document.createElement('td');
                        tdDate.className = 'py-2 px-4 mono t-mid';
                        tdDate.textContent = row.date || '—';

                        const tdNew = document.createElement('td');
                        tdNew.className = 'py-2 px-4 mono t-mid text-right';
                        tdNew.textContent = row.new_users != null ? Number(row.new_users).toLocaleString() : '—';

                        const tdOAuth = document.createElement('td');
                        tdOAuth.className = 'py-2 px-4 mono t-mid text-right';
                        tdOAuth.textContent = row.oauth_users != null ? Number(row.oauth_users).toLocaleString() : '—';

                        tr.append(tdDate, tdNew, tdOAuth);
                        return tr;
                    }));
                }
            }
        } catch {
            this._showInlineError(errorEl, errorMsgEl, 'Failed to load user stats');
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    async fetchSyncActivity() {
        try {
            const response = await this.authFetch('/admin/api/users/sync-activity');
            if (!response.ok) return;

            const data = await response.json();
            const w7 = data['7d'] || {};
            const w30 = data['30d'] || {};

            this._setText('stat-syncs-per-day-7d', w7.syncs_per_day != null ? w7.syncs_per_day.toFixed(1) : '—');
            this._setText('stat-syncs-per-day-30d-label', w30.syncs_per_day != null ? `30d: ${w30.syncs_per_day.toFixed(1)}` : '');

            this._setText('stat-avg-items-7d', w7.avg_items_synced != null ? Number(w7.avg_items_synced).toLocaleString() : '—');
            this._setText('stat-avg-items-30d-label', w30.avg_items_synced != null ? `30d: ${Number(w30.avg_items_synced).toLocaleString()}` : '');

            this._setText('stat-failure-rate-7d', w7.failure_rate != null ? `${w7.failure_rate.toFixed(1)}%` : '—');
            this._setText('stat-failure-rate-30d-label', w30.failure_rate != null ? `30d: ${w30.failure_rate.toFixed(1)}%` : '');
        } catch {
            // Silently fail — non-critical secondary fetch
        }
    }

    // ─── Storage Utilization ──────────────────────────────────────────────────

    async fetchStorage() {
        const loadingEl = document.getElementById('storage-loading');
        const errorEl = document.getElementById('storage-error');
        const errorMsgEl = document.getElementById('storage-error-msg');
        if (loadingEl) loadingEl.style.display = 'inline';
        if (errorEl) errorEl.style.display = 'none';

        try {
            const response = await this.authFetch('/admin/api/storage');
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                this._showInlineError(errorEl, errorMsgEl, err.detail || `Error ${response.status}`);
                return;
            }

            const data = await response.json();
            this._renderNeo4j(data.neo4j || {});
            this._renderPostgres(data.postgres || {});
            this._renderRedis(data.redis || {});
        } catch {
            this._showInlineError(errorEl, errorMsgEl, 'Failed to load storage data');
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    _renderNeo4j(neo4j) {
        const badge = document.getElementById('neo4j-status-badge');
        if (badge) {
            const ok = neo4j.status === 'ok';
            badge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${ok ? 'badge-ok' : 'badge-error'}`;
            badge.textContent = neo4j.status || '—';
        }

        if (neo4j.status !== 'ok') return;

        // Node counts
        const nodesTbody = document.getElementById('neo4j-nodes-body');
        if (nodesTbody) {
            const nodes = neo4j.node_counts || [];
            if (nodes.length === 0) {
                nodesTbody.replaceChildren(_emptyRow(2, 'No data'));
            } else {
                nodesTbody.replaceChildren(...nodes.map(item => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';
                    const tdLabel = document.createElement('td');
                    tdLabel.className = 'py-1.5 pr-4 mono t-mid';
                    tdLabel.textContent = item.label || '—';
                    const tdCount = document.createElement('td');
                    tdCount.className = 'py-1.5 mono t-mid text-right';
                    tdCount.textContent = item.count != null ? Number(item.count).toLocaleString() : '—';
                    tr.append(tdLabel, tdCount);
                    return tr;
                }));
            }
        }

        // Relationship counts
        const relsTbody = document.getElementById('neo4j-rels-body');
        if (relsTbody) {
            const rels = neo4j.relationship_counts || [];
            if (rels.length === 0) {
                relsTbody.replaceChildren(_emptyRow(2, 'No data'));
            } else {
                relsTbody.replaceChildren(...rels.map(item => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';
                    const tdType = document.createElement('td');
                    tdType.className = 'py-1.5 pr-4 mono t-mid';
                    tdType.textContent = item.type || '—';
                    const tdCount = document.createElement('td');
                    tdCount.className = 'py-1.5 mono t-mid text-right';
                    tdCount.textContent = item.count != null ? Number(item.count).toLocaleString() : '—';
                    tr.append(tdType, tdCount);
                    return tr;
                }));
            }
        }

        // Store sizes summary
        const storeSizesEl = document.getElementById('neo4j-store-sizes');
        if (storeSizesEl) {
            storeSizesEl.replaceChildren();
            const sizes = neo4j.store_sizes || {};
            const entries = Object.entries(sizes);
            if (entries.length > 0) {
                const label = document.createElement('p');
                label.className = 'text-[10px] font-bold uppercase tracking-wider t-muted mb-2';
                label.textContent = 'Store Sizes';
                storeSizesEl.appendChild(label);

                const grid = document.createElement('div');
                grid.className = 'flex flex-wrap gap-3';
                entries.forEach(([key, value]) => {
                    const card = document.createElement('div');
                    card.className = 'stat-card';
                    card.style.flex = '0 1 auto';
                    card.style.minWidth = '140px';
                    const cardLabel = document.createElement('p');
                    cardLabel.className = 'text-[10px] font-bold uppercase tracking-wider t-muted mb-1';
                    cardLabel.textContent = key.replace(/_/g, ' ');
                    const cardValue = document.createElement('p');
                    cardValue.className = 'text-base font-semibold mono t-high';
                    cardValue.textContent = value || '—';
                    card.append(cardLabel, cardValue);
                    grid.appendChild(card);
                });
                storeSizesEl.appendChild(grid);
            }
        }
    }

    _renderPostgres(postgres) {
        const badge = document.getElementById('postgres-status-badge');
        if (badge) {
            const ok = postgres.status === 'ok';
            badge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${ok ? 'badge-ok' : 'badge-error'}`;
            badge.textContent = postgres.status || '—';
        }

        if (postgres.status !== 'ok') return;

        const dbSizeEl = document.getElementById('postgres-db-size');
        if (dbSizeEl && postgres.total_size) {
            dbSizeEl.textContent = `Total database size: ${postgres.total_size}`;
        }

        const tbody = document.getElementById('postgres-tables-body');
        if (tbody) {
            const tables = postgres.tables || [];
            if (tables.length === 0) {
                tbody.replaceChildren(_emptyRow(4, 'No data'));
            } else {
                tbody.replaceChildren(...tables.map(t => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';

                    const tdName = document.createElement('td');
                    tdName.className = 'py-2 pr-4 mono t-mid';
                    tdName.textContent = t.table_name || '—';

                    const tdRows = document.createElement('td');
                    tdRows.className = 'py-2 pr-4 mono t-mid text-right';
                    tdRows.textContent = t.row_count != null ? Number(t.row_count).toLocaleString() : '—';

                    const tdData = document.createElement('td');
                    tdData.className = 'py-2 pr-4 mono t-mid text-right';
                    tdData.textContent = t.data_size || '—';

                    const tdIndex = document.createElement('td');
                    tdIndex.className = 'py-2 mono t-mid text-right';
                    tdIndex.textContent = t.index_size || '—';

                    tr.append(tdName, tdRows, tdData, tdIndex);
                    return tr;
                }));
            }
        }
    }

    _renderRedis(redis) {
        const badge = document.getElementById('redis-status-badge');
        if (badge) {
            const ok = redis.status === 'ok';
            badge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${ok ? 'badge-ok' : 'badge-error'}`;
            badge.textContent = redis.status || '—';
        }

        if (redis.status !== 'ok') return;

        this._setText('redis-mem-used', redis.memory_used || '—');
        this._setText('redis-mem-peak', redis.memory_peak || '—');
        this._setText('redis-total-keys', redis.total_keys != null ? Number(redis.total_keys).toLocaleString() : '—');

        const tbody = document.getElementById('redis-keys-body');
        if (tbody) {
            const prefixes = redis.keys_by_prefix || {};
            const entries = Object.entries(prefixes);
            if (entries.length === 0) {
                tbody.replaceChildren(_emptyRow(2, 'No key data'));
            } else {
                tbody.replaceChildren(...entries.map(([prefix, count]) => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';
                    const tdPrefix = document.createElement('td');
                    tdPrefix.className = 'py-1.5 pr-4 mono t-mid';
                    tdPrefix.textContent = prefix;
                    const tdCount = document.createElement('td');
                    tdCount.className = 'py-1.5 mono t-mid text-right';
                    tdCount.textContent = Number(count).toLocaleString();
                    tr.append(tdPrefix, tdCount);
                    return tr;
                }));
            }
        }
    }

    // ─── Toast ───────────────────────────────────────────────────────────────

    showToast(message, type = 'success') {
        const toast = document.getElementById('toast');
        if (!toast) return;

        toast.textContent = message;
        toast.style.display = 'block';

        if (type === 'success') {
            toast.style.backgroundColor = '#059669';
            toast.style.color = '#fff';
        } else {
            toast.style.backgroundColor = '#DC2626';
            toast.style.color = '#fff';
        }

        // Animate in
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        // Animate out after 3 seconds
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(0.5rem)';
            setTimeout(() => {
                toast.style.display = 'none';
            }, 300);
        }, 3000);
    }

    // ─── Auto-refresh ────────────────────────────────────────────────────────

    startAutoRefresh() {
        this.stopAutoRefresh();
        this.refreshInterval = setInterval(() => {
            this.loadExtractions();
            if (this.activeTab === 'users') {
                this.fetchUserStats();
                this.fetchSyncActivity();
            } else if (this.activeTab === 'storage') {
                this.fetchStorage();
            }
        }, 60000);
    }

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    // ─── Helpers ─────────────────────────────────────────────────────────────

    _statusBadgeClass(status) {
        switch ((status || '').toLowerCase()) {
            case 'completed': return 'badge-completed';
            case 'failed':    return 'badge-failed';
            case 'running':
            case 'pending':   return 'badge-running';
            default:          return 'badge-idle';
        }
    }

    _setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    _showInlineError(errorEl, errorMsgEl, message) {
        if (errorMsgEl) errorMsgEl.textContent = message;
        if (errorEl) errorEl.style.display = 'flex';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.adminDashboard = new AdminDashboard();
});
