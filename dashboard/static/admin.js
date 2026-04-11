'use strict';

const DLQ_NAMES = [
    'graphinator-artists-dlq', 'graphinator-labels-dlq',
    'graphinator-masters-dlq', 'graphinator-releases-dlq',
    'tableinator-artists-dlq', 'tableinator-labels-dlq',
    'tableinator-masters-dlq', 'tableinator-releases-dlq',
    'brainzgraphinator-artists-dlq', 'brainzgraphinator-labels-dlq',
    'brainzgraphinator-releases-dlq', 'brainzgraphinator-release-groups-dlq',
    'brainztableinator-artists-dlq', 'brainztableinator-labels-dlq',
    'brainztableinator-releases-dlq', 'brainztableinator-release-groups-dlq',
];

const QUEUE_CHART_COLORS = [
    '#818cf8', '#34d399', '#f59e0b', '#f87171',
    '#a78bfa', '#38bdf8', '#fb923c', '#e879f9',
];

// generateSparklineSVG is now a DOM-safe method: AdminDashboard._createSparklineSVGElement

// Helper: HTML-escape a value for safe display (use with textContent, not innerHTML)
function _esc(str) {
    const div = document.createElement('div');
    div.textContent = String(str ?? '');
    return div.innerHTML;
}

// Helper: shorten queue names by stripping the common "discogsography-" prefix
function _shortQueueName(name) {
    return name.replace(/^discogsography-/, '');
}

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
        this.queueDepthChart = null;
        this.responseTimeChart = null;
        this._auditLogPage = 1;
        this._eaVersions = [];
        this._eaSelectedRecords = new Map();
        this._eaParsingErrors = null;
        this._eaVdRule = '';
        this._eaVdEntityType = '';
        this._eaVdPage = 1;
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
            autoIcon.style.display = mode === 'auto' ? '' : 'none';
            sunIcon.style.display = mode === 'light' ? '' : 'none';
            moonIcon.style.display = mode === 'dark' ? '' : 'none';
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

        const triggerDiscogsBtn = document.getElementById('trigger-discogs-btn');
        if (triggerDiscogsBtn) {
            triggerDiscogsBtn.addEventListener('click', () => this.triggerExtraction('discogs'));
        }

        const triggerMusicbrainzBtn = document.getElementById('trigger-musicbrainz-btn');
        if (triggerMusicbrainzBtn) {
            triggerMusicbrainzBtn.addEventListener('click', () => this.triggerExtraction('musicbrainz'));
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

        // Queue Trends refresh
        const qtRefreshBtn = document.getElementById('qt-refresh-btn');
        if (qtRefreshBtn) {
            qtRefreshBtn.addEventListener('click', () => this.fetchQueueHistory(this._getRange('queue-trends')));
        }

        // System Health refresh
        const shRefreshBtn = document.getElementById('sh-refresh-btn');
        if (shRefreshBtn) {
            shRefreshBtn.addEventListener('click', () => this.fetchHealthHistory(this._getRange('system-health')));
        }

        // Audit Log refresh and controls
        const alRefreshBtn = document.getElementById('al-refresh-btn');
        if (alRefreshBtn) alRefreshBtn.addEventListener('click', () => this.fetchAuditLog());

        const alActionFilter = document.getElementById('al-action-filter');
        if (alActionFilter) alActionFilter.addEventListener('change', () => { this._auditLogPage = 1; this.fetchAuditLog(); });

        const alPrevBtn = document.getElementById('al-prev-btn');
        if (alPrevBtn) alPrevBtn.addEventListener('click', () => { if (this._auditLogPage > 1) { this._auditLogPage--; this.fetchAuditLog(); } });

        const alNextBtn = document.getElementById('al-next-btn');
        if (alNextBtn) alNextBtn.addEventListener('click', () => { this._auditLogPage++; this.fetchAuditLog(); });

        // Range selector buttons
        document.querySelectorAll('.range-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const range = btn.dataset.range;
                const tabRange = btn.dataset.tabRange;
                // Update active state for this tab's range buttons
                document.querySelectorAll(`.range-btn[data-tab-range="${tabRange}"]`).forEach(b => {
                    b.classList.toggle('active', b === btn);
                });
                localStorage.setItem(`admin_range_${tabRange}`, range);
                if (tabRange === 'queue-trends') {
                    this.fetchQueueHistory(range);
                } else if (tabRange === 'system-health') {
                    this.fetchHealthHistory(range);
                }
            });
        });

        // Restore persisted range selections
        ['queue-trends', 'system-health'].forEach(tab => {
            const saved = localStorage.getItem(`admin_range_${tab}`);
            if (saved) {
                const btns = document.querySelectorAll(`.range-btn[data-tab-range="${tab}"]`);
                btns.forEach(b => b.classList.toggle('active', b.dataset.range === saved));
            }
        });

        // Extraction Analysis bindings
        document.querySelectorAll('.ea-view-btn').forEach(btn => {
            btn.addEventListener('click', () => this._eaSwitchView(btn.dataset.eaView));
        });

        const eaVersionSelect = document.getElementById('ea-version-select');
        if (eaVersionSelect) {
            eaVersionSelect.addEventListener('change', () => this._eaLoadReport());
        }

        const eaRefreshBtn = document.getElementById('ea-refresh-btn');
        if (eaRefreshBtn) eaRefreshBtn.addEventListener('click', () => this._eaLoadReport());

        const eaSelectAll = document.getElementById('ea-select-all');
        if (eaSelectAll) eaSelectAll.addEventListener('change', (e) => this._eaToggleSelectAll(e.target.checked));

        const eaCompareBtn = document.getElementById('ea-compare-btn');
        if (eaCompareBtn) eaCompareBtn.addEventListener('click', () => this._eaCompare());

        const eaGenerateBtn = document.getElementById('ea-generate-btn');
        if (eaGenerateBtn) eaGenerateBtn.addEventListener('click', () => this._eaGeneratePrompt());

        const eaAiGenerateBtn = document.getElementById('ea-ai-generate-btn');
        if (eaAiGenerateBtn) eaAiGenerateBtn.addEventListener('click', () => this._eaGenerateAiPrompt());

        const eaCopyBtn = document.getElementById('ea-copy-btn');
        if (eaCopyBtn) eaCopyBtn.addEventListener('click', () => this._eaCopyPrompt());

        const eaModalClose = document.getElementById('ea-modal-close');
        if (eaModalClose) eaModalClose.addEventListener('click', () => {
            const modal = document.getElementById('ea-modal');
            if (modal) modal.style.display = 'none';
        });

        // Violations detail pagination
        const eaVdClose = document.getElementById('ea-vd-close');
        if (eaVdClose) eaVdClose.addEventListener('click', () => {
            const section = document.getElementById('ea-violations-detail');
            if (section) section.style.display = 'none';
        });
        const eaVdPrev = document.getElementById('ea-vd-prev');
        if (eaVdPrev) eaVdPrev.addEventListener('click', () => {
            if (this._eaVdPage > 1) { this._eaVdPage--; this._eaLoadViolationsPage(); }
        });
        const eaVdNext = document.getElementById('ea-vd-next');
        if (eaVdNext) eaVdNext.addEventListener('click', () => {
            this._eaVdPage++; this._eaLoadViolationsPage();
        });
        const eaVdPageSize = document.getElementById('ea-vd-page-size');
        if (eaVdPageSize) eaVdPageSize.addEventListener('change', () => {
            this._eaVdPage = 1; this._eaLoadViolationsPage();
        });
    }

    // ─── Tab switching ───────────────────────────────────────────────────────

    switchTab(tabName) {
        this.activeTab = tabName;

        // Update button active states
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Show/hide panels
        const panels = ['extractions', 'dlq', 'users', 'storage', 'queue-trends', 'system-health', 'audit-log', 'extraction-analysis'];
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
        } else if (tabName === 'queue-trends') {
            this.fetchQueueHistory(this._getRange('queue-trends'));
        } else if (tabName === 'system-health') {
            this.fetchHealthHistory(this._getRange('system-health'));
        } else if (tabName === 'audit-log') {
            this.fetchAuditLog();
        } else if (tabName === 'extraction-analysis') {
            this.fetchExtractionAnalysisVersions();
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
                this.token = data.access_token;
                localStorage.setItem('admin_token', data.access_token);
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
            throw new Error('Session expired');
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

    async triggerExtraction(source = 'discogs') {
        const btnId = source === 'musicbrainz' ? 'trigger-musicbrainz-btn' : 'trigger-discogs-btn';
        const triggerBtn = document.getElementById(btnId);
        const spinner = document.getElementById('trigger-spinner');

        triggerBtn.disabled = true;
        spinner.style.display = 'inline-block';

        const endpoint = source === 'musicbrainz'
            ? '/admin/api/extractions/trigger-musicbrainz'
            : '/admin/api/extractions/trigger';

        try {
            const response = await this.authFetch(endpoint, {
                method: 'POST',
            });

            if (response.ok) {
                const label = source === 'musicbrainz' ? 'MusicBrainz' : 'Discogs';
                this.showToast(`${label} extraction triggered successfully`, 'success');
                await this.loadExtractions();
            } else {
                const err = await response.json().catch(() => ({}));
                this.showToast(err.detail || `Failed to trigger ${source} extraction`, 'error');
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
            row.className = 'flex items-center justify-between py-3.5 border-b b-row';

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
            this._renderPostgres(data.postgresql || {});
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

        if (neo4j.status !== 'ok') {
            const nodesTbody = document.getElementById('neo4j-nodes-body');
            if (nodesTbody) nodesTbody.replaceChildren(_emptyRow(2, neo4j.status === 'error' ? 'Connection error' : 'No data'));
            const relsTbody = document.getElementById('neo4j-rels-body');
            if (relsTbody) relsTbody.replaceChildren(_emptyRow(2, neo4j.status === 'error' ? 'Connection error' : 'No data'));
            return;
        }

        // Node counts
        const nodesTbody = document.getElementById('neo4j-nodes-body');
        if (nodesTbody) {
            const nodes = neo4j.nodes || neo4j.node_counts || [];
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
            const rels = neo4j.relationships || neo4j.relationship_counts || [];
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

        if (postgres.status !== 'ok') {
            // Clear the "Loading..." placeholder when status is not ok
            const tbody = document.getElementById('postgres-tables-body');
            if (tbody) tbody.replaceChildren(_emptyRow(4, postgres.status === 'error' ? 'Connection error' : 'No data'));
            return;
        }

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
                    tdName.textContent = t.name || t.table_name || '—';

                    const tdRows = document.createElement('td');
                    tdRows.className = 'py-2 pr-4 mono t-mid text-right';
                    tdRows.textContent = t.row_count != null ? Number(t.row_count).toLocaleString() : '—';

                    const tdData = document.createElement('td');
                    tdData.className = 'py-2 pr-4 mono t-mid text-right';
                    tdData.textContent = t.size || t.data_size || '—';

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
            } else if (this.activeTab === 'queue-trends') {
                this.fetchQueueHistory(this._getRange('queue-trends'));
            } else if (this.activeTab === 'system-health') {
                this.fetchHealthHistory(this._getRange('system-health'));
            } else if (this.activeTab === 'audit-log') {
                this.fetchAuditLog();
            }
        }, 60000);
    }

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    // ─── Queue Trends ───────────────────────────────────────────────────

    async fetchQueueHistory(range) {
        const loadingEl = document.getElementById('qt-loading');
        const errorEl = document.getElementById('qt-error');
        const errorMsgEl = document.getElementById('qt-error-msg');
        if (loadingEl) loadingEl.style.display = 'inline';
        if (errorEl) errorEl.style.display = 'none';

        try {
            const response = await this.authFetch(`/admin/api/queues/history?range=${encodeURIComponent(range)}`);
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                this._showInlineError(errorEl, errorMsgEl, err.detail || `Error ${response.status}`);
                return;
            }

            const data = await response.json();
            const normalized = this._normalizeQueueData(data);
            this.renderQueueSummaryTiles(normalized);
            this.renderQueueDepthChart(normalized);
            this.renderDlqGrid(normalized);
        } catch (err) {
            this._showInlineError(errorEl, errorMsgEl, `Failed to load queue history: ${err.message || err}`);
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    renderQueueSummaryTiles(data) {
        const container = document.getElementById('queue-summary-tiles');
        if (!container) return;

        const queues = data.queues || [];
        const dlqs = data.dlq_summary || [];

        const totalDepth = queues.reduce((sum, q) => {
            const pts = q.data_points || [];
            const latest = pts.length > 0 ? (pts[pts.length - 1].messages_ready || 0) : 0;
            return sum + latest;
        }, 0);
        const depthSparkPoints = this._aggregateSparkline(queues, 'messages_ready');

        const dlqTotal = dlqs.reduce((sum, q) => {
            const pts = q.data_points || [];
            const latest = pts.length > 0 ? (pts[pts.length - 1].messages_ready || 0) : 0;
            return sum + latest;
        }, 0);
        const dlqSparkPoints = this._aggregateSparkline(dlqs, 'messages_ready');

        const avgPublish = this._avgLatest(queues, 'publish_rate');
        const avgAck = this._avgLatest(queues, 'ack_rate');
        const totalConsumers = queues.reduce((sum, q) => {
            const pts = q.data_points || [];
            const latest = pts.length > 0 ? (pts[pts.length - 1].consumers || 0) : 0;
            return sum + latest;
        }, 0);

        const tiles = [
            { label: 'Total Queue Depth', value: totalDepth.toLocaleString(), spark: depthSparkPoints, color: '#818cf8' },
            { label: 'DLQ Messages', value: dlqTotal.toLocaleString(), spark: dlqSparkPoints, color: '#f87171' },
            { label: 'Avg Publish Rate', value: `${avgPublish.toFixed(1)}/s`, spark: null, color: null },
            { label: 'Avg Ack Rate', value: `${avgAck.toFixed(1)}/s`, spark: null, color: null },
            { label: 'Active Consumers', value: totalConsumers.toLocaleString(), spark: null, color: null },
        ];

        container.replaceChildren(...tiles.map(t => {
            const card = document.createElement('div');
            card.className = 'stat-card';

            const labelEl = document.createElement('p');
            labelEl.className = 'text-[10px] font-bold uppercase tracking-wider t-muted mb-1';
            labelEl.textContent = t.label;

            const row = document.createElement('div');
            row.className = 'flex items-center justify-between';

            const valEl = document.createElement('p');
            valEl.className = 'text-2xl font-semibold mono t-high';
            valEl.textContent = t.value;

            row.appendChild(valEl);

            if (t.spark && t.spark.length >= 2) {
                const sparkDiv = document.createElement('div');
                sparkDiv.appendChild(this._createSparklineSVGElement(t.spark, t.color));
                row.appendChild(sparkDiv);
            }

            card.append(labelEl, row);
            return card;
        }));
    }

    renderQueueDepthChart(data) {
        const canvas = document.getElementById('queue-depth-chart');
        if (!canvas) return;

        if (this.queueDepthChart) {
            this.queueDepthChart.destroy();
            this.queueDepthChart = null;
        }

        const queues = data.queues || [];
        if (queues.length === 0) return;

        const datasets = queues.map((q, i) => {
            const pts = q.data_points || [];
            return {
                label: _shortQueueName(q.queue_name || `Queue ${i + 1}`),
                data: pts.map(p => ({ x: p.timestamp, y: p.messages_ready || 0 })),
                borderColor: QUEUE_CHART_COLORS[i % QUEUE_CHART_COLORS.length],
                backgroundColor: QUEUE_CHART_COLORS[i % QUEUE_CHART_COLORS.length] + '20',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.3,
                fill: false,
            };
        });

        // Update legend area using safe DOM methods
        const legendEl = document.getElementById('queue-chart-legend');
        if (legendEl) {
            legendEl.replaceChildren(...datasets.map(ds => {
                const span = document.createElement('span');
                span.className = 'flex items-center gap-1';
                const swatch = document.createElement('span');
                swatch.style.cssText = `display:inline-block;width:12px;height:3px;background:${ds.borderColor};border-radius:2px`;
                const label = document.createElement('span');
                label.className = 't-muted';
                label.textContent = ds.label;
                span.append(swatch, label);
                return span;
            }));
        }

        this.queueDepthChart = new Chart(canvas, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: true },
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { tooltipFormat: 'MMM d, HH:mm' },
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', maxTicksLimit: 8 },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8' },
                    },
                },
            },
        });
    }

    renderDlqGrid(data) {
        const container = document.getElementById('dlq-grid');
        if (!container) return;

        const dlqs = data.dlq_summary || [];
        if (dlqs.length === 0) {
            container.replaceChildren();
            const empty = document.createElement('p');
            empty.className = 'text-xs t-muted col-span-2 text-center py-4';
            empty.textContent = 'No DLQ data available';
            container.appendChild(empty);
            return;
        }

        container.replaceChildren(...dlqs.map(q => {
            const card = document.createElement('div');
            card.className = 'stat-card';

            const name = document.createElement('p');
            name.className = 'text-[10px] font-bold uppercase tracking-wider t-muted mb-1 truncate';
            name.textContent = _shortQueueName(q.queue_name || '\u2014');
            name.title = q.queue_name || '';

            const row = document.createElement('div');
            row.className = 'flex items-center justify-between';

            const pts = q.data_points || [];
            const latest = pts.length > 0 ? (pts[pts.length - 1].messages_ready || 0) : 0;

            const val = document.createElement('p');
            val.className = 'text-xl font-semibold mono t-high';
            val.textContent = latest.toLocaleString();

            row.appendChild(val);

            const sparkPts = pts.map(p => p.messages_ready || 0);
            if (sparkPts.length >= 2) {
                const sparkDiv = document.createElement('div');
                sparkDiv.appendChild(this._createSparklineSVGElement(sparkPts, '#f87171'));
                row.appendChild(sparkDiv);
            }

            card.append(name, row);
            return card;
        }));
    }

    // ─── System Health ────────────────────────────────────────────────────

    async fetchHealthHistory(range) {
        const loadingEl = document.getElementById('sh-loading');
        const errorEl = document.getElementById('sh-error');
        const errorMsgEl = document.getElementById('sh-error-msg');
        if (loadingEl) loadingEl.style.display = 'inline';
        if (errorEl) errorEl.style.display = 'none';

        try {
            const response = await this.authFetch(`/admin/api/health/history?range=${encodeURIComponent(range)}`);
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                this._showInlineError(errorEl, errorMsgEl, err.detail || `Error ${response.status}`);
                return;
            }

            const data = await response.json();
            const normalized = this._normalizeHealthData(data);
            this.renderServiceCards(normalized);
            this.renderResponseTimeChart(normalized);
            this.renderEndpointsTable(normalized);
        } catch (err) {
            this._showInlineError(errorEl, errorMsgEl, `Failed to load health history: ${err.message || err}`);
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    renderServiceCards(data) {
        const container = document.getElementById('service-status-cards');
        if (!container) return;

        const services = data.services || [];
        if (services.length === 0) {
            container.replaceChildren();
            const empty = document.createElement('p');
            empty.className = 'text-xs t-muted col-span-5 text-center py-4';
            empty.textContent = 'No service data available';
            container.appendChild(empty);
            return;
        }

        container.replaceChildren(...services.map(svc => {
            const card = document.createElement('div');
            card.className = 'stat-card';

            const status = (svc.status || 'unknown').toLowerCase();
            let borderColor = '#ef4444';
            if (status === 'healthy') borderColor = '#34d399';
            else if (status === 'degraded' || status === 'starting') borderColor = '#f59e0b';
            card.style.borderLeft = `3px solid ${borderColor}`;

            const nameEl = document.createElement('p');
            nameEl.className = 'text-xs font-semibold t-high mb-2';
            nameEl.textContent = svc.service_name || '\u2014';

            const statusEl = document.createElement('p');
            statusEl.className = 'text-[10px] font-bold uppercase tracking-wider mb-2';
            statusEl.style.color = borderColor;
            statusEl.textContent = svc.status || 'unknown';

            const uptimeLabel = document.createElement('p');
            uptimeLabel.className = 'text-[10px] font-bold uppercase tracking-wider t-muted mb-0.5';
            uptimeLabel.textContent = 'Uptime';
            const uptimeVal = document.createElement('p');
            uptimeVal.className = 'text-sm font-semibold mono t-high';
            uptimeVal.textContent = svc.uptime_pct != null ? `${svc.uptime_pct.toFixed(1)}%` : '\u2014';

            const rtLabel = document.createElement('p');
            rtLabel.className = 'text-[10px] font-bold uppercase tracking-wider t-muted mb-0.5 mt-2';
            rtLabel.textContent = 'Response Time';
            const rtVal = document.createElement('p');
            rtVal.className = 'text-sm font-semibold mono t-high';
            rtVal.textContent = svc.response_time_ms != null ? `${svc.response_time_ms.toFixed(0)}ms` : '\u2014';

            card.append(nameEl, statusEl, uptimeLabel, uptimeVal, rtLabel, rtVal);
            return card;
        }));
    }

    renderResponseTimeChart(data) {
        const canvas = document.getElementById('response-time-chart');
        if (!canvas) return;

        if (this.responseTimeChart) {
            this.responseTimeChart.destroy();
            this.responseTimeChart = null;
        }

        const timeSeries = data.response_time_series || [];
        if (timeSeries.length === 0) return;

        const datasets = [
            {
                label: 'p50',
                data: timeSeries.map(p => ({ x: p.timestamp, y: p.p50 || 0 })),
                borderColor: '#34d399',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.3,
                fill: false,
            },
            {
                label: 'p95',
                data: timeSeries.map(p => ({ x: p.timestamp, y: p.p95 || 0 })),
                borderColor: '#f59e0b',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.3,
                fill: false,
            },
            {
                label: 'p99',
                data: timeSeries.map(p => ({ x: p.timestamp, y: p.p99 || 0 })),
                borderColor: '#f87171',
                borderWidth: 2,
                borderDash: [5, 3],
                pointRadius: 0,
                tension: 0.3,
                fill: false,
            },
        ];

        this.responseTimeChart = new Chart(canvas, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: true },
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { tooltipFormat: 'MMM d, HH:mm' },
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', maxTicksLimit: 8 },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: '#334155' },
                        ticks: {
                            color: '#94a3b8',
                            callback: (v) => `${v}ms`,
                        },
                    },
                },
            },
        });
    }

    renderEndpointsTable(data) {
        const tbody = document.getElementById('endpoints-tbody');
        if (!tbody) return;

        const endpoints = data.endpoints || [];
        if (endpoints.length === 0) {
            tbody.replaceChildren(_emptyRow(6, 'No endpoint data available'));
            return;
        }

        const sorted = [...endpoints].sort((a, b) => (b.request_count || 0) - (a.request_count || 0));

        tbody.replaceChildren(...sorted.map(ep => {
            const tr = document.createElement('tr');
            tr.className = 'border-b b-row';

            const tdPath = document.createElement('td');
            tdPath.className = 'py-2 px-4 mono text-xs';
            tdPath.style.color = '#818cf8';
            tdPath.textContent = ep.endpoint || '\u2014';

            const tdReqs = document.createElement('td');
            tdReqs.className = 'py-2 px-4 mono t-mid text-right';
            tdReqs.textContent = ep.request_count != null ? Number(ep.request_count).toLocaleString() : '\u2014';

            const tdP50 = document.createElement('td');
            tdP50.className = 'py-2 px-4 mono t-mid text-right';
            tdP50.textContent = ep.p50 != null ? `${ep.p50.toFixed(0)}ms` : '\u2014';

            const tdP95 = document.createElement('td');
            tdP95.className = 'py-2 px-4 mono t-mid text-right';
            tdP95.textContent = ep.p95 != null ? `${ep.p95.toFixed(0)}ms` : '\u2014';

            const tdP99 = document.createElement('td');
            tdP99.className = 'py-2 px-4 mono t-mid text-right';
            tdP99.textContent = ep.p99 != null ? `${ep.p99.toFixed(0)}ms` : '\u2014';

            const tdErr = document.createElement('td');
            tdErr.className = 'py-2 px-4 mono text-right font-semibold';
            const errPct = ep.error_pct != null ? ep.error_pct : 0;
            tdErr.textContent = `${errPct.toFixed(1)}%`;
            if (errPct < 1) tdErr.style.color = '#34d399';
            else if (errPct <= 5) tdErr.style.color = '#f59e0b';
            else tdErr.style.color = '#ef4444';

            tr.append(tdPath, tdReqs, tdP50, tdP95, tdP99, tdErr);
            return tr;
        }));
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

    _getRange(tabName) {
        return localStorage.getItem(`admin_range_${tabName}`) || '24h';
    }

    _normalizeHealthData(data) {
        // API returns {services: {name: {history: [{ts, status, response_time_ms}]}}}
        // Frontend expects {services: [{service_name, status, uptime_pct, response_time_ms}],
        //                   response_time_series: [{timestamp, p50, p95, p99}], endpoints: []}
        if (Array.isArray(data.services)) return data;

        const servicesObj = data.services || {};
        const services = Object.entries(servicesObj).map(([name, svc]) => {
            const history = svc.history || [];
            const healthyCount = history.filter(h => h.status === 'healthy').length;
            const uptime_pct = history.length > 0 ? (healthyCount / history.length) * 100 : 0;
            const latest = history.length > 0 ? history[history.length - 1] : {};
            const avgRt = history.length > 0
                ? history.reduce((s, h) => s + (h.response_time_ms || 0), 0) / history.length
                : 0;
            return {
                service_name: name,
                status: latest.status || 'unknown',
                uptime_pct,
                response_time_ms: avgRt,
            };
        });

        // Build response_time_series from all services' history
        const allTimestamps = new Map();
        for (const [, svc] of Object.entries(servicesObj)) {
            for (const h of (svc.history || [])) {
                const ts = h.ts;
                if (!allTimestamps.has(ts)) allTimestamps.set(ts, []);
                allTimestamps.get(ts).push(h.response_time_ms || 0);
            }
        }
        const response_time_series = [...allTimestamps.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([ts, times]) => {
                const sorted = [...times].sort((a, b) => a - b);
                const p = (pct) => sorted[Math.min(Math.floor(sorted.length * pct), sorted.length - 1)] || 0;
                return { timestamp: ts, p50: p(0.5), p95: p(0.95), p99: p(0.99) };
            });

        return { ...data, services, response_time_series, endpoints: data.endpoints || [] };
    }

    _normalizeQueueData(data) {
        // API returns {queues: {name: {history: [{ts, ready, unacked, total, publish_rate, deliver_rate}]}}}
        // Frontend expects {queues: [{queue_name, data_points: [{timestamp, messages_ready, ...}]}],
        //                   dlq_summary: [{queue_name, data_points: [...]}]}
        if (Array.isArray(data.queues)) return data;

        const queuesObj = data.queues || {};
        const queues = [];
        const dlq_summary = [];

        for (const [name, qData] of Object.entries(queuesObj)) {
            const data_points = (qData.history || []).map(h => ({
                timestamp: h.ts,
                messages_ready: h.ready || 0,
                messages_unacknowledged: h.unacked || 0,
                consumers: h.consumers || 0,
                publish_rate: h.publish_rate || 0,
                ack_rate: h.deliver_rate || 0,
            }));
            const entry = { queue_name: name, data_points };
            if (name.endsWith('.dlq')) {
                dlq_summary.push(entry);
            } else {
                queues.push(entry);
            }
        }

        return { ...data, queues, dlq_summary };
    }

    _aggregateSparkline(queues, field) {
        if (!queues || queues.length === 0) return [];
        // Find the max number of data points across queues
        const maxLen = Math.max(...queues.map(q => (q.data_points || []).length));
        if (maxLen === 0) return [];
        const result = [];
        for (let i = 0; i < maxLen; i++) {
            let sum = 0;
            for (const q of queues) {
                const pts = q.data_points || [];
                if (i < pts.length) {
                    sum += pts[i][field] || 0;
                }
            }
            result.push(sum);
        }
        return result;
    }

    _avgLatest(queues, field) {
        if (!queues || queues.length === 0) return 0;
        let sum = 0;
        let count = 0;
        for (const q of queues) {
            const pts = q.data_points || [];
            if (pts.length > 0) {
                sum += pts[pts.length - 1][field] || 0;
                count++;
            }
        }
        return count > 0 ? sum / count : 0;
    }

    _createSparklineSVGElement(points, color, width = 55, height = 20) {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('width', String(width));
        svg.setAttribute('height', String(height));

        if (!points || points.length < 2) return svg;

        const max = Math.max(...points);
        const min = Math.min(...points);
        const range = max - min || 1;
        const pad = 2;
        const usableH = height - pad * 2;
        const step = (width - pad * 2) / (points.length - 1);
        const coords = points.map((v, i) =>
            `${(pad + i * step).toFixed(1)},${(pad + usableH - ((v - min) / range) * usableH).toFixed(1)}`
        ).join(' ');

        const polyline = document.createElementNS(ns, 'polyline');
        polyline.setAttribute('points', coords);
        polyline.setAttribute('fill', 'none');
        polyline.setAttribute('stroke', color);
        polyline.setAttribute('stroke-width', '1.5');
        polyline.setAttribute('stroke-linecap', 'round');
        polyline.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(polyline);

        return svg;
    }

    static _prettyPrintXml(xml) {
        let formatted = '';
        let indent = 0;
        const parts = xml.replace(/>\s*</g, '><').split(/(<[^>]+>)/);
        for (const part of parts) {
            if (!part.trim()) continue;
            if (part.startsWith('</')) {
                indent = Math.max(0, indent - 1);
                formatted += '  '.repeat(indent) + part + '\n';
            } else if (part.startsWith('<') && !part.startsWith('<?') && !part.endsWith('/>') && !part.startsWith('<!')) {
                formatted += '  '.repeat(indent) + part + '\n';
                indent++;
            } else if (part.endsWith('/>')) {
                formatted += '  '.repeat(indent) + part + '\n';
            } else {
                formatted += '  '.repeat(indent) + part + '\n';
            }
        }
        return formatted.trim();
    }

    // ─── Audit Log ───────────────────────────────────────────────────────────

    async fetchAuditLog() {
        const loading = document.getElementById('al-loading');
        const error = document.getElementById('al-error');
        const errorMsg = document.getElementById('al-error-msg');

        if (loading) loading.style.display = '';
        if (error) error.style.display = 'none';

        const actionFilter = document.getElementById('al-action-filter')?.value || '';
        let url = `/admin/api/audit-log?page=${this._auditLogPage}&page_size=50`;
        if (actionFilter) url += `&action=${encodeURIComponent(actionFilter)}`;

        try {
            const resp = await this.authFetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this.renderAuditLog(data);
        } catch (err) {
            if (errorMsg) errorMsg.textContent = err.message;
            if (error) error.style.display = '';
        } finally {
            if (loading) loading.style.display = 'none';
        }
    }

    renderAuditLog(data) {
        const tbody = document.getElementById('al-table-body');
        if (!tbody) return;

        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

        if (!data.entries || data.entries.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.setAttribute('colspan', '5');
            td.className = 'text-center py-8 t-muted';
            td.textContent = 'No audit log entries';
            tr.appendChild(td);
            tbody.appendChild(tr);
        } else {
            for (const entry of data.entries) {
                const tr = document.createElement('tr');
                tr.className = 'border-b b-theme hover:bg-white/5 transition-colors';

                const tdTs = document.createElement('td');
                tdTs.className = 'py-2 px-3 t-muted whitespace-nowrap';
                tdTs.textContent = new Date(entry.created_at).toLocaleString();
                tr.appendChild(tdTs);

                const tdAdmin = document.createElement('td');
                tdAdmin.className = 'py-2 px-3';
                tdAdmin.textContent = entry.admin_email;
                tr.appendChild(tdAdmin);

                const tdAction = document.createElement('td');
                tdAction.className = 'py-2 px-3';
                const badge = document.createElement('span');
                badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400';
                badge.textContent = entry.action;
                tdAction.appendChild(badge);
                tr.appendChild(tdAction);

                const tdTarget = document.createElement('td');
                tdTarget.className = 'py-2 px-3 t-muted';
                tdTarget.textContent = entry.target || '\u2014';
                tr.appendChild(tdTarget);

                const tdDetails = document.createElement('td');
                tdDetails.className = 'py-2 px-3 t-muted text-[10px] font-mono max-w-[200px] truncate';
                const detailsText = entry.details ? JSON.stringify(entry.details) : '\u2014';
                tdDetails.textContent = detailsText;
                tdDetails.title = detailsText;
                tr.appendChild(tdDetails);

                tbody.appendChild(tr);
            }
        }

        const pagination = document.getElementById('al-pagination');
        const pageInfo = document.getElementById('al-page-info');
        const prevBtn = document.getElementById('al-prev-btn');
        const nextBtn = document.getElementById('al-next-btn');

        if (pagination && data.total > 0) {
            pagination.style.display = '';
            const totalPages = Math.ceil(data.total / data.page_size);
            if (pageInfo) pageInfo.textContent = `Page ${data.page} of ${totalPages} (${data.total} entries)`;
            if (prevBtn) prevBtn.disabled = data.page <= 1;
            if (nextBtn) nextBtn.disabled = data.page >= totalPages;
        } else if (pagination) {
            pagination.style.display = 'none';
        }
    }

    // ─── Extraction Analysis ─────────────────────────────────────────────────

    _eaSwitchView(viewName) {
        // Toggle sub-view buttons
        document.querySelectorAll('.ea-view-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.eaView === viewName);
        });
        // Toggle sub-view panels
        ['report', 'compare', 'prompt'].forEach(name => {
            const panel = document.getElementById(`ea-view-${name}`);
            if (panel) panel.style.display = name === viewName ? '' : 'none';
        });
        // Show/hide report controls in the header
        const reportControls = document.getElementById('ea-report-controls');
        if (reportControls) reportControls.style.display = viewName === 'report' ? '' : 'none';

        if (viewName === 'prompt') this._eaUpdatePromptCount();
    }

    async fetchExtractionAnalysisVersions() {
        try {
            const resp = await this.authFetch('/admin/api/extraction-analysis/versions');
            if (!resp.ok) return;
            const data = await resp.json();
            this._eaVersions = data.versions || [];
            this._eaPopulateVersionSelects();
            // Auto-load the first version
            if (this._eaVersions.length > 0) {
                const sel = document.getElementById('ea-version-select');
                if (sel && sel.value === '') {
                    sel.value = this._eaVersionString(this._eaVersions[0]);
                    this._eaLoadReport();
                }
            }
        } catch {
            // Silently fail — non-critical
        }
    }

    _eaVersionString(v) {
        return typeof v === 'string' ? v : v.version;
    }

    _eaVersionLabel(v) {
        if (typeof v === 'string') return v;
        return v.source ? `${v.version} (${v.source})` : v.version;
    }

    _eaPopulateVersionSelects() {
        const ids = ['ea-version-select', 'ea-cmp-version-a', 'ea-cmp-version-b'];
        ids.forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const current = sel.value;
            // Rebuild options
            while (sel.firstChild) sel.removeChild(sel.firstChild);
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '— select —';
            sel.appendChild(placeholder);
            this._eaVersions.forEach(v => {
                const opt = document.createElement('option');
                opt.value = this._eaVersionString(v);
                opt.textContent = this._eaVersionLabel(v);
                sel.appendChild(opt);
            });
            // Restore previous selection if still valid
            const versionStrings = this._eaVersions.map(v => this._eaVersionString(v));
            if (current && versionStrings.includes(current)) sel.value = current;
        });
    }

    async _eaLoadReport() {
        const sel = document.getElementById('ea-version-select');
        const version = sel ? sel.value : '';
        if (!version) return;

        // Reset parsing errors cache for new version
        this._eaParsingErrors = null;

        const spinner = document.getElementById('ea-loading-spinner');
        if (spinner) spinner.style.display = '';

        // Fetch summary and parsing errors in parallel
        try {
            const [summaryResp, errorsResp] = await Promise.all([
                this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/summary`),
                this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/parsing-errors`),
            ]);

            if (summaryResp.ok) {
                const summary = await summaryResp.json();
                // Update source badge
                const badge = document.getElementById('ea-source-badge');
                if (badge) {
                    badge.textContent = summary.source || 'unknown';
                    badge.style.display = '';
                    badge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${summary.source === 'discogs' ? 'badge-completed' : 'badge-running'}`;
                }
                this._eaRenderPipelineStatus(summary.pipeline_status || {});
                this._eaRenderEntityCards(summary);
                // Store parsing errors for use in rule breakdown
                if (errorsResp.ok) {
                    const errData = await errorsResp.json();
                    this._eaParsingErrors = errData;
                }
                this._eaRenderRuleBreakdown(summary.by_rule || []);
            }
        } catch {
            // Silently fail
        } finally {
            if (spinner) spinner.style.display = 'none';
        }
    }

    _eaRenderPipelineStatus(pipelineStatus) {
        const container = document.getElementById('ea-pipeline-cards');
        if (!container) return;
        const phases = Object.entries(pipelineStatus);
        if (phases.length === 0) {
            container.replaceChildren();
            const p = document.createElement('p');
            p.className = 'text-xs t-muted';
            p.textContent = 'No pipeline status available.';
            container.appendChild(p);
            return;
        }
        const cards = phases.map(([phase, status]) => {
            const card = document.createElement('div');
            card.className = 'stat-card flex flex-col gap-1';
            const label = document.createElement('p');
            label.className = 'text-[10px] font-bold uppercase tracking-wider t-muted';
            label.textContent = phase;
            const badgeEl = document.createElement('span');
            const badgeClass = status === 'completed' ? 'badge-completed' : status === 'running' ? 'badge-running' : status === 'failed' ? 'badge-failed' : 'badge-idle';
            badgeEl.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${badgeClass}`;
            badgeEl.textContent = String(status);
            card.append(label, badgeEl);
            return card;
        });
        container.replaceChildren(...cards);
    }

    _eaRenderEntityCards(summary) {
        const container = document.getElementById('ea-entity-cards');
        if (!container) return;
        const byEntity = summary.by_entity || {};
        const entries = Object.entries(byEntity);
        if (entries.length === 0) {
            container.replaceChildren();
            const p = document.createElement('p');
            p.className = 'text-xs t-muted';
            p.textContent = 'No violation data.';
            container.appendChild(p);
            return;
        }
        const cards = entries.map(([entityType, counts]) => {
            const card = document.createElement('div');
            card.className = 'stat-card flex flex-col gap-1';
            const label = document.createElement('p');
            label.className = 'text-[10px] font-bold uppercase tracking-wider t-muted';
            label.textContent = entityType;
            const total = document.createElement('p');
            total.className = 'text-xl font-bold t-high';
            total.textContent = (counts.total ?? 0).toLocaleString();
            const sub = document.createElement('p');
            sub.className = 'text-[10px] t-muted';
            sub.textContent = `${(counts.errors ?? 0)} errors · ${(counts.warnings ?? 0)} warnings`;
            card.append(label, total, sub);
            return card;
        });
        container.replaceChildren(...cards);
    }

    _eaRenderRuleBreakdown(byRule) {
        const tbody = document.getElementById('ea-rule-tbody');
        if (!tbody) return;
        if (!byRule || byRule.length === 0) {
            tbody.replaceChildren(_emptyRow(7, 'No violations found.'));
            return;
        }
        // Count parsing errors per entity type for the badge column
        const parseErrByEntity = {};
        if (this._eaParsingErrors && this._eaParsingErrors.by_entity) {
            Object.entries(this._eaParsingErrors.by_entity).forEach(([et, c]) => {
                parseErrByEntity[et] = c;
            });
        }
        const rows = byRule.map(row => {
            const tr = document.createElement('tr');
            tr.className = 'border-b b-row hover:bg-inner cursor-pointer';

            // Checkbox
            const tdChk = document.createElement('td');
            tdChk.className = 'py-2 px-2';
            const chk = document.createElement('input');
            chk.type = 'checkbox';
            chk.className = 'rounded ea-rule-chk';
            chk.dataset.rule = row.rule;
            chk.dataset.entityType = row.entity_type;
            chk.addEventListener('change', () => {
                const key = `${row.rule}::${row.entity_type}`;
                if (chk.checked) {
                    this._eaSelectedRecords.set(key, { rule: row.rule, entity_type: row.entity_type });
                } else {
                    this._eaSelectedRecords.delete(key);
                }
                this._eaUpdatePromptCount();
            });
            tdChk.appendChild(chk);

            // Rule name
            const tdRule = document.createElement('td');
            tdRule.className = 'py-2 px-2 mono t-mid';
            tdRule.textContent = row.rule;

            // Entity type
            const tdEntity = document.createElement('td');
            tdEntity.className = 'py-2 px-2 t-dim';
            tdEntity.textContent = row.entity_type || '—';

            // Severity
            const tdSev = document.createElement('td');
            tdSev.className = 'py-2 px-2';
            const sevBadge = document.createElement('span');
            const sevClass = row.severity === 'error' ? 'badge-error' : row.severity === 'warning' ? 'badge-running' : 'badge-idle';
            sevBadge.className = `text-[10px] px-1.5 py-0.5 rounded uppercase font-bold ${sevClass}`;
            sevBadge.textContent = row.severity || 'info';
            tdSev.appendChild(sevBadge);

            // Violation count
            const tdCount = document.createElement('td');
            tdCount.className = 'py-2 px-2 text-right mono t-mid';
            tdCount.textContent = (row.count ?? 0).toLocaleString();

            // Parsing errors badge
            const tdParseErr = document.createElement('td');
            tdParseErr.className = 'py-2 px-2 text-right';
            const parseCount = parseErrByEntity[row.entity_type] ?? 0;
            if (parseCount > 0) {
                const badge = document.createElement('span');
                badge.className = 'text-[10px] px-1.5 py-0.5 rounded font-bold badge-error';
                badge.textContent = parseCount.toLocaleString();
                tdParseErr.appendChild(badge);
            } else {
                tdParseErr.textContent = '—';
                tdParseErr.className += ' t-muted';
            }

            // Sample button
            const tdSample = document.createElement('td');
            tdSample.className = 'py-2 px-2 text-right';
            const sampleBtn = document.createElement('button');
            sampleBtn.className = 'text-[10px] px-2 py-0.5 rounded border b-theme t-dim hover:t-high';
            sampleBtn.textContent = 'View';
            sampleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._eaShowViolationsForRule(row.rule, row.entity_type);
            });
            tdSample.appendChild(sampleBtn);

            tr.append(tdChk, tdRule, tdEntity, tdSev, tdCount, tdParseErr, tdSample);
            return tr;
        });
        tbody.replaceChildren(...rows);
    }

    async _eaShowViolationsForRule(rule, entityType) {
        this._eaVdRule = rule;
        this._eaVdEntityType = entityType;
        this._eaVdPage = 1;
        await this._eaLoadViolationsPage();
    }

    async _eaLoadViolationsPage() {
        const sel = document.getElementById('ea-version-select');
        const version = sel ? sel.value : '';
        if (!version) return;

        const section = document.getElementById('ea-violations-detail');
        if (!section) return;
        section.style.display = '';
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });

        const ruleEl = document.getElementById('ea-vd-rule');
        if (ruleEl) ruleEl.textContent = this._eaVdRule;
        const entityEl = document.getElementById('ea-vd-entity');
        if (entityEl) entityEl.textContent = this._eaVdEntityType ? `(${this._eaVdEntityType})` : '';

        const pageSizeEl = document.getElementById('ea-vd-page-size');
        const pageSize = pageSizeEl ? parseInt(pageSizeEl.value, 10) : 50;

        const params = new URLSearchParams({
            rule: this._eaVdRule,
            page: String(this._eaVdPage),
            page_size: String(pageSize),
        });
        if (this._eaVdEntityType) params.set('entity_type', this._eaVdEntityType);

        const tbody = document.getElementById('ea-vd-tbody');
        if (tbody) tbody.replaceChildren(_emptyRow(6, 'Loading...'));

        try {
            const resp = await this.authFetch(
                `/admin/api/extraction-analysis/${encodeURIComponent(version)}/violations?${params}`,
            );
            if (!resp.ok) {
                if (tbody) tbody.replaceChildren(_emptyRow(6, 'Failed to load violations.'));
                return;
            }
            const data = await resp.json();
            const violations = data.violations || [];
            const pagination = data.pagination || {};

            if (violations.length === 0) {
                if (tbody) tbody.replaceChildren(_emptyRow(6, 'No violations found.'));
            } else if (tbody) {
                const rows = violations.map(v => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';

                    const tdId = document.createElement('td');
                    tdId.className = 'py-2 px-2 mono t-mid';
                    tdId.textContent = v.record_id || '—';

                    const tdRule = document.createElement('td');
                    tdRule.className = 'py-2 px-2 mono t-dim';
                    tdRule.textContent = v.rule || '—';

                    const tdSev = document.createElement('td');
                    tdSev.className = 'py-2 px-2';
                    const sevBadge = document.createElement('span');
                    const sevClass = v.severity === 'error' ? 'badge-error' : v.severity === 'warning' ? 'badge-running' : 'badge-idle';
                    sevBadge.className = `text-[10px] px-1.5 py-0.5 rounded uppercase font-bold ${sevClass}`;
                    sevBadge.textContent = v.severity || 'info';
                    tdSev.appendChild(sevBadge);

                    const tdField = document.createElement('td');
                    tdField.className = 'py-2 px-2 mono t-dim';
                    tdField.textContent = v.field || '—';

                    const tdValue = document.createElement('td');
                    tdValue.className = 'py-2 px-2 mono t-dim';
                    tdValue.textContent = v.field_value || '—';

                    const tdDetail = document.createElement('td');
                    tdDetail.className = 'py-2 px-2 text-right';
                    const detailBtn = document.createElement('button');
                    detailBtn.className = 'text-[10px] px-2 py-0.5 rounded border b-theme t-dim hover:t-high';
                    detailBtn.textContent = 'View';
                    detailBtn.addEventListener('click', () => this._eaShowRecordDetail(version, v.record_id));
                    tdDetail.appendChild(detailBtn);

                    tr.append(tdId, tdRule, tdSev, tdField, tdValue, tdDetail);
                    return tr;
                });
                tbody.replaceChildren(...rows);
            }

            // Update pagination controls
            const infoEl = document.getElementById('ea-vd-info');
            if (infoEl) {
                const start = ((pagination.page || 1) - 1) * (pagination.page_size || pageSize) + 1;
                const end = Math.min(start + violations.length - 1, pagination.total_items || 0);
                infoEl.textContent = `${start}–${end} of ${(pagination.total_items || 0).toLocaleString()}`;
            }

            const labelEl = document.getElementById('ea-vd-page-label');
            if (labelEl) labelEl.textContent = `${pagination.page || 1} / ${pagination.total_pages || 1}`;

            const prevBtn = document.getElementById('ea-vd-prev');
            const nextBtn = document.getElementById('ea-vd-next');
            if (prevBtn) prevBtn.disabled = (pagination.page || 1) <= 1;
            if (nextBtn) nextBtn.disabled = (pagination.page || 1) >= (pagination.total_pages || 1);
        } catch {
            if (tbody) tbody.replaceChildren(_emptyRow(6, 'Error loading violations.'));
        }
    }

    async _eaShowRecordDetail(version, recordId) {
        const modal = document.getElementById('ea-modal');
        if (!modal) return;
        try {
            const resp = await this.authFetch(
                `/admin/api/extraction-analysis/${encodeURIComponent(version)}/violations/${encodeURIComponent(recordId)}`,
            );
            if (!resp.ok) return;
            const data = await resp.json();

            const recordIdEl = document.getElementById('ea-modal-record-id');
            if (recordIdEl) recordIdEl.textContent = recordId;

            const xmlEl = document.getElementById('ea-modal-xml');
            if (xmlEl) xmlEl.textContent = data.raw_xml ? AdminDashboard._prettyPrintXml(data.raw_xml) : '(none)';

            const jsonEl = document.getElementById('ea-modal-json');
            if (jsonEl) {
                if (data.parsed_json && data.parsed_json._truncated) {
                    jsonEl.textContent = `${data.parsed_json._message}\n\nPreview:\n${data.parsed_json._preview || ''}`;
                } else {
                    jsonEl.textContent = data.parsed_json ? JSON.stringify(data.parsed_json, null, 2) : '(none)';
                }
            }

            const violList = document.getElementById('ea-modal-violations');
            if (violList) {
                const items = (data.violations || []).map(v => {
                    const li = document.createElement('li');
                    li.className = 'flex items-start gap-2';
                    const dot = document.createElement('span');
                    dot.className = `material-symbols-outlined text-xs ${v.severity === 'error' ? 'text-red-400' : 'text-amber-400'}`;
                    dot.textContent = 'circle';
                    const text = document.createElement('span');
                    text.className = 'text-xs t-mid';
                    text.textContent = `[${v.rule}] ${v.message || ''}`;
                    li.append(dot, text);
                    return li;
                });
                if (items.length === 0) {
                    const li = document.createElement('li');
                    li.className = 'text-xs t-muted';
                    li.textContent = 'No violations.';
                    violList.replaceChildren(li);
                } else {
                    violList.replaceChildren(...items);
                }
            }

            modal.style.display = 'flex';
        } catch {
            // Silently fail
        }
    }

    async _eaCompare() {
        const vA = document.getElementById('ea-cmp-version-a')?.value;
        const vB = document.getElementById('ea-cmp-version-b')?.value;
        if (!vA || !vB) {
            this.showToast('Select both versions to compare', 'error');
            return;
        }
        try {
            const resp = await this.authFetch(
                `/admin/api/extraction-analysis/${encodeURIComponent(vA)}/compare/${encodeURIComponent(vB)}`,
            );
            if (!resp.ok) {
                this.showToast('Comparison failed', 'error');
                return;
            }
            const data = await resp.json();
            const summary = document.getElementById('ea-cmp-summary');
            const tableWrap = document.getElementById('ea-cmp-table-wrap');
            const tbody = document.getElementById('ea-cmp-tbody');
            if (!summary || !tableWrap || !tbody) return;

            const totalA = data.total_a ?? 0;
            const totalB = data.total_b ?? 0;
            const delta = totalB - totalA;
            const sign = delta > 0 ? '+' : '';
            summary.textContent = `${vA}: ${totalA.toLocaleString()} violations → ${vB}: ${totalB.toLocaleString()} violations (${sign}${delta.toLocaleString()})`;
            summary.style.display = '';

            const deltas = data.delta || [];
            if (deltas.length === 0) {
                tbody.replaceChildren(_emptyRow(5, 'No differences found.'));
            } else {
                const rows = deltas.map(d => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';
                    const tdRule = document.createElement('td');
                    tdRule.className = 'py-2 px-2 mono t-mid';
                    tdRule.textContent = d.rule;
                    const tdEt = document.createElement('td');
                    tdEt.className = 'py-2 px-2 t-dim';
                    tdEt.textContent = d.entity_type || '—';
                    const tdA = document.createElement('td');
                    tdA.className = 'py-2 px-2 text-right mono t-mid';
                    tdA.textContent = (d.count_a ?? 0).toLocaleString();
                    const tdB = document.createElement('td');
                    tdB.className = 'py-2 px-2 text-right mono t-mid';
                    tdB.textContent = (d.count_b ?? 0).toLocaleString();
                    const tdDelta = document.createElement('td');
                    tdDelta.className = 'py-2 px-2 text-right mono font-bold';
                    const diff = (d.count_b ?? 0) - (d.count_a ?? 0);
                    tdDelta.textContent = (diff > 0 ? '+' : '') + diff.toLocaleString();
                    tdDelta.style.color = diff > 0 ? 'var(--text-high)' : diff < 0 ? '#10B981' : 'var(--text-dim)';
                    tr.append(tdRule, tdEt, tdA, tdB, tdDelta);
                    return tr;
                });
                tbody.replaceChildren(...rows);
            }
            tableWrap.style.display = '';
        } catch {
            this.showToast('Comparison error', 'error');
        }
    }

    _eaToggleSelectAll(checked) {
        document.querySelectorAll('.ea-rule-chk').forEach(chk => {
            chk.checked = checked;
            const key = `${chk.dataset.rule}::${chk.dataset.entityType}`;
            if (checked) {
                this._eaSelectedRecords.set(key, { rule: chk.dataset.rule, entity_type: chk.dataset.entityType });
            } else {
                this._eaSelectedRecords.delete(key);
            }
        });
        this._eaUpdatePromptCount();
    }

    _eaUpdatePromptCount() {
        const el = document.getElementById('ea-prompt-count');
        if (el) el.textContent = `${this._eaSelectedRecords.size} rule${this._eaSelectedRecords.size === 1 ? '' : 's'} selected`;
    }

    async _eaGeneratePrompt() {
        const sel = document.getElementById('ea-version-select');
        const version = sel ? sel.value : '';
        if (!version) { this.showToast('Select a version first', 'error'); return; }
        if (this._eaSelectedRecords.size === 0) { this.showToast('Select at least one rule', 'error'); return; }

        const textarea = document.getElementById('ea-prompt-textarea');
        if (textarea) textarea.value = 'Generating…';

        try {
            const rules = Array.from(this._eaSelectedRecords.values());
            const resp = await this.authFetch(
                `/admin/api/extraction-analysis/${encodeURIComponent(version)}/prompt-context`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rules }),
                },
            );
            if (!resp.ok) {
                if (textarea) textarea.value = 'Error generating prompt.';
                return;
            }
            const data = await resp.json();
            const lines = [
                `# Extraction Analysis — Version ${version}`,
                '',
                'You are debugging data quality violations from the Discogsography extraction pipeline.',
                'For each rule below, analyze the sample records to determine:',
                '1. Root cause — why did the validation rule fire?',
                '2. Whether this is a data issue (upstream Discogs data) or a parser bug',
                '3. Suggested fix or workaround',
                '',
                '---',
                '',
            ];
            (data.contexts || []).forEach(ctx => {
                lines.push(`## Rule: ${ctx.rule} (${ctx.entity_type})`);
                lines.push(`- **Severity:** ${ctx.severity || 'unknown'}`);
                lines.push(`- **Total violations:** ${(ctx.total_violations || 0).toLocaleString()}`);
                if (ctx.sample_records && ctx.sample_records.length > 0) {
                    lines.push('');
                    ctx.sample_records.forEach((rec, i) => {
                        lines.push(`### Sample ${i + 1} — Record ID: ${rec.record_id || '?'}`);
                        lines.push('');
                        if (rec.violations && rec.violations.length > 0) {
                            lines.push('**Violations:**');
                            rec.violations.forEach(v => {
                                lines.push(`- \`${v.rule}\` on field \`${v.message || '(unknown)'}\``);
                            });
                            lines.push('');
                        }
                        if (rec.parsed_json) {
                            const jsonStr = typeof rec.parsed_json === 'string'
                                ? rec.parsed_json
                                : JSON.stringify(rec.parsed_json, null, 2);
                            // Limit JSON to ~2000 chars to keep prompt manageable
                            const trimmed = jsonStr.length > 2000
                                ? jsonStr.slice(0, 2000) + '\n... (truncated)'
                                : jsonStr;
                            lines.push('**Parsed JSON:**');
                            lines.push('```json');
                            lines.push(trimmed);
                            lines.push('```');
                            lines.push('');
                        }
                        if (rec.raw_xml) {
                            // Limit XML to ~2000 chars
                            const trimmed = rec.raw_xml.length > 2000
                                ? rec.raw_xml.slice(0, 2000) + '\n... (truncated)'
                                : rec.raw_xml;
                            lines.push('**Raw XML:**');
                            lines.push('```xml');
                            lines.push(trimmed);
                            lines.push('```');
                            lines.push('');
                        }
                    });
                }
                lines.push('---');
                lines.push('');
            });
            if (textarea) textarea.value = lines.join('\n');
        } catch {
            if (textarea) textarea.value = 'Error generating prompt.';
        }
    }

    async _eaGenerateAiPrompt() {
        const sel = document.getElementById('ea-version-select');
        const version = sel ? sel.value : '';
        if (!version) { this.showToast('Select a version first', 'error'); return; }
        if (this._eaSelectedRecords.size === 0) { this.showToast('Select at least one rule', 'error'); return; }

        const textarea = document.getElementById('ea-prompt-textarea');
        const aiBtn = document.getElementById('ea-ai-generate-btn');
        const spinner = document.getElementById('ea-ai-spinner');

        if (textarea) textarea.value = 'Analyzing violations with AI — this may take a moment...';
        if (aiBtn) aiBtn.disabled = true;
        if (spinner) spinner.style.display = '';

        try {
            const rules = Array.from(this._eaSelectedRecords.values());
            const resp = await this.authFetch(
                `/admin/api/extraction-analysis/${encodeURIComponent(version)}/generate-ai-prompt`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rules }),
                },
            );
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                const detail = err.detail || 'AI prompt generation failed';
                if (textarea) textarea.value = `Error: ${detail}`;
                this.showToast(detail, 'error');
                return;
            }
            const data = await resp.json();
            if (textarea) textarea.value = data.prompt || 'No prompt generated.';
            this.showToast('AI analysis complete', 'success');
        } catch {
            if (textarea) textarea.value = 'Error: connection failed.';
            this.showToast('Connection error', 'error');
        } finally {
            if (aiBtn) aiBtn.disabled = false;
            if (spinner) spinner.style.display = 'none';
        }
    }

    async _eaCopyPrompt() {
        const textarea = document.getElementById('ea-prompt-textarea');
        if (!textarea || !textarea.value) { this.showToast('Nothing to copy', 'error'); return; }
        try {
            await navigator.clipboard.writeText(textarea.value);
            this.showToast('Prompt copied to clipboard', 'success');
        } catch {
            this.showToast('Copy failed — select all text manually', 'error');
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.adminDashboard = new AdminDashboard();
});
