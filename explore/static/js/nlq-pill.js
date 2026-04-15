/**
 * Global floating Ask pill — conversation surface.
 *
 * State machine:
 *   collapsed → expanded → loading → answered → collapsed
 *
 * The pill is a single fixed-position widget that stays open while the user
 * converses with the graph. Submitting transitions the SAME card through
 * loading and into answered; the input stays visible so follow-ups are one
 * Enter away. On collapse, if an answer exists the pill renders a small
 * "last answer" receipt above the collapsed button — clicking it reopens the
 * full answer.
 */

import { renderSummary } from './nlq-markdown.js';
import { NlqSuggestions } from './nlq-suggestions.js';

const RECEIPT_MAX_CHARS = 64;

export class NlqPill {
    constructor({
        mountId = 'nlqPillMount',
        fetchSuggestions = null,
        getContext = () => ({ pane: 'explore' }),
        onSubmit = null,
        onUndo = null,
        onEntityClick = null,
    } = {}) {
        this.mountId = mountId;
        this.fetchSuggestions = fetchSuggestions;
        this.getContext = getContext;
        this.onSubmit = onSubmit;
        this.onUndo = onUndo;
        this.onEntityClick = onEntityClick;
        this.state = 'collapsed';
        this.root = null;
        this._lastAnswer = null;
        this._pendingInputValue = '';
    }

    mount() {
        const mount = document.getElementById(this.mountId);
        if (!mount) return;
        this.root = document.createElement('div');
        this.root.className = 'nlq-pill-root';
        mount.appendChild(this.root);
        this._render();
        this._bindGlobalKeys();
    }

