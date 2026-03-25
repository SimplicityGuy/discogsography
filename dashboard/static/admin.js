'use strict';

const DLQ_NAMES = [
    'graphinator-artists-dlq', 'graphinator-labels-dlq',
    'graphinator-masters-dlq', 'graphinator-releases-dlq',
    'tableinator-artists-dlq', 'tableinator-labels-dlq',
    'tableinator-masters-dlq', 'tableinator-releases-dlq',
];

class AdminDashboard {
    constructor() {
        this.token = localStorage.getItem('admin_token');
        this.refreshInterval = null;
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
        this.refreshInterval = setInterval(() => this.loadExtractions(), 30000);
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
}

document.addEventListener('DOMContentLoaded', () => {
    window.adminDashboard = new AdminDashboard();
});
