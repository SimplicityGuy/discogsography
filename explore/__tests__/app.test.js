import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Create full DOM required for TimelineScrubber.
 */
function setupTimelineDOM() {
    document.body.textContent = '';
    document.documentElement.className = '';

    const ids = {
        timelineScrubber: 'div',
        timelineSlider: 'input',
        timelineYearLabel: 'span',
        timelinePlayBtn: 'button',
        timelinePlayIcon: 'span',
        timelineSpeedToggle: 'button',
        timelineSpeedLabel: 'span',
        timelineResetBtn: 'button',
        timelineExploreControls: 'div',
        timelineCompareControls: 'div',
        timelineCompareBtn: 'button',
        timelineExitCompareBtn: 'button',
        compareSliderA: 'input',
        compareSliderB: 'input',
        compareYearALabel: 'span',
        compareYearBLabel: 'span',
        compareLegend: 'div',
        compareLegendClose: 'button',
        compareSameYearHint: 'div',
    };

    for (const [id, tag] of Object.entries(ids)) {
        const el = document.createElement(tag);
        el.id = id;
        if (tag === 'input') {
            el.type = 'range';
            el.min = '1900';
            el.max = '2025';
            el.value = '2025';
        }
        document.body.appendChild(el);
    }
}

/**
 * Minimal DOM for ExploreApp (only what's needed for targeted tests).
 */
function setupAppDOM() {
    document.body.textContent = '';
    document.documentElement.className = '';

    const allIds = [
        // Timeline
        'timelineScrubber', 'timelineSlider', 'timelineYearLabel', 'timelinePlayBtn',
        'timelinePlayIcon', 'timelineSpeedToggle', 'timelineSpeedLabel', 'timelineResetBtn',
        'timelineExploreControls', 'timelineCompareControls', 'timelineCompareBtn',
        'timelineExitCompareBtn', 'timelineCloseBtn', 'compareSliderA', 'compareSliderB',
        'compareYearALabel', 'compareYearBLabel', 'compareLegend', 'compareLegendClose',
        'compareSameYearHint',
        // App
        'searchInput', 'searchTypeBtn', 'searchBtn',
        'autocompleteDropdown', 'timelineToggleBtn',
        'graphContainer', 'graphSvg', 'graphPlaceholder', 'graphLoading',
        'trendsChart', 'trendsPlaceholder', 'trendsLoading',
        'infoPanel', 'infoPanelBody', 'infoPanelTitle',
        'closePanelBtn',
        'compareBtn', 'clearCompareBtn', 'compareBadge', 'compareInfo', 'compareHint',
        'shareBtn', 'shareToast', 'shareToastMsg',
        'authButtons', 'userDropdown', 'userEmailDisplay',
        'discogsStatusDisplay', 'connectDiscogsBtn', 'disconnectDiscogsBtn', 'syncBtn',
        'navSecondary', 'navCollection', 'navWantlist', 'navRecommendations', 'navGaps',
        'loginEmail', 'loginPassword', 'loginError', 'loginSubmitBtn',
        'registerEmail', 'registerPassword', 'registerError', 'registerSuccess', 'registerSubmitBtn',
        'logoutBtn', 'navLoginBtn',
        'insightsGenreChips',
        // Note: pathFromInput is intentionally omitted so initPathFinder() returns early
        'zoomInBtn', 'zoomOutBtn', 'zoomResetBtn', 'fullscreenBtn',
        // Panes
        'explorePane', 'trendsPane', 'searchPane', 'insightsPane',
        'collectionPane', 'wantlistPane', 'recommendationsPane', 'gapsPane',
    ];

    const inputIds = new Set([
        'searchInput', 'loginEmail', 'loginPassword',
        'registerEmail', 'registerPassword',
        'timelineSlider', 'compareSliderA', 'compareSliderB',
    ]);

    allIds.forEach(id => {
        const tag = inputIds.has(id) ? 'input' : 'div';
        const el = document.createElement(tag);
        el.id = id;
        if (['zoomInBtn', 'zoomOutBtn', 'zoomResetBtn', 'fullscreenBtn'].includes(id)) {
            el.className = 'button';
            const icon = document.createElement('span');
            icon.className = 'material-symbols-outlined';
            el.appendChild(icon);
        }
        if (['timelineSlider', 'compareSliderA', 'compareSliderB'].includes(id)) {
            el.type = 'range';
            el.min = '1900';
            el.max = '2025';
            el.value = '2025';
        }
        if (['explorePane', 'trendsPane', 'searchPane', 'insightsPane',
             'collectionPane', 'wantlistPane', 'recommendationsPane', 'gapsPane'].includes(id)) {
            el.className = 'pane';
        }
        document.body.appendChild(el);
    });
}

/**
 * Provide D3 mock.
 */
function createD3Mock() {
    const sel = {
        attr: vi.fn().mockReturnThis(),
        style: vi.fn().mockReturnThis(),
        text: vi.fn().mockReturnThis(),
        call: vi.fn().mockReturnThis(),
        append: vi.fn().mockReturnThis(),
        select: vi.fn().mockReturnThis(),
        selectAll: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        classed: vi.fn().mockReturnThis(),
        remove: vi.fn().mockReturnThis(),
        each: vi.fn().mockReturnThis(),
        data: vi.fn().mockReturnThis(),
        join: vi.fn().mockReturnThis(),
        transition: vi.fn().mockReturnThis(),
        duration: vi.fn().mockReturnThis(),
    };
    const zoom = {
        scaleExtent: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        transform: vi.fn(),
        scaleBy: vi.fn(),
    };
    const sim = {
        force: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        stop: vi.fn(),
        alpha: vi.fn().mockReturnThis(),
        alphaTarget: vi.fn().mockReturnThis(),
        restart: vi.fn(),
    };
    return {
        select: vi.fn().mockReturnValue(sel),
        zoom: vi.fn().mockReturnValue(zoom),
        zoomIdentity: {},
        forceSimulation: vi.fn().mockReturnValue(sim),
        forceLink: vi.fn().mockReturnValue({ id: vi.fn().mockReturnThis(), distance: vi.fn().mockReturnThis() }),
        forceManyBody: vi.fn().mockReturnValue({ strength: vi.fn().mockReturnThis() }),
        forceCenter: vi.fn(),
        forceCollide: vi.fn().mockReturnValue({ radius: vi.fn().mockReturnThis() }),
        drag: vi.fn().mockReturnValue({ on: vi.fn().mockReturnThis() }),
    };
}

