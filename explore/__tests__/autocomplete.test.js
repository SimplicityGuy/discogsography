import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Set up the DOM elements required by autocomplete.js.
 */
function setupAutocompleteDOM() {
    document.body.textContent = '';

    const input = document.createElement('input');
    input.id = 'searchInput';
    input.type = 'text';
    document.body.appendChild(input);

    const dropdown = document.createElement('div');
    dropdown.id = 'autocompleteDropdown';
    document.body.appendChild(dropdown);

    const searchBtn = document.createElement('button');
    searchBtn.id = 'searchBtn';
    document.body.appendChild(searchBtn);
}

describe('Autocomplete', () => {
    let instance;

    beforeAll(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        loadScriptDirect('autocomplete.js');
    });

    beforeEach(() => {
        setupAutocompleteDOM();
        // Provide a minimal apiClient stub
        window.apiClient = {
            autocomplete: vi.fn().mockResolvedValue([]),
        };
        // Instantiate with fresh DOM
        instance = new Autocomplete();
        window._testAutocomplete = instance;
    });

    describe('constructor', () => {
        it('should initialize with default state', () => {
            expect(instance.activeIndex).toBe(-1);
            expect(instance.results).toEqual([]);
            expect(instance.onSelect).toBeNull();
            expect(instance.debounceMs).toBe(300);
            expect(instance.minChars).toBe(2);
        });

        it('should reference the DOM elements', () => {
            expect(instance.input).toBe(document.getElementById('searchInput'));
            expect(instance.dropdown).toBe(document.getElementById('autocompleteDropdown'));
        });
    });

    describe('close', () => {
        it('should remove show class and reset activeIndex', () => {
            const dropdown = document.getElementById('autocompleteDropdown');
            dropdown.classList.add('show');
            instance.activeIndex = 2;

            instance.close();

            expect(dropdown.classList.contains('show')).toBe(false);
            expect(instance.activeIndex).toBe(-1);
        });
    });

    describe('_render', () => {
        it('should close when results are empty', () => {
            const dropdown = document.getElementById('autocompleteDropdown');
            dropdown.classList.add('show');
            instance.results = [];

            instance._render();

            expect(dropdown.classList.contains('show')).toBe(false);
        });

        it('should render items and show dropdown', () => {
            instance.results = [
                { name: 'Radiohead' },
                { name: 'Radiohead Jr' },
            ];
            instance._render();

            const dropdown = document.getElementById('autocompleteDropdown');
            expect(dropdown.classList.contains('show')).toBe(true);
            const items = dropdown.querySelectorAll('.autocomplete-item');
            expect(items).toHaveLength(2);
            expect(items[0].querySelector('.name').textContent).toBe('Radiohead');
            expect(items[1].querySelector('.name').textContent).toBe('Radiohead Jr');
        });

        it('should mark the active item with active class', () => {
            instance.results = [{ name: 'A' }, { name: 'B' }, { name: 'C' }];
            instance.activeIndex = 1;
            instance._render();

            const items = document.getElementById('autocompleteDropdown').querySelectorAll('.autocomplete-item');
            expect(items[0].classList.contains('active')).toBe(false);
            expect(items[1].classList.contains('active')).toBe(true);
            expect(items[2].classList.contains('active')).toBe(false);
        });
    });

    describe('_selectItem', () => {
        it('should set input value and call onSelect', () => {
            const onSelect = vi.fn();
            instance.onSelect = onSelect;
            instance.results = [{ name: 'Pink Floyd' }];

            instance._selectItem(0);

            expect(instance.input.value).toBe('Pink Floyd');
            expect(onSelect).toHaveBeenCalledWith('Pink Floyd');
        });

        it('should do nothing for invalid index', () => {
            const onSelect = vi.fn();
            instance.onSelect = onSelect;
            instance.results = [{ name: 'Pink Floyd' }];

            instance._selectItem(5);

            expect(onSelect).not.toHaveBeenCalled();
        });

        it('should close the dropdown after selection', () => {
            const dropdown = document.getElementById('autocompleteDropdown');
            dropdown.classList.add('show');
            instance.results = [{ name: 'Test' }];
            instance.onSelect = vi.fn();

            instance._selectItem(0);

            expect(dropdown.classList.contains('show')).toBe(false);
        });
    });

    describe('_submitSearch', () => {
        it('should call onSelect with current input value', () => {
            const onSelect = vi.fn();
            instance.onSelect = onSelect;
            instance.input.value = 'Radiohead';

            instance._submitSearch();

            expect(onSelect).toHaveBeenCalledWith('Radiohead');
        });

        it('should close dropdown before submitting', () => {
            const dropdown = document.getElementById('autocompleteDropdown');
            dropdown.classList.add('show');
            instance.onSelect = vi.fn();
            instance.input.value = 'test';

            instance._submitSearch();

            expect(dropdown.classList.contains('show')).toBe(false);
        });

        it('should not call onSelect when input is empty', () => {
            const onSelect = vi.fn();
            instance.onSelect = onSelect;
            instance.input.value = '';

            instance._submitSearch();

            expect(onSelect).not.toHaveBeenCalled();
        });
    });

    describe('keyboard navigation', () => {
        beforeEach(() => {
            instance.results = [{ name: 'A' }, { name: 'B' }, { name: 'C' }];
            instance._render(); // shows dropdown
        });

        it('should move activeIndex down on ArrowDown', () => {
            const e = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true });
            instance._onKeydown(e);
            expect(instance.activeIndex).toBe(0);
        });

        it('should move activeIndex up on ArrowUp', () => {
            instance.activeIndex = 2;
            instance._render();
            const e = new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true });
            instance._onKeydown(e);
            expect(instance.activeIndex).toBe(1);
        });

        it('should not go below -1 on ArrowUp when at top', () => {
            instance.activeIndex = -1;
            const e = new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true });
            instance._onKeydown(e);
            expect(instance.activeIndex).toBe(-1);
        });

        it('should not go past last item on ArrowDown', () => {
            instance.activeIndex = 2; // last item
            const e = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true });
            instance._onKeydown(e);
            expect(instance.activeIndex).toBe(2);
        });

        it('should close dropdown on Escape', () => {
            const e = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
            instance._onKeydown(e);
            expect(instance.dropdown.classList.contains('show')).toBe(false);
        });

        it('should select active item on Enter when activeIndex >= 0', () => {
            instance.activeIndex = 1;
            instance._render();
            const onSelect = vi.fn();
            instance.onSelect = onSelect;

            const e = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
            instance._onKeydown(e);

            expect(onSelect).toHaveBeenCalledWith('B');
        });

        it('should call onSelect with typed value on Enter when no item selected and dropdown hidden', () => {
            instance.close(); // hide dropdown
            const onSelect = vi.fn();
            instance.onSelect = onSelect;
            instance.input.value = 'my query';

            const e = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
            instance._onKeydown(e);

            expect(onSelect).toHaveBeenCalledWith('my query');
        });
    });

    describe('_onInput', () => {
        it('should close dropdown when query is too short', () => {
            const dropdown = document.getElementById('autocompleteDropdown');
            dropdown.classList.add('show');
            instance.input.value = 'a'; // less than minChars (2)

            instance._onInput();

            expect(dropdown.classList.contains('show')).toBe(false);
        });

        it('should debounce the search call', async () => {
            vi.useFakeTimers();
            const searchSpy = vi.spyOn(instance, '_search');
            instance.input.value = 'radio';

            instance._onInput();
            expect(searchSpy).not.toHaveBeenCalled();

            vi.advanceTimersByTime(300);
            expect(searchSpy).toHaveBeenCalledWith('radio');

            vi.useRealTimers();
        });
    });

    describe('_search', () => {
        it('should call apiClient.autocomplete with current search type', async () => {
            window.exploreApp = { searchType: 'label' };
            window.apiClient.autocomplete.mockResolvedValue([{ name: 'Blue Note' }]);

            await instance._search('blue');

            expect(window.apiClient.autocomplete).toHaveBeenCalledWith('blue', 'label');
            expect(instance.results).toEqual([{ name: 'Blue Note' }]);
        });

        it('should default to artist type when no exploreApp', async () => {
            delete window.exploreApp;
            window.apiClient.autocomplete.mockResolvedValue([]);

            await instance._search('test');

            expect(window.apiClient.autocomplete).toHaveBeenCalledWith('test', 'artist');
        });

        it('should reset activeIndex after search', async () => {
            instance.activeIndex = 2;
            window.apiClient.autocomplete.mockResolvedValue([{ name: 'Test' }]);

            await instance._search('test');

            expect(instance.activeIndex).toBe(-1);
        });
    });

    describe('outside click', () => {
        it('should close dropdown when clicking outside both input and dropdown', () => {
            const dropdown = document.getElementById('autocompleteDropdown');
            dropdown.classList.add('show');

            // Click outside
            const outside = document.createElement('div');
            document.body.appendChild(outside);
            const clickEvent = new MouseEvent('click', { bubbles: true });
            outside.dispatchEvent(clickEvent);

            expect(dropdown.classList.contains('show')).toBe(false);
        });
    });
});
