import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

/**
 * Create minimal DOM elements required by DiggerPane.
 */
function setupDiggerDOM() {
    document.body.textContent = '';
    const ids = ['diggerPane', 'diggerLoading', 'diggerBody', 'diggerHeaderActions'];
    for (const id of ids) {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    }
}

describe('DiggerPane', () => {
    beforeEach(() => {
        setupDiggerDOM();
        delete globalThis.window;
        globalThis.window = globalThis;
        window.authManager = {
            getToken: vi.fn().mockReturnValue('test-token'),
            isLoggedIn: vi.fn().mockReturnValue(true),
        };
        window.apiClient = {
            getDiggerSettings: vi.fn(),
            getDiggerWantlist: vi.fn(),
        };
        window.exploreApp = undefined;
        loadScript('digger.js');
    });

    // ------------------------------------------------------------------ //
    // No token guard
    // ------------------------------------------------------------------ //

    describe('no token', () => {
        it('should not call api when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            await window.diggerPane.init();
            expect(window.apiClient.getDiggerSettings).not.toHaveBeenCalled();
            expect(window.apiClient.getDiggerWantlist).not.toHaveBeenCalled();
        });

        it('should not render anything when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            const body = document.getElementById('diggerBody');
            const initialContent = body.innerHTML;
            await window.diggerPane.init();
            expect(body.innerHTML).toBe(initialContent);
        });
    });

    // ------------------------------------------------------------------ //
    // Onboarding — settings 404
    // ------------------------------------------------------------------ //

    describe('settings 404 → onboarding', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 404,
                body: null,
            });
        });

        it('should render onboarding card', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('.digger-onboarding')).not.toBeNull();
        });

        it('should show "Open Digger Settings" button', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btn = body.querySelector('button');
            expect(btn).not.toBeNull();
            expect(btn.textContent).toContain('Open Digger Settings');
        });

        it('should NOT load wantlist on 404', async () => {
            await window.diggerPane.init();
            expect(window.apiClient.getDiggerWantlist).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // Onboarding — enabled: false
    // ------------------------------------------------------------------ //

    describe('settings ok + enabled:false → onboarding', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: {
                    enabled: false,
                    country_code: 'US',
                    currency: 'USD',
                    scheduled_cadence: 'daily',
                    preferred_model: 'claude-opus',
                    daily_token_cap_interactive: 10000,
                    daily_token_cap_scheduled: 50000,
                },
            });
        });

        it('should render onboarding card when enabled is false', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('.digger-onboarding')).not.toBeNull();
        });

        it('should NOT load wantlist when disabled', async () => {
            await window.diggerPane.init();
            expect(window.apiClient.getDiggerWantlist).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // Onboarding button navigation
    // ------------------------------------------------------------------ //

    describe('onboarding button click', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 404,
                body: null,
            });
        });

        it('should call exploreApp._switchPane("settings") when clicked', async () => {
            window.exploreApp = { _switchPane: vi.fn() };
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btn = body.querySelector('button');
            btn.click();
            expect(window.exploreApp._switchPane).toHaveBeenCalledWith('settings');
        });

        it('should set _previousPane before switching', async () => {
            window.exploreApp = { _switchPane: vi.fn() };
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btn = body.querySelector('button');
            btn.click();
            expect(window.exploreApp._previousPane).toBe('digger');
        });

        it('should not throw when exploreApp is undefined', async () => {
            window.exploreApp = undefined;
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btn = body.querySelector('button');
            expect(() => btn.click()).not.toThrow();
        });

        it('should not throw when exploreApp is null', async () => {
            window.exploreApp = null;
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btn = body.querySelector('button');
            expect(() => btn.click()).not.toThrow();
        });
    });

    // ------------------------------------------------------------------ //
    // Enabled + wantlist with items
    // ------------------------------------------------------------------ //

    describe('enabled + wantlist with 2 items', () => {
        const twoItems = [
            {
                release_id: 1,
                title: 'OK Computer',
                artist: 'Radiohead',
                year: 1997,
                tier: 'A',
                min_media_condition: 'VG+',
                min_sleeve_condition: 'VG',
                max_price_cents: 5000,
                active_listings: 12,
                last_scraped_at: '2026-05-01T10:00:00Z',
            },
            {
                release_id: 2,
                title: 'Homogenic',
                artist: 'Bjork',
                year: 1997,
                tier: 'B',
                min_media_condition: null,
                min_sleeve_condition: null,
                max_price_cents: null,
                active_listings: 0,
                last_scraped_at: null,
            },
        ];

        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: {
                    enabled: true,
                    country_code: 'US',
                    currency: 'USD',
                    scheduled_cadence: 'daily',
                    preferred_model: 'claude-opus',
                    daily_token_cap_interactive: 10000,
                    daily_token_cap_scheduled: 50000,
                },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: twoItems },
            });
        });

        it('should render a table with 2 body rows', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const rows = body.querySelectorAll('tbody tr');
            expect(rows).toHaveLength(2);
        });

        it('should render artist name in first row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            expect(firstRow.textContent).toContain('Radiohead');
        });

        it('should render title in first row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            expect(firstRow.textContent).toContain('OK Computer');
        });

        it('should render year in first row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            expect(firstRow.textContent).toContain('1997');
        });

        it('should render tier in first row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            expect(firstRow.textContent).toContain('A');
        });

        it('should render active_listings in first row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            expect(firstRow.textContent).toContain('12');
        });

        it('should set data-release-id on each row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const rows = body.querySelectorAll('tbody tr');
            expect(rows[0].dataset.releaseId).toBe('1');
            expect(rows[1].dataset.releaseId).toBe('2');
        });

        it('should show "never" for null last_scraped_at in second row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const secondRow = body.querySelectorAll('tbody tr')[1];
            expect(secondRow.textContent).toContain('never');
        });

        it('should show a formatted date for non-null last_scraped_at', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            // Should have some date text — not "never", not empty
            const lastCell = firstRow.querySelectorAll('td');
            const lastScrapedCell = lastCell[lastCell.length - 1];
            expect(lastScrapedCell.textContent).not.toBe('never');
            expect(lastScrapedCell.textContent.trim().length).toBeGreaterThan(0);
        });

        it('should store items in _items', async () => {
            await window.diggerPane.init();
            expect(window.diggerPane._items).toHaveLength(2);
        });

        it('should store settings in _settings', async () => {
            await window.diggerPane.init();
            expect(window.diggerPane._settings).not.toBeNull();
            expect(window.diggerPane._settings.enabled).toBe(true);
        });
    });

    // ------------------------------------------------------------------ //
    // Enabled + empty wantlist
    // ------------------------------------------------------------------ //

    describe('enabled + empty wantlist', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [] },
            });
        });

        it('should render empty state message', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should NOT render a table when empty', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('table')).toBeNull();
        });
    });

    // ------------------------------------------------------------------ //
    // Loading overlay
    // ------------------------------------------------------------------ //

    describe('loading overlay', () => {
        it('should remove active class from loading overlay after successful load', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [] },
            });
            await window.diggerPane.init();
            const loading = document.getElementById('diggerLoading');
            expect(loading.classList.contains('active')).toBe(false);
        });

        it('should remove active class from loading overlay after 404', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 404,
                body: null,
            });
            await window.diggerPane.init();
            const loading = document.getElementById('diggerLoading');
            expect(loading.classList.contains('active')).toBe(false);
        });

        it('should remove active class from loading overlay on API error', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 500,
                body: null,
            });
            await window.diggerPane.init();
            const loading = document.getElementById('diggerLoading');
            expect(loading.classList.contains('active')).toBe(false);
        });
    });

    // ------------------------------------------------------------------ //
    // Error / unexpected response
    // ------------------------------------------------------------------ //

    describe('settings error (non-404)', () => {
        it('should render an error message on 500', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 500,
                body: null,
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            // Should show something — not empty
            expect(body.textContent.trim().length).toBeGreaterThan(0);
        });

        it('should NOT load wantlist on settings error', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 500,
                body: null,
            });
            await window.diggerPane.init();
            expect(window.apiClient.getDiggerWantlist).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // Wantlist load failure
    // ------------------------------------------------------------------ //

    describe('wantlist load error', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'weekly', preferred_model: 'sonnet', daily_token_cap_interactive: 200000, daily_token_cap_scheduled: 100000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: false,
                status: 500,
                body: null,
            });
        });

        it('should attempt to load the wantlist when settings are enabled', async () => {
            await window.diggerPane.init();
            expect(window.apiClient.getDiggerWantlist).toHaveBeenCalled();
        });

        it('should render the error state (not the empty state) when the wantlist request fails', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const icon = body.querySelector('.user-pane-empty .material-symbols-outlined');
            // Error state uses error_outline; the empty state uses travel_explore.
            expect(icon).not.toBeNull();
            expect(icon.textContent).toBe('error_outline');
            expect(body.querySelector('table')).toBeNull();
        });
    });

    // ------------------------------------------------------------------ //
    // Table header columns
    // ------------------------------------------------------------------ //

    describe('table columns', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: {
                    items: [{
                        release_id: 42,
                        title: 'Test Album',
                        artist: 'Test Artist',
                        year: 2000,
                        tier: 'C',
                        min_media_condition: null,
                        min_sleeve_condition: null,
                        max_price_cents: null,
                        active_listings: 3,
                        last_scraped_at: null,
                    }],
                },
            });
        });

        it('should render table with Artist column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Artist');
        });

        it('should render table with Title column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Title');
        });

        it('should render table with Year column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Year');
        });

        it('should render table with Tier column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Tier');
        });

        it('should render table with Active listings column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts.some(t => t.toLowerCase().includes('active'))).toBe(true);
        });

        it('should render table with Last scraped column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts.some(t => t.toLowerCase().includes('scraped') || t.toLowerCase().includes('last'))).toBe(true);
        });
    });

    // ------------------------------------------------------------------ //
    // Null value fallbacks
    // ------------------------------------------------------------------ //

    describe('null field fallbacks', () => {
        beforeEach(() => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true,
                status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
        });

        it('should show "—" for null artist', async () => {
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [{ release_id: 1, title: 'T', artist: null, year: 2000, tier: 'A', min_media_condition: null, min_sleeve_condition: null, max_price_cents: null, active_listings: 0, last_scraped_at: null }] },
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const cells = row.querySelectorAll('td');
            expect(cells[0].textContent).toBe('—');
        });

        it('should show "—" for null title', async () => {
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [{ release_id: 1, title: null, artist: 'A', year: 2000, tier: 'A', min_media_condition: null, min_sleeve_condition: null, max_price_cents: null, active_listings: 0, last_scraped_at: null }] },
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const cells = row.querySelectorAll('td');
            expect(cells[1].textContent).toBe('—');
        });

        it('should show "—" for null year', async () => {
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [{ release_id: 1, title: 'T', artist: 'A', year: null, tier: 'A', min_media_condition: null, min_sleeve_condition: null, max_price_cents: null, active_listings: 0, last_scraped_at: null }] },
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const cells = row.querySelectorAll('td');
            expect(cells[2].textContent).toBe('—');
        });
    });

    // ------------------------------------------------------------------ //
    // Concurrent load guard
    // ------------------------------------------------------------------ //

    describe('concurrent load guard', () => {
        it('should not allow concurrent init calls', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: false,
                status: 404,
                body: null,
            });
            // Fire two concurrent inits
            const p1 = window.diggerPane.init();
            const p2 = window.diggerPane.init();
            await Promise.all([p1, p2]);
            // Should only call once
            expect(window.apiClient.getDiggerSettings).toHaveBeenCalledTimes(1);
        });
    });
});
