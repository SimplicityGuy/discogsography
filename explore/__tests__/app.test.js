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
        'timelineExitCompareBtn', 'compareSliderA', 'compareSliderB',
        'compareYearALabel', 'compareYearBLabel', 'compareLegend', 'compareLegendClose',
        'compareSameYearHint',
        // App
        'searchInput', 'searchTypeBtn',
        'autocompleteDropdown',
        'graphContainer', 'graphSvg', 'graphPlaceholder', 'graphLoading',
        'trendsChart', 'trendsPlaceholder', 'trendsLoading',
        'infoPanel', 'infoPanelBody', 'infoPanelTitle',
        'closePanelBtn',
        'compareBtn', 'clearCompareBtn', 'compareBadge', 'compareInfo', 'compareHint',
        'shareBtn', 'shareToast', 'shareToastMsg',
        'authButtons', 'userDropdown', 'userEmailDisplay',
        'discogsStatusDisplay', 'connectDiscogsBtn', 'disconnectDiscogsBtn', 'syncBtn',
        'navCollection', 'navWantlist', 'navRecommendations', 'navGaps',
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
    });
});