function setupGlobalMocks() {
    globalThis.Plotly = { newPlot: vi.fn(), purge: vi.fn(), addTraces: vi.fn(), deleteTraces: vi.fn() };
    globalThis.Alpine = { store: vi.fn().mockReturnValue({ authOpen: false, discogsOpen: false }) };
    globalThis.d3 = createD3Mock();

    window.apiClient = {
        autocomplete: vi.fn().mockResolvedValue([]),
        explore: vi.fn().mockResolvedValue(null),
        expand: vi.fn().mockResolvedValue({ children: [], total: 0, limit: 30, has_more: false }),
        getNodeDetails: vi.fn().mockResolvedValue(null),
        getTrends: vi.fn().mockResolvedValue(null),
        login: vi.fn().mockResolvedValue(null),
        register: vi.fn().mockResolvedValue(false),
        logout: vi.fn().mockResolvedValue(null),
        getMe: vi.fn().mockResolvedValue(null),
        getDiscogsStatus: vi.fn().mockResolvedValue(null),
        saveSnapshot: vi.fn().mockResolvedValue(null),
        restoreSnapshot: vi.fn().mockResolvedValue(null),
        findPath: vi.fn().mockResolvedValue(null),
        getUserStatus: vi.fn().mockResolvedValue(null),
        getYearRange: vi.fn().mockResolvedValue({ min_year: 1950, max_year: 2023 }),
        getGenreEmergence: vi.fn().mockResolvedValue({ genres: [], styles: [] }),
    };

    window.authManager = {
        init: vi.fn().mockResolvedValue(false),
        isLoggedIn: vi.fn().mockReturnValue(false),
        getToken: vi.fn().mockReturnValue(null),
        getUser: vi.fn().mockReturnValue(null),
        getDiscogsStatus: vi.fn().mockReturnValue(null),
        setToken: vi.fn(),
        setUser: vi.fn(),
        setDiscogsStatus: vi.fn(),
        clear: vi.fn(),
        notify: vi.fn(),
        onChange: vi.fn(),
    };

    window.insightsPanel = {
        load: vi.fn().mockResolvedValue(null),
        startPolling: vi.fn(),
        stopPolling: vi.fn(),
    };

    window.searchPane = { focus: vi.fn() };

    window.UserPanes = class {
        loadCollection = vi.fn();
        loadWantlist = vi.fn();
        loadRecommendations = vi.fn();
        loadCollectionStats = vi.fn();
        loadTasteFingerprint = vi.fn();
        startDiscogsOAuth = vi.fn();
        disconnectDiscogs = vi.fn();
        submitDiscogsVerifier = vi.fn();
        triggerSync = vi.fn();
        clearTasteCache = vi.fn();
        loadGapAnalysis = vi.fn();
    };
}

// Load all class-based scripts once at module level
// (They share the same global scope across all tests in this file)
beforeAll(() => {
    delete globalThis.window;
    globalThis.window = globalThis;
    setupAppDOM();
    setupGlobalMocks();

    // Load class files in dependency order
    loadScriptDirect('autocomplete.js');
    loadScriptDirect('graph.js');
    loadScriptDirect('trends.js');
    loadScriptDirect('user-panes.js');
    loadScriptDirect('app.js');
});

describe('TimelineScrubber', () => {
    beforeEach(() => {
        setupTimelineDOM();
        window.apiClient.getYearRange = vi.fn().mockResolvedValue({ min_year: 1950, max_year: 2023 });
        window.apiClient.getGenreEmergence = vi.fn().mockResolvedValue({ genres: [], styles: [] });
    });

    it('should initialize playing to false', () => {
        const ts = new TimelineScrubber();
        expect(ts.playing).toBe(false);
    });

    it('should initialize speed to year', () => {
        const ts = new TimelineScrubber();
        expect(ts.speed).toBe('year');
    });

    it('should initialize comparing to false', () => {
        const ts = new TimelineScrubber();
        expect(ts.comparing).toBe(false);
    });

    it('should initialize currentYear to null', () => {
        const ts = new TimelineScrubber();
        expect(ts.currentYear).toBeNull();
    });

    describe('init', () => {
        it('should set year range from API and show container', async () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            await ts.init();

            expect(ts.minYear).toBe(1950);
            expect(ts.maxYear).toBe(2023);
            expect(document.getElementById('timelineScrubber').classList.contains('hidden')).toBe(false);
        });

        it('should return early when range is null', async () => {
            window.apiClient.getYearRange = vi.fn().mockResolvedValue(null);
            const ts = new TimelineScrubber();
            await ts.init();

            // Should remain at default values
            expect(ts.minYear).toBe(1900);
        });

        it('should return early when min_year is null', async () => {
            window.apiClient.getYearRange = vi.fn().mockResolvedValue({ min_year: null, max_year: null });
            const ts = new TimelineScrubber();
            await ts.init();

            expect(ts.minYear).toBe(1900);
        });
    });

    describe('play and pause', () => {
        it('play should set playing to true and set play interval', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.currentYear = 1990;

            ts.play();

            expect(ts.playing).toBe(true);
            expect(ts.playInterval).not.toBeNull();

            ts.pause();
            vi.useRealTimers();
        });

        it('pause should clear interval and set playing to false', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.currentYear = 1990;
            ts.play();
            ts.pause();

            expect(ts.playing).toBe(false);
            expect(ts.playInterval).toBeNull();

            vi.useRealTimers();
        });

        it('play should start from minYear when currentYear is null', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.currentYear = null;

            ts.play();

            expect(ts.currentYear).toBe(1950);

            ts.pause();
            vi.useRealTimers();
        });

        it('play advances year on tick', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.currentYear = 2000;
            ts.onYearChange = vi.fn();

            ts.play();
            vi.advanceTimersByTime(1000);

            expect(ts.currentYear).toBe(2001);

            ts.pause();
            vi.useRealTimers();
        });

        it('play stops when reaching maxYear', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.currentYear = 2022;
            ts.onYearChange = vi.fn();

            ts.play();
            vi.advanceTimersByTime(2000);

            expect(ts.currentYear).toBe(2023);
            expect(ts.playing).toBe(false);

            vi.useRealTimers();
        });
    });

    describe('hide', () => {
        it('should add hidden class to container', () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            const container = document.getElementById('timelineScrubber');
            container.classList.remove('hidden');

            ts.hide();

            expect(container.classList.contains('hidden')).toBe(true);
        });

        it('should stop playback if playing', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.currentYear = 1990;
            ts.play();

            ts.hide();

            expect(ts.playing).toBe(false);
            vi.useRealTimers();
        });
    });

    describe('enterCompare / exitCompare', () => {
        it('enterCompare should set comparing to true', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;

            ts.enterCompare();

            expect(ts.comparing).toBe(true);
        });

        it('enterCompare should be idempotent', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;

            ts.enterCompare();
            ts.enterCompare();

            expect(ts.comparing).toBe(true);
        });

        it('exitCompare should set comparing to false', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.enterCompare();

            ts.exitCompare();

            expect(ts.comparing).toBe(false);
        });

        it('exitCompare should restore saved year', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.currentYear = 1995;

            ts.enterCompare();
            ts.exitCompare();

            expect(ts.currentYear).toBe(1995);
        });

        it('exitCompare should call onCompareExit if set', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            const onCompareExit = vi.fn();
            ts.onCompareExit = onCompareExit;

            ts.enterCompare();
            ts.exitCompare();

            expect(onCompareExit).toHaveBeenCalled();
        });

        it('exitCompare should do nothing when not comparing', () => {
            const ts = new TimelineScrubber();
            const onCompareExit = vi.fn();
            ts.onCompareExit = onCompareExit;

            ts.exitCompare();

            expect(onCompareExit).not.toHaveBeenCalled();
        });
    });

    describe('_emitCompareChange', () => {
        it('should normalize yearA as min and yearB as max', () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            const onCompareChange = vi.fn();
            ts.onCompareChange = onCompareChange;
            ts.compareYearA = 2010;
            ts.compareYearB = 1990;

            ts._emitCompareChange();

            expect(onCompareChange).toHaveBeenCalledWith(1990, 2010);
        });

        it('should show same-year hint when years are equal', () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            ts.compareYearA = 1990;
            ts.compareYearB = 1990;

            ts._emitCompareChange();

            expect(document.getElementById('compareSameYearHint').classList.contains('hidden')).toBe(false);
        });

        it('should hide same-year hint when years differ', () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            ts.compareYearA = 1990;
            ts.compareYearB = 2000;

            ts._emitCompareChange();

            expect(document.getElementById('compareSameYearHint').classList.contains('hidden')).toBe(true);
        });
    });

    describe('_checkEmergence', () => {
        it('should cache API responses by year', async () => {
            window.apiClient.getGenreEmergence = vi.fn().mockResolvedValue({ genres: [{ name: 'Rock' }], styles: [] });

            const ts = new TimelineScrubber();
            await ts._checkEmergence(1990);
            await ts._checkEmergence(1990);

            // API should only be called once (second call uses cache)
            expect(window.apiClient.getGenreEmergence).toHaveBeenCalledTimes(1);
        });

        it('should detect new genres and call onGenreEmergence', async () => {
            window.apiClient.getGenreEmergence = vi.fn().mockResolvedValue({ genres: [{ name: 'Electronic' }], styles: [] });

            const ts = new TimelineScrubber();
            const onGenreEmergence = vi.fn();
            ts.onGenreEmergence = onGenreEmergence;
            ts._previousGenres = new Set(); // no previous genres

            await ts._checkEmergence(1990);

            expect(onGenreEmergence).toHaveBeenCalledWith(expect.arrayContaining(['Electronic']));
        });

        it('should not call onGenreEmergence for already-known genres', async () => {
            window.apiClient.getGenreEmergence = vi.fn().mockResolvedValue({ genres: [{ name: 'Rock' }], styles: [] });

            const ts = new TimelineScrubber();
            const onGenreEmergence = vi.fn();
            ts.onGenreEmergence = onGenreEmergence;
            ts._previousGenres = new Set(['Rock']); // already known

            await ts._checkEmergence(1990);

            expect(onGenreEmergence).not.toHaveBeenCalled();
        });
    });

    describe('speed toggle', () => {
        it('should advance by 10 years per tick in decade mode', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.currentYear = 1950;
            ts.speed = 'decade';
            ts.onYearChange = vi.fn();

            ts.play();
            vi.advanceTimersByTime(500);

            expect(ts.currentYear).toBe(1960);

            ts.pause();
            vi.useRealTimers();
        });
    });

    describe('reset button', () => {
        it('should reset year to null on reset button click', () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            ts.currentYear = 1990;
            const onYearChange = vi.fn();
            ts.onYearChange = onYearChange;

            document.getElementById('timelineResetBtn').click();

            expect(ts.currentYear).toBeNull();
            expect(document.getElementById('timelineYearLabel').textContent).toBe('All');
            expect(onYearChange).toHaveBeenCalledWith(null);
        });
    });
});

