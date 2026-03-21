import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

const MOCK_DATA = {
    artist_id: '123',
    artist_name: 'Radiohead',
    collaborators: [
        {
            artist_id: '456',
            artist_name: 'Thom Yorke',
            release_count: 5,
            first_year: 1993,
            last_year: 2011,
            yearly_counts: [
                { year: 1993, count: 1 },
                { year: 2000, count: 3 },
                { year: 2011, count: 1 },
            ],
        },
        {
            artist_id: '789',
            artist_name: 'Jonny Greenwood',
            release_count: 1,
            first_year: 2007,
            last_year: 2007,
            yearly_counts: [{ year: 2007, count: 1 }],
        },
    ],
    total: 42,
};

function setupDOM() {
    document.body.textContent = '';
    const container = document.createElement('div');
    container.id = 'collaboratorsContainer';
    document.body.appendChild(container);
}

function createD3Mock() {
    return {
        select: vi.fn(() => ({
            append: vi.fn(function () { return this; }),
            attr: vi.fn(function () { return this; }),
            datum: vi.fn(function () { return this; }),
            selectAll: vi.fn(() => ({
                data: vi.fn(() => ({
                    enter: vi.fn(() => ({
                        append: vi.fn(() => ({
                            attr: vi.fn(function () { return this; }),
                        })),
                    })),
                })),
            })),
        })),
        scaleLinear: vi.fn(() => {
            const scale = vi.fn((v) => v);
            scale.domain = vi.fn(() => scale);
            scale.range = vi.fn(() => scale);
            return scale;
        }),
        extent: vi.fn(() => [1993, 2011]),
        max: vi.fn(() => 5),
        line: vi.fn(() => {
            const line = vi.fn(() => 'M0,0');
            line.x = vi.fn(() => line);
            line.y = vi.fn(() => line);
            line.curve = vi.fn(() => line);
            return line;
        }),
        curveMonotoneX: 'monotoneX',
    };
}

describe('CollaboratorsPanel', () => {
    beforeEach(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        globalThis.d3 = createD3Mock();
        globalThis.window.apiClient = {
            getCollaborators: vi.fn(),
        };
        globalThis.window.exploreApp = {
            _onNodeExpand: vi.fn(),
        };
        loadScript('collaborators.js');
        setupDOM();
    });

    it('should register on window.collaboratorsPanel', () => {
        expect(window.collaboratorsPanel).toBeDefined();
        expect(typeof window.collaboratorsPanel.load).toBe('function');
    });

    describe('_renderList', () => {
        it('should render collaborator items', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            const items = container.querySelectorAll('.collaborator-item');
            expect(items.length).toBe(2);
        });

        it('should render collaborator names as links', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            const names = container.querySelectorAll('.collaborator-name');
            expect(names[0].textContent).toBe('Thom Yorke');
            expect(names[1].textContent).toBe('Jonny Greenwood');
        });

        it('should render release count and year range in meta', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            const metas = container.querySelectorAll('.collaborator-meta');
            expect(metas[0].textContent).toContain('5 releases');
            expect(metas[0].textContent).toContain('1993');
            expect(metas[0].textContent).toContain('2011');
        });

        it('should use singular "release" for count of 1', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            const metas = container.querySelectorAll('.collaborator-meta');
            expect(metas[1].textContent).toContain('1 release ');
        });

        it('should create sparkline containers', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            const sparklines = container.querySelectorAll('.collaborator-sparkline');
            expect(sparklines.length).toBe(2);
        });

        it('should call d3.select for sparklines with yearly counts', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            expect(globalThis.d3.select).toHaveBeenCalled();
        });

        it('should show "no collaborators" message for empty list', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, {
                collaborators: [],
                total: 0,
            });

            expect(container.textContent).toContain('No collaborators found');
            expect(container.querySelectorAll('.collaborator-item').length).toBe(0);
        });

        it('should show "no collaborators" when collaborators is undefined', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, { total: 0 });

            expect(container.textContent).toContain('No collaborators found');
        });

        it('should show count summary when total exceeds displayed', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            expect(container.textContent).toContain('Showing 2 of 42 collaborators');
        });

        it('should not show count summary when all collaborators displayed', () => {
            const container = document.getElementById('collaboratorsContainer');
            const data = { ...MOCK_DATA, total: 2 };
            window.collaboratorsPanel._renderList(container, data);

            expect(container.textContent).not.toContain('Showing');
        });
    });

    describe('click handler', () => {
        it('should call exploreApp._onNodeExpand on name click', () => {
            const container = document.getElementById('collaboratorsContainer');
            window.collaboratorsPanel._renderList(container, MOCK_DATA);

            const nameLink = container.querySelector('.collaborator-name');
            nameLink.click();

            expect(window.exploreApp._onNodeExpand).toHaveBeenCalledWith(
                'Thom Yorke',
                'artist'
            );
        });
    });

    describe('load', () => {
        it('should call apiClient.getCollaborators and render', async () => {
            window.apiClient.getCollaborators.mockResolvedValue(MOCK_DATA);

            await window.collaboratorsPanel.load('123');

            expect(window.apiClient.getCollaborators).toHaveBeenCalledWith('123');
            const container = document.getElementById('collaboratorsContainer');
            expect(container.querySelectorAll('.collaborator-item').length).toBe(2);
        });

        it('should not render when API returns null', async () => {
            window.apiClient.getCollaborators.mockResolvedValue(null);
            const container = document.getElementById('collaboratorsContainer');
            const loadingText = document.createElement('p');
            loadingText.textContent = 'Loading...';
            container.appendChild(loadingText);

            await window.collaboratorsPanel.load('123');

            // Container should remain unchanged
            expect(container.textContent).toBe('Loading...');
        });

        it('should not crash when container is missing', async () => {
            window.apiClient.getCollaborators.mockResolvedValue(MOCK_DATA);
            document.body.textContent = '';

            await window.collaboratorsPanel.load('123');
        });
    });
});
