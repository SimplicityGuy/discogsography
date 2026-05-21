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
