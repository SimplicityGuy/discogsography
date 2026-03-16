import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Set up DOM with all elements needed for initPathFinder.
 */
function setupPathFinderDOM() {
    document.body.textContent = '';
    document.documentElement.className = '';

    // Minimal timeline + app elements needed for script load
    const appIds = [
        'timelineScrubber', 'timelineSlider', 'timelineYearLabel', 'timelinePlayBtn',
        'timelinePlayIcon', 'timelineSpeedToggle', 'timelineSpeedLabel', 'timelineResetBtn',
        'timelineExploreControls', 'timelineCompareControls', 'timelineCompareBtn',
        'timelineExitCompareBtn', 'compareSliderA', 'compareSliderB',
        'compareYearALabel', 'compareYearBLabel', 'compareLegend', 'compareLegendClose',
        'compareSameYearHint',
        'searchInput', 'searchTypeBtn', 'autocompleteDropdown',
        'graphContainer', 'graphSvg', 'graphPlaceholder', 'graphLoading',
        'trendsChart', 'trendsPlaceholder', 'trendsLoading',
        'infoPanel', 'infoPanelBody', 'infoPanelTitle', 'closePanelBtn',
        'compareBtn', 'clearCompareBtn', 'compareBadge', 'compareInfo', 'compareHint',
        'shareBtn', 'shareToast', 'shareToastMsg',
        'authButtons', 'userDropdown', 'userEmailDisplay',
        'discogsStatusDisplay', 'connectDiscogsBtn', 'disconnectDiscogsBtn', 'syncBtn',
        'navCollection', 'navWantlist', 'navRecommendations', 'navGaps',
        'loginEmail', 'loginPassword', 'loginError', 'loginSubmitBtn',
        'registerEmail', 'registerPassword', 'registerError', 'registerSuccess', 'registerSubmitBtn',
        'logoutBtn', 'navLoginBtn', 'insightsGenreChips',
        'zoomInBtn', 'zoomOutBtn', 'zoomResetBtn', 'fullscreenBtn',
        'explorePane', 'trendsPane', 'searchPane', 'insightsPane',
        'collectionPane', 'wantlistPane', 'recommendationsPane', 'gapsPane',
        // Path finder elements
        'pathFromInput', 'pathToInput', 'pathFromTypeBtn', 'pathToTypeBtn',
        'pathFromDropdown', 'pathToDropdown', 'pathConnectBtn',
        'pathLoading', 'pathPlaceholder', 'pathResult', 'pathResultSummary',
        'pathChain', 'pathError',
    ];

    const inputIds = new Set([
        'searchInput', 'loginEmail', 'loginPassword', 'registerEmail', 'registerPassword',
        'timelineSlider', 'compareSliderA', 'compareSliderB',
        'pathFromInput', 'pathToInput',
    ]);

    appIds.forEach(id => {
        const tag = inputIds.has(id) ? 'input' : 'div';
        const el = document.createElement(tag);
        el.id = id;
        if (['timelineSlider', 'compareSliderA', 'compareSliderB'].includes(id)) {
            el.type = 'range'; el.min = '1900'; el.max = '2025'; el.value = '2025';
        }
        if (['zoomInBtn', 'zoomOutBtn', 'zoomResetBtn', 'fullscreenBtn'].includes(id)) {
            const icon = document.createElement('span');
            icon.className = 'material-symbols-outlined';
            el.appendChild(icon);
        }
        if (['explorePane', 'trendsPane', 'searchPane', 'insightsPane',
             'collectionPane', 'wantlistPane', 'recommendationsPane', 'gapsPane'].includes(id)) {
            el.className = 'pane';
        }
        document.body.appendChild(el);
    });

    // Type selector links for path finder
    ['artist', 'label', 'genre'].forEach(type => {
        const fromLink = document.createElement('a');
        fromLink.dataset.pathFromType = type;
        document.body.appendChild(fromLink);
        const toLink = document.createElement('a');
        toLink.dataset.pathToType = type;
        document.body.appendChild(toLink);
    });
}

