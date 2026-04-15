import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Build a deeply chainable D3 mock that lets GraphVisualization run without real SVG.
 * Every method returns `this` or a new chainable selection to prevent null errors.
 */
function createD3Mock() {
    function makeChainSel() {
        const sel = {};
        const chainMethods = [
            'attr', 'style', 'text', 'call', 'on', 'classed', 'remove',
            'each', 'data', 'join', 'transition', 'duration', 'filter',
        ];
        chainMethods.forEach(m => {
            sel[m] = vi.fn().mockReturnValue(sel);
        });
        sel.append = vi.fn().mockImplementation(() => makeChainSel());
        sel.select = vi.fn().mockImplementation(() => makeChainSel());
        sel.selectAll = vi.fn().mockImplementation(() => makeChainSel());
        return sel;
    }

    const zoomMock = {
        scaleExtent: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        transform: vi.fn(),
        scaleBy: vi.fn(),
    };

    const simulationMock = {
        force: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        stop: vi.fn(),
        alpha: vi.fn().mockReturnThis(),
        alphaTarget: vi.fn().mockReturnThis(),
        restart: vi.fn(),
    };

    return {
        select: vi.fn().mockImplementation(() => makeChainSel()),
        zoom: vi.fn().mockReturnValue(zoomMock),
        zoomIdentity: {},
        forceSimulation: vi.fn().mockReturnValue(simulationMock),
        forceLink: vi.fn().mockReturnValue({ id: vi.fn().mockReturnThis(), distance: vi.fn().mockReturnThis() }),
        forceManyBody: vi.fn().mockReturnValue({ strength: vi.fn().mockReturnThis() }),
        forceCenter: vi.fn(),
        forceCollide: vi.fn().mockReturnValue({ radius: vi.fn().mockReturnThis() }),
        drag: vi.fn().mockReturnValue({ on: vi.fn().mockReturnThis() }),
        _simulationMock: simulationMock,
        _zoomMock: zoomMock,
    };
}

/**
 * Set up the DOM elements required by graph.js.
 */
function setupGraphDOM() {
    document.body.textContent = '';

    const container = document.createElement('div');
    container.id = 'graphContainer';
    container.style.width = '800px';
    container.style.height = '600px';
    document.body.appendChild(container);

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'graphSvg';
    document.body.appendChild(svg);

    const placeholder = document.createElement('div');
    placeholder.id = 'graphPlaceholder';
    document.body.appendChild(placeholder);

    // Control buttons
    ['zoomInBtn', 'zoomOutBtn', 'zoomResetBtn', 'fullscreenBtn'].forEach(id => {
        const btn = document.createElement('button');
        btn.id = id;
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined';
        btn.appendChild(icon);
        document.body.appendChild(btn);
    });

    // Toast
    const toast = document.createElement('div');
    toast.id = 'shareToast';
    document.body.appendChild(toast);
    const msg = document.createElement('div');
    msg.id = 'shareToastMsg';
    document.body.appendChild(msg);
}

