import { describe, it, expect, vi, beforeEach } from 'vitest';
import { buildHandlers, buildSnapshotter } from '../static/js/nlq-handlers.js';

describe('buildHandlers', () => {
    let app;

    beforeEach(() => {
        app = {
            _switchPane: vi.fn(),
            _loadExplore: vi.fn(),
            graph: {
                clearAll: vi.fn(),
                addEntity: vi.fn(),
                highlightPath: vi.fn(),
                focusNode: vi.fn(),
                snapshot: vi.fn().mockReturnValue({ nodes: [], edges: [] }),
                restore: vi.fn(),
            },
        };
    });

    it('switchPane delegates to app._switchPane', () => {
        const handlers = buildHandlers({ app });
        handlers.switchPane({ pane: 'trends' });
        expect(app._switchPane).toHaveBeenCalledWith('trends');
    });

    it('seedGraph clears when replace=true', () => {
        const handlers = buildHandlers({ app });
        handlers.seedGraph({ entities: [{ name: 'Kraftwerk', entity_type: 'artist' }], replace: true });
        expect(app.graph.clearAll).toHaveBeenCalled();
        expect(app.graph.addEntity).toHaveBeenCalledWith({ name: 'Kraftwerk', entity_type: 'artist' });
    });

    it('focusNode triggers _loadExplore', () => {
        const handlers = buildHandlers({ app });
        handlers.focusNode({ name: 'Kraftwerk', entity_type: 'artist' });
        expect(app._loadExplore).toHaveBeenCalledWith('Kraftwerk', 'artist');
    });

    it('snapshotter captures graph + active pane', () => {
        app.activePane = 'explore';
        const snap = buildSnapshotter({ app });
        const s = snap.capture();
        expect(s.pane).toBe('explore');
        expect(app.graph.snapshot).toHaveBeenCalled();
    });

    it('snapshotter restore dispatches to graph and pane', () => {
        const snap = buildSnapshotter({ app });
        snap.restore({ pane: 'trends', graph: { nodes: [1] } });
        expect(app._switchPane).toHaveBeenCalledWith('trends');
        expect(app.graph.restore).toHaveBeenCalledWith({ nodes: [1] });
    });
});
