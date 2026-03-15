import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

/**
 * Create minimal DOM elements required by InsightsPanel.
 * Uses safe DOM APIs (createElement/appendChild) to build the fixture.
 */
function setupInsightsDOM() {
    document.body.textContent = '';
    const ids = [
        'insightsPane', 'insightsLoading', 'insightsPlaceholder',
        'insightsContent', 'insightsTopArtists', 'insightsGenreChart',
        'insightsThisMonth', 'insightsCompleteness', 'insightsStatus',
    ];
    for (const id of ids) {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    }
}

describe('InsightsPanel', () => {
    beforeEach(() => {
        setupInsightsDOM();
        delete globalThis.window;
        globalThis.window = globalThis;
        // Stub Plotly since it's loaded via CDN
        globalThis.Plotly = { newPlot: vi.fn(), purge: vi.fn() };
        loadScript('insights.js');
    });

    describe('_timeAgo', () => {
        it('should return "just now" for recent dates', () => {
            const now = new Date();
            expect(window.insightsPanel._timeAgo(now)).toBe('just now');
        });

        it('should return minutes ago', () => {
            const date = new Date(Date.now() - 5 * 60 * 1000);
            expect(window.insightsPanel._timeAgo(date)).toBe('5m ago');
        });

        it('should return hours ago', () => {
            const date = new Date(Date.now() - 3 * 60 * 60 * 1000);
            expect(window.insightsPanel._timeAgo(date)).toBe('3h ago');
        });

        it('should return days ago', () => {
            const date = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
            expect(window.insightsPanel._timeAgo(date)).toBe('2d ago');
        });
    });

    describe('_hasChanged', () => {
        it('should return false when no previous timestamps exist', () => {
            window.insightsPanel._lastComputedAt = null;
            const newMap = new Map([['top_artists', '2026-01-01']]);
            expect(window.insightsPanel._hasChanged(newMap)).toBe(false);
        });

        it('should return true when sizes differ', () => {
            window.insightsPanel._lastComputedAt = new Map([['top_artists', '2026-01-01']]);
            const newMap = new Map([
                ['top_artists', '2026-01-01'],
                ['genre_trends', '2026-01-01'],
            ]);
            expect(window.insightsPanel._hasChanged(newMap)).toBe(true);
        });

        it('should return true when a timestamp changed', () => {
            window.insightsPanel._lastComputedAt = new Map([
                ['top_artists', '2026-01-01T00:00:00'],
                ['genre_trends', '2026-01-01T00:00:00'],
            ]);
            const newMap = new Map([
                ['top_artists', '2026-01-01T12:00:00'],
                ['genre_trends', '2026-01-01T00:00:00'],
            ]);
            expect(window.insightsPanel._hasChanged(newMap)).toBe(true);
        });

        it('should return false when timestamps are identical', () => {
            window.insightsPanel._lastComputedAt = new Map([
                ['top_artists', '2026-01-01'],
                ['genre_trends', '2026-01-02'],
            ]);
            const newMap = new Map([
                ['top_artists', '2026-01-01'],
                ['genre_trends', '2026-01-02'],
            ]);
            expect(window.insightsPanel._hasChanged(newMap)).toBe(false);
        });
    });

    describe('polling', () => {
        it('startPolling should set interval', () => {
            vi.useFakeTimers();
            window.insightsPanel.startPolling();
            expect(window.insightsPanel._pollInterval).not.toBeNull();
            window.insightsPanel.stopPolling();
            vi.useRealTimers();
        });

        it('stopPolling should clear interval', () => {
            vi.useFakeTimers();
            window.insightsPanel.startPolling();
            window.insightsPanel.stopPolling();
            expect(window.insightsPanel._pollInterval).toBeNull();
            vi.useRealTimers();
        });

        it('startPolling should be idempotent', () => {
            vi.useFakeTimers();
            window.insightsPanel.startPolling();
            const firstInterval = window.insightsPanel._pollInterval;
            window.insightsPanel.startPolling();
            expect(window.insightsPanel._pollInterval).toBe(firstInterval);
            window.insightsPanel.stopPolling();
            vi.useRealTimers();
        });
    });

    describe('load', () => {
        it('should show empty state when no data is available', async () => {
            window.apiClient = {
                getInsightsTopArtists: vi.fn().mockResolvedValue(null),
                getInsightsThisMonth: vi.fn().mockResolvedValue(null),
                getInsightsDataCompleteness: vi.fn().mockResolvedValue(null),
                getInsightsStatus: vi.fn().mockResolvedValue(null),
            };

            await window.insightsPanel.load();

            const content = document.getElementById('insightsContent');
            expect(content.classList.contains('hidden')).toBe(true);
            const placeholder = document.getElementById('insightsPlaceholder');
            expect(placeholder.classList.contains('hidden')).toBe(false);
        });

        it('should render data and store timestamps when data is available', async () => {
            window.apiClient = {
                getInsightsTopArtists: vi.fn().mockResolvedValue({
                    items: [{ rank: 1, artist_name: 'Radiohead', edge_count: 100 }],
                }),
                getInsightsThisMonth: vi.fn().mockResolvedValue({ items: [] }),
                getInsightsDataCompleteness: vi.fn().mockResolvedValue({ items: [] }),
                getInsightsStatus: vi.fn().mockResolvedValue({
                    statuses: [{ insight_type: 'top_artists', last_computed: '2026-01-01', status: 'completed' }],
                }),
                getInsightsGenreTrends: vi.fn().mockResolvedValue({ trends: [] }),
            };

            await window.insightsPanel.load();

            expect(window.insightsPanel._loaded).toBe(true);
            expect(window.insightsPanel._lastComputedAt.get('top_artists')).toBe('2026-01-01');

            // Verify top artists rendered
            const table = document.getElementById('insightsTopArtists');
            expect(table.querySelector('table')).not.toBeNull();
        });
    });
});
