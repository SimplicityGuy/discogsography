import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

/**
 * Regression coverage for discogsography-3t37: overlapping toasts must not
 * cancel each other early. AdminDashboard.showToast() lives in
 * dashboard/static/admin.js, outside the explore test tree, so this suite
 * loads it directly via the same vm-based technique explore/__tests__/helpers.js
 * uses for explore/static/js/*.js.
 */
const __dirname = dirname(fileURLToPath(import.meta.url));
const ADMIN_JS_PATH = resolve(__dirname, '..', '..', 'dashboard', 'static', 'admin.js');

function loadAdminDashboardClass() {
    const code = readFileSync(ADMIN_JS_PATH, 'utf-8');
    // Strip the DOMContentLoaded auto-instantiation tail so loading the
    // script doesn't try to construct AdminDashboard before the test sets
    // up its own minimal DOM / mocks. The class declaration itself is kept.
    const withoutAutoInit = code.replace(
        /document\.addEventListener\(\s*['"]DOMContentLoaded['"][\s\S]*$/,
        ''
    );
    const wrapped = `(function() {\n${withoutAutoInit}\nglobalThis.__AdminDashboard = AdminDashboard;\n})();`;
    vm.runInThisContext(wrapped, { filename: ADMIN_JS_PATH });
    return globalThis.__AdminDashboard;
}

function setupAdminDOM() {
    document.body.textContent = '';

    ['login-view', 'admin-view', 'toast'].forEach((id) => {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    });
}

describe('AdminDashboard.showToast (discogsography-3t37)', () => {
    let AdminDashboard;

    beforeEach(() => {
        vi.useFakeTimers();
        setupAdminDOM();
        localStorage.clear();
        AdminDashboard = loadAdminDashboardClass();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('keeps a second toast visible instead of being hidden by the first toast stale timer', () => {
        const app = new AdminDashboard();
        const toast = document.getElementById('toast');

        app.showToast('First message', 'success');
        // Advance partway through the first toast's 3000ms window.
        vi.advanceTimersByTime(1000);

        app.showToast('Second message', 'success');
        expect(toast.textContent).toBe('Second message');

        // Advance to when the FIRST toast's original timer would have fired
        // (2000ms after the second showToast call = 3000ms after the first).
        vi.advanceTimersByTime(2000);

        // The first toast's stale timer must not have hidden the second toast.
        expect(toast.style.display).toBe('block');
        expect(toast.style.opacity).not.toBe('0');
    });

    it('still hides the toast after its own full 3000ms + 300ms window elapses', () => {
        const app = new AdminDashboard();
        const toast = document.getElementById('toast');

        app.showToast('Only message', 'success');
        vi.advanceTimersByTime(3000);
        expect(toast.style.opacity).toBe('0');

        vi.advanceTimersByTime(300);
        expect(toast.style.display).toBe('none');
    });

    it('clears a pending inner (300ms) remove timer from a rapid overlapping toast', () => {
        const app = new AdminDashboard();
        const toast = document.getElementById('toast');

        app.showToast('First message', 'success');
        // Let the first toast fully fade (opacity 0) but not yet be removed.
        vi.advanceTimersByTime(3000);
        expect(toast.style.opacity).toBe('0');

        // A new toast arrives before the 300ms display:none timer fires.
        app.showToast('Second message', 'success');
        vi.advanceTimersByTime(300);

        // The stale inner timer must not have hidden the second toast.
        expect(toast.style.display).toBe('block');
        expect(toast.textContent).toBe('Second message');
    });
});
