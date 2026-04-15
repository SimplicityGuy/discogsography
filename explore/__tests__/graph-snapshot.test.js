import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Minimal d3 stub sufficient for GraphVisualization constructor in jsdom.
 */
function createD3Stub() {
    function makeChainSel() {
        const sel = {};
        const chainMethods = [
            'attr', 'style', 'text', 'call', 'on', 'classed', 'remove',
            'each', 'data', 'join', 'transition', 'duration', 'filter',
        ];
        chainMethods.forEach(m => { sel[m] = vi.fn().mockReturnValue(sel); });
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

    return {
        select: vi.fn().mockImplementation(() => makeChainSel()),
        zoom: vi.fn().mockReturnValue(zoomMock),
        zoomIdentity: {},
        forceSimulation: vi.fn().mockReturnValue({
            force: vi.fn().mockReturnThis(),
            on: vi.fn().mockReturnThis(),
            stop: vi.fn(),
            alpha: vi.fn().mockReturnThis(),
            alphaTarget: vi.fn().mockReturnThis(),
            restart: vi.fn(),
        }),
        forceLink: vi.fn().mockReturnValue({ id: vi.fn().mockReturnThis(), distance: vi.fn().mockReturnThis() }),
        forceManyBody: vi.fn().mockReturnValue({ strength: vi.fn().mockReturnThis() }),
        forceCenter: vi.fn(),
        forceCollide: vi.fn().mockReturnValue({ radius: vi.fn().mockReturnThis() }),
        drag: vi.fn().mockReturnValue({ on: vi.fn().mockReturnThis() }),
    };
}

function setupDOM() {
    document.body.textContent = '';

    const container = document.createElement('div');
    container.id = 'graphContainer';
    container.style.width = '400px';
    container.style.height = '400px';
    document.body.appendChild(container);

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'graphSvg';
    document.body.appendChild(svg);

    const placeholder = document.createElement('div');
    placeholder.id = 'graphPlaceholder';
    document.body.appendChild(placeholder);

    ['zoomInBtn', 'zoomOutBtn', 'zoomResetBtn', 'fullscreenBtn'].forEach(id => {
        const btn = document.createElement('button');
        btn.id = id;
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined';
        btn.appendChild(icon);
        document.body.appendChild(btn);
    });
}

describe('GraphVisualization snapshot/restore/clearAll/addEntity', () => {
    let graph;

    beforeAll(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        globalThis.d3 = createD3Stub();
        setupDOM();
        loadScriptDirect('graph.js');
    });

    beforeEach(() => {
        setupDOM();
        globalThis.d3 = createD3Stub();
        graph = new GraphVisualization('graphContainer'); // eslint-disable-line no-undef
    });

    it('snapshot returns deep copies of current nodes and links', () => {
        graph.nodes = [{ id: '1', name: 'Kraftwerk' }];
        graph.links = [{ source: '1', target: '2' }];
        const snap = graph.snapshot();
        expect(snap.nodes).toEqual([{ id: '1', name: 'Kraftwerk' }]);
        expect(snap.links).toEqual([{ source: '1', target: '2' }]);
        // Verify deep copy — mutations don't affect original
        snap.nodes[0].name = 'changed';
        expect(graph.nodes[0].name).toBe('Kraftwerk');
    });

    it('restore replaces nodes and links and calls _render', () => {
        graph._render = vi.fn();
        graph.restore({ nodes: [{ id: '2' }], links: [] });
        expect(graph.nodes).toEqual([{ id: '2' }]);
        expect(graph.links).toEqual([]);
        expect(graph._render).toHaveBeenCalled();
    });

    it('clearAll empties nodes and links and calls _render', () => {
        graph.nodes = [{ id: '1' }];
        graph.links = [{ source: '1', target: '2' }];
        graph._render = vi.fn();
        graph.clearAll();
        expect(graph.nodes).toEqual([]);
        expect(graph.links).toEqual([]);
        expect(graph._render).toHaveBeenCalled();
    });

    it('addEntity appends a node and calls _render', () => {
        graph.nodes = [];
        graph._render = vi.fn();
        graph.addEntity({ name: 'Aphex Twin', entity_type: 'artist' });
        expect(graph.nodes).toHaveLength(1);
        expect(graph.nodes[0]).toMatchObject({ id: 'Aphex Twin', name: 'Aphex Twin', type: 'artist' });
        expect(graph._render).toHaveBeenCalled();
    });
});