describe('initPathFinder', () => {
    beforeAll(() => {
        delete globalThis.window;
        globalThis.window = globalThis;

        setupPathFinderDOM();

        // D3 mock
        const sel = {
            attr: vi.fn().mockReturnThis(), style: vi.fn().mockReturnThis(),
            text: vi.fn().mockReturnThis(), call: vi.fn().mockReturnThis(),
            append: vi.fn().mockReturnThis(), select: vi.fn().mockReturnThis(),
            selectAll: vi.fn().mockReturnThis(), on: vi.fn().mockReturnThis(),
            classed: vi.fn().mockReturnThis(), remove: vi.fn().mockReturnThis(),
            each: vi.fn().mockReturnThis(), data: vi.fn().mockReturnThis(),
            join: vi.fn().mockReturnThis(), transition: vi.fn().mockReturnThis(),
            duration: vi.fn().mockReturnThis(),
        };
        const zoom = { scaleExtent: vi.fn().mockReturnThis(), on: vi.fn().mockReturnThis(), transform: vi.fn(), scaleBy: vi.fn() };
        const sim = { force: vi.fn().mockReturnThis(), on: vi.fn().mockReturnThis(), stop: vi.fn(), alpha: vi.fn().mockReturnThis(), alphaTarget: vi.fn().mockReturnThis(), restart: vi.fn() };
        globalThis.d3 = {
            select: vi.fn().mockReturnValue(sel), zoom: vi.fn().mockReturnValue(zoom), zoomIdentity: {},
            forceSimulation: vi.fn().mockReturnValue(sim),
            forceLink: vi.fn().mockReturnValue({ id: vi.fn().mockReturnThis(), distance: vi.fn().mockReturnThis() }),
            forceManyBody: vi.fn().mockReturnValue({ strength: vi.fn().mockReturnThis() }),
            forceCenter: vi.fn(), forceCollide: vi.fn().mockReturnValue({ radius: vi.fn().mockReturnThis() }),
            drag: vi.fn().mockReturnValue({ on: vi.fn().mockReturnThis() }),
        };
        globalThis.Plotly = { newPlot: vi.fn(), purge: vi.fn(), addTraces: vi.fn(), deleteTraces: vi.fn() };
        globalThis.Alpine = { store: vi.fn().mockReturnValue({ authOpen: false, discogsOpen: false }) };

        window.apiClient = {
            autocomplete: vi.fn().mockResolvedValue([]),
            explore: vi.fn().mockResolvedValue(null),
            expand: vi.fn().mockResolvedValue({ children: [], total: 0, limit: 30, has_more: false }),
            getNodeDetails: vi.fn().mockResolvedValue(null),
            getTrends: vi.fn().mockResolvedValue(null),
            login: vi.fn().mockResolvedValue(null), register: vi.fn().mockResolvedValue(false),
            logout: vi.fn().mockResolvedValue(null), getMe: vi.fn().mockResolvedValue(null),
            getDiscogsStatus: vi.fn().mockResolvedValue(null),
            saveSnapshot: vi.fn().mockResolvedValue(null), restoreSnapshot: vi.fn().mockResolvedValue(null),
            findPath: vi.fn().mockResolvedValue(null),
            getUserStatus: vi.fn().mockResolvedValue(null),
            getYearRange: vi.fn().mockResolvedValue({ min_year: 1950, max_year: 2023 }),
            getGenreEmergence: vi.fn().mockResolvedValue({ genres: [], styles: [] }),
        };
        window.authManager = {
            init: vi.fn().mockResolvedValue(false), isLoggedIn: vi.fn().mockReturnValue(false),
            getToken: vi.fn().mockReturnValue(null), getUser: vi.fn().mockReturnValue(null),
            getDiscogsStatus: vi.fn().mockReturnValue(null), setToken: vi.fn(), setUser: vi.fn(),
            setDiscogsStatus: vi.fn(), clear: vi.fn(), notify: vi.fn(), onChange: vi.fn(),
        };
        window.insightsPanel = { load: vi.fn().mockResolvedValue(null), startPolling: vi.fn(), stopPolling: vi.fn() };
        window.searchPane = { focus: vi.fn() };
        window.UserPanes = class {
            loadCollection = vi.fn(); loadWantlist = vi.fn(); loadRecommendations = vi.fn();
            loadCollectionStats = vi.fn(); loadTasteFingerprint = vi.fn();
            startDiscogsOAuth = vi.fn(); disconnectDiscogs = vi.fn(); submitDiscogsVerifier = vi.fn();
            triggerSync = vi.fn(); clearTasteCache = vi.fn(); loadGapAnalysis = vi.fn();
        };

        // Load all scripts in dependency order — this will initialize initPathFinder
        loadScriptDirect('autocomplete.js');
        loadScriptDirect('graph.js');
        loadScriptDirect('trends.js');
        loadScriptDirect('user-panes.js');
        loadScriptDirect('app.js');
    });

    beforeEach(() => {
        window.apiClient.findPath.mockReset().mockResolvedValue(null);
        window.apiClient.autocomplete.mockReset().mockResolvedValue([]);
        document.getElementById('pathFromInput').value = '';
        document.getElementById('pathToInput').value = '';
        document.getElementById('pathError').textContent = '';
        document.getElementById('pathError').classList.add('hidden');
        document.getElementById('pathResult').classList.add('hidden');
        document.getElementById('pathResultSummary').textContent = '';
        document.getElementById('pathChain').textContent = '';
        document.getElementById('pathPlaceholder').classList.remove('hidden');
        document.getElementById('pathLoading').classList.add('hidden');
        document.getElementById('pathConnectBtn').disabled = false;
    });

    it('should show error when inputs are empty', async () => {
        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        const errorEl = document.getElementById('pathError');
        expect(errorEl.textContent).toContain('Please enter both');
        expect(errorEl.classList.contains('hidden')).toBe(false);
    });

    it('should call findPath and show error on null response', async () => {
        document.getElementById('pathFromInput').value = 'Radiohead';
        document.getElementById('pathToInput').value = 'Björk';

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        expect(document.getElementById('pathError').textContent).toContain('error occurred');
    });

    it('should show notFound error', async () => {
        document.getElementById('pathFromInput').value = 'Unknown';
        document.getElementById('pathToInput').value = 'Nobody';
        window.apiClient.findPath.mockResolvedValue({ notFound: true, error: 'Entity not found' });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        expect(document.getElementById('pathError').textContent).toContain('Entity not found');
    });

    it('should show notFound with default message when error is missing', async () => {
        document.getElementById('pathFromInput').value = 'X';
        document.getElementById('pathToInput').value = 'Y';
        window.apiClient.findPath.mockResolvedValue({ notFound: true });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        expect(document.getElementById('pathError').textContent).toContain('not found');
    });

    it('should show no path found message', async () => {
        document.getElementById('pathFromInput').value = 'A';
        document.getElementById('pathToInput').value = 'B';
        window.apiClient.findPath.mockResolvedValue({ found: false });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        expect(document.getElementById('pathResultSummary').textContent).toContain('No path found');
        expect(document.getElementById('pathResult').classList.contains('hidden')).toBe(false);
    });

    it('should render path with nodes and edges', async () => {
        document.getElementById('pathFromInput').value = 'Radiohead';
        document.getElementById('pathToInput').value = 'Björk';
        window.apiClient.findPath.mockResolvedValue({
            found: true, length: 2,
            path: [
                { name: 'Radiohead', type: 'artist' },
                { name: 'OK Computer', type: 'release', rel: 'RELEASED' },
                { name: 'Björk', type: 'artist', rel: 'COLLABORATED_WITH' },
            ],
        });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        expect(document.getElementById('pathResultSummary').textContent).toContain('2 hops');
        const chainEl = document.getElementById('pathChain');
        expect(chainEl.querySelectorAll('.path-node')).toHaveLength(3);
        expect(chainEl.querySelectorAll('.path-edge')).toHaveLength(2);
    });

    it('should use singular "hop" for length 1', async () => {
        document.getElementById('pathFromInput').value = 'A';
        document.getElementById('pathToInput').value = 'B';
        window.apiClient.findPath.mockResolvedValue({
            found: true, length: 1,
            path: [{ name: 'A', type: 'artist' }, { name: 'B', type: 'artist', rel: 'MEMBER_OF' }],
        });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        const text = document.getElementById('pathResultSummary').textContent;
        expect(text).toContain('1 hop');
        expect(text).not.toContain('hops');
    });

    it('should change from type on selector click', () => {
        document.querySelector('[data-path-from-type="label"]').click();
        expect(document.getElementById('pathFromTypeBtn').textContent).toBe('Label');
    });

    it('should change to type on selector click', () => {
        document.querySelector('[data-path-to-type="genre"]').click();
        expect(document.getElementById('pathToTypeBtn').textContent).toBe('Genre');
    });

    it('should trigger handleConnect on Enter', async () => {
        document.getElementById('pathFromInput').value = 'A';
        document.getElementById('pathToInput').value = 'B';

        document.getElementById('pathFromInput').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        await new Promise(r => setTimeout(r, 10));

        expect(window.apiClient.findPath).toHaveBeenCalled();
    });

    it('should re-enable connect button after request', async () => {
        document.getElementById('pathFromInput').value = 'A';
        document.getElementById('pathToInput').value = 'B';

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        expect(document.getElementById('pathConnectBtn').disabled).toBe(false);
    });

    it('should wire autocomplete and show dropdown', async () => {
        vi.useFakeTimers();
        const fromInput = document.getElementById('pathFromInput');
        fromInput.value = 'Rad';
        window.apiClient.autocomplete.mockResolvedValue([{ name: 'Radiohead' }]);

        fromInput.dispatchEvent(new Event('input'));
        vi.advanceTimersByTime(250);
        await vi.runAllTimersAsync();

        const dropdown = document.getElementById('pathFromDropdown');
        expect(dropdown.classList.contains('show')).toBe(true);
        expect(dropdown.querySelector('.autocomplete-item').textContent).toBe('Radiohead');
        vi.useRealTimers();
    });

    it('should not show dropdown for short queries', () => {
        vi.useFakeTimers();
        document.getElementById('pathFromInput').value = 'Ra';
        document.getElementById('pathFromInput').dispatchEvent(new Event('input'));
        vi.advanceTimersByTime(250);

        expect(document.getElementById('pathFromDropdown').classList.contains('show')).toBe(false);
        vi.useRealTimers();
    });

    it('should close dropdown on blur', () => {
        vi.useFakeTimers();
        const dropdown = document.getElementById('pathFromDropdown');
        dropdown.classList.add('show');

        document.getElementById('pathFromInput').dispatchEvent(new Event('blur'));
        vi.advanceTimersByTime(200);

        expect(dropdown.classList.contains('show')).toBe(false);
        vi.useRealTimers();
    });

    it('should select autocomplete item on mousedown', async () => {
        vi.useFakeTimers();
        const fromInput = document.getElementById('pathFromInput');
        fromInput.value = 'Rad';
        window.apiClient.autocomplete.mockResolvedValue([{ name: 'Radiohead' }]);

        fromInput.dispatchEvent(new Event('input'));
        vi.advanceTimersByTime(250);
        await vi.runAllTimersAsync();

        const item = document.getElementById('pathFromDropdown').querySelector('.autocomplete-item');
        item.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));

        expect(fromInput.value).toBe('Radiohead');
        expect(document.getElementById('pathFromDropdown').classList.contains('show')).toBe(false);
        vi.useRealTimers();
    });

    it('should not show autocomplete when results are empty', async () => {
        vi.useFakeTimers();
        const fromInput = document.getElementById('pathFromInput');
        fromInput.value = 'Zzz';
        window.apiClient.autocomplete.mockResolvedValue([]);

        fromInput.dispatchEvent(new Event('input'));
        vi.advanceTimersByTime(250);
        await vi.runAllTimersAsync();

        const dropdown = document.getElementById('pathFromDropdown');
        expect(dropdown.classList.contains('show')).toBe(false);
        vi.useRealTimers();
    });

    it('should render node cards with type and name', async () => {
        document.getElementById('pathFromInput').value = 'A';
        document.getElementById('pathToInput').value = 'B';
        window.apiClient.findPath.mockResolvedValue({
            found: true, length: 1,
            path: [
                { name: 'Radiohead', type: 'artist' },
                { name: 'OK Computer', type: 'release', rel: 'RELEASED' },
            ],
        });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        const nodes = document.getElementById('pathChain').querySelectorAll('.path-node');
        expect(nodes[0].querySelector('.path-node-type').textContent).toBe('artist');
        expect(nodes[0].querySelector('.path-node-name').textContent).toBe('Radiohead');
        expect(nodes[1].querySelector('.path-node-type').textContent).toBe('release');
    });

    it('should render edge labels', async () => {
        document.getElementById('pathFromInput').value = 'A';
        document.getElementById('pathToInput').value = 'B';
        window.apiClient.findPath.mockResolvedValue({
            found: true, length: 1,
            path: [
                { name: 'A', type: 'artist' },
                { name: 'B', type: 'release', rel: 'RELEASED_ON' },
            ],
        });

        document.getElementById('pathConnectBtn').click();
        await new Promise(r => setTimeout(r, 10));

        const edges = document.getElementById('pathChain').querySelectorAll('.path-edge');
        expect(edges[0].querySelector('.path-edge-label').textContent).toBe('RELEASED_ON');
    });
});
