import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Set up minimal DOM elements for UserPanes tests.
 */
function setupUserPanesDOM() {
    document.body.textContent = '';

    const ids = [
        'collectionLoading', 'collectionBody', 'collectionStats',
        'wantlistLoading', 'wantlistBody',
        'recommendationsLoading', 'recommendationsBody',
        'gapsLoading', 'gapsBody', 'gapsPane',
        'tasteStrip',
        'navGaps',
        'syncBtn',
        'discogsVerifierInput', 'discogsVerifierError', 'discogsVerifierSubmit',
    ];

    ids.forEach(id => {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    });

    // Add nav-link elements for gap pane switching
    const navGaps = document.getElementById('navGaps');
    const link = document.createElement('a');
    link.className = 'nav-link';
    navGaps.appendChild(link);
}

describe('UserPanes', () => {
    let userPanes;

    beforeAll(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        loadScriptDirect('user-panes.js');
    });

    beforeEach(() => {
        setupUserPanesDOM();

        window.apiClient = {
            getUserCollection: vi.fn().mockResolvedValue(null),
            getUserWantlist: vi.fn().mockResolvedValue(null),
            getUserRecommendations: vi.fn().mockResolvedValue(null),
            getUserCollectionStats: vi.fn().mockResolvedValue(null),
            getTasteFingerprint: vi.fn().mockResolvedValue(null),
            getTasteCard: vi.fn().mockResolvedValue(null),
            getCollectionGaps: vi.fn().mockResolvedValue(null),
            getCollectionFormats: vi.fn().mockResolvedValue({ formats: [] }),
            triggerSync: vi.fn().mockResolvedValue({ ok: false, status: 500, body: null }),
            authorizeDiscogs: vi.fn().mockResolvedValue(null),
            verifyDiscogs: vi.fn().mockResolvedValue(null),
            revokeDiscogs: vi.fn().mockResolvedValue(null),
            getDiscogsStatus: vi.fn().mockResolvedValue(null),
        };

        window.authManager = {
            getToken: vi.fn().mockReturnValue('test-token'),
            getDiscogsStatus: vi.fn().mockReturnValue({ connected: false }),
            setDiscogsStatus: vi.fn(),
            notify: vi.fn(),
        };

        userPanes = new UserPanes();
    });

    describe('constructor', () => {
        it('should initialize with zero offsets', () => {
            expect(userPanes._collectionOffset).toBe(0);
            expect(userPanes._wantlistOffset).toBe(0);
        });

        it('should initialize with page size 50', () => {
            expect(userPanes._pageSize).toBe(50);
        });

        it('should initialize with null taste cache', () => {
            expect(userPanes._tasteCache).toBeNull();
        });

        it('should initialize _tasteLoading to false', () => {
            expect(userPanes._tasteLoading).toBe(false);
        });
    });

    describe('loadCollection', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);

            await userPanes.loadCollection();

            expect(window.apiClient.getUserCollection).not.toHaveBeenCalled();
        });

        it('should call getUserCollection with token and pagination', async () => {
            await userPanes.loadCollection();

            expect(window.apiClient.getUserCollection).toHaveBeenCalledWith('test-token', 50, 0);
        });

        it('should reset offset when reset=true', async () => {
            userPanes._collectionOffset = 50;

            await userPanes.loadCollection(true);

            expect(window.apiClient.getUserCollection).toHaveBeenCalledWith('test-token', 50, 0);
        });

        it('should render empty state when API returns null', async () => {
            window.apiClient.getUserCollection.mockResolvedValue(null);

            await userPanes.loadCollection();

            const body = document.getElementById('collectionBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should render collection list when data has releases', async () => {
            window.apiClient.getUserCollection.mockResolvedValue({
                releases: [
                    { title: 'OK Computer', artist: 'Radiohead', year: 1997 },
                ],
                total: 1,
                has_more: false,
            });

            await userPanes.loadCollection();

            const body = document.getElementById('collectionBody');
            expect(body.querySelector('table')).not.toBeNull();
        });

        it('should render empty state when releases array is empty', async () => {
            window.apiClient.getUserCollection.mockResolvedValue({
                releases: [],
                total: 0,
                has_more: false,
            });

            await userPanes.loadCollection();

            const body = document.getElementById('collectionBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should remove loading class in finally block', async () => {
            window.apiClient.getUserCollection.mockResolvedValue(null);
            const loading = document.getElementById('collectionLoading');

            await userPanes.loadCollection();

            expect(loading.classList.contains('active')).toBe(false);
        });
    });

    describe('loadWantlist', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);

            await userPanes.loadWantlist();

            expect(window.apiClient.getUserWantlist).not.toHaveBeenCalled();
        });

        it('should call getUserWantlist with token', async () => {
            await userPanes.loadWantlist();

            expect(window.apiClient.getUserWantlist).toHaveBeenCalledWith('test-token', 50, 0);
        });

        it('should render empty state when API returns null', async () => {
            window.apiClient.getUserWantlist.mockResolvedValue(null);

            await userPanes.loadWantlist();

            const body = document.getElementById('wantlistBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should render wantlist when data has releases', async () => {
            window.apiClient.getUserWantlist.mockResolvedValue({
                releases: [{ title: 'Loveless', artist: 'My Bloody Valentine', year: 1991 }],
                total: 1,
                has_more: false,
            });

            await userPanes.loadWantlist();

            const body = document.getElementById('wantlistBody');
            expect(body.querySelector('table')).not.toBeNull();
        });
    });

    describe('loadRecommendations', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);

            await userPanes.loadRecommendations();

            expect(window.apiClient.getUserRecommendations).not.toHaveBeenCalled();
        });

        it('should render empty state when no recommendations', async () => {
            window.apiClient.getUserRecommendations.mockResolvedValue({ recommendations: [] });

            await userPanes.loadRecommendations();

            const body = document.getElementById('recommendationsBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should render recommendation items', async () => {
            window.apiClient.getUserRecommendations.mockResolvedValue({
                recommendations: [
                    { title: 'Dummy', artist: 'Portishead', year: 1994, score: 0.87 },
                    { title: 'Mezzanine', artist: 'Massive Attack', year: 1998, score: 0.72 },
                ],
            });

            await userPanes.loadRecommendations();

            const body = document.getElementById('recommendationsBody');
            const items = body.querySelectorAll('.recommendation-item');
            expect(items).toHaveLength(2);
            expect(items[0].querySelector('.release-list-title').textContent).toBe('Dummy');
            expect(items[0].querySelector('.recommendation-score').textContent).toBe('87% match');
        });
    });

    describe('_renderCollectionStats', () => {
        it('should render stats cards', () => {
            userPanes._renderCollectionStats({
                total_releases: 100,
                unique_artists: 50,
                unique_labels: 20,
                average_rating: 3.5,
            });

            const el = document.getElementById('collectionStats');
            const cards = el.querySelectorAll('.stat-card');
            expect(cards).toHaveLength(4);
        });

        it('should do nothing when stats is null', () => {
            userPanes._renderCollectionStats(null);

            const el = document.getElementById('collectionStats');
            expect(el.textContent).toBe('');
        });

        it('should format rating to 1 decimal', () => {
            userPanes._renderCollectionStats({
                total_releases: 10,
                unique_artists: 5,
                unique_labels: 2,
                average_rating: 4.25,
            });

            const el = document.getElementById('collectionStats');
            expect(el.textContent).toContain('4.3');
        });

        it('should show dash when no rating', () => {
            userPanes._renderCollectionStats({
                total_releases: 10,
                unique_artists: 5,
                unique_labels: 2,
                average_rating: null,
            });

            const el = document.getElementById('collectionStats');
            expect(el.textContent).toContain('\u2014');
        });

        it('should handle alternative field names (total, artists, labels)', () => {
            userPanes._renderCollectionStats({
                total: 200,
                artists: 75,
                labels: 30,
            });

            const el = document.getElementById('collectionStats');
            expect(el.textContent).toContain('200');
        });
    });

    describe('clearTasteCache', () => {
        it('should set _tasteCache to null', () => {
            userPanes._tasteCache = { some: 'data' };

            userPanes.clearTasteCache();

            expect(userPanes._tasteCache).toBeNull();
        });
    });

    describe('loadTasteFingerprint', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);

            await userPanes.loadTasteFingerprint();

            expect(window.apiClient.getTasteFingerprint).not.toHaveBeenCalled();
        });

        it('should return early when Discogs is not connected', async () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: false });

            await userPanes.loadTasteFingerprint();

            expect(window.apiClient.getTasteFingerprint).not.toHaveBeenCalled();
        });

        it('should use cache when available', async () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: true });
            userPanes._tasteCache = { genres: [], heatmap: [], drift: [] };

            await userPanes.loadTasteFingerprint();

            expect(window.apiClient.getTasteFingerprint).not.toHaveBeenCalled();
        });

        it('should not call API concurrently when already loading', async () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: true });
            userPanes._tasteLoading = true;

            await userPanes.loadTasteFingerprint();

            expect(window.apiClient.getTasteFingerprint).not.toHaveBeenCalled();
        });

        it('should clear strip when API returns null', async () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: true });
            window.apiClient.getTasteFingerprint.mockResolvedValue(null);

            const strip = document.getElementById('tasteStrip');
            const oldContent = document.createElement('div');
            oldContent.textContent = 'old content';
            strip.appendChild(oldContent);

            await userPanes.loadTasteFingerprint();

            expect(strip.children).toHaveLength(0);
        });

        it('should render taste strip when data is available', async () => {
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: true });
            window.apiClient.getTasteFingerprint.mockResolvedValue({
                obscurity: { score: 0.75 },
                peak_decade: 1990,
                drift: [{ top_genre: 'Rock' }, { top_genre: 'Electronic' }],
                heatmap: [{ genre: 'Rock', decade: 1990, count: 10 }],
                blind_spots: [],
            });

            await userPanes.loadTasteFingerprint();

            const strip = document.getElementById('tasteStrip');
            expect(strip.querySelector('.taste-strip')).not.toBeNull();
        });
    });

    describe('_formatDrift', () => {
        it('should return dash for empty drift', () => {
            expect(userPanes._formatDrift([])).toBe('\u2014');
        });

        it('should return dash for null drift', () => {
            expect(userPanes._formatDrift(null)).toBe('\u2014');
        });

        it('should indicate consistent when first and last genre are the same', () => {
            const drift = [{ top_genre: 'Rock' }, { top_genre: 'Rock' }];
            expect(userPanes._formatDrift(drift)).toBe('Rock (consistent)');
        });

        it('should show arrow when first and last genre differ', () => {
            const drift = [{ top_genre: 'Rock' }, { top_genre: 'Electronic' }];
            expect(userPanes._formatDrift(drift)).toBe('Rock \u2192 Electronic');
        });

        it('should handle single-item drift', () => {
            const drift = [{ top_genre: 'Jazz' }];
            expect(userPanes._formatDrift(drift)).toBe('Jazz (consistent)');
        });
    });

    describe('_tasteStat', () => {
        it('should create a stat row with correct label and value', () => {
            const row = userPanes._tasteStat('Obscurity', '0.75', 'purple');

            expect(row.querySelector('.taste-stat-label').textContent).toBe('Obscurity');
            expect(row.querySelector('.taste-stat-value').textContent).toBe('0.75');
            expect(row.querySelector('.taste-stat-value').className).toContain('purple');
        });
    });

    describe('_renderStars', () => {
        it('should render 5 star elements', () => {
            const frag = userPanes._renderStars(3);
            const div = document.createElement('div');
            div.appendChild(frag);
            const stars = div.querySelectorAll('span');
            expect(stars).toHaveLength(5);
        });

        it('should mark correct number of filled stars', () => {
            const frag = userPanes._renderStars(3);
            const div = document.createElement('div');
            div.appendChild(frag);
            const stars = div.querySelectorAll('span');
            const filled = Array.from(stars).filter(s => !s.className.includes('star-empty'));
            expect(filled).toHaveLength(3);
        });
    });

    describe('_buildPagination', () => {
        it('should render page info and buttons', () => {
            const onPageChange = vi.fn();
            const pag = userPanes._buildPagination(0, 5, onPageChange);

            expect(pag.querySelector('.page-info').textContent).toBe('Page 1 of 5');
            expect(pag.querySelector('.page-buttons')).not.toBeNull();
        });

        it('should disable previous button on first page', () => {
            const pag = userPanes._buildPagination(0, 5, vi.fn());
            const prevBtn = pag.querySelectorAll('.page-btn')[0];
            expect(prevBtn.disabled).toBe(true);
        });

        it('should disable next button on last page', () => {
            const pag = userPanes._buildPagination(4, 5, vi.fn());
            const buttons = pag.querySelectorAll('.page-btn');
            const nextBtn = buttons[buttons.length - 1];
            expect(nextBtn.disabled).toBe(true);
        });
    });

    describe('_getPageNumbers', () => {
        it('should return all pages when total <= 5', () => {
            const pages = userPanes._getPageNumbers(0, 3);
            expect(pages).toEqual([0, 1, 2]);
        });

        it('should include ellipsis for large page counts', () => {
            const pages = userPanes._getPageNumbers(5, 20);
            expect(pages).toContain('...');
        });

        it('should always include first and last page', () => {
            const pages = userPanes._getPageNumbers(5, 20);
            expect(pages[0]).toBe(0);
            expect(pages[pages.length - 1]).toBe(19);
        });
    });

    describe('_renderHeatmapGrid', () => {
        it('should render a heatmap grid', () => {
            const cells = [
                { genre: 'Rock', decade: 1990, count: 10 },
                { genre: 'Rock', decade: 2000, count: 5 },
                { genre: 'Jazz', decade: 1990, count: 3 },
            ];

            const grid = userPanes._renderHeatmapGrid(cells);

            expect(grid.className).toBe('taste-heatmap-grid');
            expect(grid.querySelectorAll('.taste-heatmap-label').length).toBeGreaterThan(0);
        });

        it('should render decade headers', () => {
            const cells = [
                { genre: 'Rock', decade: 1990, count: 5 },
                { genre: 'Rock', decade: 2000, count: 3 },
            ];

            const grid = userPanes._renderHeatmapGrid(cells);

            const headers = grid.querySelectorAll('.taste-heatmap-header');
            expect(headers.length).toBe(2);
            expect(headers[0].textContent).toBe('1990s');
            expect(headers[1].textContent).toBe('2000s');
        });
    });

    describe('_renderRecommendations', () => {
        it('should render empty state for null data', () => {
            const container = document.createElement('div');
            userPanes._renderRecommendations(container, null);

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should render recommendation with score', () => {
            const container = document.createElement('div');
            userPanes._renderRecommendations(container, {
                recommendations: [
                    { title: 'Test Album', artist: 'Test Artist', year: 2020, score: 0.95 },
                ],
            });

            const score = container.querySelector('.recommendation-score');
            expect(score.textContent).toBe('95% match');
        });

        it('should render clickable link when artist is present', () => {
            const container = document.createElement('div');
            userPanes._renderRecommendations(container, {
                recommendations: [
                    { title: 'OK Computer', artist: 'Radiohead', year: 1997, score: 0.8 },
                ],
            });

            const link = container.querySelector('.release-list-title a');
            expect(link).not.toBeNull();
            expect(link.textContent).toBe('OK Computer');
            expect(link.href).toContain('#');
        });

        it('should navigate to artist explore on link click', () => {
            const container = document.createElement('div');
            window.exploreApp = {
                _setSearchType: vi.fn(),
                currentQuery: '',
                _switchPane: vi.fn(),
                _loadExplore: vi.fn(),
            };
            const searchInput = document.createElement('input');
            searchInput.id = 'searchInput';
            document.body.appendChild(searchInput);

            userPanes._renderRecommendations(container, {
                recommendations: [
                    { title: 'OK Computer', artist: 'Radiohead', year: 1997, score: 0.8 },
                ],
            });

            const link = container.querySelector('.release-list-title a');
            link.click();

            expect(window.exploreApp._setSearchType).toHaveBeenCalledWith('artist');
            expect(window.exploreApp.currentQuery).toBe('Radiohead');
            expect(window.exploreApp._switchPane).toHaveBeenCalledWith('explore');
            expect(window.exploreApp._loadExplore).toHaveBeenCalledWith('Radiohead', 'artist');
            expect(document.getElementById('searchInput').value).toBe('Radiohead');

            searchInput.remove();
            delete window.exploreApp;
        });

        it('should render plain text when artist is absent', () => {
            const container = document.createElement('div');
            userPanes._renderRecommendations(container, {
                recommendations: [
                    { title: 'Mystery Album', year: 2020, score: 0.5 },
                ],
            });

            const titleDiv = container.querySelector('.release-list-title');
            expect(titleDiv.querySelector('a')).toBeNull();
            expect(titleDiv.textContent).toBe('Mystery Album');
        });

        it('should show unknown title for missing title with artist link', () => {
            const container = document.createElement('div');
            userPanes._renderRecommendations(container, {
                recommendations: [
                    { artist: 'Some Artist', score: 0.3 },
                ],
            });

            const link = container.querySelector('.release-list-title a');
            expect(link).not.toBeNull();
            expect(link.textContent).toBe('(Unknown title)');
        });
    });

    describe('_renderCollectionEmpty', () => {
        it('should render an empty state with the provided message', () => {
            const container = document.createElement('div');
            userPanes._renderCollectionEmpty(container, 'No items found');

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
            expect(container.querySelector('p').textContent).toBe('No items found');
        });

        it('should do nothing when container is null', () => {
            expect(() => userPanes._renderCollectionEmpty(null, 'msg')).not.toThrow();
        });
    });

    describe('_renderWantlistEmpty', () => {
        it('should render an empty state with the provided message', () => {
            const container = document.createElement('div');
            userPanes._renderWantlistEmpty(container, 'Wantlist is empty');

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
            expect(container.querySelector('p').textContent).toBe('Wantlist is empty');
        });
    });

    describe('_renderGapsEmpty', () => {
        it('should render empty state', () => {
            const container = document.createElement('div');
            userPanes._renderGapsEmpty(container, 'All owned!');

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
            expect(container.querySelector('p').textContent).toBe('All owned!');
        });
    });

    describe('triggerSync', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);

            await userPanes.triggerSync();

            expect(window.apiClient.triggerSync).not.toHaveBeenCalled();
        });

        it('should call triggerSync with token', async () => {
            await userPanes.triggerSync();

            expect(window.apiClient.triggerSync).toHaveBeenCalledWith('test-token');
        });

        it('should reset sync button state after completion', async () => {
            const btn = document.getElementById('syncBtn');
            window.apiClient.triggerSync.mockResolvedValue({ ok: false, status: 500, body: null });
            window.alert = vi.fn();

            await userPanes.triggerSync();

            expect(btn.classList.contains('syncing')).toBe(false);
            expect(btn.disabled).toBe(false);
        });

        it('should show cooldown message on 429', async () => {
            window.apiClient.triggerSync.mockResolvedValue({
                ok: false,
                status: 429,
                body: { status: 'cooldown', message: 'Sync rate limited.' },
            });
            window.alert = vi.fn();

            await userPanes.triggerSync();

            expect(window.alert).toHaveBeenCalledWith('Sync rate limited.');
        });
    });

    describe('_buildReleaseTable', () => {
        it('should render a table with correct columns', () => {
            const releases = [
                { artist: 'Radiohead', title: 'OK Computer', year: 1997, genres: ['Rock'] },
            ];

            const wrap = userPanes._buildReleaseTable(
                'My Collection', 'album', releases, 1, 0, 'testRefreshBtn',
                vi.fn(), false
            );

            expect(wrap.querySelector('table')).not.toBeNull();
            expect(wrap.querySelector('h5').textContent).toBe('My Collection');
        });

        it('should show showing count', () => {
            const releases = [
                { artist: 'Test', title: 'Test Album', year: 2000 },
            ];

            const wrap = userPanes._buildReleaseTable(
                'My Collection', 'album', releases, 1, 0, 'testRefreshBtn',
                vi.fn(), false
            );

            expect(wrap.querySelector('.title-count').textContent).toContain('Showing 1');
        });

        it('should render pagination when total > pageSize', () => {
            const releases = Array.from({ length: 50 }, (_, i) => ({
                artist: `Artist ${i}`, title: `Album ${i}`, year: 2000,
            }));

            const wrap = userPanes._buildReleaseTable(
                'My Collection', 'album', releases, 100, 0, 'testRefreshBtn',
                vi.fn(), true
            );

            expect(wrap.querySelector('.pane-pagination')).not.toBeNull();
        });
    });

    describe('loadCollectionStats', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            await userPanes.loadCollectionStats();
            expect(window.apiClient.getUserCollectionStats).not.toHaveBeenCalled();
        });

        it('should call getUserCollectionStats with token', async () => {
            window.apiClient.getUserCollectionStats.mockResolvedValue({
                total_releases: 100, unique_artists: 50, unique_labels: 20, average_rating: 3.5,
            });
            await userPanes.loadCollectionStats();
            expect(window.apiClient.getUserCollectionStats).toHaveBeenCalledWith('test-token');
        });

        it('should render stats when data returned', async () => {
            window.apiClient.getUserCollectionStats.mockResolvedValue({
                total_releases: 100, unique_artists: 50, unique_labels: 20, average_rating: 3.5,
            });
            await userPanes.loadCollectionStats();
            const el = document.getElementById('collectionStats');
            expect(el.querySelectorAll('.stat-card').length).toBe(4);
        });
    });

    describe('startDiscogsOAuth', () => {
        beforeEach(() => {
            globalThis.Alpine = { store: vi.fn().mockReturnValue({ discogsOpen: false }) };
        });

        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            await userPanes.startDiscogsOAuth();
            expect(window.apiClient.authorizeDiscogs).not.toHaveBeenCalled();
        });

        it('should call authorizeDiscogs with token', async () => {
            window.apiClient.authorizeDiscogs.mockResolvedValue({
                authorize_url: 'https://discogs.com/oauth', state: 'abc',
            });
            const origOpen = window.open;
            window.open = vi.fn();
            await userPanes.startDiscogsOAuth();
            expect(window.apiClient.authorizeDiscogs).toHaveBeenCalledWith('test-token');
            window.open = origOpen;
        });

        it('should store OAuth state', async () => {
            window.apiClient.authorizeDiscogs.mockResolvedValue({
                authorize_url: 'https://discogs.com/oauth', state: 'test-state',
            });
            window.open = vi.fn();
            await userPanes.startDiscogsOAuth();
            expect(userPanes._discogsOAuthState).toBe('test-state');
        });

        it('should alert when API returns null', async () => {
            window.apiClient.authorizeDiscogs.mockResolvedValue(null);
            window.alert = vi.fn();
            await userPanes.startDiscogsOAuth();
            expect(window.alert).toHaveBeenCalled();
            expect(userPanes._discogsOAuthState).toBeNull();
        });
    });

    describe('submitDiscogsVerifier', () => {
        beforeEach(() => {
            globalThis.Alpine = { store: vi.fn().mockReturnValue({ discogsOpen: false }) };
        });

        it('should show error when verifier is empty', async () => {
            const input = document.getElementById('discogsVerifierInput');
            input.value = '';
            await userPanes.submitDiscogsVerifier();
            const errorEl = document.getElementById('discogsVerifierError');
            expect(errorEl.textContent).toContain('Please enter');
        });

        it('should show error when no OAuth state', async () => {
            const input = document.getElementById('discogsVerifierInput');
            input.value = 'verifier-code';
            userPanes._discogsOAuthState = null;
            await userPanes.submitDiscogsVerifier();
            const errorEl = document.getElementById('discogsVerifierError');
            expect(errorEl.textContent).toContain('Session expired');
        });

        it('should call verifyDiscogs and update status on success', async () => {
            const input = document.getElementById('discogsVerifierInput');
            input.value = 'verifier-code';
            userPanes._discogsOAuthState = 'test-state';
            window.apiClient.verifyDiscogs.mockResolvedValue({ connected: true });
            window.apiClient.getDiscogsStatus.mockResolvedValue({ connected: true });
            await userPanes.submitDiscogsVerifier();
            expect(window.apiClient.verifyDiscogs).toHaveBeenCalledWith('test-token', 'test-state', 'verifier-code');
            expect(window.authManager.setDiscogsStatus).toHaveBeenCalledWith({ connected: true });
        });

        it('should show error on verification failure', async () => {
            const input = document.getElementById('discogsVerifierInput');
            input.value = 'bad-code';
            userPanes._discogsOAuthState = 'test-state';
            window.apiClient.verifyDiscogs.mockResolvedValue({ connected: false });
            await userPanes.submitDiscogsVerifier();
            const errorEl = document.getElementById('discogsVerifierError');
            expect(errorEl.textContent).toContain('Verification failed');
        });
    });

    describe('disconnectDiscogs', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            await userPanes.disconnectDiscogs();
            expect(window.apiClient.revokeDiscogs).not.toHaveBeenCalled();
        });

        it('should call revokeDiscogs when confirmed', async () => {
            window.confirm = vi.fn().mockReturnValue(true);
            await userPanes.disconnectDiscogs();
            expect(window.apiClient.revokeDiscogs).toHaveBeenCalledWith('test-token');
            expect(window.authManager.setDiscogsStatus).toHaveBeenCalledWith({ connected: false });
        });

        it('should not call revokeDiscogs when cancelled', async () => {
            window.confirm = vi.fn().mockReturnValue(false);
            await userPanes.disconnectDiscogs();
            expect(window.apiClient.revokeDiscogs).not.toHaveBeenCalled();
        });

        it('should clear taste cache after disconnect', async () => {
            window.confirm = vi.fn().mockReturnValue(true);
            userPanes._tasteCache = { some: 'data' };
            await userPanes.disconnectDiscogs();
            expect(userPanes._tasteCache).toBeNull();
        });
    });

    describe('loadGapAnalysis', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            await userPanes.loadGapAnalysis('artist', '123');
            expect(window.apiClient.getCollectionGaps).not.toHaveBeenCalled();
        });

        it('should call getCollectionGaps with params', async () => {
            window.apiClient.getCollectionGaps.mockResolvedValue({
                entity: { name: 'Test', type: 'artist' },
                owned_count: 5, total_count: 10, missing: [],
                pagination: { total: 5, offset: 0, limit: 50 },
            });
            await userPanes.loadGapAnalysis('artist', '123');
            expect(window.apiClient.getCollectionGaps).toHaveBeenCalled();
        });

        it('should render empty state when API returns null', async () => {
            window.apiClient.getCollectionGaps.mockResolvedValue(null);
            await userPanes.loadGapAnalysis('artist', '123');
            const body = document.getElementById('gapsBody');
            expect(body.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should reset offset when reset=true', async () => {
            userPanes._gapOffset = 50;
            window.apiClient.getCollectionGaps.mockResolvedValue(null);
            await userPanes.loadGapAnalysis('artist', '123', true);
            expect(userPanes._gapOffset).toBe(0);
        });

        it('should show gaps pane', async () => {
            window.apiClient.getCollectionGaps.mockResolvedValue(null);
            await userPanes.loadGapAnalysis('artist', '123');
            const gapsPane = document.getElementById('gapsPane');
            expect(gapsPane.classList.contains('active')).toBe(true);
        });
    });

    describe('_downloadTasteCard', () => {
        it('should return early when no token', async () => {
            window.authManager.getToken.mockReturnValue(null);
            const btn = document.createElement('button');
            await userPanes._downloadTasteCard(btn);
            expect(window.apiClient.getTasteCard).not.toHaveBeenCalled();
        });

        it('should show downloading state on button', async () => {
            window.apiClient.getTasteCard.mockResolvedValue(null);
            const btn = document.createElement('button');
            btn.textContent = 'Download Taste Card';

            // Use a flag to check state during execution
            let textDuringCall = null;
            window.apiClient.getTasteCard.mockImplementation(async () => {
                textDuringCall = btn.textContent;
                return null;
            });

            await userPanes._downloadTasteCard(btn);
            expect(textDuringCall).toBe('Downloading...');
        });

        it('should show failure message when blob is null', async () => {
            vi.useFakeTimers();
            window.apiClient.getTasteCard.mockResolvedValue(null);
            const btn = document.createElement('button');
            await userPanes._downloadTasteCard(btn);
            expect(btn.textContent).toBe('Download failed');
            vi.useRealTimers();
        });

        it('should trigger download when blob is returned', async () => {
            const blob = new Blob(['<svg></svg>'], { type: 'image/svg+xml' });
            window.apiClient.getTasteCard.mockResolvedValue(blob);
            globalThis.URL.createObjectURL = vi.fn().mockReturnValue('blob:test');
            globalThis.URL.revokeObjectURL = vi.fn();

            const btn = document.createElement('button');
            const clickSpy = vi.fn();
            const origCreateElement = document.createElement.bind(document);
            vi.spyOn(document, 'createElement').mockImplementation((tag) => {
                const el = origCreateElement(tag);
                if (tag === 'a') el.click = clickSpy;
                return el;
            });

            await userPanes._downloadTasteCard(btn);
            expect(clickSpy).toHaveBeenCalled();
            document.createElement.mockRestore();
        });
    });

    describe('_renderCollectionList', () => {
        it('should return early when container is null', () => {
            expect(() => userPanes._renderCollectionList(null, {})).not.toThrow();
        });

        it('should render empty state when releases array is empty', () => {
            const container = document.createElement('div');
            userPanes._renderCollectionList(container, { releases: [], total: 0, has_more: false });

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should render table when data has releases', () => {
            const container = document.createElement('div');
            userPanes._renderCollectionList(container, {
                releases: [{ title: 'OK Computer', artist: 'Radiohead', year: 1997, genres: ['Rock'] }],
                total: 1,
                has_more: false,
            });

            expect(container.querySelector('table')).not.toBeNull();
        });

        it('should render empty state when releases is undefined', () => {
            const container = document.createElement('div');
            userPanes._renderCollectionList(container, { total: 0, has_more: false });

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
        });
    });

    describe('_renderWantlistList', () => {
        it('should return early when container is null', () => {
            expect(() => userPanes._renderWantlistList(null, {})).not.toThrow();
        });

        it('should render empty state when releases array is empty', () => {
            const container = document.createElement('div');
            userPanes._renderWantlistList(container, { releases: [], total: 0, has_more: false });

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should render table when data has releases', () => {
            const container = document.createElement('div');
            userPanes._renderWantlistList(container, {
                releases: [{ title: 'Loveless', artist: 'My Bloody Valentine', year: 1991 }],
                total: 1,
                has_more: false,
            });

            expect(container.querySelector('table')).not.toBeNull();
        });
    });

    describe('_renderTasteStrip', () => {
        beforeEach(() => {
            setupUserPanesDOM();
        });

        it('should render all three columns', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.75 },
                peak_decade: 1990,
                drift: [{ top_genre: 'Rock' }, { top_genre: 'Electronic' }],
                heatmap: [{ genre: 'Rock', decade: 1990, count: 10 }],
                blind_spots: [{ genre: 'Jazz', artist_overlap: 5 }],
            });

            expect(strip.querySelector('.taste-strip')).not.toBeNull();
            const cols = strip.querySelectorAll('.taste-col');
            expect(cols).toHaveLength(3);
        });

        it('should render obscurity score', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.42 },
                peak_decade: null,
                drift: [],
                heatmap: [],
                blind_spots: [],
            });

            expect(strip.textContent).toContain('0.42');
        });

        it('should render dash for null obscurity', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: {},
                peak_decade: null,
                drift: [],
                heatmap: [],
                blind_spots: [],
            });

            expect(strip.textContent).toContain('\u2014');
        });

        it('should render peak decade', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.5 },
                peak_decade: 1970,
                drift: [],
                heatmap: [],
                blind_spots: [],
            });

            expect(strip.textContent).toContain('1970s');
        });

        it('should render empty heatmap placeholder', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.5 },
                peak_decade: 1990,
                drift: [],
                heatmap: [],
                blind_spots: [],
            });

            expect(strip.querySelector('.taste-empty')).not.toBeNull();
        });

        it('should render heatmap grid when data provided', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.5 },
                peak_decade: 1990,
                drift: [],
                heatmap: [
                    { genre: 'Rock', decade: 1990, count: 10 },
                    { genre: 'Rock', decade: 2000, count: 5 },
                ],
                blind_spots: [],
            });

            expect(strip.querySelector('.taste-heatmap-grid')).not.toBeNull();
        });

        it('should render blind spots', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.5 },
                peak_decade: 1990,
                drift: [],
                heatmap: [],
                blind_spots: [
                    { genre: 'Jazz', artist_overlap: 5 },
                    { genre: 'Classical', artist_overlap: 3 },
                ],
            });

            const items = strip.querySelectorAll('.taste-blindspot-item');
            expect(items).toHaveLength(2);
            expect(items[0].querySelector('.taste-blindspot-name').textContent).toBe('Jazz');
            expect(items[0].querySelector('.taste-blindspot-count').textContent).toBe('5 artists');
        });

        it('should render no blind spots message', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.5 },
                peak_decade: 1990,
                drift: [],
                heatmap: [],
                blind_spots: [],
            });

            expect(strip.textContent).toContain('No blind spots found');
        });

        it('should render download button', () => {
            const strip = document.getElementById('tasteStrip');
            userPanes._renderTasteStrip({
                obscurity: { score: 0.5 },
                peak_decade: 1990,
                drift: [],
                heatmap: [],
                blind_spots: [],
            });

            expect(strip.querySelector('.taste-download-btn')).not.toBeNull();
        });

        it('should return early when strip element is missing', () => {
            document.getElementById('tasteStrip').remove();
            expect(() => userPanes._renderTasteStrip({})).not.toThrow();
        });
    });

    describe('_renderGaps', () => {
        it('should render summary header with entity info', () => {
            const container = document.createElement('div');
            userPanes._renderGaps(container, {
                entity: { name: 'Radiohead', type: 'artist' },
                summary: { total: 50, owned: 30, missing: 20 },
                results: [
                    { title: 'Pablo Honey', artist: 'Radiohead', year: 1993, genres: ['Rock'] },
                ],
                pagination: { total: 20, offset: 0, limit: 50, has_more: false },
            });

            expect(container.querySelector('.gap-summary')).not.toBeNull();
            expect(container.querySelector('.gap-entity-title').textContent).toContain('Radiohead');
        });

        it('should render stat cards', () => {
            const container = document.createElement('div');
            userPanes._renderGaps(container, {
                entity: { name: 'Radiohead', type: 'artist' },
                summary: { total: 50, owned: 30, missing: 20 },
                results: [{ title: 'Pablo Honey', artist: 'Radiohead', year: 1993 }],
                pagination: { total: 1, offset: 0, limit: 50 },
            });

            const cards = container.querySelectorAll('.stat-card');
            expect(cards).toHaveLength(3);
        });

        it('should render empty state when no results', () => {
            const container = document.createElement('div');
            userPanes._renderGaps(container, {
                entity: { name: 'Radiohead', type: 'artist' },
                summary: { total: 10, owned: 10, missing: 0 },
                results: [],
                pagination: { total: 0, offset: 0, limit: 50 },
            });

            expect(container.querySelector('.user-pane-empty')).not.toBeNull();
        });

        it('should return early when container is null', () => {
            expect(() => userPanes._renderGaps(null, {})).not.toThrow();
        });

        it('should render label entity icon', () => {
            const container = document.createElement('div');
            userPanes._renderGaps(container, {
                entity: { name: 'Warp', type: 'label' },
                summary: { total: 100, owned: 50, missing: 50 },
                results: [{ title: 'Test', artist: 'Test', year: 2000 }],
                pagination: { total: 1, offset: 0, limit: 50 },
            });

            const icon = container.querySelector('.gap-entity-title .material-symbols-outlined');
            expect(icon.textContent).toBe('sell');
        });
    });

    describe('_buildGapTable', () => {
        it('should render a table with 7 columns', () => {
            const releases = [
                { title: 'Pablo Honey', artist: 'Radiohead', label: 'Parlophone', year: 1993, formats: ['CD'], genres: ['Rock'], on_wantlist: false },
            ];

            const wrap = userPanes._buildGapTable(releases, 1, 0, vi.fn(), false);

            expect(wrap.querySelector('table')).not.toBeNull();
            const headers = wrap.querySelectorAll('th');
            expect(headers).toHaveLength(7);
            expect(headers[0].textContent).toBe('Title');
            expect(headers[6].textContent).toBe('Status');
        });

        it('should render wantlist badge when on_wantlist is true', () => {
            const releases = [
                { title: 'Pablo Honey', artist: 'Radiohead', year: 1993, on_wantlist: true },
            ];

            const wrap = userPanes._buildGapTable(releases, 1, 0, vi.fn(), false);

            expect(wrap.querySelector('.in-wantlist')).not.toBeNull();
            expect(wrap.textContent).toContain('Wanted');
        });

        it('should render format badges', () => {
            const releases = [
                { title: 'Test', artist: 'Test', year: 2000, formats: ['Vinyl', 'CD'] },
            ];

            const wrap = userPanes._buildGapTable(releases, 1, 0, vi.fn(), false);
            const badges = wrap.querySelectorAll('.genre-badge');
            expect(badges.length).toBeGreaterThanOrEqual(2);
        });

        it('should show showing count', () => {
            const releases = [{ title: 'Test', artist: 'Test', year: 2000 }];

            const wrap = userPanes._buildGapTable(releases, 5, 0, vi.fn(), false);
            expect(wrap.querySelector('.title-count').textContent).toContain('1');
            expect(wrap.querySelector('.title-count').textContent).toContain('5');
        });

        it('should render pagination when total > pageSize', () => {
            const releases = Array.from({ length: 50 }, (_, i) => ({
                title: `Album ${i}`, artist: 'Test', year: 2000,
            }));

            const wrap = userPanes._buildGapTable(releases, 100, 0, vi.fn(), true);
            expect(wrap.querySelector('.pane-pagination')).not.toBeNull();
        });

        it('should not render pagination when total <= pageSize', () => {
            const releases = [{ title: 'Test', artist: 'Test', year: 2000 }];

            const wrap = userPanes._buildGapTable(releases, 1, 0, vi.fn(), false);
            expect(wrap.querySelector('.pane-pagination')).toBeNull();
        });
    });
});
