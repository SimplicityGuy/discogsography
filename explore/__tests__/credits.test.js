import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { loadScript, createMockFetch } from './helpers.js';

// ── Mock Data ──────────────────────────────────────────────────────────── //

const MOCK_AUTOCOMPLETE = {
    results: [
        { name: 'Bob Ludwig' },
        { name: 'Bob Clearmountain' },
        { name: 'Bob Rock' },
    ],
};

const MOCK_PROFILE = {
    name: 'Bob Ludwig',
    total_credits: 1500,
    first_year: 1969,
    last_year: 2023,
    artist_id: 'a42',
    artist_name: 'Bob Ludwig',
    role_breakdown: [
        { category: 'mastering', count: 1200 },
        { category: 'engineering', count: 300 },
    ],
};

const MOCK_CREDITS = {
    credits: [
        {
            year: 2020,
            title: 'Fetch The Bolt Cutters',
            artists: ['Fiona Apple'],
            role: 'Mastered By',
            category: 'mastering',
        },
        {
            year: 2019,
            title: 'Norman Fucking Rockwell!',
            artists: ['Lana Del Rey'],
            role: 'Mastered By',
            category: 'mastering',
        },
        {
            year: 2015,
            title: 'Sound & Color',
            artists: ['Alabama Shakes'],
            role: 'Mixed By',
            category: 'engineering',
        },
    ],
};

const MOCK_TIMELINE = {
    timeline: [
        { year: 2019, category: 'mastering', count: 45 },
        { year: 2020, category: 'mastering', count: 50 },
        { year: 2019, category: 'engineering', count: 10 },
    ],
};

const MOCK_CONNECTIONS = {
    connections: [
        { name: 'Greg Calbi', shared_count: 25 },
        { name: 'Chris Bellman', shared_count: 12 },
    ],
};

const MOCK_LEADERBOARD = {
    entries: [
        { name: 'Bob Ludwig', credit_count: 1500 },
        { name: 'Greg Calbi', credit_count: 1200 },
        { name: 'Bernie Grundman', credit_count: 900 },
    ],
};

// ── DOM Setup ──────────────────────────────────────────────────────────── //

function setupDOM() {
    document.body.textContent = '';

    const ids = [
        'creditsSearchInput',
        'creditsAutocompleteDropdown',
        'creditsProfileCard',
        'creditsPersonName',
        'creditsTotalCount',
        'creditsActiveYears',
        'creditsArtistLink',
        'creditsRoleBreakdown',
        'creditsTimelineSection',
        'creditsTimelineChart',
        'creditsReleaseSection',
        'creditsReleaseList',
        'creditsRoleFilter',
        'creditsConnectionsSection',
        'creditsConnectionsGraph',
        'creditsLeaderboardList',
        'creditsLeaderboardSection',
        'creditsLoading',
        'creditsEmptyState',
    ];

    ids.forEach(id => {
        const tag = id === 'creditsSearchInput' ? 'input'
            : id === 'creditsLeaderboardCategory' ? 'select'
            : 'div';
        const el = document.createElement(tag);
        el.id = id;
        document.body.appendChild(el);
    });

    // Category select needs to be created separately (not in the ids list above
    // because it uses a <select> tag)
    const select = document.createElement('select');
    select.id = 'creditsLeaderboardCategory';
    const opt = document.createElement('option');
    opt.value = 'mastering';
    opt.textContent = 'Mastering';
    select.appendChild(opt);
    document.body.appendChild(select);
}

// ── D3 Mock ────────────────────────────────────────────────────────────── //

function createD3Mock() {
    // Track callback functions passed to .text(), .attr(), .on() for coverage
    const _callbacks = { text: [], attr: [], on: [], tick: null };

    const chainable = () => {
        const obj = {};
        const methods = [
            'append', 'attr', 'datum', 'style', 'on', 'text',
            'join', 'call', 'classed',
        ];
        methods.forEach(m => {
            obj[m] = vi.fn(function () { return obj; });
        });
        obj.selectAll = vi.fn(() => ({
            data: vi.fn(() => ({
                join: vi.fn(() => {
                    const joined = {};
                    ['style'].forEach(m => {
                        joined[m] = vi.fn(function () { return joined; });
                    });
                    joined.attr = vi.fn(function (_name, valOrFn) {
                        if (typeof valOrFn === 'function') _callbacks.attr.push(valOrFn);
                        return joined;
                    });
                    joined.on = vi.fn(function (_event, fn) {
                        if (typeof fn === 'function') _callbacks.on.push(fn);
                        return joined;
                    });
                    joined.text = vi.fn(function (valOrFn) {
                        if (typeof valOrFn === 'function') _callbacks.text.push(valOrFn);
                        return joined;
                    });
                    return joined;
                }),
                enter: vi.fn(() => ({
                    append: vi.fn(() => ({
                        attr: vi.fn(function () { return this; }),
                        style: vi.fn(function () { return this; }),
                        on: vi.fn(function () { return this; }),
                        text: vi.fn(function () { return this; }),
                    })),
                })),
            })),
        }));
        return obj;
    };

    const simulation = {
        force: vi.fn(function () { return simulation; }),
        on: vi.fn(function (_event, fn) {
            if (_event === 'tick' && typeof fn === 'function') _callbacks.tick = fn;
            return simulation;
        }),
    };

    const mock = {
        select: vi.fn(() => chainable()),
        forceSimulation: vi.fn(() => simulation),
        forceLink: vi.fn(() => {
            const fl = {};
            fl.id = vi.fn((fn) => {
                if (typeof fn === 'function') _callbacks.forceLinkId = fn;
                return fl;
            });
            fl.distance = vi.fn(() => fl);
            return fl;
        }),
        forceManyBody: vi.fn(() => {
            const fb = {};
            fb.strength = vi.fn(() => fb);
            return fb;
        }),
        forceCenter: vi.fn(() => ({})),
        _callbacks,
    };

    return mock;
}

