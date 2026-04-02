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

    describe('_showEmpty', () => {
        it('should hide content and show placeholder', () => {
            const content = document.getElementById('insightsContent');
            const placeholder = document.getElementById('insightsPlaceholder');
            content.classList.remove('hidden');
            placeholder.classList.add('hidden');

            window.insightsPanel._showEmpty();

            expect(content.classList.contains('hidden')).toBe(true);
            expect(placeholder.classList.contains('hidden')).toBe(false);
        });
    });

    describe('_renderTopArtists', () => {
        it('should render a table with artist data', () => {
            const el = document.getElementById('insightsTopArtists');
            window.insightsPanel._renderTopArtists({
                items: [
                    { rank: 1, artist_name: 'Radiohead', edge_count: 100 },
                    { rank: 2, artist_name: 'Bjork', edge_count: 80 },
                ],
            });

            expect(el.querySelector('table')).not.toBeNull();
            expect(el.querySelectorAll('tbody tr')).toHaveLength(2);
        });

        it('should show "No data" when items are empty', () => {
            const el = document.getElementById('insightsTopArtists');
            window.insightsPanel._renderTopArtists({ items: [] });
            expect(el.textContent).toContain('No data available yet');
        });

        it('should show "No data" when data is null', () => {
            const el = document.getElementById('insightsTopArtists');
            window.insightsPanel._renderTopArtists(null);
            expect(el.textContent).toContain('No data available yet');
        });

        it('should do nothing when element is missing', () => {
            document.getElementById('insightsTopArtists').remove();
            expect(() => window.insightsPanel._renderTopArtists({ items: [] })).not.toThrow();
        });

        it('should render header columns', () => {
            const el = document.getElementById('insightsTopArtists');
            window.insightsPanel._renderTopArtists({
                items: [{ rank: 1, artist_name: 'Test', edge_count: 50 }],
            });
            const headers = el.querySelectorAll('th');
            expect(headers).toHaveLength(3);
            expect(headers[0].textContent).toBe('#');
            expect(headers[1].textContent).toBe('Artist');
            expect(headers[2].textContent).toBe('Connections');
        });
    });

    describe('_renderThisMonth', () => {
        it('should render anniversary groups', () => {
            const el = document.getElementById('insightsThisMonth');
            window.insightsPanel._renderThisMonth({
                items: [
                    { anniversary: 25, title: 'OK Computer', artist_name: 'Radiohead', release_year: 1997 },
                    { anniversary: 25, title: 'Homogenic', artist_name: 'Bjork', release_year: 1997 },
                    { anniversary: 50, title: 'Abbey Road', artist_name: 'The Beatles', release_year: 1969 },
                ],
            });
            const groups = el.querySelectorAll('.insights-anniversary-group');
            expect(groups).toHaveLength(2);
            expect(groups[0].querySelector('h4').textContent).toBe('25 Years Ago');
        });

        it('should show empty message when no items', () => {
            const el = document.getElementById('insightsThisMonth');
            window.insightsPanel._renderThisMonth({ items: [] });
            expect(el.textContent).toContain('No anniversaries this month');
        });

        it('should show empty message when null', () => {
            const el = document.getElementById('insightsThisMonth');
            window.insightsPanel._renderThisMonth(null);
            expect(el.textContent).toContain('No anniversaries this month');
        });

        it('should do nothing when element is missing', () => {
            document.getElementById('insightsThisMonth').remove();
            expect(() => window.insightsPanel._renderThisMonth({ items: [] })).not.toThrow();
        });

        it('should show "Unknown Artist" when artist_name is null', () => {
            const el = document.getElementById('insightsThisMonth');
            window.insightsPanel._renderThisMonth({
                items: [{ anniversary: 10, title: 'Album', artist_name: null, release_year: 2000 }],
            });
            expect(el.querySelector('.insights-anniversary-artist').textContent).toBe('Unknown Artist');
        });
    });

    describe('_renderDataCompleteness', () => {
        it('should render completeness bars', () => {
            const el = document.getElementById('insightsCompleteness');
            window.insightsPanel._renderDataCompleteness({
                items: [
                    { entity_type: 'releases', completeness_pct: 89.5, total_count: 15000000 },
                    { entity_type: 'artists', completeness_pct: 95.2, total_count: 8000000 },
                ],
            });
            expect(el.querySelectorAll('.insights-completeness-row')).toHaveLength(2);
        });

        it('should capitalize entity type', () => {
            const el = document.getElementById('insightsCompleteness');
            window.insightsPanel._renderDataCompleteness({
                items: [{ entity_type: 'releases', completeness_pct: 89.5, total_count: 100 }],
            });
            expect(el.querySelector('.insights-completeness-label').textContent).toBe('Releases');
        });

        it('should cap bar width at 100%', () => {
            const el = document.getElementById('insightsCompleteness');
            window.insightsPanel._renderDataCompleteness({
                items: [{ entity_type: 'test', completeness_pct: 120, total_count: 50 }],
            });
            expect(el.querySelector('.insights-completeness-bar').style.width).toBe('100%');
        });

        it('should show empty message when no items', () => {
            const el = document.getElementById('insightsCompleteness');
            window.insightsPanel._renderDataCompleteness({ items: [] });
            expect(el.textContent).toContain('No completeness data available');
        });

        it('should show empty message when null', () => {
            const el = document.getElementById('insightsCompleteness');
            window.insightsPanel._renderDataCompleteness(null);
            expect(el.textContent).toContain('No completeness data available');
        });

        it('should do nothing when element is missing', () => {
            document.getElementById('insightsCompleteness').remove();
            expect(() => window.insightsPanel._renderDataCompleteness({ items: [] })).not.toThrow();
        });
    });

    describe('_renderStatus', () => {
        it('should render healthy status when all completed', () => {
            const el = document.getElementById('insightsStatus');
            window.insightsPanel._renderStatus({
                statuses: [
                    { insight_type: 'top_artists', status: 'completed', last_computed: '2026-01-01T00:00:00Z' },
                ],
            });
            const dot = el.querySelector('.insights-status-dot');
            expect(dot.className).toContain('healthy');
            expect(dot.textContent).toBe('All healthy');
        });

        it('should render warning status when some have issues', () => {
            const el = document.getElementById('insightsStatus');
            window.insightsPanel._renderStatus({
                statuses: [
                    { insight_type: 'a', status: 'completed', last_computed: '2026-01-01T00:00:00Z' },
                    { insight_type: 'b', status: 'error', last_computed: '2026-01-01T00:00:00Z' },
                ],
            });
            const dot = el.querySelector('.insights-status-dot');
            expect(dot.className).toContain('warning');
            expect(dot.textContent).toBe('Issues detected');
        });

        it('should treat never_run as healthy', () => {
            const el = document.getElementById('insightsStatus');
            window.insightsPanel._renderStatus({
                statuses: [{ insight_type: 'a', status: 'never_run', last_computed: null }],
            });
            expect(el.querySelector('.insights-status-dot').className).toContain('healthy');
        });

        it('should clear element when no statuses', () => {
            const el = document.getElementById('insightsStatus');
            el.textContent = 'old';
            window.insightsPanel._renderStatus({ statuses: [] });
            expect(el.textContent).toBe('');
        });

        it('should clear element when data is null', () => {
            const el = document.getElementById('insightsStatus');
            el.textContent = 'old';
            window.insightsPanel._renderStatus(null);
            expect(el.textContent).toBe('');
        });

        it('should do nothing when element is missing', () => {
            document.getElementById('insightsStatus').remove();
            expect(() => window.insightsPanel._renderStatus({ statuses: [] })).not.toThrow();
        });
    });

    describe('_loadGenreTrends', () => {
        it('should update selected genre', async () => {
            window.apiClient = {
                getInsightsGenreTrends: vi.fn().mockResolvedValue({ trends: [] }),
            };
            await window.insightsPanel._loadGenreTrends('Jazz');
            expect(window.insightsPanel._selectedGenre).toBe('Jazz');
        });

        it('should toggle active class on genre chips', async () => {
            const chip1 = document.createElement('div');
            chip1.className = 'insights-genre-chip';
            chip1.dataset.genre = 'Rock';
            const chip2 = document.createElement('div');
            chip2.className = 'insights-genre-chip active';
            chip2.dataset.genre = 'Jazz';
            document.body.append(chip1, chip2);

            window.apiClient = {
                getInsightsGenreTrends: vi.fn().mockResolvedValue({ trends: [] }),
            };
            await window.insightsPanel._loadGenreTrends('Rock');
            expect(chip1.classList.contains('active')).toBe(true);
            expect(chip2.classList.contains('active')).toBe(false);
        });
    });

    describe('_renderGenreTrends', () => {
        it('should call Plotly.newPlot with trend data', () => {
            const el = document.getElementById('insightsGenreChart');
            window.insightsPanel._renderGenreTrends({
                genre: 'Rock',
                trends: [
                    { decade: 1970, release_count: 1000 },
                    { decade: 1980, release_count: 2000 },
                ],
            });
            expect(Plotly.newPlot).toHaveBeenCalled();
        });

        it('should show "No trend data" when trends are empty', () => {
            const el = document.getElementById('insightsGenreChart');
            window.insightsPanel._renderGenreTrends({ trends: [] });
            expect(el.textContent).toContain('No trend data for this genre');
        });

        it('should show "No trend data" when null', () => {
            const el = document.getElementById('insightsGenreChart');
            window.insightsPanel._renderGenreTrends(null);
            expect(el.textContent).toContain('No trend data for this genre');
        });

        it('should do nothing when element is missing', () => {
            document.getElementById('insightsGenreChart').remove();
            expect(() => window.insightsPanel._renderGenreTrends({ trends: [] })).not.toThrow();
        });

        it('should purge Plotly chart before re-render', () => {
            const el = document.getElementById('insightsGenreChart');
            const data = {
                genre: 'Rock',
                trends: [{ decade: 1970, release_count: 1000 }],
            };
            window.insightsPanel._renderGenreTrends(data);
            window.insightsPanel._renderGenreTrends(data);

            expect(Plotly.purge).toHaveBeenCalledWith(el);
        });
    });

    describe('_checkForUpdates', () => {
        it('should reload when timestamps have changed', async () => {
            window.insightsPanel._lastComputedAt = new Map([['top_artists', '2026-01-01']]);
            window.apiClient = {
                getInsightsStatus: vi.fn().mockResolvedValue({
                    statuses: [{ insight_type: 'top_artists', last_computed: '2026-01-02' }],
                }),
                getInsightsTopArtists: vi.fn().mockResolvedValue(null),
                getInsightsThisMonth: vi.fn().mockResolvedValue(null),
                getInsightsDataCompleteness: vi.fn().mockResolvedValue(null),
            };
            await window.insightsPanel._checkForUpdates();
            expect(window.insightsPanel._lastComputedAt.get('top_artists')).toBe('2026-01-02');
        });

        it('should not reload when timestamps unchanged', async () => {
            window.insightsPanel._lastComputedAt = new Map([['top_artists', '2026-01-01']]);
            const loadSpy = vi.spyOn(window.insightsPanel, 'load');
            window.apiClient = {
                getInsightsStatus: vi.fn().mockResolvedValue({
                    statuses: [{ insight_type: 'top_artists', last_computed: '2026-01-01' }],
                }),
            };
            await window.insightsPanel._checkForUpdates();
            expect(loadSpy).not.toHaveBeenCalled();
            loadSpy.mockRestore();
        });

        it('should skip on API error', async () => {
            window.apiClient = {
                getInsightsStatus: vi.fn().mockRejectedValue(new Error('fail')),
            };
            await window.insightsPanel._checkForUpdates();
        });

        it('should skip when status returns null', async () => {
            window.apiClient = {
                getInsightsStatus: vi.fn().mockResolvedValue(null),
            };
            await window.insightsPanel._checkForUpdates();
        });
    });

    describe('load error handling', () => {
        it('should show empty state on API error', async () => {
            window.apiClient = {
                getInsightsTopArtists: vi.fn().mockRejectedValue(new Error('fail')),
                getInsightsThisMonth: vi.fn().mockRejectedValue(new Error('fail')),
                getInsightsDataCompleteness: vi.fn().mockRejectedValue(new Error('fail')),
                getInsightsStatus: vi.fn().mockRejectedValue(new Error('fail')),
            };
            await window.insightsPanel.load();
            const content = document.getElementById('insightsContent');
            expect(content.classList.contains('hidden')).toBe(true);
        });

        it('should remove loading state after error', async () => {
            window.apiClient = {
                getInsightsTopArtists: vi.fn().mockRejectedValue(new Error('fail')),
                getInsightsThisMonth: vi.fn().mockRejectedValue(new Error('fail')),
                getInsightsDataCompleteness: vi.fn().mockRejectedValue(new Error('fail')),
                getInsightsStatus: vi.fn().mockRejectedValue(new Error('fail')),
            };
            await window.insightsPanel.load();
            const loading = document.getElementById('insightsLoading');
            expect(loading.classList.contains('active')).toBe(false);
        });
    });
});