describe('ExploreApp helper methods', () => {
    beforeEach(() => {
        setupAppDOM();
        setupGlobalMocks();
        globalThis.d3 = createD3Mock();
    });

    describe('ExploreApp._switchPane', () => {
        it('should activate the target pane', () => {
            const app = new ExploreApp();
            app._switchPane('trends');

            const trendsPane = document.getElementById('trendsPane');
            expect(trendsPane.classList.contains('active')).toBe(true);
        });

        it('should deactivate all other panes', () => {
            const app = new ExploreApp();
            app._switchPane('trends');

            const explorePane = document.getElementById('explorePane');
            expect(explorePane.classList.contains('active')).toBe(false);
        });

        it('should update activePane state', () => {
            const app = new ExploreApp();
            app._switchPane('trends');
            expect(app.activePane).toBe('trends');
        });

        it('should focus search pane input when switching to search', () => {
            const app = new ExploreApp();
            app._switchPane('search');
            expect(window.searchPane.focus).toHaveBeenCalled();
        });

        it('should stop insights polling when leaving insights pane', () => {
            const app = new ExploreApp();
            app._prevPane = 'insights';
            app._switchPane('trends');

            expect(window.insightsPanel.stopPolling).toHaveBeenCalled();
        });
    });

    describe('ExploreApp._setSearchType', () => {
        it('should update searchType', () => {
            const app = new ExploreApp();
            app._setSearchType('label');
            expect(app.searchType).toBe('label');
        });

        it('should update the search type button text', () => {
            const app = new ExploreApp();
            app._setSearchType('label');

            const btn = document.getElementById('searchTypeBtn');
            expect(btn.textContent).toBe('Label');
        });
    });

    describe('ExploreApp._showToast', () => {
        it('should add show class to toast', () => {
            const app = new ExploreApp();
            app._showToast('Link copied!');

            const toast = document.getElementById('shareToast');
            expect(toast.classList.contains('show')).toBe(true);
        });

        it('should set toast message text', () => {
            const app = new ExploreApp();
            app._showToast('Test message');

            const msg = document.getElementById('shareToastMsg');
            expect(msg.textContent).toBe('Test message');
        });

        it('should remove show class after timeout', () => {
            vi.useFakeTimers();
            const app = new ExploreApp();
            app._showToast('Test');

            vi.advanceTimersByTime(2500);

            const toast = document.getElementById('shareToast');
            expect(toast.classList.contains('show')).toBe(false);

            vi.useRealTimers();
        });
    });

    describe('ExploreApp._updateAuthUI', () => {
        it('should hide auth buttons when logged in', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getUser.mockReturnValue({ email: 'test@test.com' });
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: false });

            const app = new ExploreApp();
            app._updateAuthUI();

            expect(document.getElementById('authButtons').classList.contains('hidden')).toBe(true);
            expect(document.getElementById('userDropdown').classList.contains('hidden')).toBe(false);
        });

        it('should show auth buttons when logged out', () => {
            window.authManager.isLoggedIn.mockReturnValue(false);
            window.authManager.getUser.mockReturnValue(null);
            window.authManager.getDiscogsStatus.mockReturnValue(null);

            const app = new ExploreApp();
            app._updateAuthUI();

            expect(document.getElementById('authButtons').classList.contains('hidden')).toBe(false);
            expect(document.getElementById('userDropdown').classList.contains('hidden')).toBe(true);
        });

        it('should update email display when logged in with user', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getUser.mockReturnValue({ email: 'alice@example.com' });
            window.authManager.getDiscogsStatus.mockReturnValue({ connected: false });

            const app = new ExploreApp();
            app._updateAuthUI();

            expect(document.getElementById('userEmailDisplay').textContent).toBe('alice@example.com');
        });

        it('should switch to explore pane when logged out on personal pane', () => {
            window.authManager.isLoggedIn.mockReturnValue(false);
            window.authManager.getUser.mockReturnValue(null);
            window.authManager.getDiscogsStatus.mockReturnValue(null);

            const app = new ExploreApp();
            app.activePane = 'collection';
            app._updateAuthUI();

            expect(app.activePane).toBe('explore');
        });
    });

    describe('ExploreApp._detailStat', () => {
        it('should create a stat div with label and value', () => {
            const app = new ExploreApp();
            const el = app._detailStat('Releases', 42);

            expect(el.querySelector('.label').textContent).toBe('Releases');
            expect(el.querySelector('.value').textContent).toBe('42');
        });

        it('should format numbers with locale', () => {
            const app = new ExploreApp();
            const el = app._detailStat('Releases', 1000);

            const value = el.querySelector('.value').textContent;
            // 1000 locale-formatted should contain digits
            expect(value).toContain('1');
            expect(Number(value.replace(/,/g, ''))).toBe(1000);
        });
    });

    describe('ExploreApp._detailTags', () => {
        it('should render tags', () => {
            const app = new ExploreApp();
            const el = app._detailTags('Genres', ['Rock', 'Alternative']);

            const tags = el.querySelectorAll('.detail-tag');
            expect(tags).toHaveLength(2);
            expect(tags[0].textContent).toBe('Rock');
            expect(tags[1].textContent).toBe('Alternative');
        });
    });

    describe('ExploreApp._pushState', () => {
        it('should update browser history', () => {
            const pushStateSpy = vi.spyOn(history, 'pushState');
            const app = new ExploreApp();
            app._pushState('Radiohead', 'artist');

            expect(pushStateSpy).toHaveBeenCalledWith(
                { name: 'Radiohead', type: 'artist' },
                '',
                expect.stringContaining('name=Radiohead')
            );
        });
    });

    describe('ExploreApp._handleLogin - validation', () => {
        it('should show error when email or password missing', async () => {
            const app = new ExploreApp();
            document.getElementById('loginEmail').value = '';
            document.getElementById('loginPassword').value = '';

            await app._handleLogin();

            expect(document.getElementById('loginError').textContent).toBeTruthy();
            expect(window.apiClient.login).not.toHaveBeenCalled();
        });
    });

    describe('ExploreApp._handleRegister - validation', () => {
        it('should show error when password is too short', async () => {
            const app = new ExploreApp();
            document.getElementById('registerEmail').value = 'user@test.com';
            document.getElementById('registerPassword').value = 'short';

            await app._handleRegister();

            const errorEl = document.getElementById('registerError');
            expect(errorEl.textContent).toContain('8 characters');
            expect(window.apiClient.register).not.toHaveBeenCalled();
        });

        it('should show error when email is missing', async () => {
            const app = new ExploreApp();
            document.getElementById('registerEmail').value = '';
            document.getElementById('registerPassword').value = 'password123';

            await app._handleRegister();

            const errorEl = document.getElementById('registerError');
            expect(errorEl.textContent).toBeTruthy();
        });
    });

    describe('ExploreApp._handleLogout', () => {
        it('should call apiClient.logout and clear auth', async () => {
            window.authManager.getToken.mockReturnValue('some-token');
            const app = new ExploreApp();

            await app._handleLogout();

            expect(window.apiClient.logout).toHaveBeenCalledWith('some-token');
            expect(window.authManager.clear).toHaveBeenCalled();
            expect(window.authManager.notify).toHaveBeenCalled();
        });
    });

    describe('ExploreApp._enableCompareMode', () => {
        it('should set compareMode to true when primaryTrendsData exists', () => {
            const app = new ExploreApp();
            app.primaryTrendsData = { name: 'Radiohead', data: [] };

            app._enableCompareMode();

            expect(app.compareMode).toBe(true);
        });

        it('should not set compareMode when no primaryTrendsData', () => {
            const app = new ExploreApp();
            app.primaryTrendsData = null;

            app._enableCompareMode();

            expect(app.compareMode).toBe(false);
        });
    });

    describe('ExploreApp._clearComparison', () => {
        it('should reset compareMode', () => {
            const app = new ExploreApp();
            app.compareMode = true;

            app._clearComparison();

            expect(app.compareMode).toBe(false);
        });
    });

    describe('ExploreApp._onNodeExpand', () => {
        it('should not load explore for non-explorable types', async () => {
            const app = new ExploreApp();

            await app._onNodeExpand('OK Computer', 'release');

            expect(window.apiClient.explore).not.toHaveBeenCalled();
        });

        it('should set search type and query for explorable types', async () => {
            window.apiClient.explore.mockResolvedValue(null);
            const app = new ExploreApp();

            await app._onNodeExpand('Radiohead', 'artist');

            expect(app.searchType).toBe('artist');
            expect(app.currentQuery).toBe('Radiohead');
        });
    });

    describe('ExploreApp._addOwnershipBadges', () => {
        it('should add in-collection badge', () => {
            const app = new ExploreApp();
            const body = document.getElementById('infoPanelBody');
            body.textContent = '';

            app._addOwnershipBadges('123', { in_collection: true, in_wantlist: false });

            expect(body.querySelector('.in-collection')).not.toBeNull();
        });

        it('should add in-wantlist badge', () => {
            const app = new ExploreApp();
            const body = document.getElementById('infoPanelBody');
            body.textContent = '';

            app._addOwnershipBadges('123', { in_collection: false, in_wantlist: true });

            expect(body.querySelector('.in-wantlist')).not.toBeNull();
        });

        it('should not add any badges when both false', () => {
            const app = new ExploreApp();
            const body = document.getElementById('infoPanelBody');
            body.textContent = '';

            app._addOwnershipBadges('123', { in_collection: false, in_wantlist: false });

            expect(body.querySelector('.ownership-badge')).toBeNull();
        });
    });

    describe('ExploreApp._renderDetails', () => {
        it('should render explore button for artist type', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails({ name: 'Radiohead', release_count: 10 }, 'artist', 'radiohead');

            const btn = nodes.find(n => n.classList && n.classList.contains('explore-node-btn'));
            expect(btn).toBeDefined();
        });

        it('should render release count stat for artist', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails({ name: 'Radiohead', release_count: 42 }, 'artist', 'radiohead');

            const statEl = nodes.find(n => n.classList && n.classList.contains('detail-stat'));
            expect(statEl).toBeDefined();
            expect(statEl.querySelector('.value').textContent).toBe('42');
        });

        it('should render genres as tags for release', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'OK Computer', year: 1997, genres: ['Rock', 'Alternative'] },
                'release', 'ok-computer'
            );

            const tagSection = nodes.find(n => n.classList && n.classList.contains('detail-section'));
            expect(tagSection).toBeDefined();
        });

        it('should show fallback when no details for unknown type', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails({}, 'unknown-type', 'id');

            expect(nodes.length).toBeGreaterThan(0);
        });

        it('should render label details with release count', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails({ name: 'Warp Records', release_count: 500 }, 'label', 'warp');

            const exploreBtn = nodes.find(n => n.classList && n.classList.contains('explore-node-btn'));
            expect(exploreBtn).toBeDefined();
            const statEl = nodes.find(n => n.classList && n.classList.contains('detail-stat'));
            expect(statEl).toBeDefined();
            expect(statEl.querySelector('.value').textContent).toBe('500');
        });

        it('should render genre details with artist count', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails({ name: 'Electronic', artist_count: 1000 }, 'genre', 'electronic');

            const statEl = nodes.find(n => n.classList && n.classList.contains('detail-stat'));
            expect(statEl).toBeDefined();
            expect(statEl.querySelector('.value').textContent).toContain('1');
        });

        it('should render style details with artist count', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails({ name: 'IDM', artist_count: 200 }, 'style', 'idm');

            const statEl = nodes.find(n => n.classList && n.classList.contains('detail-stat'));
            expect(statEl).toBeDefined();
        });

        it('should render year stat for release', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'OK Computer', year: 1997 },
                'release', 'ok-computer'
            );

            const statEl = nodes.find(n => {
                if (!n.classList?.contains('detail-stat')) return false;
                return n.querySelector('.label')?.textContent === 'Year';
            });
            expect(statEl).toBeDefined();
            expect(statEl.querySelector('.value').textContent).toBe('1997');
        });

        it('should render artists tags for release', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'OK Computer', artists: ['Radiohead'] },
                'release', 'ok-computer'
            );

            const section = nodes.find(n => {
                if (!n.classList?.contains('detail-section')) return false;
                return n.querySelector('h6')?.textContent === 'Artists';
            });
            expect(section).toBeDefined();
        });

        it('should render labels tags for release', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'OK Computer', labels: ['Parlophone'] },
                'release', 'ok-computer'
            );

            const section = nodes.find(n => {
                if (!n.classList?.contains('detail-section')) return false;
                return n.querySelector('h6')?.textContent === 'Labels';
            });
            expect(section).toBeDefined();
        });

        it('should render styles tags for artist', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'Radiohead', release_count: 10, styles: ['Art Rock', 'Experimental'] },
                'artist', 'radiohead'
            );

            const section = nodes.find(n => {
                if (!n.classList?.contains('detail-section')) return false;
                return n.querySelector('h6')?.textContent === 'Styles';
            });
            expect(section).toBeDefined();
        });

        it('should render groups tags for artist', () => {
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'Thom Yorke', release_count: 5, groups: ['Radiohead', 'Atoms for Peace'] },
                'artist', 'thom-yorke'
            );

            const section = nodes.find(n => {
                if (!n.classList?.contains('detail-section')) return false;
                return n.querySelector('h6')?.textContent === 'Groups';
            });
            expect(section).toBeDefined();
        });

        it('should render gap analysis button for artist when logged in', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'Radiohead', release_count: 10, id: '123' },
                'artist', 'radiohead'
            );

            const gapBtn = nodes.find(n => n.classList && n.classList.contains('gap-analysis-btn'));
            expect(gapBtn).toBeDefined();
            expect(gapBtn.textContent).toContain('What am I missing?');
        });

        it('should render gap analysis button for label when logged in', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'Warp Records', release_count: 500, id: '456' },
                'label', 'warp'
            );

            const gapBtn = nodes.find(n => n.classList && n.classList.contains('gap-analysis-btn'));
            expect(gapBtn).toBeDefined();
        });

        it('should not render gap analysis button when logged out', () => {
            window.authManager.isLoggedIn.mockReturnValue(false);
            const app = new ExploreApp();
            const nodes = app._renderDetails(
                { name: 'Radiohead', release_count: 10, id: '123' },
                'artist', 'radiohead'
            );

            const gapBtn = nodes.find(n => n.classList && n.classList.contains('gap-analysis-btn'));
            expect(gapBtn).toBeUndefined();
        });
    });

    describe('ExploreApp._onSearch', () => {
        it('should set currentQuery and push state', async () => {
            const pushStateSpy = vi.spyOn(history, 'pushState');
            const app = new ExploreApp();
            app.activePane = 'explore';

            await app._onSearch('Radiohead');

            expect(app.currentQuery).toBe('Radiohead');
            expect(pushStateSpy).toHaveBeenCalled();
        });
    });

    describe('ExploreApp._loadTrends', () => {
        it('should set primaryTrendsData when not in compare mode', async () => {
            window.apiClient.getTrends.mockResolvedValue({ name: 'Radiohead', years: [] });
            const app = new ExploreApp();
            app.compareMode = false;
            app.primaryTrendsData = null;

            await app._loadTrends('Radiohead', 'artist');

            expect(app.primaryTrendsData).toEqual({ name: 'Radiohead', years: [] });
        });

        it('should handle null trends data gracefully', async () => {
            window.apiClient.getTrends.mockResolvedValue(null);
            const app = new ExploreApp();
            app.primaryTrendsData = null;

            await app._loadTrends('Unknown', 'artist');

            expect(app.primaryTrendsData).toBeNull();
        });
    });

    describe('ExploreApp._onTimelineYearChange', () => {
        it('should call graph.setBeforeYear', () => {
            const app = new ExploreApp();
            app.graph.setBeforeYear = vi.fn();

            app._onTimelineYearChange(1995);

            expect(app.graph.setBeforeYear).toHaveBeenCalledWith(1995);
        });

        it('should pass null to graph.setBeforeYear', () => {
            const app = new ExploreApp();
            app.graph.setBeforeYear = vi.fn();

            app._onTimelineYearChange(null);

            expect(app.graph.setBeforeYear).toHaveBeenCalledWith(null);
        });
    });

    describe('ExploreApp._onCompareChange', () => {
        it('should clear comparison when years are equal', () => {
            const app = new ExploreApp();
            app.graph.clearComparison = vi.fn();
            app.graph.setBeforeYear = vi.fn();
            app.graph.setCompareYears = vi.fn();

            app._onCompareChange(1990, 1990);

            expect(app.graph.clearComparison).toHaveBeenCalled();
            expect(app.graph.setBeforeYear).toHaveBeenCalledWith(1990);
            expect(app.graph.setCompareYears).not.toHaveBeenCalled();
        });

        it('should set compare years when different', () => {
            const app = new ExploreApp();
            app.graph.clearComparison = vi.fn();
            app.graph.setCompareYears = vi.fn();

            app._onCompareChange(1990, 2000);

            expect(app.graph.setCompareYears).toHaveBeenCalledWith(1990, 2000);
        });
    });

    describe('ExploreApp._onCompareExit', () => {
        it('should clear comparison and restore year', () => {
            const app = new ExploreApp();
            app.graph.clearComparison = vi.fn();
            app.graph.setBeforeYear = vi.fn();
            app.timeline.currentYear = 1995;

            app._onCompareExit();

            expect(app.graph.clearComparison).toHaveBeenCalled();
            expect(app.graph.setBeforeYear).toHaveBeenCalledWith(1995);
        });
    });

    describe('ExploreApp._loadSnapshot', () => {
        it('should call restoreSnapshot on graph when data is returned', async () => {
            window.apiClient.restoreSnapshot.mockResolvedValue({
                nodes: [{ id: 'A', type: 'artist' }],
                center: { id: 'A', type: 'artist' },
            });
            const app = new ExploreApp();
            app.graph.restoreSnapshot = vi.fn();

            await app._loadSnapshot('snap-123');

            expect(app.graph.restoreSnapshot).toHaveBeenCalled();
        });

        it('should not call restoreSnapshot when API returns null', async () => {
            window.apiClient.restoreSnapshot.mockResolvedValue(null);
            const app = new ExploreApp();
            app.graph.restoreSnapshot = vi.fn();

            await app._loadSnapshot('bad-token');

            expect(app.graph.restoreSnapshot).not.toHaveBeenCalled();
        });

        it('should add and remove loading class', async () => {
            let classDuringCall = null;
            window.apiClient.restoreSnapshot.mockImplementation(async () => {
                classDuringCall = document.getElementById('graphLoading').classList.contains('active');
                return null;
            });
            const app = new ExploreApp();

            await app._loadSnapshot('snap-123');

            expect(classDuringCall).toBe(true);
        });
    });

    describe('ExploreApp._onNodeClick', () => {
        it('should open panel and show details', async () => {
            const details = { name: 'Radiohead', release_count: 42 };
            window.apiClient.getNodeDetails.mockResolvedValue(details);
            window.authManager.isLoggedIn.mockReturnValue(false);

            const app = new ExploreApp();
            await app._onNodeClick('Radiohead', 'artist');

            const panel = document.getElementById('infoPanel');
            expect(panel.classList.contains('open')).toBe(true);
            const title = document.getElementById('infoPanelTitle');
            expect(title.textContent).toBe('Radiohead');
        });

        it('should show no details message when API returns null', async () => {
            window.apiClient.getNodeDetails.mockResolvedValue(null);

            const app = new ExploreApp();
            await app._onNodeClick('Unknown', 'artist');

            const body = document.getElementById('infoPanelBody');
            expect(body.textContent).toContain('No details available');
        });

        it('should fetch ownership status for release nodes when logged in', async () => {
            window.apiClient.getNodeDetails.mockResolvedValue({ name: 'OK Computer' });
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getToken.mockReturnValue('token');
            window.apiClient.getUserStatus.mockResolvedValue({ status: { 'ok-computer': { in_collection: true, in_wantlist: false } } });

            const app = new ExploreApp();
            await app._onNodeClick('ok-computer', 'release');

            expect(window.apiClient.getUserStatus).toHaveBeenCalledWith(['ok-computer'], 'token');
        });
    });

    describe('ExploreApp._handleLogin - full flow', () => {
        it('should set auth state on successful login', async () => {
            document.getElementById('loginEmail').value = 'test@test.com';
            document.getElementById('loginPassword').value = 'password123';
            window.apiClient.login.mockResolvedValue({ access_token: 'jwt-123' });
            window.apiClient.getMe.mockResolvedValue({ email: 'test@test.com' });
            window.apiClient.getDiscogsStatus.mockResolvedValue({ connected: false });
            globalThis.Alpine = { store: vi.fn().mockReturnValue({ authOpen: false }) };

            const app = new ExploreApp();
            await app._handleLogin();

            expect(window.authManager.setToken).toHaveBeenCalledWith('jwt-123');
            expect(window.authManager.setUser).toHaveBeenCalled();
            expect(window.authManager.notify).toHaveBeenCalled();
        });

        it('should show error on invalid credentials', async () => {
            document.getElementById('loginEmail').value = 'test@test.com';
            document.getElementById('loginPassword').value = 'wrong';
            window.apiClient.login.mockResolvedValue(null);

            const app = new ExploreApp();
            await app._handleLogin();

            expect(document.getElementById('loginError').textContent).toContain('Invalid');
        });

        it('should re-enable submit button after login attempt', async () => {
            document.getElementById('loginEmail').value = 'test@test.com';
            document.getElementById('loginPassword').value = 'password123';
            window.apiClient.login.mockResolvedValue(null);

            const app = new ExploreApp();
            await app._handleLogin();

            expect(document.getElementById('loginSubmitBtn').disabled).toBe(false);
        });
    });

    describe('ExploreApp._handleRegister - full flow', () => {
        it('should show success on successful registration', async () => {
            document.getElementById('registerEmail').value = 'new@test.com';
            document.getElementById('registerPassword').value = 'password123';
            window.apiClient.register.mockResolvedValue(true);

            const app = new ExploreApp();
            await app._handleRegister();

            const successEl = document.getElementById('registerSuccess');
            expect(successEl.classList.contains('hidden')).toBe(false);
        });

        it('should show error on failed registration', async () => {
            document.getElementById('registerEmail').value = 'existing@test.com';
            document.getElementById('registerPassword').value = 'password123';
            window.apiClient.register.mockResolvedValue(false);

            const app = new ExploreApp();
            await app._handleRegister();

            expect(document.getElementById('registerError').textContent).toContain('failed');
        });

        it('should re-enable submit button after attempt', async () => {
            document.getElementById('registerEmail').value = 'new@test.com';
            document.getElementById('registerPassword').value = 'password123';
            window.apiClient.register.mockResolvedValue(true);

            const app = new ExploreApp();
            await app._handleRegister();

            expect(document.getElementById('registerSubmitBtn').disabled).toBe(false);
        });
    });

    describe('ExploreApp._switchPane - lazy loading', () => {
        it('should load insights when switching to insights', () => {
            const app = new ExploreApp();
            app._switchPane('insights');

            expect(window.insightsPanel.load).toHaveBeenCalled();
            expect(window.insightsPanel.startPolling).toHaveBeenCalled();
        });

        it('should load collection when switching to collection while logged in', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            const app = new ExploreApp();
            app._switchPane('collection');

            expect(app.userPanes.loadCollection).toHaveBeenCalled();
            expect(app.userPanes.loadCollectionStats).toHaveBeenCalled();
            expect(app.userPanes.loadTasteFingerprint).toHaveBeenCalled();
        });

        it('should load wantlist when switching to wantlist while logged in', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            const app = new ExploreApp();
            app._switchPane('wantlist');

            expect(app.userPanes.loadWantlist).toHaveBeenCalled();
        });

        it('should load recommendations when switching to recommendations while logged in', () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            const app = new ExploreApp();
            app._switchPane('recommendations');

            expect(app.userPanes.loadRecommendations).toHaveBeenCalled();
        });
    });

    describe('ExploreApp._gapAnalysisButton', () => {
        it('should create a button with correct text', () => {
            const app = new ExploreApp();
            const btn = app._gapAnalysisButton('artist', '123', 'Radiohead');

            expect(btn.textContent).toContain('What am I missing?');
            expect(btn.classList.contains('gap-analysis-btn')).toBe(true);
        });
    });

    describe('ExploreApp._shareSnapshot', () => {
        it('should not proceed when not logged in', async () => {
            window.authManager.getToken.mockReturnValue(null);
            const app = new ExploreApp();

            await app._shareSnapshot();

            expect(window.apiClient.saveSnapshot).not.toHaveBeenCalled();
        });
    });

    describe('ExploreApp._decorateOwnership', () => {
        it('should return early when not logged in', async () => {
            window.authManager.isLoggedIn.mockReturnValue(false);
            const app = new ExploreApp();

            await app._decorateOwnership();

            expect(window.apiClient.getUserStatus).not.toHaveBeenCalled();
        });
    });

    describe('ExploreApp._initAuth', () => {
        it('should call authManager.init and updateAuthUI', async () => {
            window.authManager.init.mockResolvedValue(true);
            const app = new ExploreApp();
            const result = await app._initAuth();

            expect(window.authManager.init).toHaveBeenCalled();
            expect(result).toBe(true);
        });
    });

    describe('ExploreApp._loadExplore', () => {
        it('should call apiClient.explore and initialize timeline', async () => {
            const exploreData = { center: { id: 'Radiohead', type: 'artist' }, categories: [] };
            window.apiClient.explore.mockResolvedValue(exploreData);
            window.authManager.isLoggedIn.mockReturnValue(false);
            window.apiClient.getYearRange.mockResolvedValue({ min_year: 1950, max_year: 2023 });
            window.apiClient.getGenreEmergence.mockResolvedValue({ genres: [], styles: [] });

            const app = new ExploreApp();
            app.graph.setExploreData = vi.fn();
            app.graph._pendingExpands = 0;
            app.graph.onExpandsComplete = null;
            app.graph.nodes = [];

            await app._loadExplore('Radiohead', 'artist');

            expect(window.apiClient.explore).toHaveBeenCalledWith('Radiohead', 'artist');
            expect(app.graph.setExploreData).toHaveBeenCalledWith(exploreData);
        });

        it('should not call graph.setExploreData when API returns null', async () => {
            window.apiClient.explore.mockResolvedValue(null);

            const app = new ExploreApp();
            app.graph.setExploreData = vi.fn();

            await app._loadExplore('Unknown', 'artist');

            expect(app.graph.setExploreData).not.toHaveBeenCalled();
        });

        it('should show loading class during API call', async () => {
            let classDuringCall = null;
            window.apiClient.explore.mockImplementation(async () => {
                classDuringCall = document.getElementById('graphLoading').classList.contains('active');
                return null;
            });

            const app = new ExploreApp();
            await app._loadExplore('Test', 'artist');

            expect(classDuringCall).toBe(true);
        });

        it('should decorate ownership when logged in', async () => {
            const exploreData = { center: { id: 'Radiohead', type: 'artist' }, categories: [] };
            window.apiClient.explore.mockResolvedValue(exploreData);
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getToken.mockReturnValue('token');
            window.apiClient.getUserStatus.mockResolvedValue(null);
            window.apiClient.getYearRange.mockResolvedValue({ min_year: null, max_year: null });

            const app = new ExploreApp();
            app.graph.setExploreData = vi.fn();
            app.graph._pendingExpands = 0;
            app.graph.onExpandsComplete = null;
            app.graph.nodes = [{ type: 'release', name: 'OK Computer', nodeId: '123' }];

            await app._loadExplore('Radiohead', 'artist');

            expect(window.apiClient.getUserStatus).toHaveBeenCalled();
        });
    });

    describe('ExploreApp._shareSnapshot - full flow', () => {
        it('should save snapshot and copy URL to clipboard', async () => {
            window.authManager.getToken.mockReturnValue('jwt');
            window.apiClient.saveSnapshot.mockResolvedValue({ token: 'snap-123' });
            navigator.clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };

            const app = new ExploreApp();
            app.graph.nodes = [{ name: 'Radiohead', type: 'artist', nodeId: 'radiohead' }];
            app.graph.centerName = 'Radiohead';
            app.graph.centerType = 'artist';

            await app._shareSnapshot();

            expect(window.apiClient.saveSnapshot).toHaveBeenCalled();
            expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('snapshot=snap-123'));
        });

        it('should filter out category nodes', async () => {
            window.authManager.getToken.mockReturnValue('jwt');
            window.apiClient.saveSnapshot.mockResolvedValue({ token: 'snap-123' });
            navigator.clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };

            const app = new ExploreApp();
            app.graph.nodes = [
                { name: 'Radiohead', type: 'artist', nodeId: 'radiohead' },
                { name: 'Releases', type: 'category', isCategory: true },
            ];
            app.graph.centerName = 'Radiohead';
            app.graph.centerType = 'artist';

            await app._shareSnapshot();

            const callArgs = window.apiClient.saveSnapshot.mock.calls[0];
            expect(callArgs[0]).toHaveLength(1);
            expect(callArgs[0][0].id).toBe('radiohead');
        });

        it('should return early when no center name', async () => {
            window.authManager.getToken.mockReturnValue('jwt');

            const app = new ExploreApp();
            app.graph.nodes = [{ name: 'A', type: 'artist' }];
            app.graph.centerName = null;

            await app._shareSnapshot();

            expect(window.apiClient.saveSnapshot).not.toHaveBeenCalled();
        });

        it('should return early when no non-category nodes', async () => {
            window.authManager.getToken.mockReturnValue('jwt');

            const app = new ExploreApp();
            app.graph.nodes = [{ name: 'Cat', type: 'category', isCategory: true }];
            app.graph.centerName = 'Radiohead';
            app.graph.centerType = 'artist';

            await app._shareSnapshot();

            expect(window.apiClient.saveSnapshot).not.toHaveBeenCalled();
        });

        it('should return early when saveSnapshot returns null', async () => {
            window.authManager.getToken.mockReturnValue('jwt');
            window.apiClient.saveSnapshot.mockResolvedValue(null);

            const app = new ExploreApp();
            app.graph.nodes = [{ name: 'A', type: 'artist', nodeId: 'a' }];
            app.graph.centerName = 'A';
            app.graph.centerType = 'artist';

            await app._shareSnapshot();

            // Should not throw
        });

        it('should use prompt fallback when clipboard fails', async () => {
            window.authManager.getToken.mockReturnValue('jwt');
            window.apiClient.saveSnapshot.mockResolvedValue({ token: 'snap-123' });
            navigator.clipboard = { writeText: vi.fn().mockRejectedValue(new Error('denied')) };
            window.prompt = vi.fn();

            const app = new ExploreApp();
            app.graph.nodes = [{ name: 'A', type: 'artist', nodeId: 'a' }];
            app.graph.centerName = 'A';
            app.graph.centerType = 'artist';

            await app._shareSnapshot();

            expect(window.prompt).toHaveBeenCalledWith('Copy this link:', expect.stringContaining('snapshot=snap-123'));
        });

        it('should show toast on successful clipboard write', async () => {
            window.authManager.getToken.mockReturnValue('jwt');
            window.apiClient.saveSnapshot.mockResolvedValue({ token: 'snap-123' });
            navigator.clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };

            const app = new ExploreApp();
            app.graph.nodes = [{ name: 'A', type: 'artist', nodeId: 'a' }];
            app.graph.centerName = 'A';
            app.graph.centerType = 'artist';

            await app._shareSnapshot();

            const toast = document.getElementById('shareToast');
            expect(toast.classList.contains('show')).toBe(true);
        });
    });

    describe('ExploreApp._onGenreEmergence', () => {
        it('should call d3 selectAll and classed on genre nodes', () => {
            const app = new ExploreApp();
            app._onGenreEmergence(['Electronic', 'Rock']);

            // d3 mock's selectAll and each should be called
            expect(app.graph.g.selectAll).toHaveBeenCalledWith('g');
        });
    });

    describe('ExploreApp._loadTrends - compare mode', () => {
        it('should add comparison when in compare mode with primary data', async () => {
            const trendsData = { name: 'Radiohead', data: [{ year: 1993, count: 1 }] };
            window.apiClient.getTrends.mockResolvedValue(trendsData);

            const app = new ExploreApp();
            app.compareMode = true;
            app.primaryTrendsData = { name: 'Aphex Twin', data: [] };
            app.trends.addComparison = vi.fn();

            await app._loadTrends('Radiohead', 'artist');

            expect(app.trends.addComparison).toHaveBeenCalledWith(trendsData);
            expect(app.compareMode).toBe(false);
        });

        it('should update compare badge text', async () => {
            window.apiClient.getTrends.mockResolvedValue({ name: 'Radiohead', data: [] });

            const app = new ExploreApp();
            app.compareMode = true;
            app.primaryTrendsData = { name: 'Aphex Twin', data: [] };
            app.trends.addComparison = vi.fn();

            await app._loadTrends('Radiohead', 'artist');

            expect(document.getElementById('compareBadge').textContent).toBe('vs Radiohead');
            expect(document.getElementById('compareInfo').classList.contains('hidden')).toBe(false);
        });

        it('should show compare button for primary trends', async () => {
            window.apiClient.getTrends.mockResolvedValue({ name: 'Radiohead', data: [] });

            const app = new ExploreApp();
            app.compareMode = false;
            app.primaryTrendsData = null;
            app.trends.render = vi.fn();

            await app._loadTrends('Radiohead', 'artist');

            expect(document.getElementById('compareBtn').classList.contains('hidden')).toBe(false);
        });

        it('should remove loading class after trends load', async () => {
            window.apiClient.getTrends.mockResolvedValue(null);
            const loading = document.getElementById('trendsLoading');

            const app = new ExploreApp();
            loading.classList.add('active');
            await app._loadTrends('Test', 'artist');

            expect(loading.classList.contains('active')).toBe(false);
        });
    });

    describe('ExploreApp._restoreFromUrl', () => {
        it('should load snapshot when URL has snapshot param', async () => {
            window.apiClient.restoreSnapshot.mockResolvedValue(null);
            // Set URL with snapshot param
            const origLocation = window.location;
            delete window.location;
            window.location = { search: '?snapshot=snap-123', origin: 'http://localhost' };

            const app = new ExploreApp();
            await app._restoreFromUrl();

            expect(window.apiClient.restoreSnapshot).toHaveBeenCalledWith('snap-123');
            window.location = origLocation;
        });

        it('should restore search from URL params', async () => {
            window.apiClient.explore.mockResolvedValue(null);
            const origLocation = window.location;
            delete window.location;
            window.location = { search: '?name=Radiohead&type=artist', origin: 'http://localhost' };

            const app = new ExploreApp();
            await app._restoreFromUrl();

            expect(app.searchType).toBe('artist');
            expect(document.getElementById('searchInput').value).toBe('Radiohead');
            window.location = origLocation;
        });

        it('should do nothing when URL has no params', async () => {
            const origLocation = window.location;
            delete window.location;
            window.location = { search: '', origin: 'http://localhost' };

            const app = new ExploreApp();
            await app._restoreFromUrl();

            // Should not throw
            window.location = origLocation;
        });
    });

    describe('ExploreApp._onNodeExpand - full flow', () => {
        it('should load explore for artist type', async () => {
            window.apiClient.explore.mockResolvedValue(null);
            const app = new ExploreApp();

            await app._onNodeExpand('Radiohead', 'artist');

            expect(app.searchType).toBe('artist');
            expect(app.currentQuery).toBe('Radiohead');
            expect(document.getElementById('searchInput').value).toBe('Radiohead');
            expect(window.apiClient.explore).toHaveBeenCalledWith('Radiohead', 'artist');
        });
    });

    describe('ExploreApp._onNodeClick - explore button binding', () => {
        it('should wire up explore button click handler', async () => {
            window.apiClient.getNodeDetails.mockResolvedValue({
                name: 'Radiohead', release_count: 42,
            });
            window.authManager.isLoggedIn.mockReturnValue(false);

            const app = new ExploreApp();
            await app._onNodeClick('Radiohead', 'artist');

            const body = document.getElementById('infoPanelBody');
            const exploreBtn = body.querySelector('.explore-node-btn');
            expect(exploreBtn).not.toBeNull();
            expect(exploreBtn.dataset.name).toBe('Radiohead');
            expect(exploreBtn.dataset.type).toBe('artist');
        });
    });

    describe('ExploreApp._decorateOwnership - with nodes', () => {
        it('should call getUserStatus with release node IDs', async () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getToken.mockReturnValue('token');
            window.apiClient.getUserStatus.mockResolvedValue({ status: {} });

            const app = new ExploreApp();
            app.graph.nodes = [
                { type: 'release', name: 'OK Computer', nodeId: '123' },
                { type: 'artist', name: 'Radiohead' },
                { type: 'release', name: 'Kid A', nodeId: '456', isCategory: false },
            ];

            await app._decorateOwnership();

            expect(window.apiClient.getUserStatus).toHaveBeenCalledWith(['123', '456'], 'token');
        });

        it('should return early when no release nodes', async () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getToken.mockReturnValue('token');

            const app = new ExploreApp();
            app.graph.nodes = [
                { type: 'artist', name: 'Radiohead' },
            ];

            await app._decorateOwnership();

            expect(window.apiClient.getUserStatus).not.toHaveBeenCalled();
        });

        it('should handle null result from getUserStatus', async () => {
            window.authManager.isLoggedIn.mockReturnValue(true);
            window.authManager.getToken.mockReturnValue('token');
            window.apiClient.getUserStatus.mockResolvedValue(null);

            const app = new ExploreApp();
            app.graph.nodes = [{ type: 'release', name: 'OK Computer', nodeId: '123' }];

            await app._decorateOwnership();

            // Should not throw
        });
    });

    describe('ExploreApp._switchPane - trends with query', () => {
        it('should load trends when switching to trends with existing query', async () => {
            window.apiClient.getTrends.mockResolvedValue(null);

            const app = new ExploreApp();
            app.currentQuery = 'Radiohead';
            app.searchType = 'artist';
            app._switchPane('trends');

            expect(window.apiClient.getTrends).toHaveBeenCalledWith('Radiohead', 'artist');
        });

        it('should not load trends when switching to trends without query', () => {
            const app = new ExploreApp();
            app.currentQuery = '';
            app._switchPane('trends');

            expect(window.apiClient.getTrends).not.toHaveBeenCalled();
        });
    });

    describe('ExploreApp._clearComparison - extended', () => {
        it('should clear comparison and update UI', () => {
            const app = new ExploreApp();
            app.compareMode = true;
            app.trends.clearComparison = vi.fn();

            app._clearComparison();

            expect(app.trends.clearComparison).toHaveBeenCalled();
            expect(document.getElementById('compareBtn').classList.contains('hidden')).toBe(false);
            expect(document.getElementById('compareHint').classList.contains('hidden')).toBe(true);
            expect(document.getElementById('compareInfo').classList.contains('hidden')).toBe(true);
        });
    });

    describe('ExploreApp._enableCompareMode - extended', () => {
        it('should show compare hint and hide button', () => {
            const app = new ExploreApp();
            app.primaryTrendsData = { name: 'Radiohead', data: [] };

            app._enableCompareMode();

            expect(document.getElementById('compareBtn').classList.contains('hidden')).toBe(true);
            expect(document.getElementById('compareHint').classList.contains('hidden')).toBe(false);
        });
    });

    describe('ExploreApp._gapAnalysisButton - click handler', () => {
        it('should close info panel and call loadGapAnalysis on click', () => {
            window.userPanes = { loadGapAnalysis: vi.fn() };

            const app = new ExploreApp();
            const btn = app._gapAnalysisButton('artist', '123', 'Radiohead');

            // Simulate click
            btn.click();

            expect(window.userPanes.loadGapAnalysis).toHaveBeenCalledWith('artist', '123', true);
        });
    });
});

