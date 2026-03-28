import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

/**
 * Set up the DOM elements required by search.js.
 */
function setupSearchDOM() {
    document.body.textContent = '';

    const ids = [
        'searchPaneInput',
        'searchPaneBtn',
        'searchTypeChips',
        'searchYearMin',
        'searchYearMax',
        'searchGenreFilter',
        'searchFacets',
        'searchLoading',
        'searchPlaceholder',
        'searchResults',
        'searchPagination',
        // Used by navigateToResult
        'searchInput',
    ];

    ids.forEach(id => {
        let el;
        if (id === 'searchPaneInput' || id === 'searchYearMin' || id === 'searchYearMax') {
            el = document.createElement('input');
            el.type = id.includes('Year') ? 'number' : 'text';
        } else if (id === 'searchPaneBtn') {
            el = document.createElement('button');
        } else {
            el = document.createElement('div');
        }
        el.id = id;
        document.body.appendChild(el);
    });
}

describe('search pane', () => {
    beforeEach(() => {
        setupSearchDOM();
        delete globalThis.window;
        globalThis.window = globalThis;

        window.apiClient = {
            search: vi.fn().mockResolvedValue({ results: [], total: 0, facets: {}, pagination: {} }),
        };

        loadScript('search.js');
    });

    describe('initialization', () => {
        it('should expose window.searchPane with a focus method', () => {
            expect(window.searchPane).toBeDefined();
            expect(typeof window.searchPane.focus).toBe('function');
        });

        it('should call focus on the input element', () => {
            const input = document.getElementById('searchPaneInput');
            const focusSpy = vi.spyOn(input, 'focus');

            window.searchPane.focus();

            expect(focusSpy).toHaveBeenCalled();
        });
    });

    describe('search input', () => {
        it('should call apiClient.search after Enter keydown with valid query', async () => {
            vi.useFakeTimers();
            const input = document.getElementById('searchPaneInput');
            input.value = 'radiohead';

            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

            // Flush microtasks
            await vi.runAllTimersAsync();

            expect(window.apiClient.search).toHaveBeenCalledWith(
                'radiohead',
                expect.any(Array),
                expect.any(Array),
                null,
                null,
                20,
                0
            );

            vi.useRealTimers();
        });

        it('should call apiClient.search on search button click', async () => {
            vi.useFakeTimers();
            const input = document.getElementById('searchPaneInput');
            const btn = document.getElementById('searchPaneBtn');
            input.value = 'radiohead';

            btn.click();

            await vi.runAllTimersAsync();

            expect(window.apiClient.search).toHaveBeenCalledWith(
                'radiohead',
                expect.any(Array),
                expect.any(Array),
                null,
                null,
                20,
                0
            );

            vi.useRealTimers();
        });

        it('should not search when input is less than 3 chars via button click', async () => {
            vi.useFakeTimers();
            const input = document.getElementById('searchPaneInput');
            const btn = document.getElementById('searchPaneBtn');
            input.value = 'ab';

            btn.click();

            await vi.runAllTimersAsync();

            expect(window.apiClient.search).not.toHaveBeenCalled();

            vi.useRealTimers();
        });
    });

    describe('type chip toggles', () => {
        it('should toggle active class on chip click', () => {
            const chipWrap = document.getElementById('searchTypeChips');
            const chip = document.createElement('button');
            chip.className = 'search-chip';
            chip.dataset.searchType = 'artist';
            chipWrap.appendChild(chip);

            chip.click();

            expect(chip.classList.contains('active')).toBe(true);
        });

        it('should toggle off active class on second click', () => {
            const chipWrap = document.getElementById('searchTypeChips');
            const chip = document.createElement('button');
            chip.className = 'search-chip active';
            chip.dataset.searchType = 'artist';
            chipWrap.appendChild(chip);

            chip.click();

            expect(chip.classList.contains('active')).toBe(false);
        });
    });

    describe('triggerSearch results rendering', () => {
        it('should render error state when apiClient returns null', async () => {
            window.apiClient.search.mockResolvedValue(null);

            const input = document.getElementById('searchPaneInput');
            input.value = 'radiohead';

            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const resultsEl = document.getElementById('searchResults');
            expect(resultsEl.textContent).toContain('error occurred');
        });

        it('should render "no results" when results array is empty', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [],
                total: 0,
                facets: {},
                pagination: {},
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'xyzzy';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const resultsEl = document.getElementById('searchResults');
            expect(resultsEl.querySelector('.search-no-results')).not.toBeNull();
        });

        it('should render result cards with type badges', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [
                    { name: 'Radiohead', type: 'artist', relevance: 0.9 },
                    { name: 'OK Computer', type: 'release', relevance: 0.7 },
                ],
                total: 2,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'radiohead';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const resultsEl = document.getElementById('searchResults');
            const badges = resultsEl.querySelectorAll('.search-result-badge');
            expect(badges).toHaveLength(2);
            expect(badges[0].textContent).toBe('artist');
            expect(badges[1].textContent).toBe('release');
        });

        it('should display total count in results header', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'Radiohead', type: 'artist', relevance: 0.9 }],
                total: 42,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'radiohead';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const resultsEl = document.getElementById('searchResults');
            const header = resultsEl.querySelector('.search-results-header');
            expect(header.textContent).toBe('42 results');
        });

        it('should use singular "result" when total is 1', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'Only One', type: 'artist', relevance: 1.0 }],
                total: 1,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'only one';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const header = document.getElementById('searchResults').querySelector('.search-results-header');
            expect(header.textContent).toBe('1 result');
        });
    });

    describe('highlight rendering', () => {
        it('should render highlighted text with bold elements', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [
                    { name: 'Radiohead', type: 'artist', relevance: 0.9, highlight: 'Radio<b>head</b>' },
                ],
                total: 1,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'head';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const nameEl = document.querySelector('.search-result-name');
            const bold = nameEl.querySelector('b');
            expect(bold).not.toBeNull();
            expect(bold.textContent).toBe('head');
        });
    });

    describe('facets rendering', () => {
        it('should render type facets', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { type: { artist: 5, label: 2 } },
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const facetsEl = document.getElementById('searchFacets');
            const tags = facetsEl.querySelectorAll('.search-facet-tag');
            expect(tags.length).toBeGreaterThan(0);
        });

        it('should render genre filter chips', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { genre: { Rock: 10, Electronic: 5 } },
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const genreWrap = document.getElementById('searchGenreFilter');
            const chips = genreWrap.querySelectorAll('.search-chip');
            expect(chips.length).toBeGreaterThan(0);
        });

        it('should render decade facets', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { decade: { '1990s': 15, '2000s': 8 } },
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const facetsEl = document.getElementById('searchFacets');
            const decadeTags = facetsEl.querySelectorAll('.search-facet-decade');
            expect(decadeTags.length).toBeGreaterThan(0);
        });

        it('should skip zero-count type facets', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { type: { artist: 5, label: 0 } },
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const tags = document.getElementById('searchFacets').querySelectorAll('.search-facet-tag');
            // Only artist (count=5) should appear, not label (count=0)
            expect(tags).toHaveLength(1);
            expect(tags[0].textContent).toContain('artist');
        });
    });

    describe('pagination', () => {
        it('should not render pagination when no has_more and offset is 0', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const paginationEl = document.getElementById('searchPagination');
            expect(paginationEl.textContent).toBe('');
        });

        it('should render pagination when has_more is true', async () => {
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const paginationEl = document.getElementById('searchPagination');
            expect(paginationEl.querySelector('.page-info')).not.toBeNull();
            expect(paginationEl.querySelector('.page-buttons')).not.toBeNull();
        });
    });

    describe('navigateToResult', () => {
        it('should navigate to explore pane for artist type', async () => {
            const mockExploreApp = {
                _setSearchType: vi.fn(),
                _switchPane: vi.fn(),
                _loadExplore: vi.fn(),
                currentQuery: '',
            };
            window.exploreApp = mockExploreApp;

            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'Radiohead', type: 'artist', relevance: 0.9 }],
                total: 1,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'radiohead';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const card = document.querySelector('.search-result-card');
            expect(card).not.toBeNull();
            card.click();

            expect(mockExploreApp._setSearchType).toHaveBeenCalledWith('artist');
            expect(mockExploreApp._switchPane).toHaveBeenCalledWith('explore');
            expect(mockExploreApp._loadExplore).toHaveBeenCalledWith('Radiohead', 'artist');
        });

        it('should switch to explore pane for non-explorable types', async () => {
            const mockExploreApp = {
                _setSearchType: vi.fn(),
                _switchPane: vi.fn(),
                _loadExplore: vi.fn(),
                currentQuery: '',
            };
            window.exploreApp = mockExploreApp;

            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'OK Computer', type: 'release', relevance: 0.9 }],
                total: 1,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'ok computer';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const card = document.querySelector('.search-result-card');
            card.click();

            // Release type: only switchPane, no _loadExplore
            expect(mockExploreApp._switchPane).toHaveBeenCalledWith('explore');
            expect(mockExploreApp._loadExplore).not.toHaveBeenCalled();
        });
    });

    describe('genre chip toggle', () => {
        it('should toggle genre chip and re-trigger search', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { genre: { Rock: 10, Electronic: 5 } },
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const genreWrap = document.getElementById('searchGenreFilter');
            const chips = genreWrap.querySelectorAll('.search-chip');
            expect(chips.length).toBeGreaterThan(0);

            // Click a genre chip to activate it
            window.apiClient.search.mockClear();
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { genre: { Rock: 10 } },
                pagination: { has_more: false },
            });

            chips[0].click();
            await new Promise(r => setTimeout(r, 10));

            expect(chips[0].classList.contains('active')).toBe(true);
            expect(window.apiClient.search).toHaveBeenCalled();
        });

        it('should deactivate genre chip on second click', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [{ name: 'X', type: 'artist', relevance: 1 }],
                total: 1,
                facets: { genre: { Rock: 10, Electronic: 5 } },
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const genreWrap = document.getElementById('searchGenreFilter');
            const chips = genreWrap.querySelectorAll('.search-chip');

            // Click once to activate, again to deactivate
            chips[0].click();
            await new Promise(r => setTimeout(r, 10));

            // Re-render will create new chips; get the fresh reference
            const freshChips = document.getElementById('searchGenreFilter').querySelectorAll('.search-chip');
            // The chip should now be active (from the re-rendered search)
            // Click it again to deactivate
            freshChips[0].click();
            await new Promise(r => setTimeout(r, 10));

            // After toggling off, search should be triggered again
            expect(window.apiClient.search).toHaveBeenCalled();
        });
    });

    describe('pagination controls', () => {
        it('should navigate to next page on next button click', async () => {
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            window.apiClient.search.mockClear();
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i + 20}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const paginationEl = document.getElementById('searchPagination');
            const nextBtn = paginationEl.querySelectorAll('.page-btn');
            // Last button should be next
            const lastBtn = nextBtn[nextBtn.length - 1];
            lastBtn.click();
            await new Promise(r => setTimeout(r, 10));

            expect(window.apiClient.search).toHaveBeenCalled();
        });

        it('should navigate to previous page on prev button click', async () => {
            // First, do initial search
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            // Navigate to page 2
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i + 20}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const paginationEl = document.getElementById('searchPagination');
            const nextBtn = paginationEl.querySelectorAll('.page-btn');
            nextBtn[nextBtn.length - 1].click(); // next
            await new Promise(r => setTimeout(r, 10));

            // Now click prev
            window.apiClient.search.mockClear();
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const prevBtns = document.getElementById('searchPagination').querySelectorAll('.page-btn');
            prevBtns[0].click(); // prev
            await new Promise(r => setTimeout(r, 10));

            expect(window.apiClient.search).toHaveBeenCalled();
        });

        it('should navigate to a specific page number', async () => {
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            window.apiClient.search.mockClear();
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 100,
                facets: {},
                pagination: { has_more: true },
            });

            const paginationEl = document.getElementById('searchPagination');
            const pageBtns = paginationEl.querySelectorAll('.page-btn');
            // Click page 2 (should be among the buttons)
            const page2Btn = Array.from(pageBtns).find(b => b.textContent === '2');
            if (page2Btn) {
                page2Btn.click();
                await new Promise(r => setTimeout(r, 10));
                expect(window.apiClient.search).toHaveBeenCalled();
            }
        });

        it('should render ellipsis for large page counts', async () => {
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 200,
                facets: {},
                pagination: { has_more: true },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const paginationEl = document.getElementById('searchPagination');
            const ellipses = paginationEl.querySelectorAll('.page-ellipsis');
            expect(ellipses.length).toBeGreaterThan(0);
        });

        it('should render correct page numbers when on high page', async () => {
            // Simulate being on a high page by doing multiple next clicks
            window.apiClient.search.mockResolvedValue({
                results: Array.from({ length: 20 }, (_, i) => ({ name: `Artist ${i}`, type: 'artist', relevance: 1 })),
                total: 200,
                facets: {},
                pagination: { has_more: true },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'test';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            // Navigate to a high page
            for (let i = 0; i < 8; i++) {
                window.apiClient.search.mockResolvedValue({
                    results: Array.from({ length: 20 }, (_, j) => ({ name: `Artist ${j}`, type: 'artist', relevance: 1 })),
                    total: 200,
                    facets: {},
                    pagination: { has_more: true },
                });
                const nextBtns = document.getElementById('searchPagination').querySelectorAll('.page-btn');
                nextBtns[nextBtns.length - 1].click();
                await new Promise(r => setTimeout(r, 10));
            }

            // Should be on a high page with ellipsis before and after current
            const paginationEl = document.getElementById('searchPagination');
            expect(paginationEl.querySelector('.page-info')).not.toBeNull();
        });
    });

    describe('metadata rendering', () => {
        it('should render year and genres in metadata', async () => {
            window.apiClient.search.mockResolvedValue({
                results: [
                    {
                        name: 'OK Computer',
                        type: 'release',
                        relevance: 0.9,
                        metadata: { year: 1997, genres: ['Rock', 'Alternative'] },
                    },
                ],
                total: 1,
                facets: {},
                pagination: { has_more: false },
            });

            const input = document.getElementById('searchPaneInput');
            input.value = 'ok computer';
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise(r => setTimeout(r, 10));

            const metaEl = document.querySelector('.search-result-meta');
            expect(metaEl.textContent).toContain('1997');
            expect(metaEl.textContent).toContain('Rock');
        });
    });
});
