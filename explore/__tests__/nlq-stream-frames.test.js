/**
 * Regression tests for discogsography-ebgz.
 *
 * The SSE stream parser dispatched only `status` and `result` frames:
 *
 *  - the server's dedicated `actions` frame was parsed and thrown away, and
 *    askNlqStream had no onActions parameter at all, so every agent-driven graph
 *    action (seed_graph, switch_pane, focus_node, …) silently no-opped;
 *  - the server's `error` frame was likewise dropped, and since the engine
 *    failure closes the stream with HTTP 200 neither onResult nor onError ever
 *    fired — the pill stayed on "Thinking…" with a disabled input forever.
 *
 * These tests pin all four frame types plus the "closed without a result"
 * case, and the orchestrator's apply-exactly-once behavior now that actions
 * ride on both the sideband frame and the result frame (discogsography-l6fm).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { initNlq } from '../static/js/nlq.js';
import '../static/js/api-client.js';

function makeReadableStream(chunks) {
    let index = 0;
    return {
        getReader() {
            return {
                read() {
                    if (index < chunks.length) {
                        return Promise.resolve({ done: false, value: new TextEncoder().encode(chunks[index++]) });
                    }
                    return Promise.resolve({ done: true, value: undefined });
                },
            };
        },
    };
}

function stubStream(chunks) {
    vi.stubGlobal('fetch', async () => ({ ok: true, body: makeReadableStream(chunks) }));
}

const settle = () => new Promise(r => setTimeout(r, 50));

describe('askNlqStream frame dispatch', () => {
    beforeEach(() => {
        vi.unstubAllGlobals();
    });

    it('dispatches the actions frame to onActions', async () => {
        stubStream([
            'event: actions\ndata: {"actions":[{"type":"seed_graph"}]}\n\n',
            'event: result\ndata: {"summary":"hi","actions":[{"type":"seed_graph"}]}\n\n',
        ]);

        const onActions = vi.fn();
        window.apiClient.askNlqStream('test', null, vi.fn(), vi.fn(), vi.fn(), onActions);
        await settle();

        expect(onActions).toHaveBeenCalledWith([{ type: 'seed_graph' }]);
    });

    it('passes an empty array when the actions frame carries no actions key', async () => {
        stubStream(['event: actions\ndata: {}\n\n', 'event: result\ndata: {"summary":"hi"}\n\n']);

        const onActions = vi.fn();
        window.apiClient.askNlqStream('test', null, vi.fn(), vi.fn(), vi.fn(), onActions);
        await settle();

        expect(onActions).toHaveBeenCalledWith([]);
    });

    it('reports a server error frame through onError', async () => {
        // The engine failure closes the stream with HTTP 200, so this frame is
        // the ONLY signal the caller ever gets.
        stubStream(['event: error\ndata: {"error":"An internal error occurred"}\n\n']);

        const onError = vi.fn();
        const onResult = vi.fn();
        window.apiClient.askNlqStream('test', null, vi.fn(), onResult, onError);
        await settle();

        expect(onResult).not.toHaveBeenCalled();
        expect(onError).toHaveBeenCalledTimes(1);
        expect(onError.mock.calls[0][0].message).toBe('An internal error occurred');
    });

    it('reports a stream that closes without a result frame through onError', async () => {
        stubStream(['event: status\ndata: {"step":"thinking"}\n\n']);

        const onError = vi.fn();
        window.apiClient.askNlqStream('test', null, vi.fn(), vi.fn(), onError);
        await settle();

        expect(onError).toHaveBeenCalledTimes(1);
        expect(onError.mock.calls[0][0].message).toBe('stream closed without a result');
    });

    it('settles exactly once — a normal close after a result frame is not an error', async () => {
        stubStream(['event: result\ndata: {"summary":"hi"}\n\n']);

        const onResult = vi.fn();
        const onError = vi.fn();
        window.apiClient.askNlqStream('test', null, vi.fn(), onResult, onError);
        await settle();

        expect(onResult).toHaveBeenCalledTimes(1);
        expect(onError).not.toHaveBeenCalled();
    });

    it('settles exactly once — a close after an error frame does not fire onError twice', async () => {
        stubStream(['event: error\ndata: {"error":"boom"}\n\n']);

        const onError = vi.fn();
        window.apiClient.askNlqStream('test', null, vi.fn(), vi.fn(), onError);
        await settle();

        expect(onError).toHaveBeenCalledTimes(1);
    });

    it('still works when the caller passes no onActions (backwards compatible)', async () => {
        stubStream([
            'event: actions\ndata: {"actions":[{"type":"seed_graph"}]}\n\n',
            'event: result\ndata: {"summary":"hi"}\n\n',
        ]);

        const onResult = vi.fn();
        expect(() => window.apiClient.askNlqStream('test', null, vi.fn(), onResult, vi.fn())).not.toThrow();
        await settle();

        expect(onResult).toHaveBeenCalledWith({ summary: 'hi' });
    });
});

function makeApp() {
    return {
        activePane: 'explore',
        currentEntity: null,
        _switchPane: vi.fn(),
        _loadExplore: vi.fn(),
        graph: {
            clearAll: vi.fn(),
            addEntity: vi.fn(),
            snapshot: vi.fn().mockReturnValue({ nodes: [], links: [] }),
            restore: vi.fn(),
        },
        trends: { setRange: vi.fn(), getRange: vi.fn().mockReturnValue(null) },
        credits: { show: vi.fn() },
        insights: { openTile: vi.fn() },
        nlq: { setFollowups: vi.fn() },
    };
}

async function flush() {
    await Promise.resolve();
    await Promise.resolve();
}

function openAndSubmit(query) {
    document.querySelector('[data-testid="nlq-pill-collapsed"]').click();
    const input = document.querySelector('[data-testid="nlq-pill-input"]');
    input.value = query;
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}

function makeClient(impl) {
    return {
        checkNlqStatus: vi.fn().mockResolvedValue({ enabled: true }),
        fetchNlqSuggestions: vi.fn().mockResolvedValue({ suggestions: [] }),
        askNlqStream: vi.fn().mockImplementation(impl),
    };
}

describe('NLQ orchestrator action application', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
        localStorage.clear();
    });

    it('applies actions delivered on the actions frame, even when the result frame omits them', async () => {
        const apiClient = makeClient((_q, _ctx, _onStatus, onResult, _onError, onActions) => {
            onActions([{ type: 'switch_pane', pane: 'trends' }]);
            onResult({ summary: 'ok', entities: [] });
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('show me trends');

        expect(app._switchPane).toHaveBeenCalledWith('trends');
    });

    it('applies actions exactly once when both frames carry them', async () => {
        const actions = [{ type: 'switch_pane', pane: 'trends' }];
        const apiClient = makeClient((_q, _ctx, _onStatus, onResult, _onError, onActions) => {
            onActions(actions);
            onResult({ summary: 'ok', entities: [], actions });
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('show me trends');

        expect(app._switchPane).toHaveBeenCalledTimes(1);
    });

    it('still applies actions from the result frame when no actions frame arrives', async () => {
        const apiClient = makeClient((_q, _ctx, _onStatus, onResult) => {
            onResult({ summary: 'ok', entities: [], actions: [{ type: 'switch_pane', pane: 'trends' }] });
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('show me trends');

        expect(app._switchPane).toHaveBeenCalledWith('trends');
    });

    it('leaves the loading state when the stream reports an error frame', async () => {
        const apiClient = makeClient((_q, _ctx, _onStatus, _onResult, onError) => {
            onError(new Error('An internal error occurred'));
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('will fail');

        const answerSlot = document.querySelector('[data-testid="nlq-pill-answer"]');
        expect(answerSlot).not.toBeNull();
        expect(answerSlot.textContent.toLowerCase()).toContain('failed');
        const input = document.querySelector('[data-testid="nlq-pill-input"]');
        expect(input.disabled).toBe(false);
    });

    it('reports actions already applied when the stream errors after the actions frame', async () => {
        const apiClient = makeClient((_q, _ctx, _onStatus, _onResult, onError, onActions) => {
            onActions([{ type: 'switch_pane', pane: 'trends' }]);
            onError(new Error('engine died after acting'));
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('act then fail');

        // The action really happened, so the answer must offer Undo for it
        // rather than claiming nothing was applied.
        expect(app._switchPane).toHaveBeenCalledWith('trends');
        expect(document.querySelector('[data-testid="nlq-answer-undo"]')).not.toBeNull();
    });
});
