import { describe, it, expect, vi } from 'vitest';
import { NlqActionApplier } from '../static/js/nlq-action-applier.js';

function mockHandlers() {
    return {
        switchPane: vi.fn(),
        setTrendRange: vi.fn(),
        filterGraph: vi.fn(),
        seedGraph: vi.fn(),
        findPath: vi.fn(),
        showCredits: vi.fn(),
        highlightPath: vi.fn(),
        focusNode: vi.fn(),
        openInsightTile: vi.fn(),
        suggestFollowups: vi.fn(),
    };
}

function mockSnapshotter() {
    return {
        capture: vi.fn().mockReturnValue({ tag: 'snap1' }),
        restore: vi.fn(),
    };
}

describe('NlqActionApplier', () => {
    it('applies switch_pane before seed_graph regardless of list order', () => {
        const handlers = mockHandlers();
        const snap = mockSnapshotter();
        const applier = new NlqActionApplier({ handlers, snapshotter: snap });
        applier.apply([
            { type: 'seed_graph', entities: [{ name: 'Kraftwerk', entity_type: 'artist' }] },
            { type: 'switch_pane', pane: 'trends' },
        ]);
        const callOrder = [
            handlers.switchPane.mock.invocationCallOrder[0],
            handlers.seedGraph.mock.invocationCallOrder[0],
        ];
        expect(callOrder[0]).toBeLessThan(callOrder[1]);
    });

    it('skips unknown types and continues', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([
            { type: 'nonsense' },
            { type: 'focus_node', name: 'Kraftwerk', entity_type: 'artist' },
        ]);
        expect(handlers.focusNode).toHaveBeenCalledWith({ name: 'Kraftwerk', entity_type: 'artist' });
        expect(result.applied).toBe(1);
        expect(result.skipped).toBe(1);
    });

    it('snapshots before applying and restores on undo', () => {
        const handlers = mockHandlers();
        const snap = mockSnapshotter();
        const applier = new NlqActionApplier({ handlers, snapshotter: snap });
        applier.apply([{ type: 'seed_graph', entities: [{ name: 'K', entity_type: 'artist' }] }]);
        expect(snap.capture).toHaveBeenCalledTimes(1);
        applier.undo();
        expect(snap.restore).toHaveBeenCalledWith({ tag: 'snap1' });
    });

    it('counts a failing handler as skipped', () => {
        const handlers = mockHandlers();
        handlers.seedGraph.mockImplementation(() => { throw new Error('boom'); });
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'seed_graph', entities: [] }]);
        expect(result.applied).toBe(0);
        expect(result.skipped).toBe(1);
    });

    it('validates seed_graph entity shape and skips malformed entries', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([
            { type: 'seed_graph', entities: [{ name: 'K', entity_type: 'artist' }, { name: '', entity_type: 'artist' }] },
        ]);
        const callArg = handlers.seedGraph.mock.calls[0][0];
        expect(callArg.entities).toHaveLength(1);
        expect(result.applied).toBe(1);
    });
});

describe('NlqActionApplier — sanitizer coverage', () => {
    it('filter_graph — valid action reaches filterGraph handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'filter_graph', by: 'year', value: '1990' }]);
        expect(handlers.filterGraph).toHaveBeenCalledWith({ by: 'year', value: '1990' });
        expect(result.applied).toBe(1);
    });

    it('find_path — valid action reaches findPath handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'find_path', from: 'Kraftwerk', to: 'Daft Punk', from_type: 'artist', to_type: 'artist' }]);
        expect(handlers.findPath).toHaveBeenCalledWith({ from: 'Kraftwerk', to: 'Daft Punk', from_type: 'artist', to_type: 'artist' });
        expect(result.applied).toBe(1);
    });

    it('show_credits — valid action reaches showCredits handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'show_credits', name: 'Kraftwerk', entity_type: 'artist' }]);
        expect(handlers.showCredits).toHaveBeenCalledWith({ name: 'Kraftwerk', entity_type: 'artist' });
        expect(result.applied).toBe(1);
    });

    it('highlight_path — valid action with nodes reaches highlightPath handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'highlight_path', nodes: ['NodeA', 'NodeB'] }]);
        expect(handlers.highlightPath).toHaveBeenCalledWith({ nodes: ['NodeA', 'NodeB'] });
        expect(result.applied).toBe(1);
    });

    it('open_insight_tile — valid action with tile_id reaches openInsightTile handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'open_insight_tile', tile_id: 'top-artists' }]);
        expect(handlers.openInsightTile).toHaveBeenCalledWith({ tile_id: 'top-artists' });
        expect(result.applied).toBe(1);
    });

    it('set_trend_range — valid action with from/to reaches setTrendRange handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'set_trend_range', from: '1980', to: '1990' }]);
        expect(handlers.setTrendRange).toHaveBeenCalledWith({ from: '1980', to: '1990' });
        expect(result.applied).toBe(1);
    });

    it('suggest_followups — valid action with queries reaches suggestFollowups handler', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'suggest_followups', queries: ['Q1', 'Q2'] }]);
        expect(handlers.suggestFollowups).toHaveBeenCalledWith({ queries: ['Q1', 'Q2'] });
        expect(result.applied).toBe(1);
    });

    it('sanitizeSwitchPane returns null for invalid pane — action is skipped', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'switch_pane', pane: 'invalid_pane' }]);
        expect(handlers.switchPane).not.toHaveBeenCalled();
        expect(result.skipped).toBe(1);
    });

    it('sanitizeFocusNode returns null for missing name — action is skipped', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'focus_node', entity_type: 'artist' }]);
        expect(handlers.focusNode).not.toHaveBeenCalled();
        expect(result.skipped).toBe(1);
    });

    it('sanitizeFocusNode returns null for invalid entity_type — action is skipped', () => {
        const handlers = mockHandlers();
        const applier = new NlqActionApplier({ handlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'focus_node', name: 'Kraftwerk', entity_type: 'invalid' }]);
        expect(handlers.focusNode).not.toHaveBeenCalled();
        expect(result.skipped).toBe(1);
    });

    it('skips action when handler is not registered in the map', () => {
        const handlers = mockHandlers();
        // Remove a handler to simulate unregistered path
        const partialHandlers = { ...handlers };
        delete partialHandlers.filterGraph;
        const applier = new NlqActionApplier({ handlers: partialHandlers, snapshotter: mockSnapshotter() });
        const result = applier.apply([{ type: 'filter_graph', by: 'year', value: '1990' }]);
        expect(result.skipped).toBe(1);
        expect(result.applied).toBe(0);
    });
});