describe('TimelineScrubber event handlers', () => {
    beforeEach(() => {
        setupTimelineDOM();
        window.apiClient = {
            getYearRange: vi.fn().mockResolvedValue({ min_year: 1950, max_year: 2023 }),
            getGenreEmergence: vi.fn().mockResolvedValue({ genres: [], styles: [] }),
        };
    });

    describe('_onSliderInput', () => {
        it('should update currentYear and yearLabel on slider input', () => {
            const ts = new TimelineScrubber();
            ts.slider.value = '1990';

            ts._onSliderInput();

            expect(ts.currentYear).toBe(1990);
            expect(ts.yearLabel.textContent).toBe('1990');
        });

        it('should debounce and emit year change', () => {
            vi.useFakeTimers();
            const onYearChange = vi.fn();
            const ts = new TimelineScrubber();
            ts.onYearChange = onYearChange;
            ts.slider.value = '1990';

            ts._onSliderInput();

            // Not called immediately
            expect(onYearChange).not.toHaveBeenCalled();

            // Called after debounce
            vi.advanceTimersByTime(300);
            expect(onYearChange).toHaveBeenCalledWith(1990);

            vi.useRealTimers();
        });
    });

    describe('slider input event', () => {
        it('should pause playback when slider dragged during play', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.currentYear = 1990;
            ts.play();
            expect(ts.playing).toBe(true);

            // Simulate slider input event
            ts.slider.dispatchEvent(new Event('input'));

            expect(ts.playing).toBe(false);
            vi.useRealTimers();
        });
    });

    describe('play button click', () => {
        it('should toggle play/pause via click', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.currentYear = 1990;

            // Click to play
            ts.playBtn.click();
            expect(ts.playing).toBe(true);

            // Click to pause
            ts.playBtn.click();
            expect(ts.playing).toBe(false);

            vi.useRealTimers();
        });
    });

    describe('speed toggle click', () => {
        it('should toggle speed between year and decade', () => {
            const ts = new TimelineScrubber();
            expect(ts.speed).toBe('year');

            ts.speedToggle.click();
            expect(ts.speed).toBe('decade');
            expect(ts.speedLabel.textContent).toBe('10yr/s');

            ts.speedToggle.click();
            expect(ts.speed).toBe('year');
            expect(ts.speedLabel.textContent).toBe('1yr/s');
        });
    });

    describe('compare button clicks', () => {
        it('should enter compare mode via compare button', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;

            ts.compareBtn.click();

            expect(ts.comparing).toBe(true);
        });

        it('should exit compare mode via exit button', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.enterCompare();

            ts.exitCompareBtn.click();

            expect(ts.comparing).toBe(false);
        });
    });

    describe('compare slider input', () => {
        it('should update compare years on slider input', () => {
            vi.useFakeTimers();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.enterCompare();

            ts.sliderA.value = '1970';
            ts.sliderA.dispatchEvent(new Event('input'));

            expect(ts.compareYearA).toBe(1970);
            expect(ts.yearALabel.textContent).toBe('1970');

            vi.useRealTimers();
        });

        it('should debounce compare change emission', () => {
            vi.useFakeTimers();
            const onCompareChange = vi.fn();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.onCompareChange = onCompareChange;
            ts.enterCompare();

            // Reset call count from enterCompare
            onCompareChange.mockClear();

            ts.sliderB.value = '2010';
            ts.sliderB.dispatchEvent(new Event('input'));

            expect(onCompareChange).not.toHaveBeenCalled();

            vi.advanceTimersByTime(300);
            expect(onCompareChange).toHaveBeenCalled();

            vi.useRealTimers();
        });
    });

    describe('legend close button', () => {
        it('should hide legend on close button click', () => {
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.enterCompare();

            ts.legendCloseBtn.click();

            expect(ts.compareLegend.classList.contains('hidden')).toBe(true);
        });
    });

    describe('hide with compare mode', () => {
        it('should exit compare when hiding while comparing', () => {
            setupTimelineDOM();
            const ts = new TimelineScrubber();
            ts.minYear = 1950;
            ts.maxYear = 2023;
            ts.enterCompare();

            ts.hide();

            expect(ts.comparing).toBe(false);
            expect(ts.container.classList.contains('hidden')).toBe(true);
        });
    });
});
