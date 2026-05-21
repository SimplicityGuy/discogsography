import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

/**
 * Create the minimal DOM elements DiggerPane reads in its constructor.
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

/**
 * A representative optimizer Bundle (cents-denominated, shape per
 * common/digger_optimizer/models.py).
 */
function makeBundle(overrides = {}) {
    return {
        name: 'cheapest',
        seller_orders: [
            {
                seller_id: 1,
                listings: [
                    {
                        listing_id: 11,
                        release_id: 101,
                        price_cents: 1000,
                        currency: 'USD',
                        media_condition: 'NM',
                        sleeve_condition: 'NM',
                    },
                ],
                subtotal_item_cents: 1000,
                shipping_cents: 500,
            },
        ],
        total_item_cost_cents: 1000,
        total_shipping_cents: 500,
        grand_total_cents: 1500,
        coverage: { must: 1, nice: 0, eventually: 0 },
        avg_condition_score: 7.0,
        solver: 'ilp',
        reasoning_hint: '1 must from 1 seller.',
        ...overrides,
    };
}

describe('DiggerPane reports — render helpers', () => {
    beforeEach(() => {
        setupDiggerDOM();
        delete globalThis.window;
        globalThis.window = globalThis;
        window.authManager = {
            getToken: vi.fn().mockReturnValue('test-token'),
            isLoggedIn: vi.fn().mockReturnValue(true),
        };
        window.apiClient = {};
        window.exploreApp = undefined;
        loadScript('digger.js');
    });

    // ------------------------------------------------------------------ //
    // _formatCents
    // ------------------------------------------------------------------ //

    describe('_formatCents', () => {
        it('formats cents as a currency amount', () => {
            const out = window.diggerPane._formatCents(1500, 'USD');
            expect(out).toContain('15.00');
            expect(out).toContain('$');
        });

        it('formats zero cents', () => {
            const out = window.diggerPane._formatCents(0, 'USD');
            expect(out).toContain('0.00');
        });

        it('defaults missing/invalid cents to zero', () => {
            const out = window.diggerPane._formatCents(null, 'USD');
            expect(out).toContain('0.00');
        });

        it('falls back gracefully on an invalid currency code', () => {
            const out = window.diggerPane._formatCents(1500, 'not-a-currency');
            expect(out).toContain('15.00');
        });
    });

    // ------------------------------------------------------------------ //
    // _buildBundleCard
    // ------------------------------------------------------------------ //

    describe('_buildBundleCard', () => {
        it('renders the human-readable bundle name label', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.textContent).toContain('Cheapest');
        });

        it('renders the grand total formatted as currency', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.textContent).toContain('$15.00');
        });

        it('renders the item + shipping breakdown', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.textContent).toContain('$10.00');
            expect(card.textContent).toContain('$5.00');
            expect(card.textContent.toLowerCase()).toContain('shipping');
        });

        it('renders coverage counts', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.textContent).toContain('1 must');
            expect(card.textContent).toContain('0 nice');
            expect(card.textContent).toContain('0 eventually');
        });

        it('renders a singular seller count', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.textContent).toContain('1 seller');
            expect(card.textContent).not.toContain('1 sellers');
        });

        it('renders a plural seller count for multiple sellers', () => {
            const bundle = makeBundle({
                seller_orders: [
                    { seller_id: 1, listings: [], subtotal_item_cents: 1000, shipping_cents: 500 },
                    { seller_id: 2, listings: [], subtotal_item_cents: 800, shipping_cents: 500 },
                ],
            });
            const card = window.diggerPane._buildBundleCard(bundle, 'USD');
            expect(card.textContent).toContain('2 sellers');
        });

        it('renders the reasoning hint', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.textContent).toContain('1 must from 1 seller.');
        });

        it('tags the card element with a per-bundle class and data attribute', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            expect(card.classList.contains('digger-bundle-card')).toBe(true);
            expect(card.classList.contains('digger-bundle-cheapest')).toBe(true);
            expect(card.dataset.bundleName).toBe('cheapest');
        });

        it('does not show a greedy badge for ILP-solved bundles', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle({ solver: 'ilp' }), 'USD');
            expect(card.querySelector('.digger-solver-greedy')).toBeNull();
        });

        it('shows a greedy badge for greedy-solved bundles', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle({ solver: 'greedy' }), 'USD');
            const badge = card.querySelector('.digger-solver-greedy');
            expect(badge).not.toBeNull();
            expect(badge.textContent.toLowerCase()).toContain('greedy');
        });

        it('renders an expandable seller breakdown listing each order line', () => {
            const card = window.diggerPane._buildBundleCard(makeBundle(), 'USD');
            const details = card.querySelector('details.digger-bundle-details');
            expect(details).not.toBeNull();
            // The single order line references its release id and condition.
            expect(details.textContent).toContain('101');
            expect(details.textContent).toContain('NM');
            // And its price.
            expect(details.textContent).toContain('$10.00');
        });

        it('omits the seller breakdown when there are no seller orders', () => {
            const bundle = makeBundle({ seller_orders: [] });
            const card = window.diggerPane._buildBundleCard(bundle, 'USD');
            expect(card.querySelector('details.digger-bundle-details')).toBeNull();
        });
    });

    // ------------------------------------------------------------------ //
    // _buildWatchingList
    // ------------------------------------------------------------------ //

    describe('_buildWatchingList', () => {
        it('returns null when there is nothing to watch', () => {
            expect(window.diggerPane._buildWatchingList([])).toBeNull();
            expect(window.diggerPane._buildWatchingList(null)).toBeNull();
        });

        it('builds a list of Discogs release links', () => {
            const section = window.diggerPane._buildWatchingList([42, 99]);
            expect(section).not.toBeNull();
            const links = section.querySelectorAll('a');
            expect(links).toHaveLength(2);
            expect(links[0].getAttribute('href')).toBe('https://www.discogs.com/release/42');
            expect(links[0].textContent).toContain('42');
            expect(links[1].getAttribute('href')).toBe('https://www.discogs.com/release/99');
        });

        it('opens release links in a new tab safely', () => {
            const section = window.diggerPane._buildWatchingList([42]);
            const link = section.querySelector('a');
            expect(link.getAttribute('target')).toBe('_blank');
            expect(link.getAttribute('rel')).toContain('noopener');
        });
    });
});

