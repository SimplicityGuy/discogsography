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
            setDiggerPriority: vi.fn(),
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
                tier: 'must',
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
                tier: 'nice',
                min_media_condition: 'VG',
                min_sleeve_condition: 'G+',
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

        it('should render tier buttons (not plain text) in first row', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const firstRow = body.querySelectorAll('tbody tr')[0];
            // Tier is now a segmented toggle — should have tier buttons
            const tierBtns = firstRow.querySelectorAll('.digger-tier-btn');
            expect(tierBtns.length).toBe(3);
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
                        tier: 'nice',
                        min_media_condition: 'VG',
                        min_sleeve_condition: 'G+',
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

        it('should render table with Media column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Media');
        });

        it('should render table with Sleeve column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Sleeve');
        });

        it('should render table with Max price column header', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts.some(t => t.toLowerCase().includes('price'))).toBe(true);
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

        it('should render exactly 10 column headers (leading select column + 9 data columns)', async () => {
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const headers = body.querySelectorAll('th');
            expect(headers).toHaveLength(10);
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
                body: { items: [{ release_id: 1, title: 'T', artist: null, year: 2000, tier: 'nice', min_media_condition: 'VG', min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 0, last_scraped_at: null }] },
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const cells = row.querySelectorAll('td');
            // cells[0] is the row-selection checkbox; artist is cells[1].
            expect(cells[1].textContent).toBe('—');
        });

        it('should show "—" for null title', async () => {
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [{ release_id: 1, title: null, artist: 'A', year: 2000, tier: 'nice', min_media_condition: 'VG', min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 0, last_scraped_at: null }] },
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const cells = row.querySelectorAll('td');
            // cells[0] = select checkbox, cells[1] = artist, cells[2] = title.
            expect(cells[2].textContent).toBe('—');
        });

        it('should show "—" for null year', async () => {
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true,
                status: 200,
                body: { items: [{ release_id: 1, title: 'T', artist: 'A', year: null, tier: 'nice', min_media_condition: 'VG', min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 0, last_scraped_at: null }] },
            });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const cells = row.querySelectorAll('td');
            // cells[0] = select checkbox, cells[1] = artist, cells[2] = title, cells[3] = year.
            expect(cells[3].textContent).toBe('—');
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

    // ------------------------------------------------------------------ //
    // Tier toggle controls
    // ------------------------------------------------------------------ //

    describe('tier toggle', () => {
        const makeItem = (tier) => ({
            release_id: 10,
            title: 'Test',
            artist: 'Artist',
            year: 2020,
            tier,
            min_media_condition: 'VG',
            min_sleeve_condition: 'G+',
            max_price_cents: null,
            active_listings: 0,
            last_scraped_at: null,
        });

        function setupWantlist(tier) {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true, status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true, status: 200,
                body: { items: [makeItem(tier)] },
            });
        }

        it('should render 3 tier buttons', async () => {
            setupWantlist('must');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            const btns = row.querySelectorAll('.digger-tier-btn');
            expect(btns).toHaveLength(3);
        });

        it('should label buttons must / nice / eventually', async () => {
            setupWantlist('must');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const labels = Array.from(btns).map(b => b.textContent);
            expect(labels).toEqual(['must', 'nice', 'eventually']);
        });

        it('should mark current tier button as active and aria-pressed=true', async () => {
            setupWantlist('nice');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            expect(niceBtn.classList.contains('active')).toBe(true);
            expect(niceBtn.getAttribute('aria-pressed')).toBe('true');
        });

        it('should mark non-current tier buttons as inactive and aria-pressed=false', async () => {
            setupWantlist('must');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            const eventuallyBtn = Array.from(btns).find(b => b.textContent === 'eventually');
            expect(niceBtn.classList.contains('active')).toBe(false);
            expect(niceBtn.getAttribute('aria-pressed')).toBe('false');
            expect(eventuallyBtn.classList.contains('active')).toBe(false);
            expect(eventuallyBtn.getAttribute('aria-pressed')).toBe('false');
        });

        it('should have a role=group container with aria-label="Tier"', async () => {
            setupWantlist('must');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const group = body.querySelector('[role="group"][aria-label="Tier"]');
            expect(group).not.toBeNull();
        });

        it('clicking a different tier calls setDiggerPriority with new tier', async () => {
            setupWantlist('must');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            niceBtn.click();
            await new Promise(r => setTimeout(r, 0)); // flush microtasks
            expect(window.apiClient.setDiggerPriority).toHaveBeenCalledWith(
                'test-token', 10, { tier: 'nice' }
            );
        });

        it('clicking the already-active tier does NOT call setDiggerPriority', async () => {
            setupWantlist('must');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const mustBtn = Array.from(btns).find(b => b.textContent === 'must');
            mustBtn.click();
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).not.toHaveBeenCalled();
        });

        it('on tier success, updates aria-pressed and active class for all buttons', async () => {
            setupWantlist('must');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const eventuallyBtn = Array.from(btns).find(b => b.textContent === 'eventually');
            const mustBtn = Array.from(btns).find(b => b.textContent === 'must');
            eventuallyBtn.click();
            await new Promise(r => setTimeout(r, 0));
            expect(eventuallyBtn.getAttribute('aria-pressed')).toBe('true');
            expect(eventuallyBtn.classList.contains('active')).toBe(true);
            expect(mustBtn.getAttribute('aria-pressed')).toBe('false');
            expect(mustBtn.classList.contains('active')).toBe(false);
        });

        it('on tier success, updates in-memory item tier', async () => {
            setupWantlist('must');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            niceBtn.click();
            await new Promise(r => setTimeout(r, 0));
            expect(window.diggerPane._items[0].tier).toBe('nice');
        });

        it('on tier failure, leaves buttons unchanged', async () => {
            setupWantlist('must');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: false, status: 400, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            const mustBtn = Array.from(btns).find(b => b.textContent === 'must');
            niceBtn.click();
            await new Promise(r => setTimeout(r, 0));
            // must remains active
            expect(mustBtn.getAttribute('aria-pressed')).toBe('true');
            expect(mustBtn.classList.contains('active')).toBe(true);
            // nice stays inactive
            expect(niceBtn.getAttribute('aria-pressed')).toBe('false');
            expect(niceBtn.classList.contains('active')).toBe(false);
        });

        it('on tier failure, in-memory item tier is unchanged', async () => {
            setupWantlist('must');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: false, status: 500, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            niceBtn.click();
            await new Promise(r => setTimeout(r, 0));
            expect(window.diggerPane._items[0].tier).toBe('must');
        });

        it('tier click does nothing when no token', async () => {
            setupWantlist('must');
            await window.diggerPane.init();
            window.authManager.getToken.mockReturnValue(null);
            const body = document.getElementById('diggerBody');
            const btns = body.querySelectorAll('.digger-tier-btn');
            const niceBtn = Array.from(btns).find(b => b.textContent === 'nice');
            niceBtn.click();
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // Media condition select
    // ------------------------------------------------------------------ //

    describe('media condition select', () => {
        function setupWantlistMedia(min_media_condition) {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true, status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true, status: 200,
                body: { items: [{
                    release_id: 20,
                    title: 'Media Test',
                    artist: 'Artist',
                    year: 2021,
                    tier: 'nice',
                    min_media_condition,
                    min_sleeve_condition: 'G+',
                    max_price_cents: null,
                    active_listings: 0,
                    last_scraped_at: null,
                }] },
            });
        }

        it('should render a media select in each row', async () => {
            setupWantlistMedia('VG+');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const row = body.querySelector('tbody tr');
            // Media is the first <select> in the row; sleeve is the second.
            const mediaSelect = row.querySelectorAll('select')[0];
            expect(mediaSelect).not.toBeNull();
        });

        it('should render all 8 media condition options (no blank)', async () => {
            setupWantlistMedia('VG');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const mediaSelect = body.querySelector('tbody tr').querySelectorAll('select')[0];
            // Exactly 8 conditions: M, NM, VG+, VG, G+, G, F, P
            expect(mediaSelect.options.length).toBe(8);
            const values = Array.from(mediaSelect.options).map(o => o.value);
            expect(values).toEqual(['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P']);
        });

        it('should pre-select the current media condition', async () => {
            setupWantlistMedia('VG+');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const mediaSelect = body.querySelector('tbody tr').querySelectorAll('select')[0];
            expect(mediaSelect.value).toBe('VG+');
        });

        it('changing media select calls setDiggerPriority with min_media_condition', async () => {
            setupWantlistMedia('VG');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const mediaSelect = body.querySelector('tbody tr').querySelectorAll('select')[0];
            mediaSelect.value = 'NM';
            mediaSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).toHaveBeenCalledWith(
                'test-token', 20, { min_media_condition: 'NM' }
            );
        });

        it('on media select success, updates in-memory item', async () => {
            setupWantlistMedia('VG');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const mediaSelect = body.querySelector('tbody tr').querySelectorAll('select')[0];
            mediaSelect.value = 'M';
            mediaSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.diggerPane._items[0].min_media_condition).toBe('M');
        });

        it('on media select failure, reverts the select and leaves in-memory unchanged', async () => {
            setupWantlistMedia('VG');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: false, status: 500, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const mediaSelect = body.querySelector('tbody tr').querySelectorAll('select')[0];
            mediaSelect.value = 'M';
            mediaSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            // Reverted to original
            expect(mediaSelect.value).toBe('VG');
            expect(window.diggerPane._items[0].min_media_condition).toBe('VG');
        });

        it('media select change does nothing when no token', async () => {
            setupWantlistMedia('VG');
            await window.diggerPane.init();
            window.authManager.getToken.mockReturnValue(null);
            const body = document.getElementById('diggerBody');
            const mediaSelect = body.querySelector('tbody tr').querySelectorAll('select')[0];
            mediaSelect.value = 'NM';
            mediaSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // Sleeve condition select
    // ------------------------------------------------------------------ //

    describe('sleeve condition select', () => {
        function setupWantlistSleeve(min_sleeve_condition) {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true, status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true, status: 200,
                body: { items: [{
                    release_id: 30,
                    title: 'Sleeve Test',
                    artist: 'Artist',
                    year: 2021,
                    tier: 'eventually',
                    min_media_condition: 'VG',
                    min_sleeve_condition,
                    max_price_cents: null,
                    active_listings: 0,
                    last_scraped_at: null,
                }] },
            });
        }

        it('should render a sleeve select in each row', async () => {
            setupWantlistSleeve('VG');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const sleeveSelect = body.querySelector('tbody tr').querySelectorAll('select')[1];
            expect(sleeveSelect).not.toBeNull();
        });

        it('should render all 10 sleeve condition options (no blank)', async () => {
            setupWantlistSleeve('VG');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const sleeveSelect = body.querySelector('tbody tr').querySelectorAll('select')[1];
            // Exactly 10 conditions: M, NM, VG+, VG, G+, G, F, P, generic, no_cover
            expect(sleeveSelect.options.length).toBe(10);
            const values = Array.from(sleeveSelect.options).map(o => o.value);
            expect(values).toEqual(['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P', 'generic', 'no_cover']);
        });

        it('should pre-select the current sleeve condition', async () => {
            setupWantlistSleeve('generic');
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const sleeveSelect = body.querySelector('tbody tr').querySelectorAll('select')[1];
            expect(sleeveSelect.value).toBe('generic');
        });

        it('changing sleeve select calls setDiggerPriority with min_sleeve_condition', async () => {
            setupWantlistSleeve('VG');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const sleeveSelect = body.querySelector('tbody tr').querySelectorAll('select')[1];
            sleeveSelect.value = 'no_cover';
            sleeveSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).toHaveBeenCalledWith(
                'test-token', 30, { min_sleeve_condition: 'no_cover' }
            );
        });

        it('on sleeve select failure, reverts the select and leaves in-memory unchanged', async () => {
            setupWantlistSleeve('VG');
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: false, status: 500, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const sleeveSelect = body.querySelector('tbody tr').querySelectorAll('select')[1];
            sleeveSelect.value = 'M';
            sleeveSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(sleeveSelect.value).toBe('VG');
            expect(window.diggerPane._items[0].min_sleeve_condition).toBe('VG');
        });

        it('sleeve select change does nothing when no token', async () => {
            setupWantlistSleeve('VG');
            await window.diggerPane.init();
            window.authManager.getToken.mockReturnValue(null);
            const body = document.getElementById('diggerBody');
            const sleeveSelect = body.querySelector('tbody tr').querySelectorAll('select')[1];
            sleeveSelect.value = 'NM';
            sleeveSelect.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).not.toHaveBeenCalled();
        });
    });

    // ------------------------------------------------------------------ //
    // Max price input
    // ------------------------------------------------------------------ //

    describe('max price input', () => {
        function setupWantlistPrice(max_price_cents) {
            window.apiClient.getDiggerSettings.mockResolvedValue({
                ok: true, status: 200,
                body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
            });
            window.apiClient.getDiggerWantlist.mockResolvedValue({
                ok: true, status: 200,
                body: { items: [{
                    release_id: 40,
                    title: 'Price Test',
                    artist: 'Artist',
                    year: 2021,
                    tier: 'nice',
                    min_media_condition: 'VG',
                    min_sleeve_condition: 'G+',
                    max_price_cents,
                    active_listings: 0,
                    last_scraped_at: null,
                }] },
            });
        }

        it('should render a number input for max price', async () => {
            setupWantlistPrice(1000);
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            expect(priceInput).not.toBeNull();
        });

        it('should display cents as dollars (5000 cents → "50")', async () => {
            setupWantlistPrice(5000);
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            expect(priceInput.value).toBe('50');
        });

        it('should display empty string when max_price_cents is null', async () => {
            setupWantlistPrice(null);
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            expect(priceInput.value).toBe('');
        });

        it('entering a dollar value calls setDiggerPriority with cents', async () => {
            setupWantlistPrice(null);
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            priceInput.value = '12.50';
            priceInput.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).toHaveBeenCalledWith(
                'test-token', 40, { max_price_cents: 1250 }
            );
        });

        it('clearing the price input sends max_price_cents: null', async () => {
            setupWantlistPrice(5000);
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            priceInput.value = '';
            priceInput.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).toHaveBeenCalledWith(
                'test-token', 40, { max_price_cents: null }
            );
        });

        it('on price success, updates in-memory item max_price_cents', async () => {
            setupWantlistPrice(null);
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            priceInput.value = '25';
            priceInput.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.diggerPane._items[0].max_price_cents).toBe(2500);
        });

        it('on price failure, reverts input to original value and leaves in-memory unchanged', async () => {
            setupWantlistPrice(3000);
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: false, status: 500, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            priceInput.value = '99';
            priceInput.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(priceInput.value).toBe('30');
            expect(window.diggerPane._items[0].max_price_cents).toBe(3000);
        });

        it('price input change does nothing when no token', async () => {
            setupWantlistPrice(null);
            await window.diggerPane.init();
            window.authManager.getToken.mockReturnValue(null);
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            priceInput.value = '10';
            priceInput.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).not.toHaveBeenCalled();
        });

        it('treats a non-numeric entry as a clear (number input sanitizes it to empty → null)', async () => {
            setupWantlistPrice(5000);
            window.apiClient.setDiggerPriority.mockResolvedValue({ ok: true, status: 204, body: null });
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            priceInput.value = 'abc'; // type=number sanitizes this to '' (browsers + jsdom)
            priceInput.dispatchEvent(new Event('change'));
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.setDiggerPriority).toHaveBeenCalledWith(
                'test-token', 40, { max_price_cents: null }
            );
        });

        it('input has correct min and step attributes', async () => {
            setupWantlistPrice(null);
            await window.diggerPane.init();
            const body = document.getElementById('diggerBody');
            const priceInput = body.querySelector('tbody tr').querySelector('input[type="number"]');
            expect(priceInput.min).toBe('0');
            expect(priceInput.step).toBe('0.01');
        });
    });

    // ------------------------------------------------------------------ //
    // T4 — bulk-actions toolbar, filters, selection, stats banner
    // ------------------------------------------------------------------ //

    // A representative dataset spanning all tiers and listing availabilities.
    const T4_ITEMS = [
        { release_id: 1, title: 'A1', artist: 'AA', year: 2001, tier: 'must',       min_media_condition: 'VG+', min_sleeve_condition: 'VG', max_price_cents: 5000, active_listings: 12, last_scraped_at: '2026-05-01T10:00:00Z' },
        { release_id: 2, title: 'A2', artist: 'AB', year: 2002, tier: 'must',       min_media_condition: 'VG',  min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 0,  last_scraped_at: null },
        { release_id: 3, title: 'A3', artist: 'AC', year: 2003, tier: 'nice',       min_media_condition: 'VG',  min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 4,  last_scraped_at: null },
        { release_id: 4, title: 'A4', artist: 'AD', year: 2004, tier: 'eventually', min_media_condition: 'VG',  min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 0,  last_scraped_at: null },
        { release_id: 5, title: 'A5', artist: 'AE', year: 2005, tier: 'eventually', min_media_condition: 'VG',  min_sleeve_condition: 'G+', max_price_cents: null, active_listings: 7,  last_scraped_at: null },
    ];

    function setupT4(items = T4_ITEMS) {
        window.apiClient.bulkSetDiggerTier = vi.fn();
        window.apiClient.getDiggerSettings.mockResolvedValue({
            ok: true, status: 200,
            body: { enabled: true, country_code: 'US', currency: 'USD', scheduled_cadence: 'daily', preferred_model: 'claude-opus', daily_token_cap_interactive: 10000, daily_token_cap_scheduled: 50000 },
        });
        window.apiClient.getDiggerWantlist.mockResolvedValue({
            ok: true, status: 200,
            body: { items: items.map(i => ({ ...i })) },
        });
    }

    const rowCheckbox = (tr) => tr.querySelector('input[type="checkbox"]');
    const allRows = () => document.querySelectorAll('#diggerBody tbody tr');
    const bulkBar = () => document.querySelector('#diggerBody .digger-bulk-bar');
    const selectAll = () => document.querySelector('#diggerBody thead input[type="checkbox"]');

    describe('row selection', () => {
        it('row checkbox toggling adds then removes the id and shows/hides the bulk bar', async () => {
            setupT4();
            await window.diggerPane.init();
            // Bar hidden at 0 selected.
            const barAtZero = bulkBar();
            expect(barAtZero === null || barAtZero.classList.contains('hidden')).toBe(true);

            const cb = rowCheckbox(allRows()[0]);
            cb.click();
            expect(window.diggerPane._selected.has(1)).toBe(true);
            const barAtOne = bulkBar();
            expect(barAtOne).not.toBeNull();
            expect(barAtOne.classList.contains('hidden')).toBe(false);
            expect(barAtOne.textContent).toContain('1 selected');

            cb.click();
            expect(window.diggerPane._selected.has(1)).toBe(false);
            const barBack = bulkBar();
            expect(barBack === null || barBack.classList.contains('hidden')).toBe(true);
        });

        it('checking a row does NOT full re-render the table', async () => {
            setupT4();
            await window.diggerPane.init();
            const tbodyBefore = document.querySelector('#diggerBody tbody');
            rowCheckbox(allRows()[0]).click();
            const tbodyAfter = document.querySelector('#diggerBody tbody');
            expect(tbodyAfter).toBe(tbodyBefore); // same node — no re-render
        });

        it('select-all checks all visible rows and populates selection', async () => {
            setupT4();
            await window.diggerPane.init();
            selectAll().click();
            expect(window.diggerPane._selected.size).toBe(5);
            for (const tr of allRows()) {
                expect(rowCheckbox(tr).checked).toBe(true);
            }
            expect(bulkBar().textContent).toContain('5 selected');
        });

        it('unchecking select-all clears the selection and the bar', async () => {
            setupT4();
            await window.diggerPane.init();
            const sa = selectAll();
            sa.click();
            expect(window.diggerPane._selected.size).toBe(5);
            sa.click();
            expect(window.diggerPane._selected.size).toBe(0);
            for (const tr of allRows()) {
                expect(rowCheckbox(tr).checked).toBe(false);
            }
            const bar = bulkBar();
            expect(bar === null || bar.classList.contains('hidden')).toBe(true);
        });
    });

    describe('filters', () => {
        const tierFilterSelect = () => document.querySelector('#diggerBody .digger-filters select');
        const hideToggle = () => document.querySelector('#diggerBody .digger-filters input[type="checkbox"]');

        it("tier filter 'must' renders only must rows; 'all' shows everything", async () => {
            setupT4();
            await window.diggerPane.init();
            expect(allRows()).toHaveLength(5);

            const sel = tierFilterSelect();
            sel.value = 'must';
            sel.dispatchEvent(new Event('change'));
            expect(allRows()).toHaveLength(2);
            for (const tr of allRows()) {
                expect(['1', '2']).toContain(tr.dataset.releaseId);
            }

            sel.value = 'all';
            sel.dispatchEvent(new Event('change'));
            expect(allRows()).toHaveLength(5);
        });

        it('hide-no-listings hides rows with active_listings === 0', async () => {
            setupT4();
            await window.diggerPane.init();
            const toggle = hideToggle();
            toggle.checked = true;
            toggle.dispatchEvent(new Event('change'));
            // release_ids 2 and 4 have 0 listings → hidden.
            const ids = Array.from(allRows()).map(tr => tr.dataset.releaseId);
            expect(ids).toEqual(['1', '3', '5']);
        });

        it('select-all respects the active filter (only visible rows)', async () => {
            setupT4();
            await window.diggerPane.init();
            const sel = tierFilterSelect();
            sel.value = 'must';
            sel.dispatchEvent(new Event('change'));
            selectAll().click();
            expect(Array.from(window.diggerPane._selected).sort()).toEqual([1, 2]);
        });

        it('filter changes preserve selection checked-state for still-visible rows', async () => {
            setupT4();
            await window.diggerPane.init();
            // Select a must row (1) and an eventually row (5).
            rowCheckbox(allRows()[0]).click(); // id 1 (must)
            rowCheckbox(allRows()[4]).click(); // id 5 (eventually)
            expect(window.diggerPane._selected.size).toBe(2);

            const sel = tierFilterSelect();
            sel.value = 'must';
            sel.dispatchEvent(new Event('change'));
            // Only id 1 visible now; selection set is preserved (still has 1 and 5).
            const visibleRow = allRows()[0];
            expect(visibleRow.dataset.releaseId).toBe('1');
            expect(rowCheckbox(visibleRow).checked).toBe(true);
            expect(window.diggerPane._selected.has(5)).toBe(true);
        });
    });

    describe('bulk actions bar', () => {
        const bulkTierSelect = () => bulkBar().querySelector('select');
        const applyBtn = () => Array.from(bulkBar().querySelectorAll('button')).find(b => /apply/i.test(b.textContent));
        const clearBtn = () => Array.from(bulkBar().querySelectorAll('button')).find(b => /clear/i.test(b.textContent));

        it('Apply calls bulkSetDiggerTier with selected ids and chosen tier, then refreshes', async () => {
            setupT4();
            window.apiClient.bulkSetDiggerTier.mockResolvedValue({ ok: true, status: 200, body: { updated: 2 } });
            await window.diggerPane.init();
            rowCheckbox(allRows()[2]).click(); // id 3
            rowCheckbox(allRows()[4]).click(); // id 5

            const tierSel = bulkTierSelect();
            tierSel.value = 'must';
            tierSel.dispatchEvent(new Event('change'));

            applyBtn().click();
            await new Promise(r => setTimeout(r, 0));

            expect(window.apiClient.bulkSetDiggerTier).toHaveBeenCalledTimes(1);
            const [tokenArg, idsArg, tierArg] = window.apiClient.bulkSetDiggerTier.mock.calls[0];
            expect(tokenArg).toBe('test-token');
            expect([...idsArg].sort()).toEqual([3, 5]);
            expect(tierArg).toBe('must');

            // Refresh re-fetches the wantlist and clears selection.
            expect(window.apiClient.getDiggerWantlist).toHaveBeenCalledTimes(2);
            expect(window.diggerPane._selected.size).toBe(0);
        });

        it('Apply does nothing when there is no token', async () => {
            setupT4();
            await window.diggerPane.init();
            rowCheckbox(allRows()[0]).click();
            window.authManager.getToken.mockReturnValue(null);
            applyBtn().click();
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.bulkSetDiggerTier).not.toHaveBeenCalled();
            // Selection preserved.
            expect(window.diggerPane._selected.size).toBe(1);
        });

        it('Apply failure keeps the selection', async () => {
            setupT4();
            window.apiClient.bulkSetDiggerTier.mockResolvedValue({ ok: false, status: 500, body: null });
            await window.diggerPane.init();
            rowCheckbox(allRows()[0]).click();
            applyBtn().click();
            await new Promise(r => setTimeout(r, 0));
            expect(window.apiClient.bulkSetDiggerTier).toHaveBeenCalledTimes(1);
            expect(window.diggerPane._selected.size).toBe(1);
            // No re-fetch on failure.
            expect(window.apiClient.getDiggerWantlist).toHaveBeenCalledTimes(1);
        });

        it('bulk tier select shows title-case labels matching the filter', async () => {
            setupT4();
            await window.diggerPane.init();
            const labels = Array.from(bulkTierSelect().options).map(o => o.textContent);
            expect(labels).toEqual(['Must', 'Nice', 'Eventually']);
        });

        it('ignores a second Apply click while the first request is in flight', async () => {
            setupT4();
            let resolveApply;
            window.apiClient.bulkSetDiggerTier.mockReturnValue(new Promise((res) => { resolveApply = res; }));
            await window.diggerPane.init();
            rowCheckbox(allRows()[0]).click(); // id 1

            applyBtn().click(); // starts the in-flight request (button disabled, guard set)
            applyBtn().click(); // should be ignored
            expect(window.apiClient.bulkSetDiggerTier).toHaveBeenCalledTimes(1);

            // Let the first request finish cleanly.
            resolveApply({ ok: true, status: 200, body: { updated: 1 } });
            await new Promise(r => setTimeout(r, 0));
        });

        it('Clear empties the selection, unchecks rows, and hides the bar', async () => {
            setupT4();
            await window.diggerPane.init();
            selectAll().click();
            expect(window.diggerPane._selected.size).toBe(5);
            clearBtn().click();
            expect(window.diggerPane._selected.size).toBe(0);
            for (const tr of allRows()) {
                expect(rowCheckbox(tr).checked).toBe(false);
            }
            const bar = bulkBar();
            expect(bar === null || bar.classList.contains('hidden')).toBe(true);
        });
    });

    describe('stats banner', () => {
        const statCards = () => document.querySelectorAll('#diggerBody .digger-stats .stat-card');

        it('shows correct per-tier counts and must-available count (from all items)', async () => {
            setupT4();
            await window.diggerPane.init();
            const text = document.querySelector('#diggerBody .digger-stats').textContent;
            // T4_ITEMS: 2 must, 1 nice, 2 eventually; must with listings>0 = 1 (id 1).
            expect(text).toContain('Must');
            expect(text).toContain('Nice');
            expect(text).toContain('Eventually');
            expect(text).toMatch(/Must available/i);
            // Banner renders one card per metric.
            expect(statCards().length).toBeGreaterThanOrEqual(4);
        });

        it('stats are independent of active filters', async () => {
            setupT4();
            await window.diggerPane.init();
            const before = document.querySelector('#diggerBody .digger-stats').textContent;
            const sel = document.querySelector('#diggerBody .digger-filters select');
            sel.value = 'must';
            sel.dispatchEvent(new Event('change'));
            const after = document.querySelector('#diggerBody .digger-stats').textContent;
            expect(after).toBe(before);
        });

        it('counts reflect the dataset exactly', async () => {
            setupT4();
            await window.diggerPane.init();
            const cards = Array.from(statCards());
            const findCard = (label) => cards.find(c => c.querySelector('.stat-label')?.textContent.toLowerCase().includes(label));
            expect(findCard('must').querySelector('.stat-value').textContent).toContain('2');
            expect(findCard('nice').querySelector('.stat-value').textContent).toContain('1');
            expect(findCard('eventually').querySelector('.stat-value').textContent).toContain('2');
            // Must available: 1 of 2.
            const avail = cards.find(c => c.querySelector('.stat-label')?.textContent.toLowerCase().includes('available'));
            expect(avail.querySelector('.stat-value').textContent).toContain('1');
        });
    });
});