    _bindGlobalKeys() {
        document.addEventListener('keydown', (e) => {
            const target = e.target;
            const inInput = target && target.matches && target.matches('input, textarea, [contenteditable]');
            const insidePill = target && this.root && this.root.contains(target);
            if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                this.expand();
            } else if (e.key === '?' && !inInput) {
                e.preventDefault();
                this.expand();
            } else if (e.key === 'Escape' && this.state !== 'collapsed') {
                if (inInput && !insidePill) return;
                e.preventDefault();
                this.collapse();
            }
        });
    }

    expand() {
        if (this.state === 'expanded' || this.state === 'loading' || this.state === 'answered') {
            return;
        }
        this.state = 'expanded';
        this._render();
        this._focusInput();
    }

    collapse() {
        if (this.state === 'collapsed') return;
        this.state = 'collapsed';
        this._pendingInputValue = '';
        this._render();
    }

    setLoading() {
        if (this.state === 'collapsed') {
            this.state = 'expanded';
        }
        this.state = 'loading';
        this._render();
        this._focusInput();
    }

    setAnswer({ summary = '', entities = [], appliedActions = [], skipped = 0, isError = false } = {}) {
        this._lastAnswer = {
            summary: summary || '',
            entities: entities || [],
            appliedActions: appliedActions || [],
            skipped: skipped || 0,
            isError: Boolean(isError),
        };
        this.state = 'answered';
        this._render();
        this._focusInput();
    }

    clearAnswer() {
        this._lastAnswer = null;
        if (this.state === 'answered') {
            this.state = 'collapsed';
        }
        this._render();
    }

    reopenLastAnswer() {
        if (!this._lastAnswer) {
            this.expand();
            return;
        }
        this.state = 'answered';
        this._render();
        this._focusInput();
    }

    _focusInput() {
        if (!this.root) return;
        const input = this.root.querySelector('[data-testid="nlq-pill-input"]');
        if (input) input.focus();
    }

    _render() {
        if (!this.root) return;
        while (this.root.firstChild) this.root.removeChild(this.root.firstChild);
        if (this.state === 'collapsed') {
            this._renderCollapsed();
        } else {
            this._renderCard();
        }
    }

    _renderCollapsed() {
        if (this._lastAnswer) {
            this.root.appendChild(this._buildReceipt());
        }
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.setAttribute('data-testid', 'nlq-pill-collapsed');
        pill.className = 'nlq-pill-collapsed';
        pill.addEventListener('click', () => this.expand());
        const sparkle = document.createElement('span');
        sparkle.className = 'nlq-pill-sparkle';
        sparkle.textContent = '✨';
        const label = document.createElement('span');
        label.textContent = ' Ask the graph ';
        const kbd = document.createElement('kbd');
        kbd.textContent = '⌘K';
        pill.appendChild(sparkle);
        pill.appendChild(label);
        pill.appendChild(kbd);
        this.root.appendChild(pill);
    }

    _buildReceipt() {
        const receipt = document.createElement('div');
        receipt.setAttribute('data-testid', 'nlq-pill-receipt');
        receipt.className = 'nlq-pill-receipt';

        const body = document.createElement('button');
        body.type = 'button';
        body.className = 'nlq-pill-receipt-body';
        body.setAttribute('data-testid', 'nlq-pill-receipt-open');
        const label = document.createElement('span');
        label.className = 'nlq-pill-receipt-label';
        label.textContent = 'last answer:';
        const text = document.createElement('span');
        text.className = 'nlq-pill-receipt-text';
        text.textContent = this._truncateSummary(this._lastAnswer.summary);
        body.appendChild(label);
        body.appendChild(text);
        body.addEventListener('click', () => this.reopenLastAnswer());

        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'nlq-pill-receipt-dismiss';
        dismiss.setAttribute('data-testid', 'nlq-pill-receipt-dismiss');
        dismiss.setAttribute('aria-label', 'Clear last answer');
        dismiss.textContent = '×';
        dismiss.addEventListener('click', (e) => {
            e.stopPropagation();
            this.clearAnswer();
        });

        receipt.appendChild(body);
        receipt.appendChild(dismiss);
        return receipt;
    }

    _truncateSummary(raw) {
        const plain = (raw || '').replace(/[#*_`>~\-\[\]()!]/g, '').replace(/\s+/g, ' ').trim();
        if (plain.length <= RECEIPT_MAX_CHARS) return plain;
        return plain.slice(0, RECEIPT_MAX_CHARS - 1).trimEnd() + '…';
    }

    _renderCard() {
        const card = document.createElement('div');
        card.setAttribute('data-testid', 'nlq-pill-expanded');
        card.setAttribute('data-state', this.state);
        card.className = 'nlq-pill-expanded';

        const header = document.createElement('div');
        header.className = 'nlq-pill-header';

        const input = document.createElement('input');
        input.type = 'text';
        input.setAttribute('data-testid', 'nlq-pill-input');
        input.className = 'nlq-pill-input';
        input.placeholder = 'Ask anything about the music graph…';
        input.maxLength = 500;
        input.value = this._pendingInputValue || '';
        input.addEventListener('input', () => {
            this._pendingInputValue = input.value;
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this._submitQuery(input.value);
            }
        });
        header.appendChild(input);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'nlq-pill-close';
        closeBtn.setAttribute('data-testid', 'nlq-pill-close');
        closeBtn.setAttribute('aria-label', 'Close Ask pill');
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', () => this.collapse());
        header.appendChild(closeBtn);

        card.appendChild(header);

        const body = document.createElement('div');
        body.className = 'nlq-pill-body';
        card.appendChild(body);

        this.root.appendChild(card);

        if (this.state === 'expanded') {
            this._renderChips(body);
        } else if (this.state === 'loading') {
            this._renderLoading(body);
        } else if (this.state === 'answered') {
            this._renderAnswer(body);
        }
    }

    _renderChips(container) {
        const chipsContainer = document.createElement('div');
        chipsContainer.className = 'nlq-pill-chips';
        container.appendChild(chipsContainer);

        if (!this.fetchSuggestions) return;

        this._suggestions = new NlqSuggestions({
            container: chipsContainer,
            fetchFn: this.fetchSuggestions,
            onPick: (text) => {
                const input = this.root.querySelector('[data-testid="nlq-pill-input"]');
                if (input) input.value = text;
                this._pendingInputValue = text;
                this._submitQuery(text);
            },
        });
        const ctx = this.getContext();
        this._suggestions.render({ pane: ctx.pane, focus: ctx.focus, focusType: ctx.focusType });
    }

    _renderLoading(container) {
        const slot = document.createElement('div');
        slot.setAttribute('data-testid', 'nlq-pill-loading');
        slot.className = 'nlq-pill-loading-slot';
        const spinner = document.createElement('span');
        spinner.className = 'nlq-pill-spinner';
        spinner.setAttribute('role', 'status');
        const label = document.createElement('span');
        label.className = 'nlq-pill-loading-label';
        label.textContent = 'Thinking…';
        slot.appendChild(spinner);
        slot.appendChild(label);
        container.appendChild(slot);
    }

    _renderAnswer(container) {
        const answer = this._lastAnswer || { summary: '', entities: [], appliedActions: [], skipped: 0, isError: false };
        const slot = document.createElement('div');
        slot.setAttribute('data-testid', 'nlq-pill-answer');
        slot.className = 'nlq-answer-slot';
        if (answer.isError) slot.classList.add('nlq-answer-slot--error');

        const summaryEl = document.createElement('div');
        summaryEl.className = 'nlq-answer-summary';
        renderSummary(summaryEl, answer.summary, answer.entities, this.onEntityClick);
        slot.appendChild(summaryEl);

        const footer = document.createElement('div');
        footer.className = 'nlq-answer-footer';

        const log = document.createElement('span');
        log.className = 'nlq-action-log';
        const appliedText = (answer.appliedActions || []).map((a) => `✓ ${a}`).join(' • ');
        const skippedText = answer.skipped > 0 ? ` (${answer.skipped} action(s) skipped)` : '';
        log.textContent = appliedText + skippedText;
        footer.appendChild(log);

        if ((answer.appliedActions || []).length > 0 && this.onUndo) {
            const undoBtn = document.createElement('button');
            undoBtn.type = 'button';
            undoBtn.setAttribute('data-testid', 'nlq-answer-undo');
            undoBtn.className = 'nlq-answer-btn';
            undoBtn.textContent = '↶ Undo';
            undoBtn.addEventListener('click', () => this.onUndo());
            footer.appendChild(undoBtn);
        }

        slot.appendChild(footer);
        container.appendChild(slot);
    }

    _submitQuery(query) {
        const trimmed = (query || '').trim();
        if (!trimmed) return;
        NlqSuggestions.addRecent(trimmed);
        this._pendingInputValue = '';
        if (this.onSubmit) this.onSubmit(trimmed);
    }
}
