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

    // ---------------------------------------------------------------- //
    // Proposal cards
    // ---------------------------------------------------------------- //

    function makeProposal(overrides = {}) {
        return {
            proposal_id: 'p1',
            created_at: '2026-05-22T00:00:00+00:00',
            status: 'pending',
            payload: [{ release_id: 1, current_tier: 'nice', proposed_tier: 'must', reason: 'rare press' }],
            ...overrides,
        };
    }

    async function streamProposalAndSettle() {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => {
            cbs.onProposalCard({ proposal: { proposal_id: 'p1', count: 1 } });
            cbs.onDone({ session_id: 's1', usage: {} });
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'should I bump anything?';
        await window.diggerPane._sendChatMessage();
        await new Promise((r) => setTimeout(r, 0)); // let the proposal fetch + render settle
    }

    it('renders a proposal card from a proposal_card event and approves it', async () => {
        window.apiClient.getDiggerProposals = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [makeProposal()] } });
        window.apiClient.approveDiggerProposal = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { applied: 1 } });

        await streamProposalAndSettle();

        const body = document.getElementById('diggerBody');
        const card = body.querySelector('.digger-proposal-card[data-proposal-id="p1"]');
        expect(card).not.toBeNull();
        expect(card.textContent).toContain('rare press');
        expect(card.textContent).toContain('must');

        card.querySelectorAll('.digger-proposal-actions button')[0].click(); // Approve
        await new Promise((r) => setTimeout(r, 0));
        expect(window.apiClient.approveDiggerProposal).toHaveBeenCalledWith('test-token', 'p1');
        expect(card.textContent).toContain('Applied 1 change');
        expect(card.querySelector('.digger-proposal-actions')).toBeNull();
    });

    it('rejects a proposal from the card', async () => {
        window.apiClient.getDiggerProposals = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [makeProposal()] } });
        window.apiClient.rejectDiggerProposal = vi.fn().mockResolvedValue({ ok: true, status: 204, body: null });

        await streamProposalAndSettle();

        const card = document.getElementById('diggerBody').querySelector('.digger-proposal-card[data-proposal-id="p1"]');
        card.querySelectorAll('.digger-proposal-actions button')[1].click(); // Reject
        await new Promise((r) => setTimeout(r, 0));
        expect(window.apiClient.rejectDiggerProposal).toHaveBeenCalledWith('test-token', 'p1');
        expect(card.textContent).toContain('Rejected');
    });

    it('shows a note when the proposal is no longer available', async () => {
        window.apiClient.getDiggerProposals = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [] } });

        await streamProposalAndSettle();

        expect(document.getElementById('diggerBody').textContent).toContain('no longer available');
    });

    it('surfaces an approve failure without collapsing the actions', async () => {
        window.apiClient.getDiggerProposals = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [makeProposal()] } });
        window.apiClient.approveDiggerProposal = vi.fn().mockResolvedValue({ ok: false, status: 404, body: null });

        await streamProposalAndSettle();

        const card = document.getElementById('diggerBody').querySelector('.digger-proposal-card[data-proposal-id="p1"]');
        card.querySelectorAll('.digger-proposal-actions button')[0].click();
        await new Promise((r) => setTimeout(r, 0));
        expect(card.textContent).toContain('Could not approve');
        expect(card.querySelector('.digger-proposal-actions')).not.toBeNull();
    });

    // ---------------------------------------------------------------- //
    // Cost indicator + session list
    // ---------------------------------------------------------------- //

    it('cost indicator shows used and remaining tokens', () => {
        const el = window.diggerPane._buildCostIndicator(5000, 200000);
        expect(el.textContent).toContain('5,000');
        expect(el.textContent).toContain('195,000');
    });

    it('cost indicator treats a zero cap as 1 to avoid divide-by-zero', () => {
        const el = window.diggerPane._buildCostIndicator(0, 0);
        expect(el.querySelector('.digger-cost-bar-fill').style.width).toBe('0%');
    });

    it('surfaces a reject failure without collapsing the actions', async () => {
        window.apiClient.getDiggerProposals = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { items: [makeProposal()] } });
        window.apiClient.rejectDiggerProposal = vi.fn().mockResolvedValue({ ok: false, status: 404, body: null });

        await streamProposalAndSettle();

        const card = document.getElementById('diggerBody').querySelector('.digger-proposal-card[data-proposal-id="p1"]');
        card.querySelectorAll('.digger-proposal-actions button')[1].click();
        await new Promise((r) => setTimeout(r, 0));
        expect(card.textContent).toContain('Could not reject');
        expect(card.querySelector('.digger-proposal-actions')).not.toBeNull();
    });

    it('renders a session list, new-chat button, and cost indicator in the sidebar', async () => {
        window.apiClient.getDiggerAgentSessions = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            body: {
                items: [
                    { session_id: 'sess-1', started_at: '2026-05-20T00:00:00+00:00', last_active_at: '2026-05-21T00:00:00+00:00', total_cost_usd: 0.01 },
                ],
            },
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        const body = document.getElementById('diggerBody');
        expect(body.querySelector('.digger-chat-new')).not.toBeNull();
        expect(body.querySelector('.digger-cost-indicator')).not.toBeNull();
        expect(body.querySelectorAll('.digger-session-item')).toHaveLength(1);
    });

    it('continues a past session when its list item is clicked', async () => {
        window.apiClient.getDiggerAgentSessions = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            body: { items: [{ session_id: 'sess-1', started_at: '2026-05-20T00:00:00+00:00', last_active_at: '2026-05-21T00:00:00+00:00', total_cost_usd: 0 }] },
        });
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        document.querySelector('.digger-session-item .digger-session-link').click();
        await Promise.resolve();
        expect(window.diggerPane._chatSessionId).toBe('sess-1');
        expect(document.querySelector('.digger-session-item').classList.contains('active')).toBe(true);
    });

    it('accumulates used tokens from done events and updates the cost indicator', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => cbs.onDone({ session_id: 's1', usage: { input: 1000, output: 500, cache_read: 0 } }));
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'hi';
        await window.diggerPane._sendChatMessage();
        expect(window.diggerPane._chatUsedTokens).toBe(1500);
        expect(document.querySelector('.digger-cost-indicator').textContent).toContain('1,500');
    });

    it('starts a new chat, clearing the session id and messages', async () => {
        window.apiClient.streamDiggerAgent = vi.fn((token, body, cbs) => cbs.onDone({ session_id: 's1', usage: {} }));
        await window.diggerPane.init();
        await window.diggerPane._showChat();
        window.diggerPane._chatInput.value = 'hi';
        await window.diggerPane._sendChatMessage();
        expect(window.diggerPane._chatSessionId).toBe('s1');

        document.querySelector('.digger-chat-new').click();
        await Promise.resolve();
        expect(window.diggerPane._chatSessionId).toBeNull();
        expect(document.querySelectorAll('.digger-chat-msg')).toHaveLength(0);
    });
});