// ---------------------------------------------------------------------- //
// Reports inbox, header navigation, and the report viewer
// ---------------------------------------------------------------------- //

const ENABLED_SETTINGS = {
    ok: true,
    status: 200,
    body: {
        enabled: true,
        country_code: 'US',
        currency: 'USD',
        scheduled_cadence: 'weekly',
        preferred_model: 'claude-opus',
        daily_token_cap_interactive: 10000,
        daily_token_cap_scheduled: 50000,
    },
};

function makeInboxItem(overrides = {}) {
    return {
        report_id: 'r1',
        kind: 'scheduled',
        generated_at: '2026-05-15T00:00:00Z',
        read_at: null,
        title: 'Weekly dig',
        summary: { wantlist_size: 5 },
        change_flag: 'significant',
        ...overrides,
    };
}

function makeFullReport(overrides = {}) {
    return {
        report_id: 'r1',
        user_id: 'u1',
        kind: 'scheduled',
        generated_at: '2026-05-15T00:00:00Z',
        read_at: null,
        title: 'Weekly dig',
        summary: { wantlist_size: 5, currency: 'USD' },
        bundles: [
            { name: 'cheapest', seller_orders: [], total_item_cost_cents: 1000, total_shipping_cents: 500, grand_total_cents: 1500, coverage: { must: 1, nice: 0, eventually: 0 }, avg_condition_score: 7, solver: 'ilp', reasoning_hint: 'a' },
            { name: 'most_coverage', seller_orders: [], total_item_cost_cents: 2000, total_shipping_cents: 500, grand_total_cents: 2500, coverage: { must: 1, nice: 1, eventually: 0 }, avg_condition_score: 7, solver: 'ilp', reasoning_hint: 'b' },
            { name: 'best_quality', seller_orders: [], total_item_cost_cents: 3000, total_shipping_cents: 500, grand_total_cents: 3500, coverage: { must: 1, nice: 0, eventually: 0 }, avg_condition_score: 8, solver: 'ilp', reasoning_hint: 'c' },
            { name: 'fewest_sellers', seller_orders: [], total_item_cost_cents: 1800, total_shipping_cents: 300, grand_total_cents: 2100, coverage: { must: 1, nice: 0, eventually: 0 }, avg_condition_score: 7, solver: 'greedy', reasoning_hint: 'd' },
        ],
        watching: [42, 99],
        change_flag: 'significant',
        shipping_confidence: 'high',
        ...overrides,
    };
}

