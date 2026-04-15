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
