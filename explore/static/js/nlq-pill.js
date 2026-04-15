/**
 * Global floating Ask pill — state machine: collapsed → expanded → loading → summary.
 */

import { NlqSuggestions } from './nlq-suggestions.js';

export class NlqPill {
    constructor({
        mountId = 'nlqPillMount',
        fetchSuggestions = null,
        getContext = () => ({ pane: 'explore' }),
        onSubmit = null,
    } = {}) {
        this.mountId = mountId;
        this.fetchSuggestions = fetchSuggestions;
        this.getContext = getContext;
        this.onSubmit = onSubmit;
        this.state = 'collapsed';
        this.root = null;
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
            if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                this.expand();
            } else if (e.key === '?' && !inInput) {
                e.preventDefault();
                this.expand();
            } else if (e.key === 'Escape' && this.state === 'expanded') {
                e.preventDefault();
                this.collapse();
            }
        });
    }

    expand() {
        if (this.state === 'expanded') return;
        this.state = 'expanded';
        this._render();
        const input = this.root.querySelector('[data-testid="nlq-pill-input"]');
        if (input) input.focus();
    }

    collapse() {
        if (this.state === 'collapsed') return;
        this.state = 'collapsed';
        this._render();
    }

    _render() {
        if (!this.root) return;
        while (this.root.firstChild) this.root.removeChild(this.root.firstChild);
        if (this.state === 'collapsed') {
            this._renderCollapsed();
        } else if (this.state === 'expanded') {
            this._renderExpanded();
        }
    }

    _renderCollapsed() {
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

    _renderExpanded() {
        const card = document.createElement('div');
        card.setAttribute('data-testid', 'nlq-pill-expanded');
        card.className = 'nlq-pill-expanded';

        const input = document.createElement('input');
        input.type = 'text';
        input.setAttribute('data-testid', 'nlq-pill-input');
        input.className = 'nlq-pill-input';
        input.placeholder = 'Ask anything about the music graph…';
        input.maxLength = 500;
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this._submitQuery(input.value);
            }
        });
        card.appendChild(input);

        const chipsContainer = document.createElement('div');
        chipsContainer.className = 'nlq-pill-chips';
        card.appendChild(chipsContainer);

        this.root.appendChild(card);

        if (this.fetchSuggestions) {
            this._suggestions = new NlqSuggestions({
                container: chipsContainer,
                fetchFn: this.fetchSuggestions,
                onPick: (text) => {
                    input.value = text;
                    this._submitQuery(text);
                },
            });
            const ctx = this.getContext();
            this._suggestions.render({ pane: ctx.pane, focus: ctx.focus, focusType: ctx.focusType });
        }
    }

    _submitQuery(query) {
        const trimmed = (query || '').trim();
        if (!trimmed) return;
        NlqSuggestions.addRecent(trimmed);
        this.collapse();
        if (this.onSubmit) this.onSubmit(trimmed);
    }
}