describe('DiggerPane reports — inbox, navigation & viewer', () => {
    function setupDOM() {
        document.body.textContent = '';
        for (const id of ['diggerPane', 'diggerLoading', 'diggerBody', 'diggerHeaderActions']) {
            const el = document.createElement('div');
            el.id = id;
            document.body.appendChild(el);
        }
    }

    beforeEach(() => {
        setupDOM();
        delete globalThis.window;
        globalThis.window = globalThis;
        window.authManager = {
            getToken: vi.fn().mockReturnValue('test-token'),
            isLoggedIn: vi.fn().mockReturnValue(true),
        };
        window.apiClient = {
            getDiggerSettings: vi.fn().mockResolvedValue(ENABLED_SETTINGS),
            getDiggerWantlist: vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [] } }),
            setDiggerPriority: vi.fn(),
            getDiggerReports: vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [makeInboxItem()] } }),
            getDiggerReport: vi.fn().mockResolvedValue({ ok: true, status: 200, body: makeFullReport() }),
            markDiggerReportRead: vi.fn().mockResolvedValue({ ok: true, status: 204, body: null }),
        };
        window.exploreApp = undefined;
        loadScript('digger.js');
    });

    // ---------------------------------------------------------------- //
    // Header navigation
    // ---------------------------------------------------------------- //

    describe('header navigation', () => {
        it('renders Wantlist and Reports nav buttons when Digger is enabled', async () => {
            await window.diggerPane.init();
            const header = document.getElementById('diggerHeaderActions');
            const navBtns = header.querySelectorAll('.digger-nav-btn');
            const labels = Array.from(navBtns).map((b) => b.textContent);
            expect(labels).toContain('Wantlist');
            expect(labels).toContain('Reports');
        });

        it('marks the Wantlist nav button active by default', async () => {
            await window.diggerPane.init();
            const header = document.getElementById('diggerHeaderActions');
            const wantlistBtn = header.querySelector('.digger-nav-btn[data-view="wantlist"]');
            expect(wantlistBtn.classList.contains('active')).toBe(true);
        });

        it('does not render nav buttons on the onboarding (disabled) path', async () => {
            window.apiClient.getDiggerSettings.mockResolvedValue({ ok: false, status: 404, body: null });
            await window.diggerPane.init();
            const header = document.getElementById('diggerHeaderActions');
            expect(header.querySelectorAll('.digger-nav-btn')).toHaveLength(0);
        });

        it('switches to the reports view when the Reports nav button is clicked', async () => {
            await window.diggerPane.init();
            const header = document.getElementById('diggerHeaderActions');
            const reportsBtn = header.querySelector('.digger-nav-btn[data-view="reports"]');
            reportsBtn.click();
            await Promise.resolve();
            await Promise.resolve();
            expect(window.apiClient.getDiggerReports).toHaveBeenCalledWith('test-token');
            expect(reportsBtn.classList.contains('active')).toBe(true);
        });

        it('returns to the wantlist when the Wantlist nav button is clicked', async () => {
            await window.diggerPane.init();
            const header = document.getElementById('diggerHeaderActions');
            header.querySelector('.digger-nav-btn[data-view="reports"]').click();
            await Promise.resolve();
            const wantlistBtn = header.querySelector('.digger-nav-btn[data-view="wantlist"]');
            wantlistBtn.click();
            await Promise.resolve();
            expect(window.apiClient.getDiggerWantlist).toHaveBeenCalled();
            expect(wantlistBtn.classList.contains('active')).toBe(true);
        });
    });

    // ---------------------------------------------------------------- //
    // Reports inbox
    // ---------------------------------------------------------------- //

    describe('reports inbox', () => {
        it('does not fetch reports when there is no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            await window.diggerPane._showReports();
            expect(window.apiClient.getDiggerReports).not.toHaveBeenCalled();
        });

        it('renders one list item per report', async () => {
            window.apiClient.getDiggerReports.mockResolvedValue({
                ok: true, status: 200,
                body: { items: [makeInboxItem({ report_id: 'a' }), makeInboxItem({ report_id: 'b' })] },
            });
            await window.diggerPane._showReports();
            const items = document.getElementById('diggerBody').querySelectorAll('.digger-report-item');
            expect(items).toHaveLength(2);
        });

        it('marks unread reports unread and read reports read', async () => {
            window.apiClient.getDiggerReports.mockResolvedValue({
                ok: true, status: 200,
                body: { items: [
                    makeInboxItem({ report_id: 'a', read_at: null }),
                    makeInboxItem({ report_id: 'b', read_at: '2026-05-16T00:00:00Z' }),
                ] },
            });
            await window.diggerPane._showReports();
            const body = document.getElementById('diggerBody');
            const unread = body.querySelector('.digger-report-item[data-report-id="a"]');
            const read = body.querySelector('.digger-report-item[data-report-id="b"]');
            expect(unread.classList.contains('unread')).toBe(true);
            expect(read.classList.contains('read')).toBe(true);
        });

        it('shows the title and change-flag label for a report', async () => {
            await window.diggerPane._showReports();
            const item = document.getElementById('diggerBody').querySelector('.digger-report-item');
            expect(item.textContent).toContain('Weekly dig');
            expect(item.textContent).toContain('significant');
        });

        it('renders an empty state when there are no reports', async () => {
            window.apiClient.getDiggerReports.mockResolvedValue({ ok: true, status: 200, body: { items: [] } });
            await window.diggerPane._showReports();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('.digger-report-item')).toBeNull();
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('renders an error state when the reports load fails', async () => {
            window.apiClient.getDiggerReports.mockResolvedValue({ ok: false, status: 500, body: null });
            await window.diggerPane._showReports();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
            expect(body.textContent.toLowerCase()).toContain('could not');
        });

        it('opens the report when a list item is clicked', async () => {
            await window.diggerPane._showReports();
            const item = document.getElementById('diggerBody').querySelector('.digger-report-item button, .digger-report-item .digger-report-link');
            item.click();
            await Promise.resolve();
            await Promise.resolve();
            expect(window.apiClient.getDiggerReport).toHaveBeenCalledWith('test-token', 'r1');
        });
    });

    // ---------------------------------------------------------------- //
    // Report viewer
    // ---------------------------------------------------------------- //

    describe('report viewer', () => {
        it('renders the report title', async () => {
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            expect(document.getElementById('diggerBody').textContent).toContain('Weekly dig');
        });

        it('renders one bundle card per bundle', async () => {
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            const cards = document.getElementById('diggerBody').querySelectorAll('.digger-bundle-card');
            expect(cards).toHaveLength(4);
        });

        it('renders the watching list when releases are being watched', async () => {
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            const body = document.getElementById('diggerBody');
            const watching = body.querySelector('.digger-watching-list');
            expect(watching).not.toBeNull();
            expect(watching.textContent).toContain('42');
        });

        it('omits the watching list when nothing is watched', async () => {
            window.apiClient.getDiggerReport.mockResolvedValue({ ok: true, status: 200, body: makeFullReport({ watching: [] }) });
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            expect(document.getElementById('diggerBody').querySelector('.digger-watching-list')).toBeNull();
        });

        it('shows the shipping-confidence badge', async () => {
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            const badge = document.getElementById('diggerBody').querySelector('.digger-confidence-high');
            expect(badge).not.toBeNull();
            expect(badge.textContent.toLowerCase()).toContain('shipping');
        });

        it('marks an unread report read on open', async () => {
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            await Promise.resolve();
            expect(window.apiClient.markDiggerReportRead).toHaveBeenCalledWith('test-token', 'r1');
        });

        it('does not mark an already-read report read again', async () => {
            window.apiClient.getDiggerReport.mockResolvedValue({
                ok: true, status: 200, body: makeFullReport({ read_at: '2026-05-16T00:00:00Z' }),
            });
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            await Promise.resolve();
            expect(window.apiClient.markDiggerReportRead).not.toHaveBeenCalled();
        });

        it('renders an error state when the report fails to load', async () => {
            window.apiClient.getDiggerReport.mockResolvedValue({ ok: false, status: 404, body: null });
            await window.diggerPane._openReport('missing');
            await Promise.resolve();
            const body = document.getElementById('diggerBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('renders a back control that returns to the inbox', async () => {
            await window.diggerPane._openReport('r1');
            await Promise.resolve();
            const back = document.getElementById('diggerBody').querySelector('.digger-back-btn');
            expect(back).not.toBeNull();
            back.click();
            await Promise.resolve();
            expect(window.apiClient.getDiggerReports).toHaveBeenCalled();
        });
    });
});
