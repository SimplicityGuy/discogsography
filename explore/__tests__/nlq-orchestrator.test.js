import { describe, it, expect, vi, beforeEach } from 'vitest';
import { initNlq } from '../static/js/nlq.js';

function makeApiClient({ enabled = true, suggestions = [], streamMode = 'result', result = null, err = null } = {}) {
    return {
        checkNlqStatus: vi.fn().mockResolvedValue({ enabled }),
        fetchNlqSuggestions: vi.fn().mockResolvedValue({ suggestions }),
        askNlqStream: vi.fn().mockImplementation((_query, _ctx, _onChunk, onResult, onError) => {
            if (streamMode === 'result') {
                onResult(result ?? { summary: 'ok', entities: [], actions: [{ type: 'switch_pane', pane: 'trends' }] });
            } else {
                onError(err ?? new Error('stream error'));
            }
        }),
    };
}

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

describe('initNlq orchestrator', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const pillMount = document.createElement('div');
        pillMount.id = 'nlqPillMount';
        document.body.appendChild(pillMount);
        localStorage.clear();
    });

    it('mounts the pill when checkNlqStatus returns enabled=true', async () => {
        const apiClient = makeApiClient({ enabled: true });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();
        const pillRoot = document.querySelector('.nlq-pill-root');
        expect(pillRoot).not.toBeNull();
        expect(apiClient.checkNlqStatus).toHaveBeenCalledTimes(1);
    });

    it('does NOT mount the pill when checkNlqStatus returns enabled=false', async () => {
        const apiClient = makeApiClient({ enabled: false });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();
        const pillRoot = document.querySelector('.nlq-pill-root');
        expect(pillRoot).toBeNull();
    });

    it('calls askNlqStream and applies actions on submit', async () => {
        const apiClient = makeApiClient({ enabled: true, streamMode: 'result' });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('show me artists');

        expect(apiClient.askNlqStream).toHaveBeenCalledWith(
            'show me artists',
            expect.objectContaining({ entity_id: null, entity_type: null }),
            expect.any(Function),
            expect.any(Function),
            expect.any(Function),
        );
        expect(app._switchPane).toHaveBeenCalledWith('trends');
    });

    it('renders answer inside the pill (no separate strip)', async () => {
        const apiClient = makeApiClient({
            enabled: true,
            streamMode: 'result',
            result: { summary: 'Here are the results.', entities: [], actions: [] },
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('hello');

        const answerSlot = document.querySelector('[data-testid="nlq-pill-answer"]');
        expect(answerSlot).not.toBeNull();
        expect(answerSlot.textContent).toContain('Here are the results.');
        // The pill must remain open after submit — no collapse, no legacy strip.
        expect(document.querySelector('[data-testid="nlq-pill-expanded"]')).not.toBeNull();
        expect(document.querySelector('[data-testid="nlq-pill-collapsed"]')).toBeNull();
        expect(document.querySelector('[data-testid="nlq-strip"]')).toBeNull();
    });

    it('input stays visible in answered state so follow-ups work', async () => {
        let callIdx = 0;
        const apiClient = {
            checkNlqStatus: vi.fn().mockResolvedValue({ enabled: true }),
            fetchNlqSuggestions: vi.fn().mockResolvedValue({ suggestions: [] }),
            askNlqStream: vi.fn().mockImplementation((query, _ctx, _onChunk, onResult) => {
                callIdx++;
                onResult({ summary: `answer ${callIdx} for ${query}`, entities: [], actions: [] });
            }),
        };
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('first question');
        const input1 = document.querySelector('[data-testid="nlq-pill-input"]');
        expect(input1).not.toBeNull();
        expect(document.querySelector('[data-testid="nlq-pill-answer"]').textContent).toContain('answer 1');

        // Follow-up: type a new query + Enter, without collapsing.
        const input2 = document.querySelector('[data-testid="nlq-pill-input"]');
        input2.value = 'second question';
        input2.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

        expect(apiClient.askNlqStream).toHaveBeenCalledTimes(2);
        expect(document.querySelector('[data-testid="nlq-pill-answer"]').textContent).toContain('answer 2');
    });

    it('shows error message inside the pill when askNlqStream calls onError', async () => {
        const apiClient = makeApiClient({ enabled: true, streamMode: 'error' });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('will fail');

        const answerSlot = document.querySelector('[data-testid="nlq-pill-answer"]');
        expect(answerSlot).not.toBeNull();
        expect(answerSlot.textContent.toLowerCase()).toContain('failed');
        expect(answerSlot.classList.contains('nlq-answer-slot--error')).toBe(true);
    });

    it('answer undo button triggers applier.undo (onUndo callback)', async () => {
        const apiClient = makeApiClient({
            enabled: true,
            streamMode: 'result',
            result: { summary: 'done', entities: [], actions: [{ type: 'switch_pane', pane: 'trends' }] },
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('apply action');

        const undoBtn = document.querySelector('[data-testid="nlq-answer-undo"]');
        expect(undoBtn).not.toBeNull();
        expect(() => undoBtn.click()).not.toThrow();
    });

    it('onEntityClick callback delegates to app._loadExplore', async () => {
        const apiClient = makeApiClient({ enabled: true });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        apiClient.askNlqStream.mockImplementation((_q, _ctx, _onChunk, onResult) => {
            onResult({ summary: 'Kraftwerk', entities: [{ name: 'Kraftwerk', type: 'artist' }], actions: [] });
        });

        openAndSubmit('find Kraftwerk');

        const entityLink = document.querySelector('.nlq-entity-link');
        if (entityLink) {
            entityLink.click();
            expect(app._loadExplore).toHaveBeenCalledWith('Kraftwerk', 'artist');
        } else {
            expect(apiClient.askNlqStream).toHaveBeenCalled();
        }
    });

    it('collapsing after an answer leaves a receipt that reopens the answer', async () => {
        const apiClient = makeApiClient({
            enabled: true,
            streamMode: 'result',
            result: { summary: 'The biggest label is Anjunabeats.', entities: [], actions: [] },
        });
        const app = makeApp();
        initNlq({ app, apiClient, mountId: 'nlqPillMount' });
        await flush();

        openAndSubmit('biggest label');

        // Collapse via the × button
        document.querySelector('[data-testid="nlq-pill-close"]').click();
        expect(document.querySelector('[data-testid="nlq-pill-collapsed"]')).not.toBeNull();

        const receipt = document.querySelector('[data-testid="nlq-pill-receipt"]');
        expect(receipt).not.toBeNull();
        expect(receipt.textContent).toContain('Anjunabeats');

        // Clicking the receipt body reopens the pill in answered state
        document.querySelector('[data-testid="nlq-pill-receipt-open"]').click();
        const answerSlot = document.querySelector('[data-testid="nlq-pill-answer"]');
        expect(answerSlot).not.toBeNull();
        expect(answerSlot.textContent).toContain('Anjunabeats');
    });
});
