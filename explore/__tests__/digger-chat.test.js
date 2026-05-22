import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

/**
 * Create the minimal DOM elements DiggerPane reads in its constructor.
 */
function setupDiggerDOM() {
    document.body.textContent = '';
    const ids = ['diggerPane', 'diggerLoading', 'diggerBody', 'diggerHeaderActions'];
    for (const id of ids) {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
    }
}

const ENABLED_SETTINGS = { ok: true, status: 200, body: { enabled: true, currency: 'USD' } };

function makeBundle(overrides = {}) {
    return {
        name: 'cheapest',
        seller_orders: [],
        total_item_cost_cents: 1000,
        total_shipping_cents: 500,
        grand_total_cents: 1500,
        coverage: { must: 1, nice: 0, eventually: 0 },
        avg_condition_score: 7.0,
        solver: 'ilp',
        reasoning_hint: '1 must from 1 seller.',
        ...overrides,
    };
}

describe('DiggerPane chat', () => {
    beforeEach(() => {
        setupDiggerDOM();
        delete globalThis.window;
        globalThis.window = globalThis;
        window.authManager = {
            getToken: vi.fn().mockReturnValue('test-token'),
            isLoggedIn: vi.fn().mockReturnValue(true),
        };
        window.apiClient = {
            getDiggerSettings: vi.fn().mockResolvedValue(ENABLED_SETTINGS),
            getDiggerWantlist: vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [] } }),
            getDiggerReports: vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [] } }),
            getDiggerAgentSessions: vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [] } }),
            streamDiggerAgent: vi.fn(),
        };
        window.exploreApp = undefined;
        loadScript('digger.js');
    });

    // ---------------------------------------------------------------- //
    // Navigation
    // ---------------------------------------------------------------- //

    it('renders a Chat nav button when Digger is enabled', async () => {
        await window.diggerPane.init();
        const header = document.getElementById('diggerHeaderActions');
        const labels = Array.from(header.querySelectorAll('.digger-nav-btn')).map((b) => b.textContent);
        expect(labels).toContain('Chat');
    });

    it('marks the Chat nav button active in the chat view', async () => {
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        const chatBtn = document.getElementById('diggerHeaderActions').querySelector('.digger-nav-btn[data-view="chat"]');
        expect(chatBtn.classList.contains('active')).toBe(true);
    });

    it('switches to the chat view when the Chat nav button is clicked', async () => {
        await window.diggerPane.init();
        document.getElementById('diggerHeaderActions').querySelector('.digger-nav-btn[data-view="chat"]').click();
        await Promise.resolve();
        expect(window.diggerPane._view).toBe('chat');
    });

    // ---------------------------------------------------------------- //
    // Chat view scaffold
    // ---------------------------------------------------------------- //

    it('renders a message list and composer', async () => {
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        const body = document.getElementById('diggerBody');
        expect(body.querySelector('.digger-chat-messages')).not.toBeNull();
        expect(body.querySelector('.digger-chat-input')).not.toBeNull();
        expect(body.querySelector('.digger-chat-send')).not.toBeNull();
    });

    // ---------------------------------------------------------------- //
    // Sending + streaming
    // ---------------------------------------------------------------- //

    it('renders the user message and streamed assistant text, capturing the session id', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => {
            cbs.onText({ delta: 'Hel' });
            cbs.onText({ delta: 'lo' });
            cbs.onDone({ session_id: 's1', usage: { input: 1, output: 1, cache_read: 0 } });
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'find me a deal';
        await window.diggerPane._sendChatMessage();

        const body = document.getElementById('diggerBody');
        expect(body.querySelector('.digger-chat-msg-user').textContent).toContain('find me a deal');
        expect(body.querySelector('.digger-chat-msg-assistant').textContent).toContain('Hello');
        expect(window.diggerPane._chatSessionId).toBe('s1');
        // payload carried the (initially null) session id
        expect(window.apiClient.streamDiggerAgent).toHaveBeenCalledWith(
            'test-token',
            { user_message: 'find me a deal', session_id: null },
            expect.any(Object),
        );
    });

    it('ignores empty drafts and concurrent sends', async () => {
        window.apiClient.streamDiggerAgent = vi.fn();
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = '   ';
        await window.diggerPane._sendChatMessage();
        expect(window.apiClient.streamDiggerAgent).not.toHaveBeenCalled();

        // concurrent guard
        window.diggerPane._chatInput.value = 'hi';
        window.diggerPane._chatBusy = true;
        await window.diggerPane._sendChatMessage();
        expect(window.apiClient.streamDiggerAgent).not.toHaveBeenCalled();
    });

    it('renders tool-call pills and tool-result details', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => {
            cbs.onToolCall({ id: 't1', name: 'compute_bundles', input: { budget_cap_cents: 20000 } });
            cbs.onToolResult({ id: 't1', name: 'compute_bundles', output: { bundles: [] } });
            cbs.onDone({ session_id: 's1', usage: {} });
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'deals?';
        await window.diggerPane._sendChatMessage();

        const body = document.getElementById('diggerBody');
        expect(body.querySelector('.digger-tool-pill')).not.toBeNull();
        expect(body.querySelector('.digger-tool-pill').textContent).toContain('compute_bundles');
        const details = body.querySelector('details.digger-tool-result');
        expect(details).not.toBeNull();
        expect(details.querySelector('pre').textContent).toContain('bundles');
    });

    it('renders a bundle card for bundle_card events', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => {
            cbs.onBundleCard({ bundle: makeBundle() });
            cbs.onDone({ session_id: 's1', usage: {} });
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'bundle please';
        await window.diggerPane._sendChatMessage();

        expect(document.getElementById('diggerBody').querySelector('.digger-bundle-card')).not.toBeNull();
    });

    it('renders an error bubble on error events and re-enables sending', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => {
            cbs.onError({ reason: 'daily token cap exceeded' });
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'hi';
        await window.diggerPane._sendChatMessage();

        const body = document.getElementById('diggerBody');
        expect(body.querySelector('.digger-chat-msg-error')).not.toBeNull();
        expect(body.textContent).toContain('daily token cap exceeded');
        expect(window.diggerPane._chatBusy).toBe(false);
        expect(window.diggerPane._chatSendBtn.disabled).toBe(false);
    });

    it('sends on Enter (without shift) from the composer', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => cbs.onDone({ session_id: 's1', usage: {} }));
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        const input = window.diggerPane._chatInput;
        input.value = 'hello';
        input.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await Promise.resolve();
        expect(window.apiClient.streamDiggerAgent).toHaveBeenCalled();
    });
});
