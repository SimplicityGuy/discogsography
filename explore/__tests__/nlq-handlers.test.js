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

    it('setTrendRange delegates to app.trends.setRange', () => {
        app.trends = { setRange: vi.fn() };
        const handlers = buildHandlers({ app });
        handlers.setTrendRange({ from: '1980', to: '1990' });
        expect(app.trends.setRange).toHaveBeenCalledWith('1980', '1990');
    });

    it('filterGraph delegates to app.graph.applyFilter', () => {
        app.graph.applyFilter = vi.fn();
        const handlers = buildHandlers({ app });
        handlers.filterGraph({ by: 'year', value: '1990' });
        expect(app.graph.applyFilter).toHaveBeenCalledWith('year', '1990');
    });

    it('findPath delegates to app.graph.findPath with kwargs', () => {
        app.graph.findPath = vi.fn();
        const handlers = buildHandlers({ app });
        handlers.findPath({ from: 'Kraftwerk', to: 'Daft Punk', from_type: 'artist', to_type: 'artist' });
        expect(app.graph.findPath).toHaveBeenCalledWith({ from: 'Kraftwerk', to: 'Daft Punk', fromType: 'artist', toType: 'artist' });
    });

    it('showCredits delegates to app.credits.show', () => {
        app.credits = { show: vi.fn() };
        const handlers = buildHandlers({ app });
        handlers.showCredits({ name: 'Kraftwerk', entity_type: 'artist' });
        expect(app.credits.show).toHaveBeenCalledWith('Kraftwerk', 'artist');
    });

    it('highlightPath delegates to app.graph.highlightPath', () => {
        app.graph.highlightPath = vi.fn();
        const handlers = buildHandlers({ app });
        handlers.highlightPath({ nodes: ['A', 'B'] });
        expect(app.graph.highlightPath).toHaveBeenCalledWith(['A', 'B']);
    });

    it('openInsightTile delegates to app.insights.openTile', () => {
        app.insights = { openTile: vi.fn() };
        const handlers = buildHandlers({ app });
        handlers.openInsightTile({ tile_id: 'top-artists' });
        expect(app.insights.openTile).toHaveBeenCalledWith('top-artists');
    });

    it('suggestFollowups delegates to app.nlq.setFollowups', () => {
        app.nlq = { setFollowups: vi.fn() };
        const handlers = buildHandlers({ app });
        handlers.suggestFollowups({ queries: ['Q1', 'Q2'] });
        expect(app.nlq.setFollowups).toHaveBeenCalledWith(['Q1', 'Q2']);
    });

    it('buildSnapshotter.capture includes trendRange when app.trends.getRange is defined', () => {
        app.trends = { getRange: vi.fn().mockReturnValue({ from: '1980', to: '1990' }) };
        app.activePane = 'trends';
        const snap = buildSnapshotter({ app });
        const s = snap.capture();
        expect(s.trendRange).toEqual({ from: '1980', to: '1990' });
    });

    it('buildSnapshotter.restore calls trends.setRange when snapshot has trendRange', () => {
        app.trends = { setRange: vi.fn() };
        const snap = buildSnapshotter({ app });
        snap.restore({ trendRange: { from: '1980', to: '1990' } });
        expect(app.trends.setRange).toHaveBeenCalledWith('1980', '1990');
    });
});
