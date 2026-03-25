import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

const MOCK_DATA = {
    genres: [
        {
            name: 'Rock',
            release_count: 98000,
            styles: [
                { name: 'Alternative Rock', release_count: 15000 },
                { name: 'Punk', release_count: 9500 },
            ],
        },
        {
            name: 'Jazz',
            release_count: 42000,
            styles: [
                { name: 'Free Jazz', release_count: 3200 },
            ],
        },
    ],
};

function setupDOM() {
    document.body.textContent = '';
    const container = document.createElement('div');
    container.id = 'genreTreeContainer';
    document.body.appendChild(container);
}

describe('GenreTreeView', () => {
    beforeEach(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        globalThis.window.apiClient = {
            getGenreTree: vi.fn(),
        };
        globalThis.window.exploreApp = {
            _setSearchType: vi.fn(),
            _onSearch: vi.fn(),
            _switchPane: vi.fn(),
        };
        loadScript('genre-tree.js');
        setupDOM();
    });

    it('should register on window.genreTreeView', () => {
        expect(window.genreTreeView).toBeDefined();
        expect(typeof window.genreTreeView.load).toBe('function');
    });

    describe('load', () => {
        it('should call apiClient.getGenreTree and render genres', async () => {
            window.apiClient.getGenreTree.mockResolvedValue(MOCK_DATA);

            await window.genreTreeView.load();

            expect(window.apiClient.getGenreTree).toHaveBeenCalled();
            const container = document.getElementById('genreTreeContainer');
            const items = container.querySelectorAll('.genre-tree-item');
            expect(items.length).toBe(2);
        });

        it('should not reload on subsequent calls', async () => {
            window.apiClient.getGenreTree.mockResolvedValue(MOCK_DATA);

            await window.genreTreeView.load();
            await window.genreTreeView.load();

            expect(window.apiClient.getGenreTree).toHaveBeenCalledTimes(1);
        });

        it('should show error message when API returns null', async () => {
            window.apiClient.getGenreTree.mockResolvedValue(null);

            await window.genreTreeView.load();

            const container = document.getElementById('genreTreeContainer');
            expect(container.textContent).toContain('Failed to load genre tree');
        });

        it('should not crash when container is missing', async () => {
            document.body.textContent = '';
            window.apiClient.getGenreTree.mockResolvedValue(MOCK_DATA);

            await window.genreTreeView.load();
            // Should not throw
        });
    });

    describe('_renderTree', () => {
        it('should render genre names', async () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, MOCK_DATA.genres);

            const names = container.querySelectorAll('.genre-tree-name');
            expect(names[0].textContent).toBe('Rock');
            expect(names[1].textContent).toBe('Jazz');
        });

        it('should render release counts as badges', async () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, MOCK_DATA.genres);

            const badges = container.querySelectorAll('.release-count-badge');
            // 2 genre badges + 3 style badges = 5 total
            expect(badges.length).toBe(5);
            // First badge is Rock's count
            expect(badges[0].textContent).toBe('98,000');
        });

        it('should render style children', async () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, MOCK_DATA.genres);

            const styleNames = container.querySelectorAll('.genre-tree-style-name');
            expect(styleNames.length).toBe(3);
            expect(styleNames[0].textContent).toBe('Alternative Rock');
            expect(styleNames[1].textContent).toBe('Punk');
            expect(styleNames[2].textContent).toBe('Free Jazz');
        });

        it('should show "No genres found" for empty array', () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, []);

            expect(container.textContent).toContain('No genres found');
        });

        it('should handle genres without styles', () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, [
                { name: 'Electronic', release_count: 5000, styles: [] },
            ]);

            const items = container.querySelectorAll('.genre-tree-item');
            expect(items.length).toBe(1);
            const children = container.querySelectorAll('.genre-tree-children');
            expect(children.length).toBe(0);
        });
    });

    describe('_toggleGenre (expand/collapse)', () => {
        it('should toggle expanded class on click', () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, MOCK_DATA.genres);

            const item = container.querySelector('.genre-tree-item');
            expect(item.classList.contains('expanded')).toBe(false);

            // Simulate header click
            const header = item.querySelector('.genre-tree-header');
            header.click();

            expect(item.classList.contains('expanded')).toBe(true);

            // Click again to collapse
            header.click();
            expect(item.classList.contains('expanded')).toBe(false);
        });
    });

    describe('_navigateTo', () => {
        it('should call exploreApp methods to navigate to genre', () => {
            window.genreTreeView._navigateTo('Rock', 'genre');

            expect(window.exploreApp._setSearchType).toHaveBeenCalledWith('genre');
            expect(window.exploreApp._onSearch).toHaveBeenCalledWith('Rock');
            expect(window.exploreApp._switchPane).toHaveBeenCalledWith('explore');
        });

        it('should call exploreApp methods to navigate to style', () => {
            window.genreTreeView._navigateTo('Punk', 'style');

            expect(window.exploreApp._setSearchType).toHaveBeenCalledWith('style');
            expect(window.exploreApp._onSearch).toHaveBeenCalledWith('Punk');
            expect(window.exploreApp._switchPane).toHaveBeenCalledWith('explore');
        });

        it('should navigate when genre name link is clicked', () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, MOCK_DATA.genres);

            const genreLink = container.querySelector('.genre-tree-name');
            genreLink.click();

            expect(window.exploreApp._setSearchType).toHaveBeenCalledWith('genre');
            expect(window.exploreApp._onSearch).toHaveBeenCalledWith('Rock');
        });

        it('should navigate when style name link is clicked', () => {
            const container = document.getElementById('genreTreeContainer');
            window.genreTreeView._renderTree(container, MOCK_DATA.genres);

            const styleLink = container.querySelector('.genre-tree-style-name');
            styleLink.click();

            expect(window.exploreApp._setSearchType).toHaveBeenCalledWith('style');
            expect(window.exploreApp._onSearch).toHaveBeenCalledWith('Alternative Rock');
        });
    });
});