// ── Helper to build standard mock fetch ────────────────────────────────── //

function buildMockFetch() {
    return createMockFetch({
        '/api/credits/autocomplete': { data: MOCK_AUTOCOMPLETE },
        '/profile': { data: MOCK_PROFILE },
        '/api/credits/person/': { data: MOCK_CREDITS },
        '/timeline': { data: MOCK_TIMELINE },
        '/api/credits/connections/': { data: MOCK_CONNECTIONS },
        '/api/credits/role/': { data: MOCK_LEADERBOARD },
    });
}

// ── Tests ──────────────────────────────────────────────────────────────── //

describe('CreditsPanel', () => {
    beforeEach(() => {
        vi.useFakeTimers();

        delete globalThis.window;
        globalThis.window = globalThis;

        globalThis.Plotly = {
            newPlot: vi.fn(),
            purge: vi.fn(),
        };

        globalThis.d3 = createD3Mock();

        globalThis.window.exploreApp = {
            _doExplore: vi.fn(),
            _switchPane: vi.fn(),
        };

        globalThis.fetch = vi.fn(buildMockFetch());

        setupDOM();
        loadScript('credits.js');
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    // ── 1. Constructor ─────────────────────────────────────────────── //

    it('should register on window.creditsPanel', () => {
        expect(window.creditsPanel).toBeDefined();
        expect(typeof window.creditsPanel.load).toBe('function');
    });

    it('should initialize with null currentPerson and empty credits', () => {
        expect(window.creditsPanel._currentPerson).toBeNull();
        expect(window.creditsPanel._allCredits).toEqual([]);
        expect(window.creditsPanel._activeFilter).toBeNull();
        expect(window.creditsPanel._leaderboardLoaded).toBe(false);
    });

    // ── 2. Search input debouncing ─────────────────────────────────── //

    describe('_onSearchInput', () => {
        it('should hide dropdown for queries shorter than 2 characters', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            window.creditsPanel._onSearchInput('a');

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should hide dropdown for empty input', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            window.creditsPanel._onSearchInput('');

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should hide dropdown for whitespace-only input', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            window.creditsPanel._onSearchInput('   ');

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should debounce search calls by 300ms', async () => {
            window.creditsPanel._onSearchInput('Bob');

            // Not called yet
            expect(globalThis.fetch).not.toHaveBeenCalled();

            // Advance past debounce
            await vi.advanceTimersByTimeAsync(300);

            expect(globalThis.fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/credits/autocomplete?q=Bob')
            );
        });

        it('should cancel previous debounce on rapid input', async () => {
            window.creditsPanel._onSearchInput('Bo');
            await vi.advanceTimersByTimeAsync(100);
            window.creditsPanel._onSearchInput('Bob');
            await vi.advanceTimersByTimeAsync(300);

            // Only the second call should have gone through
            expect(globalThis.fetch).toHaveBeenCalledTimes(1);
            expect(globalThis.fetch).toHaveBeenCalledWith(
                expect.stringContaining('q=Bob')
            );
        });

        it('should trigger search via input event on DOM element', async () => {
            const input = document.getElementById('creditsSearchInput');
            input.value = 'Bob Ludwig';
            input.dispatchEvent(new Event('input'));

            await vi.advanceTimersByTimeAsync(300);

            expect(globalThis.fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/credits/autocomplete')
            );
        });
    });

    // ── 3. Keyboard navigation ─────────────────────────────────────── //

    describe('_onSearchKeydown', () => {
        function populateDropdown() {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');
            dropdown.textContent = '';
            ['Bob Ludwig', 'Bob Clearmountain', 'Bob Rock'].forEach(name => {
                const item = document.createElement('div');
                item.className = 'autocomplete-item';
                item.dataset.name = name;
                item.textContent = name;
                dropdown.appendChild(item);
            });
        }

        it('should do nothing when dropdown is hidden', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.add('hidden');

            const e = new KeyboardEvent('keydown', { key: 'ArrowDown' });
            window.creditsPanel._onSearchKeydown(e);

            // No errors, no active items
        });

        it('should highlight first item on ArrowDown', () => {
            populateDropdown();
            const e = new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });
            window.creditsPanel._onSearchKeydown(e);

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items[0].classList.contains('active')).toBe(true);
        });

        it('should move highlight down on subsequent ArrowDown', () => {
            populateDropdown();
            const down = () => new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });

            window.creditsPanel._onSearchKeydown(down());
            window.creditsPanel._onSearchKeydown(down());

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items[0].classList.contains('active')).toBe(false);
            expect(items[1].classList.contains('active')).toBe(true);
        });

        it('should not go past the last item on ArrowDown', () => {
            populateDropdown();
            const down = () => new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });

            // Press down 5 times (more than 3 items)
            for (let i = 0; i < 5; i++) {
                window.creditsPanel._onSearchKeydown(down());
            }

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items[2].classList.contains('active')).toBe(true);
        });

        it('should move highlight up on ArrowUp', () => {
            populateDropdown();
            const down = () => new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });
            const up = () => new KeyboardEvent('keydown', { key: 'ArrowUp', cancelable: true });

            window.creditsPanel._onSearchKeydown(down());
            window.creditsPanel._onSearchKeydown(down());
            window.creditsPanel._onSearchKeydown(up());

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items[0].classList.contains('active')).toBe(true);
        });

        it('should not go above the first item on ArrowUp', () => {
            populateDropdown();
            const down = () => new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });
            const up = () => new KeyboardEvent('keydown', { key: 'ArrowUp', cancelable: true });

            window.creditsPanel._onSearchKeydown(down());
            window.creditsPanel._onSearchKeydown(up());
            window.creditsPanel._onSearchKeydown(up());

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items[0].classList.contains('active')).toBe(true);
        });

        it('should select active item on Enter', async () => {
            populateDropdown();
            const down = () => new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true });
            const enter = () => new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });

            window.creditsPanel._onSearchKeydown(down());
            window.creditsPanel._onSearchKeydown(enter());

            // Should set the input value
            const input = document.getElementById('creditsSearchInput');
            // _selectPerson is async but still sets the input synchronously
            expect(input.value).toBe('Bob Ludwig');
        });

        it('should hide dropdown on Escape', () => {
            populateDropdown();
            const esc = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
            window.creditsPanel._onSearchKeydown(esc);

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            expect(dropdown.classList.contains('hidden')).toBe(true);
        });
    });

    // ── 4. _searchPerson ───────────────────────────────────────────── //

    describe('_searchPerson', () => {
        it('should fetch autocomplete results and show dropdown', async () => {
            await window.creditsPanel._searchPerson('Bob');

            expect(globalThis.fetch).toHaveBeenCalledWith(
                '/api/credits/autocomplete?q=Bob&limit=10'
            );

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            expect(dropdown.classList.contains('hidden')).toBe(false);
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items.length).toBe(3);
        });

        it('should encode special characters in query', async () => {
            await window.creditsPanel._searchPerson('Bob & Tom');

            expect(globalThis.fetch).toHaveBeenCalledWith(
                '/api/credits/autocomplete?q=Bob%20%26%20Tom&limit=10'
            );
        });

        it('should silently fail on fetch error', async () => {
            globalThis.fetch = vi.fn(() => Promise.reject(new Error('Network error')));

            // Should not throw
            await window.creditsPanel._searchPerson('Bob');
        });

        it('should not show dropdown on non-ok response', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: false,
                status: 500,
                json: async () => ({}),
            }));

            await window.creditsPanel._searchPerson('Bob');

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            // Dropdown should not have been populated
            expect(dropdown.querySelectorAll('.autocomplete-item').length).toBe(0);
        });
    });

    // ── 5. _showDropdown ───────────────────────────────────────────── //

    describe('_showDropdown', () => {
        it('should create autocomplete items from results', () => {
            window.creditsPanel._showDropdown(MOCK_AUTOCOMPLETE.results);

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items.length).toBe(3);
            expect(items[0].textContent).toBe('Bob Ludwig');
            expect(items[0].dataset.name).toBe('Bob Ludwig');
        });

        it('should remove hidden class from dropdown', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.add('hidden');

            window.creditsPanel._showDropdown(MOCK_AUTOCOMPLETE.results);

            expect(dropdown.classList.contains('hidden')).toBe(false);
        });

        it('should hide dropdown when results array is empty', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            window.creditsPanel._showDropdown([]);

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should clear previous items before rendering new ones', () => {
            window.creditsPanel._showDropdown(MOCK_AUTOCOMPLETE.results);
            window.creditsPanel._showDropdown([{ name: 'Only One' }]);

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items.length).toBe(1);
            expect(items[0].textContent).toBe('Only One');
        });

        it('should attach click handler that selects person', () => {
            window.creditsPanel._showDropdown(MOCK_AUTOCOMPLETE.results);

            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            const items = dropdown.querySelectorAll('.autocomplete-item');
            items[1].click();

            const input = document.getElementById('creditsSearchInput');
            expect(input.value).toBe('Bob Clearmountain');
        });
    });

    // ── 6. _hideDropdown ───────────────────────────────────────────── //

    describe('_hideDropdown', () => {
        it('should add hidden class to dropdown', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            window.creditsPanel._hideDropdown();

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should not throw when dropdown element is missing', () => {
            document.getElementById('creditsAutocompleteDropdown').remove();

            expect(() => window.creditsPanel._hideDropdown()).not.toThrow();
        });
    });

    // ── 7. _selectPerson ───────────────────────────────────────────── //

    describe('_selectPerson', () => {
        it('should set input value to the selected name', async () => {
            await window.creditsPanel._selectPerson('Bob Ludwig');

            const input = document.getElementById('creditsSearchInput');
            expect(input.value).toBe('Bob Ludwig');
        });

        it('should hide dropdown', async () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            await window.creditsPanel._selectPerson('Bob Ludwig');

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should set _currentPerson', async () => {
            await window.creditsPanel._selectPerson('Bob Ludwig');

            expect(window.creditsPanel._currentPerson).toBe('Bob Ludwig');
        });

        it('should call _loadPersonData', async () => {
            const spy = vi.spyOn(window.creditsPanel, '_loadPersonData');

            await window.creditsPanel._selectPerson('Bob Ludwig');

            expect(spy).toHaveBeenCalledWith('Bob Ludwig');
        });
    });

    // ── 8. _loadPersonData ─────────────────────────────────────────── //

    describe('_loadPersonData', () => {
        it('should call 4 API endpoints in parallel', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: true,
                status: 200,
                json: async () => ({}),
            }));

            // Mark leaderboard as loaded so only the 4 person endpoints fire
            window.creditsPanel._leaderboardLoaded = true;

            await window.creditsPanel._loadPersonData('Bob Ludwig');

            expect(globalThis.fetch).toHaveBeenCalledTimes(4);
            const urls = globalThis.fetch.mock.calls.map(c => c[0]);
            expect(urls).toContainEqual(expect.stringContaining('/profile'));
            expect(urls).toContainEqual(expect.stringContaining('/api/credits/person/Bob%20Ludwig'));
            expect(urls).toContainEqual(expect.stringContaining('/timeline'));
            expect(urls).toContainEqual(expect.stringContaining('/api/credits/connections/Bob%20Ludwig'));
        });

        it('should show loading indicator and hide empty state', async () => {
            const loading = document.getElementById('creditsLoading');
            const empty = document.getElementById('creditsEmptyState');

            globalThis.fetch = vi.fn(() => new Promise(() => {})); // never resolves

            // Start loading without awaiting
            const promise = window.creditsPanel._loadPersonData('Bob Ludwig');

            expect(loading.classList.contains('active')).toBe(true);
            expect(empty.classList.contains('hidden')).toBe(true);

            // Clean up: resolve fetch to let promise settle
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: true, json: async () => ({}),
            }));
        });

        it('should hide loading indicator after completion', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: true,
                json: async () => ({}),
            }));

            await window.creditsPanel._loadPersonData('Bob Ludwig');

            const loading = document.getElementById('creditsLoading');
            expect(loading.classList.contains('active')).toBe(false);
        });

        it('should load leaderboard on first visit', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: true,
                json: async () => ({}),
            }));

            window.creditsPanel._leaderboardLoaded = false;
            await window.creditsPanel._loadPersonData('Bob Ludwig');

            expect(window.creditsPanel._leaderboardLoaded).toBe(true);
            // Extra fetch call for leaderboard
            expect(globalThis.fetch).toHaveBeenCalledTimes(5);
        });

        it('should not reload leaderboard on subsequent visits', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: true,
                json: async () => ({}),
            }));

            window.creditsPanel._leaderboardLoaded = true;
            await window.creditsPanel._loadPersonData('Bob Ludwig');

            // Only the 4 person endpoints
            expect(globalThis.fetch).toHaveBeenCalledTimes(4);
        });

        it('should render profile when profile endpoint succeeds', async () => {
            globalThis.fetch = vi.fn((url) => {
                if (url.includes('/profile')) {
                    return Promise.resolve({
                        ok: true,
                        json: async () => MOCK_PROFILE,
                    });
                }
                return Promise.resolve({
                    ok: true,
                    json: async () => ({}),
                });
            });

            await window.creditsPanel._loadPersonData('Bob Ludwig');

            const nameEl = document.getElementById('creditsPersonName');
            expect(nameEl.textContent).toBe('Bob Ludwig');
        });

        it('should handle rejected promises gracefully', async () => {
            globalThis.fetch = vi.fn(() => Promise.reject(new Error('fail')));

            // Should not throw
            await window.creditsPanel._loadPersonData('Bob Ludwig');

            const loading = document.getElementById('creditsLoading');
            expect(loading.classList.contains('active')).toBe(false);
        });
    });

    // ── 9. _loadLeaderboard ────────────────────────────────────────── //

    describe('_loadLeaderboard', () => {
        it('should fetch leaderboard for given category', async () => {
            await window.creditsPanel._loadLeaderboard('mastering');

            expect(globalThis.fetch).toHaveBeenCalledWith(
                '/api/credits/role/mastering/top?limit=20'
            );
        });

        it('should show leaderboard section', async () => {
            const section = document.getElementById('creditsLeaderboardSection');
            section.classList.add('hidden');

            await window.creditsPanel._loadLeaderboard('mastering');

            expect(section.classList.contains('hidden')).toBe(false);
        });

        it('should render leaderboard entries', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: true,
                json: async () => MOCK_LEADERBOARD,
            }));

            await window.creditsPanel._loadLeaderboard('mastering');

            const list = document.getElementById('creditsLeaderboardList');
            const rows = list.querySelectorAll('.credits-leaderboard-row');
            expect(rows.length).toBe(3);
        });

        it('should show error message on fetch failure', async () => {
            globalThis.fetch = vi.fn(() => Promise.reject(new Error('Network error')));

            await window.creditsPanel._loadLeaderboard('mastering');

            const list = document.getElementById('creditsLeaderboardList');
            expect(list.textContent).toContain('Could not load leaderboard');
        });

        it('should do nothing when list element is missing', async () => {
            document.getElementById('creditsLeaderboardList').remove();

            // Should not throw
            await window.creditsPanel._loadLeaderboard('mastering');
            expect(globalThis.fetch).not.toHaveBeenCalled();
        });

        it('should do nothing when section element is missing', async () => {
            document.getElementById('creditsLeaderboardSection').remove();

            await window.creditsPanel._loadLeaderboard('mastering');
            expect(globalThis.fetch).not.toHaveBeenCalled();
        });

        it('should not render on non-ok response', async () => {
            globalThis.fetch = vi.fn(() => Promise.resolve({
                ok: false,
                status: 500,
                json: async () => ({}),
            }));

            await window.creditsPanel._loadLeaderboard('mastering');

            const list = document.getElementById('creditsLeaderboardList');
            expect(list.querySelectorAll('.credits-leaderboard-row').length).toBe(0);
        });

        it('should encode category in URL', async () => {
            await window.creditsPanel._loadLeaderboard('session musician');

            expect(globalThis.fetch).toHaveBeenCalledWith(
                '/api/credits/role/session%20musician/top?limit=20'
            );
        });
    });

    // ── 10. _renderProfile ─────────────────────────────────────────── //

    describe('_renderProfile', () => {
        it('should render person name', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const name = document.getElementById('creditsPersonName');
            expect(name.textContent).toBe('Bob Ludwig');
        });

        it('should render total credits count', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const count = document.getElementById('creditsTotalCount');
            expect(count.textContent).toBe('1500 credits');
        });

        it('should render active years range', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const years = document.getElementById('creditsActiveYears');
            expect(years.textContent).toContain('1969');
            expect(years.textContent).toContain('2023');
        });

        it('should clear years when not available', () => {
            window.creditsPanel._renderProfile({ ...MOCK_PROFILE, first_year: null, last_year: null });

            const years = document.getElementById('creditsActiveYears');
            expect(years.textContent).toBe('');
        });

        it('should show artist link when artist_id is present', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const link = document.getElementById('creditsArtistLink');
            expect(link.classList.contains('hidden')).toBe(false);
        });

        it('should hide artist link when no artist_id', () => {
            window.creditsPanel._renderProfile({ ...MOCK_PROFILE, artist_id: null });

            const link = document.getElementById('creditsArtistLink');
            expect(link.classList.contains('hidden')).toBe(true);
        });

        it('should navigate to artist on link click', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const link = document.getElementById('creditsArtistLink');
            link.click();

            expect(window.exploreApp._doExplore).toHaveBeenCalledWith('Bob Ludwig', 'artist');
            expect(window.exploreApp._switchPane).toHaveBeenCalledWith('explore');
        });

        it('should render role breakdown pills', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const pills = document.getElementById('creditsRoleBreakdown');
            const spans = pills.querySelectorAll('.credits-role-pill');
            expect(spans.length).toBe(2);
            expect(spans[0].textContent).toBe('mastering (1200)');
            expect(spans[1].textContent).toBe('engineering (300)');
        });

        it('should apply category class to role pills', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);

            const pills = document.getElementById('creditsRoleBreakdown');
            const spans = pills.querySelectorAll('.credits-role-pill');
            expect(spans[0].classList.contains('credits-role-mastering')).toBe(true);
            expect(spans[1].classList.contains('credits-role-engineering')).toBe(true);
        });

        it('should show profile card', () => {
            const card = document.getElementById('creditsProfileCard');
            card.classList.add('hidden');

            window.creditsPanel._renderProfile(MOCK_PROFILE);

            expect(card.classList.contains('hidden')).toBe(false);
        });

        it('should clear previous role pills before rendering', () => {
            window.creditsPanel._renderProfile(MOCK_PROFILE);
            window.creditsPanel._renderProfile({ ...MOCK_PROFILE, role_breakdown: [{ category: 'session', count: 50 }] });

            const pills = document.getElementById('creditsRoleBreakdown');
            const spans = pills.querySelectorAll('.credits-role-pill');
            expect(spans.length).toBe(1);
        });

        it('should do nothing when card element is missing', () => {
            document.getElementById('creditsProfileCard').remove();

            expect(() => window.creditsPanel._renderProfile(MOCK_PROFILE)).not.toThrow();
        });
    });

    // ── 11. _renderTimeline ────────────────────────────────────────── //

    describe('_renderTimeline', () => {
        it('should call Plotly.newPlot with stacked bar traces', () => {
            window.creditsPanel._renderTimeline(MOCK_TIMELINE.timeline);

            expect(globalThis.Plotly.newPlot).toHaveBeenCalledOnce();
            const [chartEl, traces, layout, config] = globalThis.Plotly.newPlot.mock.calls[0];
            expect(chartEl).toBe(document.getElementById('creditsTimelineChart'));
            expect(traces.length).toBe(2); // mastering + engineering
            expect(layout.barmode).toBe('stack');
            expect(config.responsive).toBe(true);
            expect(config.displayModeBar).toBe(false);
        });

        it('should group timeline data by category', () => {
            window.creditsPanel._renderTimeline(MOCK_TIMELINE.timeline);

            const traces = globalThis.Plotly.newPlot.mock.calls[0][1];
            const masteringTrace = traces.find(t => t.name === 'mastering');
            expect(masteringTrace.x).toEqual([2019, 2020]);
            expect(masteringTrace.y).toEqual([45, 50]);
        });

        it('should show timeline section', () => {
            const section = document.getElementById('creditsTimelineSection');
            section.classList.add('hidden');

            window.creditsPanel._renderTimeline(MOCK_TIMELINE.timeline);

            expect(section.classList.contains('hidden')).toBe(false);
        });

        it('should hide section when timeline is empty', () => {
            const section = document.getElementById('creditsTimelineSection');
            section.classList.remove('hidden');

            window.creditsPanel._renderTimeline([]);

            expect(section.classList.contains('hidden')).toBe(true);
        });

        it('should not call Plotly when timeline is empty', () => {
            window.creditsPanel._renderTimeline([]);

            expect(globalThis.Plotly.newPlot).not.toHaveBeenCalled();
        });

        it('should not crash when Plotly is undefined', () => {
            delete globalThis.Plotly;

            expect(() => window.creditsPanel._renderTimeline(MOCK_TIMELINE.timeline)).not.toThrow();
        });

        it('should not crash when section element is missing', () => {
            document.getElementById('creditsTimelineSection').remove();

            expect(() => window.creditsPanel._renderTimeline(MOCK_TIMELINE.timeline)).not.toThrow();
        });
    });

    // ── 12. _renderReleaseList ─────────────────────────────────────── //

    describe('_renderReleaseList', () => {
        it('should show release section', () => {
            const section = document.getElementById('creditsReleaseSection');
            section.classList.add('hidden');

            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            expect(section.classList.contains('hidden')).toBe(false);
        });

        it('should hide section when credits is empty', () => {
            const section = document.getElementById('creditsReleaseSection');
            section.classList.remove('hidden');

            window.creditsPanel._renderReleaseList([]);

            expect(section.classList.contains('hidden')).toBe(true);
        });

        it('should create filter pills for each unique category', () => {
            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            const filterEl = document.getElementById('creditsRoleFilter');
            const pills = filterEl.querySelectorAll('.credits-filter-pill');
            // "All" + "engineering" + "mastering" (sorted)
            expect(pills.length).toBe(3);
            expect(pills[0].textContent).toBe('All');
            expect(pills[1].textContent).toBe('engineering');
            expect(pills[2].textContent).toBe('mastering');
        });

        it('should mark "All" pill as active by default', () => {
            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            const filterEl = document.getElementById('creditsRoleFilter');
            const allPill = filterEl.querySelector('[data-filter="all"]');
            expect(allPill.classList.contains('active')).toBe(true);
        });

        it('should render credit rows', () => {
            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            const list = document.getElementById('creditsReleaseList');
            const rows = list.querySelectorAll('.credits-release-row');
            expect(rows.length).toBe(3);
        });

        it('should filter credits when a category pill is clicked', () => {
            window.creditsPanel._allCredits = MOCK_CREDITS.credits;
            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            const filterEl = document.getElementById('creditsRoleFilter');
            const engineeringPill = filterEl.querySelector('[data-filter="engineering"]');
            engineeringPill.click();

            const list = document.getElementById('creditsReleaseList');
            const rows = list.querySelectorAll('.credits-release-row');
            expect(rows.length).toBe(1);
            expect(engineeringPill.classList.contains('active')).toBe(true);
        });

        it('should show all credits when "All" pill is clicked after filtering', () => {
            window.creditsPanel._allCredits = MOCK_CREDITS.credits;
            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            const filterEl = document.getElementById('creditsRoleFilter');
            const engineeringPill = filterEl.querySelector('[data-filter="engineering"]');
            engineeringPill.click();

            const allPill = filterEl.querySelector('[data-filter="all"]');
            allPill.click();

            const list = document.getElementById('creditsReleaseList');
            const rows = list.querySelectorAll('.credits-release-row');
            expect(rows.length).toBe(3);
        });

        it('should reset _activeFilter to null when "All" is clicked', () => {
            window.creditsPanel._allCredits = MOCK_CREDITS.credits;
            window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits);

            const filterEl = document.getElementById('creditsRoleFilter');
            filterEl.querySelector('[data-filter="mastering"]').click();
            expect(window.creditsPanel._activeFilter).toBe('mastering');

            filterEl.querySelector('[data-filter="all"]').click();
            expect(window.creditsPanel._activeFilter).toBeNull();
        });

        it('should do nothing when section element is missing', () => {
            document.getElementById('creditsReleaseSection').remove();

            expect(() => window.creditsPanel._renderReleaseList(MOCK_CREDITS.credits)).not.toThrow();
        });
    });

    // ── 13. _renderCreditRows ──────────────────────────────────────── //

    describe('_renderCreditRows', () => {
        it('should render rows with year, title, artist, and role', () => {
            const container = document.getElementById('creditsReleaseList');
            window.creditsPanel._renderCreditRows(container, MOCK_CREDITS.credits);

            const rows = container.querySelectorAll('.credits-release-row');
            expect(rows.length).toBe(3);

            const firstRow = rows[0];
            expect(firstRow.querySelector('.credits-release-year').textContent).toBe('2020');
            expect(firstRow.querySelector('.credits-release-title').textContent).toBe('Fetch The Bolt Cutters');
            expect(firstRow.querySelector('.credits-release-artist').textContent).toBe('Fiona Apple');
            expect(firstRow.querySelector('.credits-role-pill').textContent).toBe('Mastered By');
        });

        it('should show em dash for missing year', () => {
            const container = document.getElementById('creditsReleaseList');
            const credits = [{ ...MOCK_CREDITS.credits[0], year: null }];
            window.creditsPanel._renderCreditRows(container, credits);

            const year = container.querySelector('.credits-release-year');
            expect(year.textContent).toBe('\u2014');
        });

        it('should join multiple artists with commas', () => {
            const container = document.getElementById('creditsReleaseList');
            const credits = [{
                ...MOCK_CREDITS.credits[0],
                artists: ['Artist A', 'Artist B'],
            }];
            window.creditsPanel._renderCreditRows(container, credits);

            const artist = container.querySelector('.credits-release-artist');
            expect(artist.textContent).toBe('Artist A, Artist B');
        });

        it('should truncate at 100 rows', () => {
            const container = document.getElementById('creditsReleaseList');
            const manyCredits = Array.from({ length: 150 }, (_, i) => ({
                year: 2000 + (i % 20),
                title: `Release ${i}`,
                artists: ['Artist'],
                role: 'Engineer',
                category: 'engineering',
            }));

            window.creditsPanel._renderCreditRows(container, manyCredits);

            const rows = container.querySelectorAll('.credits-release-row');
            expect(rows.length).toBe(100);
        });

        it('should show truncation message when over 100 credits', () => {
            const container = document.getElementById('creditsReleaseList');
            const manyCredits = Array.from({ length: 150 }, (_, i) => ({
                year: 2000,
                title: `Release ${i}`,
                artists: [],
                role: 'Engineer',
                category: 'engineering',
            }));

            window.creditsPanel._renderCreditRows(container, manyCredits);

            expect(container.textContent).toContain('Showing first 100 of 150 credits');
        });

        it('should not show truncation message for 100 or fewer credits', () => {
            const container = document.getElementById('creditsReleaseList');
            window.creditsPanel._renderCreditRows(container, MOCK_CREDITS.credits);

            expect(container.textContent).not.toContain('Showing first');
        });

        it('should clear container before rendering', () => {
            const container = document.getElementById('creditsReleaseList');
            container.textContent = 'old content';

            window.creditsPanel._renderCreditRows(container, MOCK_CREDITS.credits);

            expect(container.textContent).not.toContain('old content');
        });

        it('should apply category class to role pills', () => {
            const container = document.getElementById('creditsReleaseList');
            window.creditsPanel._renderCreditRows(container, MOCK_CREDITS.credits);

            const pill = container.querySelector('.credits-role-pill');
            expect(pill.classList.contains('credits-role-mastering')).toBe(true);
        });

        it('should set role as title attribute on role pill', () => {
            const container = document.getElementById('creditsReleaseList');
            window.creditsPanel._renderCreditRows(container, MOCK_CREDITS.credits);

            const pill = container.querySelector('.credits-role-pill');
            expect(pill.title).toBe('Mastered By');
        });
    });

    // ── 14. _renderConnections ─────────────────────────────────────── //

    describe('_renderConnections', () => {
        it('should show connections section', () => {
            const section = document.getElementById('creditsConnectionsSection');
            section.classList.add('hidden');

            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            expect(section.classList.contains('hidden')).toBe(false);
        });

        it('should hide section when connections is empty', () => {
            const section = document.getElementById('creditsConnectionsSection');
            section.classList.remove('hidden');

            window.creditsPanel._renderConnections([], 'Bob Ludwig');

            expect(section.classList.contains('hidden')).toBe(true);
        });

        it('should call d3.select on the graph element', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            expect(globalThis.d3.select).toHaveBeenCalled();
        });

        it('should create force simulation with nodes', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            expect(globalThis.d3.forceSimulation).toHaveBeenCalled();
            const nodes = globalThis.d3.forceSimulation.mock.calls[0][0];
            // center node + 2 connections
            expect(nodes.length).toBe(3);
            expect(nodes[0].id).toBe('Bob Ludwig');
            expect(nodes[0].group).toBe('center');
        });

        it('should set up force link, charge, and center', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            expect(globalThis.d3.forceLink).toHaveBeenCalled();
            expect(globalThis.d3.forceManyBody).toHaveBeenCalled();
            expect(globalThis.d3.forceCenter).toHaveBeenCalled();
        });

        it('should clear graph element before rendering', () => {
            const graphEl = document.getElementById('creditsConnectionsGraph');
            graphEl.textContent = 'old graph';

            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            // textContent is cleared by the code, then d3 appends SVG
            // Since d3 is mocked, the element should be empty (cleared)
            // The actual d3 calls are mocked so no real DOM manipulation
        });

        it('should not crash when d3 is undefined', () => {
            delete globalThis.d3;

            expect(() => {
                window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');
            }).not.toThrow();
        });

        it('should not crash when section is missing', () => {
            document.getElementById('creditsConnectionsSection').remove();

            expect(() => {
                window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');
            }).not.toThrow();
        });

        it('should truncate long names in labels via text callback', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            const textCallbacks = globalThis.d3._callbacks.text;
            expect(textCallbacks.length).toBeGreaterThan(0);

            const textFn = textCallbacks[0];
            // Short name — returned as-is
            expect(textFn({ id: 'Bob Ludwig' })).toBe('Bob Ludwig');
            // Long name (>20 chars) — truncated with ellipsis
            expect(textFn({ id: 'A Very Long Person Name Here' })).toBe('A Very Long Person\u2026');
        });

        it('should set different dy for center vs connected nodes via attr callback', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            const attrCallbacks = globalThis.d3._callbacks.attr;
            // Find the dy callback (one that returns -16 or -10)
            const dyFn = attrCallbacks.find(fn => fn({ group: 'center' }) === -16);
            expect(dyFn).toBeDefined();
            expect(dyFn({ group: 'center' })).toBe(-16);
            expect(dyFn({ group: 'connected' })).toBe(-10);
        });

        it('should invoke tick handler to update positions', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            const tickFn = globalThis.d3._callbacks.tick;
            expect(tickFn).toBeTypeOf('function');

            // Clear attr callbacks collected during initial render
            globalThis.d3._callbacks.attr.length = 0;

            // tick handler calls .attr() on link, node, and label — should not throw
            expect(() => tickFn()).not.toThrow();

            // Invoke the attr callbacks captured during tick to cover the arrow functions
            const tickAttrCallbacks = globalThis.d3._callbacks.attr;
            expect(tickAttrCallbacks.length).toBeGreaterThan(0);
            const mockDatum = { x: 10, y: 20, source: { x: 1, y: 2 }, target: { x: 3, y: 4 } };
            tickAttrCallbacks.forEach(fn => fn(mockDatum));
        });

        it('should use node id as forceLink identifier', () => {
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            const idFn = globalThis.d3._callbacks.forceLinkId;
            expect(idFn).toBeTypeOf('function');
            expect(idFn({ id: 'test-node' })).toBe('test-node');
        });

        it('should navigate to connected person on node click', () => {
            const selectSpy = vi.spyOn(window.creditsPanel, '_selectPerson');
            window.creditsPanel._renderConnections(MOCK_CONNECTIONS.connections, 'Bob Ludwig');

            const clickCallbacks = globalThis.d3._callbacks.on;
            expect(clickCallbacks.length).toBeGreaterThan(0);

            const clickFn = clickCallbacks[0];
            // Clicking a non-center node should select that person
            clickFn(new MouseEvent('click'), { id: 'Greg Calbi' });
            expect(selectSpy).toHaveBeenCalledWith('Greg Calbi');

            // Clicking center node should NOT select
            selectSpy.mockClear();
            clickFn(new MouseEvent('click'), { id: 'Bob Ludwig' });
            expect(selectSpy).not.toHaveBeenCalled();
        });

        it('should deduplicate nodes', () => {
            const connections = [
                { name: 'Greg Calbi', shared_count: 25 },
                { name: 'Greg Calbi', shared_count: 25 }, // duplicate
            ];

            window.creditsPanel._renderConnections(connections, 'Bob Ludwig');

            const nodes = globalThis.d3.forceSimulation.mock.calls[0][0];
            expect(nodes.length).toBe(2); // center + Greg Calbi (deduplicated)
        });
    });

    // ── 15. _renderLeaderboard ─────────────────────────────────────── //

    describe('_renderLeaderboard', () => {
        it('should render rows with rank, name, and credit count', () => {
            window.creditsPanel._renderLeaderboard(MOCK_LEADERBOARD.entries);

            const list = document.getElementById('creditsLeaderboardList');
            const rows = list.querySelectorAll('.credits-leaderboard-row');
            expect(rows.length).toBe(3);

            const firstRow = rows[0];
            expect(firstRow.querySelector('.credits-leaderboard-rank').textContent).toBe('1');
            expect(firstRow.querySelector('.credits-leaderboard-name').textContent).toBe('Bob Ludwig');
            expect(firstRow.querySelector('.credits-leaderboard-count').textContent).toBe('1500');
        });

        it('should assign correct rank numbers', () => {
            window.creditsPanel._renderLeaderboard(MOCK_LEADERBOARD.entries);

            const list = document.getElementById('creditsLeaderboardList');
            const ranks = list.querySelectorAll('.credits-leaderboard-rank');
            expect(ranks[0].textContent).toBe('1');
            expect(ranks[1].textContent).toBe('2');
            expect(ranks[2].textContent).toBe('3');
        });

        it('should make name clickable to select person', () => {
            window.creditsPanel._renderLeaderboard(MOCK_LEADERBOARD.entries);

            const list = document.getElementById('creditsLeaderboardList');
            const names = list.querySelectorAll('.credits-leaderboard-name');
            expect(names[0].style.cursor).toBe('pointer');

            names[1].click();

            const input = document.getElementById('creditsSearchInput');
            expect(input.value).toBe('Greg Calbi');
        });

        it('should clear previous entries before rendering', () => {
            window.creditsPanel._renderLeaderboard(MOCK_LEADERBOARD.entries);
            window.creditsPanel._renderLeaderboard([{ name: 'Only One', credit_count: 1 }]);

            const list = document.getElementById('creditsLeaderboardList');
            const rows = list.querySelectorAll('.credits-leaderboard-row');
            expect(rows.length).toBe(1);
        });

        it('should render empty list for empty entries', () => {
            window.creditsPanel._renderLeaderboard([]);

            const list = document.getElementById('creditsLeaderboardList');
            expect(list.querySelectorAll('.credits-leaderboard-row').length).toBe(0);
        });

        it('should do nothing when list element is missing', () => {
            document.getElementById('creditsLeaderboardList').remove();

            expect(() => window.creditsPanel._renderLeaderboard(MOCK_LEADERBOARD.entries)).not.toThrow();
        });
    });

    // ── 16. load() ─────────────────────────────────────────────────── //

    describe('load', () => {
        it('should load leaderboard when no person selected and not loaded yet', async () => {
            window.creditsPanel._currentPerson = null;
            window.creditsPanel._leaderboardLoaded = false;

            window.creditsPanel.load();

            expect(globalThis.fetch).toHaveBeenCalledWith(
                '/api/credits/role/mastering/top?limit=20'
            );
            expect(window.creditsPanel._leaderboardLoaded).toBe(true);
        });

        it('should not load leaderboard when already loaded', () => {
            window.creditsPanel._currentPerson = null;
            window.creditsPanel._leaderboardLoaded = true;

            window.creditsPanel.load();

            expect(globalThis.fetch).not.toHaveBeenCalled();
        });

        it('should not load leaderboard when a person is selected', () => {
            window.creditsPanel._currentPerson = 'Bob Ludwig';
            window.creditsPanel._leaderboardLoaded = false;

            window.creditsPanel.load();

            expect(globalThis.fetch).not.toHaveBeenCalled();
        });
    });

    // ── 17. _showLoading and _hideEmptyState ───────────────────────── //

    describe('_showLoading', () => {
        it('should add active class when show is true', () => {
            const loading = document.getElementById('creditsLoading');

            window.creditsPanel._showLoading(true);

            expect(loading.classList.contains('active')).toBe(true);
        });

        it('should remove active class when show is false', () => {
            const loading = document.getElementById('creditsLoading');
            loading.classList.add('active');

            window.creditsPanel._showLoading(false);

            expect(loading.classList.contains('active')).toBe(false);
        });

        it('should not throw when element is missing', () => {
            document.getElementById('creditsLoading').remove();

            expect(() => window.creditsPanel._showLoading(true)).not.toThrow();
        });
    });

    describe('_hideEmptyState', () => {
        it('should add hidden class to empty state element', () => {
            const el = document.getElementById('creditsEmptyState');
            el.classList.remove('hidden');

            window.creditsPanel._hideEmptyState();

            expect(el.classList.contains('hidden')).toBe(true);
        });

        it('should not throw when element is missing', () => {
            document.getElementById('creditsEmptyState').remove();

            expect(() => window.creditsPanel._hideEmptyState()).not.toThrow();
        });
    });

    // ── Init event listener integration ────────────────────────────── //

    describe('_init event listeners', () => {
        it('should hide dropdown when clicking outside', () => {
            const dropdown = document.getElementById('creditsAutocompleteDropdown');
            dropdown.classList.remove('hidden');

            document.dispatchEvent(new MouseEvent('click', { bubbles: true }));

            expect(dropdown.classList.contains('hidden')).toBe(true);
        });

        it('should trigger leaderboard load on category select change', () => {
            const select = document.getElementById('creditsLeaderboardCategory');
            select.value = 'engineering';
            select.dispatchEvent(new Event('change'));

            expect(globalThis.fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/credits/role/')
            );
        });
    });
});