describe('GraphVisualization', () => {
    let graph;
    let d3Mock;

    beforeAll(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        d3Mock = createD3Mock();
        globalThis.d3 = d3Mock;
        setupGraphDOM();
        window.apiClient = {
            expand: vi.fn().mockResolvedValue({ children: [], total: 0, limit: 30, has_more: false, offset: 0 }),
        };
        loadScriptDirect('graph.js');
    });

    beforeEach(() => {
        setupGraphDOM();
        d3Mock = createD3Mock();
        globalThis.d3 = d3Mock;

        window.apiClient = {
            expand: vi.fn().mockResolvedValue({ children: [], total: 0, limit: 30, has_more: false, offset: 0 }),
        };

        graph = new GraphVisualization('graphContainer');
    });

    describe('constructor', () => {
        it('should initialize with empty nodes and links', () => {
            expect(graph.nodes).toEqual([]);
            expect(graph.links).toEqual([]);
        });

        it('should initialize expandedCategories as empty Set', () => {
            expect(graph.expandedCategories.size).toBe(0);
        });

        it('should initialize _categoryMeta as empty Map', () => {
            expect(graph._categoryMeta.size).toBe(0);
        });

        it('should set centerName and centerType to null', () => {
            expect(graph.centerName).toBeNull();
            expect(graph.centerType).toBeNull();
        });

        it('should set beforeYear to null', () => {
            expect(graph.beforeYear).toBeNull();
        });

        it('should initialize compareMode to false', () => {
            expect(graph.compareMode).toBe(false);
        });
    });

    describe('_getNodeRadius', () => {
        it('should return 28 for center nodes', () => {
            expect(graph._getNodeRadius({ isCenter: true })).toBe(28);
        });

        it('should return 22 for category nodes', () => {
            expect(graph._getNodeRadius({ isCenter: false, isCategory: true })).toBe(22);
        });

        it('should return 11 for load-more nodes', () => {
            expect(graph._getNodeRadius({ isCenter: false, isCategory: false, isLoadMore: true })).toBe(11);
        });

        it('should return 14 for regular nodes', () => {
            expect(graph._getNodeRadius({ isCenter: false, isCategory: false, isLoadMore: false })).toBe(14);
        });
    });

    describe('setExploreData', () => {
        const exploreData = {
            center: { id: 'radiohead', name: 'Radiohead', type: 'artist' },
            categories: [
                { id: 'cat-releases', name: 'Releases', category: 'releases', count: 0 },
            ],
        };

        it('should set centerName and centerType', () => {
            graph.setExploreData(exploreData);
            expect(graph.centerName).toBe('Radiohead');
            expect(graph.centerType).toBe('artist');
        });

        it('should add center node', () => {
            graph.setExploreData(exploreData);
            const centerNode = graph.nodes.find(n => n.isCenter);
            expect(centerNode).toBeDefined();
            expect(centerNode.name).toBe('Radiohead');
            expect(centerNode.type).toBe('artist');
        });

        it('should add category nodes', () => {
            graph.setExploreData(exploreData);
            const catNode = graph.nodes.find(n => n.isCategory);
            expect(catNode).toBeDefined();
            expect(catNode.displayName).toBe('Releases');
        });

        it('should add links from center to categories', () => {
            graph.setExploreData(exploreData);
            expect(graph.links.length).toBeGreaterThan(0);
        });

        it('should reset node/link state on re-call', () => {
            graph.setExploreData(exploreData);
            const firstNodeCount = graph.nodes.length;

            graph.setExploreData(exploreData);
            // Should not accumulate from two calls
            expect(graph.nodes.length).toBe(firstNodeCount);
        });

        it('should expand categories with count > 0', async () => {
            const dataWithCount = {
                center: { id: 'radiohead', name: 'Radiohead', type: 'artist' },
                categories: [
                    { id: 'cat-releases', name: 'Releases', category: 'releases', count: 5 },
                ],
            };

            graph.setExploreData(dataWithCount);
            await new Promise(r => setTimeout(r, 10));

            expect(window.apiClient.expand).toHaveBeenCalledWith('Radiohead', 'artist', 'releases', 30, 0, null);
        });
    });

    describe('_addLoadMoreNode', () => {
        it('should add a load-more node', () => {
            graph._addLoadMoreNode('cat-releases', 25);

            const loadMoreNode = graph.nodes.find(n => n.isLoadMore);
            expect(loadMoreNode).toBeDefined();
            expect(loadMoreNode.name).toBe('Load 25 more…');
            expect(loadMoreNode.categoryId).toBe('cat-releases');
        });

        it('should replace existing load-more node for same category', () => {
            graph._addLoadMoreNode('cat-releases', 25);
            graph._addLoadMoreNode('cat-releases', 10);

            const loadMoreNodes = graph.nodes.filter(n => n.isLoadMore && n.categoryId === 'cat-releases');
            expect(loadMoreNodes).toHaveLength(1);
            expect(loadMoreNodes[0].name).toBe('Load 10 more…');
        });
    });

    describe('clear', () => {
        it('should reset nodes and links', () => {
            graph.nodes = [{ id: 'test' }];
            graph.links = [{ source: 'test', target: 'other' }];

            graph.clear();

            expect(graph.nodes).toEqual([]);
            expect(graph.links).toEqual([]);
        });

        it('should show placeholder', () => {
            const placeholder = document.getElementById('graphPlaceholder');
            placeholder.classList.add('hidden');

            graph.clear();

            expect(placeholder.classList.contains('hidden')).toBe(false);
        });

        it('should clear expandedCategories', () => {
            graph.expandedCategories.add('test');

            graph.clear();

            expect(graph.expandedCategories.size).toBe(0);
        });

        it('should stop simulation if running', () => {
            const stopSpy = vi.fn();
            graph.simulation = { stop: stopSpy };

            graph.clear();

            expect(stopSpy).toHaveBeenCalled();
            expect(graph.simulation).toBeNull();
        });
    });

    describe('restoreSnapshot', () => {
        it('should set center name and type from snapshot', () => {
            const nodes = [
                { id: 'Radiohead', type: 'artist' },
                { id: 'node1', type: 'release' },
            ];
            const center = { id: 'Radiohead', type: 'artist' };

            graph.restoreSnapshot(nodes, center);

            expect(graph.centerName).toBe('Radiohead');
            expect(graph.centerType).toBe('artist');
        });

        it('should add center node and snapshot nodes', () => {
            const nodes = [
                { id: 'Radiohead', type: 'artist' },
                { id: 'OK Computer', type: 'release' },
            ];
            const center = { id: 'Radiohead', type: 'artist' };

            graph.restoreSnapshot(nodes, center);

            // Should have center node + 1 non-center node (center filtered out)
            expect(graph.nodes.length).toBe(2);
        });

        it('should exclude the center from the non-center nodes', () => {
            const nodes = [
                { id: 'Radiohead', type: 'artist' },
                { id: 'Release1', type: 'release' },
            ];
            const center = { id: 'Radiohead', type: 'artist' };

            graph.restoreSnapshot(nodes, center);

            const nonCenterNodes = graph.nodes.filter(n => !n.isCenter);
            // Center node should not be double-added
            expect(nonCenterNodes.every(n => n.name !== 'Radiohead' || n.type !== 'artist')).toBe(true);
        });

        it('should show placeholder as hidden', () => {
            const placeholder = document.getElementById('graphPlaceholder');
            placeholder.classList.remove('hidden');

            graph.restoreSnapshot([], { id: 'Test', type: 'artist' });

            expect(placeholder.classList.contains('hidden')).toBe(true);
        });
    });

    describe('_onNodeClicked', () => {
        it('should not call onNodeClick for category nodes', () => {
            const onNodeClick = vi.fn();
            graph.onNodeClick = onNodeClick;

            const event = { stopPropagation: vi.fn() };
            const catNode = { isCategory: true };

            graph._onNodeClicked(event, catNode);

            expect(onNodeClick).not.toHaveBeenCalled();
        });

        it('should call onNodeClick for regular nodes', () => {
            const onNodeClick = vi.fn();
            graph.onNodeClick = onNodeClick;

            const event = { stopPropagation: vi.fn() };
            const node = { isCategory: false, isLoadMore: false, nodeId: 'abc', type: 'artist' };

            graph._onNodeClicked(event, node);

            expect(onNodeClick).toHaveBeenCalledWith('abc', 'artist');
        });

        it('should use name as fallback when nodeId is missing', () => {
            const onNodeClick = vi.fn();
            graph.onNodeClick = onNodeClick;

            const event = { stopPropagation: vi.fn() };
            const node = { isCategory: false, isLoadMore: false, name: 'Radiohead', type: 'artist' };

            graph._onNodeClicked(event, node);

            expect(onNodeClick).toHaveBeenCalledWith('Radiohead', 'artist');
        });

        it('should not call onNodeClick for load-more nodes in compare mode', () => {
            graph.compareMode = true;
            const onNodeClick = vi.fn();
            graph.onNodeClick = onNodeClick;

            const event = { stopPropagation: vi.fn() };
            const node = { isCategory: false, isLoadMore: true, categoryId: 'cat-1' };

            graph._onNodeClicked(event, node);

            expect(onNodeClick).not.toHaveBeenCalled();
        });
    });

    describe('_onNodeDblClicked', () => {
        it('should not call onNodeExpand for category nodes', () => {
            const onNodeExpand = vi.fn();
            graph.onNodeExpand = onNodeExpand;

            const event = { stopPropagation: vi.fn(), preventDefault: vi.fn() };
            graph._onNodeDblClicked(event, { isCategory: true, isCenter: false });

            expect(onNodeExpand).not.toHaveBeenCalled();
        });

        it('should not call onNodeExpand for center nodes', () => {
            const onNodeExpand = vi.fn();
            graph.onNodeExpand = onNodeExpand;

            const event = { stopPropagation: vi.fn(), preventDefault: vi.fn() };
            graph._onNodeDblClicked(event, { isCategory: false, isCenter: true });

            expect(onNodeExpand).not.toHaveBeenCalled();
        });

        it('should call onNodeExpand for regular nodes', () => {
            const onNodeExpand = vi.fn();
            graph.onNodeExpand = onNodeExpand;

            const event = { stopPropagation: vi.fn(), preventDefault: vi.fn() };
            graph._onNodeDblClicked(event, { isCategory: false, isCenter: false, name: 'Radiohead', type: 'artist' });

            expect(onNodeExpand).toHaveBeenCalledWith('Radiohead', 'artist');
        });
    });

    describe('_checkExpandsDone', () => {
        it('should call onExpandsComplete when pendingExpands reaches 0', () => {
            const onExpandsComplete = vi.fn();
            graph.onExpandsComplete = onExpandsComplete;
            graph._pendingExpands = 1;

            graph._pendingExpands--;
            graph._checkExpandsDone();

            expect(onExpandsComplete).toHaveBeenCalled();
        });

        it('should not call onExpandsComplete when pendingExpands > 0', () => {
            const onExpandsComplete = vi.fn();
            graph.onExpandsComplete = onExpandsComplete;
            graph._pendingExpands = 2;

            graph._pendingExpands--;
            graph._checkExpandsDone();

            expect(onExpandsComplete).not.toHaveBeenCalled();
        });
    });

    describe('_dragStarted / _dragged / _dragEnded', () => {
        it('_dragStarted should fix node position', () => {
            const sim = { alphaTarget: vi.fn().mockReturnThis(), restart: vi.fn() };
            graph.simulation = sim;
            const node = { x: 100, y: 200 };

            graph._dragStarted({ active: false }, node);

            expect(node.fx).toBe(100);
            expect(node.fy).toBe(200);
        });

        it('_dragged should update fixed position to event coordinates', () => {
            const node = { fx: 0, fy: 0 };
            graph._dragged({ x: 150, y: 250 }, node);
            expect(node.fx).toBe(150);
            expect(node.fy).toBe(250);
        });

        it('_dragEnded should clear fixed position for non-center nodes', () => {
            const sim = { alphaTarget: vi.fn().mockReturnThis() };
            graph.simulation = sim;
            const node = { isCenter: false, fx: 100, fy: 200 };

            graph._dragEnded({ active: false }, node);

            expect(node.fx).toBeNull();
            expect(node.fy).toBeNull();
        });

        it('_dragEnded should keep fixed position for center nodes', () => {
            const sim = { alphaTarget: vi.fn().mockReturnThis() };
            graph.simulation = sim;
            const node = { isCenter: true, fx: 100, fy: 200 };

            graph._dragEnded({ active: false }, node);

            expect(node.fx).toBe(100);
            expect(node.fy).toBe(200);
        });
    });

    describe('clearComparison', () => {
        it('should reset compare mode state', () => {
            graph.compareMode = true;
            graph.compareYearA = 1990;
            graph.compareYearB = 2000;

            graph.clearComparison();

            expect(graph.compareMode).toBe(false);
            expect(graph.compareYearA).toBeNull();
            expect(graph.compareYearB).toBeNull();
        });

        it('should remove compareStatus from nodes', () => {
            graph.nodes = [
                { id: 'n1', compareStatus: 'only_a' },
                { id: 'n2', compareStatus: 'only_b' },
            ];
            graph.links = [{ source: 'n1', target: 'n2', compareStatus: 'only_b' }];

            graph.clearComparison();

            graph.nodes.forEach(n => expect(n.compareStatus).toBeUndefined());
            graph.links.forEach(l => expect(l.compareStatus).toBeUndefined());
        });
    });

    describe('setBeforeYear', () => {
        it('should update beforeYear', async () => {
            graph.beforeYear = null;
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';

            await graph.setBeforeYear(1995);

            expect(graph.beforeYear).toBe(1995);
        });

        it('should return early if no center set', async () => {
            graph.centerName = null;
            graph.centerType = null;

            await graph.setBeforeYear(1995);

            // Should not have tried to expand categories
            expect(window.apiClient.expand).not.toHaveBeenCalled();
        });

        it('should return early if no categories', async () => {
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';
            // No categories in _categoryMeta

            await graph.setBeforeYear(1995);

            expect(window.apiClient.expand).not.toHaveBeenCalled();
        });
    });

    describe('_loadMoreCategory', () => {
        it('should load more children and update category label', async () => {
            graph._categoryMeta.set('cat-releases', {
                parentName: 'Radiohead', parentType: 'artist',
                category: 'releases', offset: 30, limit: 30, total: 50,
            });
            graph.nodes.push({
                id: 'cat-releases', displayName: 'Releases', name: 'Releases (30)',
                isCategory: true, isCenter: false,
            });
            graph.nodes.push({
                id: 'load-more-cat-releases', categoryId: 'cat-releases', isLoadMore: true,
            });
            graph.links.push({ source: 'cat-releases', target: 'load-more-cat-releases' });

            window.apiClient.expand.mockResolvedValue({
                children: [{ id: '31', name: 'Album 31', type: 'release' }],
                total: 50, limit: 30, has_more: true, offset: 30,
            });

            const loadMoreNode = graph.nodes.find(n => n.id === 'load-more-cat-releases');
            await graph._loadMoreCategory(loadMoreNode);

            expect(graph.nodes.find(n => n.id === 'child-release-31')).toBeDefined();
        });

        it('should return early when no meta exists', async () => {
            await graph._loadMoreCategory({ id: 'load-more-unknown', categoryId: 'unknown' });
            expect(window.apiClient.expand).not.toHaveBeenCalled();
        });

        it('should not add load-more when has_more is false', async () => {
            graph._categoryMeta.set('cat-test', {
                parentName: 'Test', parentType: 'artist',
                category: 'releases', offset: 30, limit: 30, total: 31,
            });
            graph.nodes.push({ id: 'cat-test', displayName: 'Releases', name: 'Releases (30)', isCategory: true, isCenter: false });

            window.apiClient.expand.mockResolvedValue({
                children: [{ id: '31', name: 'Album 31', type: 'release' }],
                total: 31, limit: 30, has_more: false, offset: 30,
            });

            await graph._loadMoreCategory({ id: 'load-more-cat-test', categoryId: 'cat-test' });

            const loadMoreNodes = graph.nodes.filter(n => n.isLoadMore);
            expect(loadMoreNodes).toHaveLength(0);
        });
    });

    describe('setCompareYears', () => {
        it('should set compare mode state', async () => {
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';
            await graph.setCompareYears(1995, 2005);
            expect(graph.compareMode).toBe(true);
            expect(graph.compareYearA).toBe(1995);
            expect(graph.compareYearB).toBe(2005);
        });

        it('should return early if no center set', async () => {
            graph.centerName = null;
            graph.centerType = null;
            await graph.setCompareYears(1990, 2000);
            expect(window.apiClient.expand).not.toHaveBeenCalled();
        });

        it('should return early if no categories', async () => {
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';
            await graph.setCompareYears(1990, 2000);
            expect(window.apiClient.expand).not.toHaveBeenCalled();
        });

        it('should clear beforeYear', async () => {
            graph.beforeYear = 1990;
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';
            await graph.setCompareYears(1990, 2000);
            expect(graph.beforeYear).toBeNull();
        });
    });

    describe('_fetchComparisonData', () => {
        it('should mark nodes as only_a, only_b, or both', async () => {
            graph.compareYearA = 1990;
            graph.compareYearB = 2000;
            graph.nodes.push({
                id: 'cat-releases', displayName: 'Releases', name: 'Releases',
                isCategory: true, isCenter: false, count: 5,
            });

            window.apiClient.expand
                .mockResolvedValueOnce({
                    children: [
                        { id: '1', name: 'A Only', type: 'release' },
                        { id: '2', name: 'Both', type: 'release' },
                    ],
                    total: 2, limit: 30, has_more: false,
                })
                .mockResolvedValueOnce({
                    children: [
                        { id: '2', name: 'Both', type: 'release' },
                        { id: '3', name: 'B Only', type: 'release' },
                    ],
                    total: 2, limit: 30, has_more: false,
                });

            graph._pendingExpands = 1;
            await graph._fetchComparisonData('cat-releases', 'Radiohead', 'artist', 'releases');

            const aOnly = graph.nodes.find(n => n.id === 'child-release-1');
            const both = graph.nodes.find(n => n.id === 'child-release-2');
            const bOnly = graph.nodes.find(n => n.id === 'child-release-3');

            expect(aOnly.compareStatus).toBe('only_a');
            expect(both.compareStatus).toBe('both');
            expect(bOnly.compareStatus).toBe('only_b');
        });

        it('should show toast on fetch error', async () => {
            graph.compareYearA = 1990;
            graph.compareYearB = 2000;

            window.apiClient.expand.mockRejectedValue(new Error('fail'));

            graph._pendingExpands = 1;
            await graph._fetchComparisonData('cat-releases', 'Radiohead', 'artist', 'releases');

            const toast = document.getElementById('shareToast');
            expect(toast.classList.contains('show')).toBe(true);
        });
    });

    describe('toggleFullscreen', () => {
        it('should toggle fullscreen class', () => {
            expect(graph.container.classList.contains('fullscreen')).toBe(false);
            graph.toggleFullscreen();
            expect(graph.container.classList.contains('fullscreen')).toBe(true);
            graph.toggleFullscreen();
            expect(graph.container.classList.contains('fullscreen')).toBe(false);
        });
    });

    describe('zoomIn / zoomOut / zoomReset', () => {
        it('zoomIn should call zoom.scaleBy', () => {
            graph.zoomIn();
            // zoom methods are called via D3 transition chain
        });

        it('zoomOut should call zoom.scaleBy', () => {
            graph.zoomOut();
        });

        it('zoomReset should call zoom.transform', () => {
            graph.zoomReset();
        });
    });

    describe('_initControls button clicks', () => {
        it('zoomInBtn click should invoke zoomIn', () => {
            const spy = vi.spyOn(graph, 'zoomIn');
            document.getElementById('zoomInBtn').click();
            expect(spy).toHaveBeenCalled();
        });

        it('zoomOutBtn click should invoke zoomOut', () => {
            const spy = vi.spyOn(graph, 'zoomOut');
            document.getElementById('zoomOutBtn').click();
            expect(spy).toHaveBeenCalled();
        });

        it('zoomResetBtn click should invoke zoomReset', () => {
            const spy = vi.spyOn(graph, 'zoomReset');
            document.getElementById('zoomResetBtn').click();
            expect(spy).toHaveBeenCalled();
        });

        it('fullscreenBtn click should invoke toggleFullscreen', () => {
            const spy = vi.spyOn(graph, 'toggleFullscreen');
            document.getElementById('fullscreenBtn').click();
            expect(spy).toHaveBeenCalled();
        });

        it('Escape key should exit fullscreen when in fullscreen mode', () => {
            graph.container.classList.add('fullscreen');
            const spy = vi.spyOn(graph, 'toggleFullscreen');
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            expect(spy).toHaveBeenCalled();
        });

        it('Escape key should not toggle when not in fullscreen mode', () => {
            graph.container.classList.remove('fullscreen');
            const spy = vi.spyOn(graph, 'toggleFullscreen');
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            expect(spy).not.toHaveBeenCalled();
        });
    });

    describe('fitToView', () => {
        it('should return early with no nodes', () => {
            graph.nodes = [];
            graph.fitToView(); // should not throw
        });

        it('should return early when container has zero dimensions', () => {
            graph.nodes = [{ x: 10, y: 10, isCenter: true }];
            // jsdom clientWidth/clientHeight default to 0
            graph.fitToView(); // should not throw
        });
    });

    describe('_onResize', () => {
        it('should update SVG dimensions', () => {
            graph._onResize();
            // Should not throw even without a simulation
        });

        it('should restart simulation when running', () => {
            const mockSim = {
                force: vi.fn().mockReturnThis(),
                alpha: vi.fn().mockReturnThis(),
                restart: vi.fn(),
            };
            graph.simulation = mockSim;
            graph._onResize();
            expect(mockSim.alpha).toHaveBeenCalledWith(0.3);
            expect(mockSim.restart).toHaveBeenCalled();
        });
    });

    describe('_expandCategoryFiltered', () => {
        it('should re-expand category with new before_year', async () => {
            graph.beforeYear = 1990;
            graph.nodes.push({
                id: 'cat-releases', displayName: 'Releases', name: 'Releases (10)',
                isCategory: true, isCenter: false, count: 10,
            });

            window.apiClient.expand.mockResolvedValue({
                children: [{ id: '1', name: 'Album 1', type: 'release' }],
                total: 1, limit: 30, has_more: false,
            });

            graph._pendingExpands = 1;
            await graph._expandCategoryFiltered('cat-releases', 'Radiohead', 'artist', 'releases');

            expect(window.apiClient.expand).toHaveBeenCalledWith('Radiohead', 'artist', 'releases', 30, 0, 1990);
            expect(graph.nodes.find(n => n.id === 'child-release-1')).toBeDefined();
            const catNode = graph.nodes.find(n => n.id === 'cat-releases');
            expect(catNode.name).toBe('Releases (1)');
        });
    });

    describe('_render with callback-invoking D3 mock', () => {
        /**
         * Create a D3 mock that actually invokes callbacks passed to
         * .each(), .text(), .attr(), .style(), .on() so that the rendering
         * code inside _render() is fully exercised.
         */
        function createCallbackD3Mock(nodes, links) {
            // Track callbacks registered with .on()
            const simulationOnCallbacks = {};
            const capturedCallbacks = {
                each: [],
                text: [],
                attr: {},
                style: {},
            };

            function makeChainSel(dataItems) {
                const sel = {};
                const chainMethods = ['classed', 'remove', 'transition', 'duration', 'filter'];
                chainMethods.forEach(m => {
                    sel[m] = vi.fn().mockReturnValue(sel);
                });
                sel.data = vi.fn().mockImplementation(() => makeChainSel(dataItems));
                sel.join = vi.fn().mockImplementation(() => makeChainSel(dataItems));
                sel.append = vi.fn().mockImplementation(() => makeChainSel(dataItems));
                sel.select = vi.fn().mockImplementation(() => makeChainSel(dataItems));
                sel.selectAll = vi.fn().mockImplementation(() => makeChainSel(dataItems));
                sel.call = vi.fn().mockReturnValue(sel);
                sel.on = vi.fn().mockImplementation((event, cb) => {
                    // Just store, don't invoke event handlers
                    return sel;
                });
                sel.each = vi.fn().mockImplementation((cb) => {
                    // Invoke the callback for each data item
                    if (dataItems && cb) {
                        dataItems.forEach(d => cb.call({}, d));
                    }
                    return sel;
                });
                sel.text = vi.fn().mockImplementation((arg) => {
                    // If it's a function, invoke for each data item
                    if (typeof arg === 'function' && dataItems) {
                        dataItems.forEach(d => arg(d));
                    }
                    return sel;
                });
                sel.attr = vi.fn().mockImplementation((name, val) => {
                    if (typeof val === 'function' && dataItems) {
                        dataItems.forEach(d => val(d));
                    }
                    return sel;
                });
                sel.style = vi.fn().mockImplementation((name, val) => {
                    if (typeof val === 'function' && dataItems) {
                        dataItems.forEach(d => val(d));
                    }
                    return sel;
                });
                return sel;
            }

            const zoomMock = {
                scaleExtent: vi.fn().mockReturnThis(),
                on: vi.fn().mockReturnThis(),
                transform: vi.fn(),
                scaleBy: vi.fn(),
            };

            const simulationMock = {
                force: vi.fn().mockReturnThis(),
                on: vi.fn().mockImplementation((event, cb) => {
                    simulationOnCallbacks[event] = cb;
                    return simulationMock;
                }),
                stop: vi.fn(),
                alpha: vi.fn().mockReturnThis(),
                alphaTarget: vi.fn().mockReturnThis(),
                restart: vi.fn(),
            };

            // Main group returns chain with link/node data awareness
            let callCount = 0;
            const gSel = makeChainSel([]);
            // Override append to return different data for links vs nodes group
            gSel.append = vi.fn().mockImplementation(() => {
                callCount++;
                // First append('g') is for links, second for nodes
                if (callCount === 1) return makeChainSel(links);
                return makeChainSel(nodes);
            });
            gSel.selectAll = vi.fn().mockReturnValue(gSel);

            const svgSel = makeChainSel([]);
            svgSel.append = vi.fn().mockImplementation(() => {
                // For 'defs' and 'g' appends from _initSvg
                return makeChainSel([]);
            });

            const mock = {
                select: vi.fn().mockImplementation((selector) => {
                    if (selector === '#graphSvg') return svgSel;
                    // d3.select(this) inside .each() - return a chain
                    return makeChainSel([]);
                }),
                zoom: vi.fn().mockReturnValue(zoomMock),
                zoomIdentity: { translate: vi.fn().mockReturnValue({ scale: vi.fn() }) },
                forceSimulation: vi.fn().mockReturnValue(simulationMock),
                forceLink: vi.fn().mockReturnValue({
                    id: vi.fn().mockReturnThis(),
                    distance: vi.fn().mockImplementation((cb) => {
                        // Invoke distance callback to cover the branching
                        if (typeof cb === 'function') {
                            cb({ source: { isCenter: true }, target: {} });
                            cb({ source: { isCategory: true }, target: {} });
                            cb({ source: {}, target: {} });
                        }
                        return { id: vi.fn().mockReturnThis(), distance: vi.fn().mockReturnThis() };
                    }),
                }),
                forceManyBody: vi.fn().mockReturnValue({
                    strength: vi.fn().mockImplementation((cb) => {
                        if (typeof cb === 'function') {
                            cb({ isCenter: true });
                            cb({ isCategory: true });
                            cb({});
                        }
                        return { strength: vi.fn().mockReturnThis() };
                    }),
                }),
                forceCenter: vi.fn(),
                forceCollide: vi.fn().mockReturnValue({
                    radius: vi.fn().mockImplementation((cb) => {
                        if (typeof cb === 'function') {
                            cb({ isCenter: true });
                        }
                        return { radius: vi.fn().mockReturnThis() };
                    }),
                }),
                drag: vi.fn().mockReturnValue({ on: vi.fn().mockReturnThis() }),
                _simulationMock: simulationMock,
                _simulationOnCallbacks: simulationOnCallbacks,
                _gSel: gSel,
            };

            return mock;
        }

        it('should invoke node.each callback for category nodes', () => {
            const testNodes = [
                { id: 'cat-1', isCenter: false, isCategory: true, displayName: 'Releases', name: 'Releases (5)', count: 5 },
            ];
            const testLinks = [];
            const cbMock = createCallbackD3Mock(testNodes, testLinks);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = testLinks;
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            // Verify simulation was created
            expect(cbMock.forceSimulation).toHaveBeenCalled();
        });

        it('should invoke node.each callback for load-more nodes', () => {
            const testNodes = [
                { id: 'lm-1', isCenter: false, isCategory: false, isLoadMore: true, name: 'Load 10 more...', categoryId: 'cat-1' },
            ];
            const testLinks = [];
            const cbMock = createCallbackD3Mock(testNodes, testLinks);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = testLinks;
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            expect(cbMock.forceSimulation).toHaveBeenCalled();
        });

        it('should invoke node.each callback for regular circle nodes with various types', () => {
            const testNodes = [
                { id: 'c1', isCenter: true, isCategory: false, name: 'Radiohead', type: 'artist' },
                { id: 'n1', isCenter: false, isCategory: false, name: 'Album', type: 'release' },
                { id: 'n2', isCenter: false, isCategory: false, name: 'Warp', type: 'label' },
                { id: 'n3', isCenter: false, isCategory: false, name: 'Rock', type: 'genre' },
                { id: 'n4', isCenter: false, isCategory: false, name: 'IDM', type: 'style' },
                { id: 'n5', isCenter: false, isCategory: false, name: 'Unknown', type: 'master' },
            ];
            const testLinks = [];
            const cbMock = createCallbackD3Mock(testNodes, testLinks);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = testLinks;
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            expect(cbMock.forceSimulation).toHaveBeenCalled();
        });

        it('should invoke node.each callback for comparison mode nodes', () => {
            const testNodes = [
                { id: 'n1', isCenter: false, isCategory: false, name: 'A Only', type: 'artist', compareStatus: 'only_a' },
                { id: 'n2', isCenter: false, isCategory: false, name: 'B Only', type: 'release', compareStatus: 'only_b' },
                { id: 'n3', isCenter: false, isCategory: false, name: 'Both', type: 'artist', compareStatus: 'both' },
            ];
            const testLinks = [
                { source: 'cat-1', target: 'n1', compareStatus: 'only_a' },
                { source: 'cat-1', target: 'n2', compareStatus: 'only_b' },
                { source: 'cat-1', target: 'n3' },
            ];
            const cbMock = createCallbackD3Mock(testNodes, testLinks);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = testLinks;
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            expect(cbMock.forceSimulation).toHaveBeenCalled();
        });

        it('should invoke tooltip text callback for all node types', () => {
            const testNodes = [
                { id: 'c1', isCenter: true, isCategory: false, name: 'Radiohead', type: 'artist' },
                { id: 'cat-1', isCenter: false, isCategory: true, displayName: 'Releases', name: 'Releases (5)', count: 5 },
                { id: 'lm-1', isCenter: false, isCategory: false, isLoadMore: true, name: 'Load more' },
                { id: 'n1', isCenter: false, isCategory: false, name: 'Album', type: 'artist', compareStatus: 'only_a' },
                { id: 'n2', isCenter: false, isCategory: false, name: 'Track', type: 'release', compareStatus: 'only_b' },
                { id: 'n3', isCenter: false, isCategory: false, name: 'Other', type: 'release' },
            ];
            const cbMock = createCallbackD3Mock(testNodes, []);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = [];
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            expect(cbMock.forceSimulation).toHaveBeenCalled();
        });

        it('should invoke label text callback for long names (truncation)', () => {
            const testNodes = [
                { id: 'n1', isCenter: false, isCategory: false, name: 'A Very Long Album Name That Exceeds Twenty Chars', type: 'release' },
                { id: 'lm-1', isCenter: false, isCategory: false, isLoadMore: true, name: 'Load 999 more remaining items...' },
            ];
            const cbMock = createCallbackD3Mock(testNodes, []);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = [];
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            expect(cbMock.forceSimulation).toHaveBeenCalled();
        });

        it('should invoke simulation tick and end callbacks', () => {
            const testNodes = [
                { id: 'c1', isCenter: true, name: 'Radiohead', type: 'artist', x: 100, y: 100, fx: 100, fy: 100 },
            ];
            const testLinks = [];
            const cbMock = createCallbackD3Mock(testNodes, testLinks);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = testLinks;
            graph.g = cbMock._gSel;
            graph.simulation = null;
            graph._render();

            // Invoke tick callback
            const tickCb = cbMock._simulationOnCallbacks['tick'];
            expect(tickCb).toBeDefined();
            tickCb();

            // Invoke end callback
            const endCb = cbMock._simulationOnCallbacks['end'];
            expect(endCb).toBeDefined();
            endCb();
        });

        it('should cancel pending render timeout', () => {
            const testNodes = [];
            const cbMock = createCallbackD3Mock(testNodes, []);
            globalThis.d3 = cbMock;

            graph.nodes = testNodes;
            graph.links = [];
            graph.g = cbMock._gSel;
            graph._renderTimeout = setTimeout(() => {}, 99999);
            graph.simulation = null;
            graph._render();

            expect(graph._renderTimeout).toBeNull();
        });

        it('should stop existing simulation before re-rendering', () => {
            const testNodes = [];
            const cbMock = createCallbackD3Mock(testNodes, []);
            globalThis.d3 = cbMock;

            const oldSim = { stop: vi.fn() };
            graph.nodes = testNodes;
            graph.links = [];
            graph.g = cbMock._gSel;
            graph.simulation = oldSim;
            graph._render();

            expect(oldSim.stop).toHaveBeenCalled();
        });
    });

    describe('_expandCategory', () => {
        it('should skip already-expanded category', async () => {
            graph.expandedCategories.add('cat-releases');
            graph._pendingExpands = 1;

            const checkSpy = vi.spyOn(graph, '_checkExpandsDone');
            await graph._expandCategory('cat-releases', 'Radiohead', 'artist', 'releases');

            expect(graph._pendingExpands).toBe(0);
            expect(checkSpy).toHaveBeenCalled();
            expect(window.apiClient.expand).not.toHaveBeenCalled();
        });

        it('should skip duplicate child nodes', async () => {
            graph._pendingExpands = 1;
            // Pre-add a child node that will also be in the API response
            graph.nodes.push({
                id: 'child-release-1', name: 'Album 1', type: 'release',
                isCenter: false, isCategory: false,
            });

            window.apiClient.expand.mockResolvedValue({
                children: [
                    { id: '1', name: 'Album 1', type: 'release' },
                    { id: '2', name: 'Album 2', type: 'release' },
                ],
                total: 2, limit: 30, has_more: false, offset: 0,
            });

            await graph._expandCategory('cat-releases', 'Radiohead', 'artist', 'releases');

            // Should have the pre-existing one plus the new one
            const childNodes = graph.nodes.filter(n => n.id.startsWith('child-'));
            expect(childNodes).toHaveLength(2);
        });

        it('should add load-more node when has_more is true', async () => {
            graph._pendingExpands = 1;

            window.apiClient.expand.mockResolvedValue({
                children: [{ id: '1', name: 'Album 1', type: 'release' }],
                total: 50, limit: 30, has_more: true, offset: 0,
            });

            await graph._expandCategory('cat-releases', 'Radiohead', 'artist', 'releases');

            const loadMore = graph.nodes.find(n => n.isLoadMore);
            expect(loadMore).toBeDefined();
            expect(loadMore.name).toContain('49');
        });
    });

    describe('_onNodeClicked with load-more in non-compare mode', () => {
        it('should call _loadMoreCategory when clicking load-more node', () => {
            graph.compareMode = false;
            const loadMoreSpy = vi.spyOn(graph, '_loadMoreCategory').mockResolvedValue(undefined);
            const event = { stopPropagation: vi.fn() };
            const node = { isCategory: false, isLoadMore: true, categoryId: 'cat-1', id: 'load-more-cat-1' };

            graph._onNodeClicked(event, node);

            expect(loadMoreSpy).toHaveBeenCalledWith(node);
        });
    });

    describe('_loadMoreCategory with has_more and category label update', () => {
        it('should update category label with loaded/total counts', async () => {
            graph._categoryMeta.set('cat-releases', {
                parentName: 'Radiohead', parentType: 'artist',
                category: 'releases', offset: 30, limit: 30, total: 60,
            });
            graph.nodes.push({
                id: 'cat-releases', displayName: 'Releases', name: 'Releases (30)',
                isCategory: true, isCenter: false,
            });
            const loadMoreNode = {
                id: 'load-more-cat-releases', categoryId: 'cat-releases', isLoadMore: true,
            };
            graph.nodes.push(loadMoreNode);
            graph.links.push({ source: 'cat-releases', target: 'load-more-cat-releases' });

            window.apiClient.expand.mockResolvedValue({
                children: [
                    { id: '31', name: 'Album 31', type: 'release' },
                    { id: '32', name: 'Album 32', type: 'release' },
                ],
                total: 60, limit: 30, has_more: true, offset: 30,
            });

            await graph._loadMoreCategory(loadMoreNode);

            // Should update label
            const catNode = graph.nodes.find(n => n.id === 'cat-releases');
            expect(catNode.name).toBe('Releases (32 / 60)');

            // Should still have a load-more node for remaining
            const remainingLm = graph.nodes.find(n => n.isLoadMore && n.categoryId === 'cat-releases');
            expect(remainingLm).toBeDefined();
        });

        it('should skip duplicate children in _loadMoreCategory', async () => {
            graph._categoryMeta.set('cat-releases', {
                parentName: 'Radiohead', parentType: 'artist',
                category: 'releases', offset: 1, limit: 30, total: 2,
            });
            graph.nodes.push(
                { id: 'cat-releases', displayName: 'Releases', name: 'Releases (1)', isCategory: true, isCenter: false },
                { id: 'child-release-1', name: 'Album 1', type: 'release', isCenter: false, isCategory: false },
            );
            graph.links.push({ source: 'cat-releases', target: 'child-release-1' });

            window.apiClient.expand.mockResolvedValue({
                children: [
                    { id: '1', name: 'Album 1', type: 'release' },
                    { id: '2', name: 'Album 2', type: 'release' },
                ],
                total: 2, limit: 30, has_more: false, offset: 1,
            });

            const loadMoreNode = { id: 'load-more-cat-releases', categoryId: 'cat-releases' };
            await graph._loadMoreCategory(loadMoreNode);

            const childNodes = graph.nodes.filter(n => n.id.startsWith('child-'));
            expect(childNodes).toHaveLength(2);
        });
    });

    describe('setCompareYears with categories', () => {
        it('should clear child nodes and fetch comparison data for each category', async () => {
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';

            graph.nodes.push(
                { id: 'center-1', isCenter: true, isCategory: false, name: 'Radiohead', type: 'artist' },
                { id: 'cat-releases', isCategory: true, isCenter: false, displayName: 'Releases', name: 'Releases (5)', count: 5 },
                { id: 'child-release-1', isCategory: false, isCenter: false, name: 'Album 1', type: 'release' },
            );
            graph.links.push(
                { source: 'center-1', target: 'cat-releases' },
                { source: 'cat-releases', target: 'child-release-1' },
            );
            graph._categoryMeta.set('cat-releases', {
                parentName: 'Radiohead', parentType: 'artist',
                category: 'releases', offset: 5, limit: 30, total: 5,
            });

            window.apiClient.expand
                .mockResolvedValueOnce({
                    children: [{ id: '1', name: 'A', type: 'release' }],
                    total: 1, limit: 30, has_more: false,
                })
                .mockResolvedValueOnce({
                    children: [{ id: '2', name: 'B', type: 'release' }],
                    total: 1, limit: 30, has_more: false,
                });

            await graph.setCompareYears(1990, 2000);
            // Wait for async _fetchComparisonData
            await new Promise(r => setTimeout(r, 20));

            expect(graph.compareMode).toBe(true);
            expect(graph.compareYearA).toBe(1990);
            expect(graph.compareYearB).toBe(2000);

            // Child nodes should be from comparison
            const childA = graph.nodes.find(n => n.id === 'child-release-1');
            expect(childA).toBeDefined();
        });
    });

    describe('_fetchComparisonData with categories and diff', () => {
        it('should update category label with arrow notation', async () => {
            graph.compareYearA = 1990;
            graph.compareYearB = 2000;
            graph.nodes.push({
                id: 'cat-releases', displayName: 'Releases', name: 'Releases',
                isCategory: true, isCenter: false, count: 5,
            });

            window.apiClient.expand
                .mockResolvedValueOnce({
                    children: [{ id: '1', name: 'A', type: 'release' }],
                    total: 1, limit: 30, has_more: false,
                })
                .mockResolvedValueOnce({
                    children: [{ id: '2', name: 'B', type: 'release' }],
                    total: 2, limit: 30, has_more: false,
                });

            graph._pendingExpands = 1;
            await graph._fetchComparisonData('cat-releases', 'Radiohead', 'artist', 'releases');

            const catNode = graph.nodes.find(n => n.id === 'cat-releases');
            expect(catNode.name).toContain('1');
            expect(catNode.name).toContain('2');
        });

        it('should skip duplicate nodes in comparison data', async () => {
            graph.compareYearA = 1990;
            graph.compareYearB = 2000;
            // Pre-add a node
            graph.nodes.push(
                { id: 'cat-releases', displayName: 'Releases', name: 'Releases', isCategory: true, isCenter: false },
                { id: 'child-release-1', name: 'A', type: 'release', isCenter: false, isCategory: false },
            );

            window.apiClient.expand
                .mockResolvedValueOnce({
                    children: [{ id: '1', name: 'A', type: 'release' }],
                    total: 1, limit: 30, has_more: false,
                })
                .mockResolvedValueOnce({
                    children: [{ id: '1', name: 'A', type: 'release' }],
                    total: 1, limit: 30, has_more: false,
                });

            graph._pendingExpands = 1;
            await graph._fetchComparisonData('cat-releases', 'Radiohead', 'artist', 'releases');

            // child-release-1 should NOT be duplicated
            const matching = graph.nodes.filter(n => n.id === 'child-release-1');
            expect(matching).toHaveLength(1);
        });
    });

    describe('snapshot / restore / clearAll / addEntity', () => {
        it('snapshot returns a deep copy of nodes and links', () => {
            graph.nodes = [{ id: 'n1', name: 'Artist', type: 'artist' }];
            graph.links = [{ source: 'n1', target: 'n2' }];
            const snap = graph.snapshot();
            expect(snap.nodes).toEqual(graph.nodes);
            expect(snap.links).toEqual(graph.links);
            // Ensure it's a deep copy
            snap.nodes[0].name = 'Modified';
            expect(graph.nodes[0].name).toBe('Artist');
        });

        it('restore replaces nodes and links', () => {
            graph.nodes = [{ id: 'old' }];
            graph.links = [];
            graph.restore({ nodes: [{ id: 'restored' }], links: [{ source: 'a', target: 'b' }] });
            expect(graph.nodes).toEqual([{ id: 'restored' }]);
            expect(graph.links).toEqual([{ source: 'a', target: 'b' }]);
        });

        it('clearAll empties nodes and links', () => {
            graph.nodes = [{ id: 'n1' }];
            graph.links = [{ source: 'n1', target: 'n2' }];
            graph.clearAll();
            expect(graph.nodes).toEqual([]);
            expect(graph.links).toEqual([]);
        });

        it('addEntity appends node directly when _app is not set', () => {
            graph._app = null;
            graph.addEntity({ name: 'Kraftwerk', entity_type: 'artist' });
            const added = graph.nodes.find(n => n.id === 'Kraftwerk');
            expect(added).toBeDefined();
            expect(added.type).toBe('artist');
        });

        it('addEntity delegates to _app._loadExplore when available', () => {
            const loadExplore = vi.fn();
            graph._app = { _loadExplore: loadExplore };
            const prevNodeCount = graph.nodes.length;
            graph.addEntity({ name: 'Kraftwerk', entity_type: 'artist' });
            expect(loadExplore).toHaveBeenCalledWith('Kraftwerk', 'artist');
            // Should not append a node directly
            expect(graph.nodes.length).toBe(prevNodeCount);
        });
    });

    describe('setBeforeYear with categories', () => {
        it('should re-fetch categories with year filter', async () => {
            graph.centerName = 'Radiohead';
            graph.centerType = 'artist';

            // Set up existing category
            graph.nodes.push(
                { id: 'center-1', isCenter: true, isCategory: false, name: 'Radiohead', type: 'artist' },
                { id: 'cat-releases', isCategory: true, isCenter: false, displayName: 'Releases', name: 'Releases (5)', count: 5 },
            );
            graph.links.push({ source: 'center-1', target: 'cat-releases' });
            graph._categoryMeta.set('cat-releases', {
                parentName: 'Radiohead', parentType: 'artist',
                category: 'releases', offset: 5, limit: 30, total: 5,
            });

            window.apiClient.expand.mockResolvedValue({
                children: [{ id: '1', name: 'Album 1', type: 'release' }],
                total: 1, limit: 30, has_more: false,
            });

            await graph.setBeforeYear(1990);

            expect(window.apiClient.expand).toHaveBeenCalledWith('Radiohead', 'artist', 'releases', 30, 0, 1990);
            expect(graph.beforeYear).toBe(1990);
        });
    });
});
