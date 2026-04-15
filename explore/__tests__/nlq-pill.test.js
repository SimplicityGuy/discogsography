import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent } from '@testing-library/dom';
import { NlqPill } from '../static/js/nlq-pill.js';

describe('NlqPill', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
    });

    it('mounts a collapsed pill by default', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        const el = document.querySelector('[data-testid="nlq-pill-collapsed"]');
        expect(el).not.toBeNull();
        expect(el.textContent).toContain('Ask the graph');
    });

    it('shows keyboard hint', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        const kbd = document.querySelector('[data-testid="nlq-pill-collapsed"] kbd');
        expect(kbd).not.toBeNull();
        expect(kbd.textContent).toMatch(/⌘K|Ctrl\+K/);
    });
});

describe('NlqPill interactions', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
    });

    it('expands on pill click', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        document.querySelector('[data-testid="nlq-pill-collapsed"]').click();
        expect(pill.state).toBe('expanded');
        expect(document.querySelector('[data-testid="nlq-pill-expanded"]')).not.toBeNull();
    });

    it('expands on ⌘K', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        fireEvent.keyDown(document, { key: 'k', metaKey: true });
        expect(pill.state).toBe('expanded');
    });

    it('expands on ? when no input focused', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        fireEvent.keyDown(document, { key: '?' });
        expect(pill.state).toBe('expanded');
    });

    it('does NOT expand on ? when an input is focused', () => {
        const other = document.createElement('input');
        other.id = 'other';
        document.body.appendChild(other);
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        other.focus();
        fireEvent.keyDown(other, { key: '?' });
        expect(pill.state).toBe('collapsed');
    });

    it('collapses on Esc', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(pill.state).toBe('collapsed');
    });
});

describe('NlqPill submit via Enter key', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
        localStorage.clear();
    });

    it('calls onSubmit when Enter is pressed in the input', () => {
        const onSubmit = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', onSubmit });
        pill.mount();
        pill.expand();
        const input = document.querySelector('[data-testid="nlq-pill-input"]');
        input.value = 'test query';
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(onSubmit).toHaveBeenCalledWith('test query');
    });

    it('does NOT call onSubmit when Enter is pressed with empty input', () => {
        const onSubmit = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', onSubmit });
        pill.mount();
        pill.expand();
        const input = document.querySelector('[data-testid="nlq-pill-input"]');
        input.value = '   ';
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(onSubmit).not.toHaveBeenCalled();
    });

    it('renders expanded card without suggestions when fetchSuggestions is null', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount', fetchSuggestions: null });
        pill.mount();
        pill.expand();
        const card = document.querySelector('[data-testid="nlq-pill-expanded"]');
        expect(card).not.toBeNull();
        const chips = document.querySelectorAll('[data-testid="nlq-suggestion-chip"]');
        expect(chips.length).toBe(0);
    });
});

describe('NlqPill suggestions integration', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
        localStorage.clear();
    });

    it('renders suggestions into the expanded card', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Suggested Q'] });
        const pill = new NlqPill({ mountId: 'nlqPillMount', fetchSuggestions: fetchFn });
        pill.mount();
        pill.expand();
        await Promise.resolve();
        await Promise.resolve();
        const chip = document.querySelector('[data-testid="nlq-suggestion-chip"]');
        expect(chip).not.toBeNull();
    });

    it('picks a suggestion into the input on click', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Suggested Q'] });
        const onSubmit = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', fetchSuggestions: fetchFn, onSubmit });
        pill.mount();
        pill.expand();
        await Promise.resolve();
        await Promise.resolve();
        document.querySelector('[data-testid="nlq-suggestion-chip"]').click();
        expect(onSubmit).toHaveBeenCalledWith('Suggested Q');
    });
});

describe('NlqPill state machine', () => {
    beforeEach(() => {
        document.body.replaceChildren();
        const mount = document.createElement('div');
        mount.id = 'nlqPillMount';
        document.body.appendChild(mount);
        localStorage.clear();
    });

    it('setLoading renders a thinking slot and keeps the input visible', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.setLoading();
        expect(pill.state).toBe('loading');
        expect(document.querySelector('[data-testid="nlq-pill-loading"]')).not.toBeNull();
        expect(document.querySelector('[data-testid="nlq-pill-input"]')).not.toBeNull();
        expect(document.querySelector('[data-testid="nlq-pill-answer"]')).toBeNull();
    });

    it('setAnswer renders the markdown summary and transitions to answered', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.setAnswer({
            summary: '**Kraftwerk** is a pioneering German band.',
            entities: [{ name: 'Kraftwerk', type: 'artist' }],
            appliedActions: ['switch_pane'],
            skipped: 0,
        });
        expect(pill.state).toBe('answered');
        const answer = document.querySelector('[data-testid="nlq-pill-answer"]');
        expect(answer).not.toBeNull();
        expect(answer.querySelector('strong')).not.toBeNull();
        expect(answer.textContent).toContain('switch_pane');
        // Input still available for follow-ups.
        expect(document.querySelector('[data-testid="nlq-pill-input"]')).not.toBeNull();
    });

    it('answered → Enter triggers onSubmit with the new follow-up query', () => {
        const onSubmit = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', onSubmit });
        pill.mount();
        pill.expand();
        pill.setAnswer({ summary: 'first', entities: [], appliedActions: [], skipped: 0 });
        const input = document.querySelector('[data-testid="nlq-pill-input"]');
        input.value = 'follow up';
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(onSubmit).toHaveBeenCalledWith('follow up');
    });

    it('undo button appears only when appliedActions is non-empty AND onUndo is supplied', () => {
        const onUndo = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', onUndo });
        pill.mount();
        pill.expand();
        pill.setAnswer({ summary: 'done', entities: [], appliedActions: ['switch_pane'], skipped: 0 });
        const btn = document.querySelector('[data-testid="nlq-answer-undo"]');
        expect(btn).not.toBeNull();
        btn.click();
        expect(onUndo).toHaveBeenCalledTimes(1);
    });

    it('undo button is absent when no actions were applied', () => {
        const onUndo = vi.fn();
        const pill = new NlqPill({ mountId: 'nlqPillMount', onUndo });
        pill.mount();
        pill.expand();
        pill.setAnswer({ summary: 'done', entities: [], appliedActions: [], skipped: 0 });
        expect(document.querySelector('[data-testid="nlq-answer-undo"]')).toBeNull();
    });

    it('close button collapses and renders a receipt when an answer exists', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.setAnswer({
            summary: 'Anjunabeats has the most trance releases.',
            entities: [],
            appliedActions: [],
            skipped: 0,
        });
        document.querySelector('[data-testid="nlq-pill-close"]').click();
        expect(pill.state).toBe('collapsed');
        const receipt = document.querySelector('[data-testid="nlq-pill-receipt"]');
        expect(receipt).not.toBeNull();
        expect(receipt.textContent).toContain('Anjunabeats');
    });

    it('no receipt is rendered on first collapse when no answer has been set', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.collapse();
        expect(document.querySelector('[data-testid="nlq-pill-receipt"]')).toBeNull();
    });

    it('receipt dismiss clears the stored answer so it does not return', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.setAnswer({ summary: 'done', entities: [], appliedActions: [], skipped: 0 });
        pill.collapse();
        document.querySelector('[data-testid="nlq-pill-receipt-dismiss"]').click();
        expect(document.querySelector('[data-testid="nlq-pill-receipt"]')).toBeNull();
        pill.expand();
        pill.collapse();
        expect(document.querySelector('[data-testid="nlq-pill-receipt"]')).toBeNull();
    });

    it('receipt body click reopens the pill directly in answered state', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.setAnswer({ summary: 'the answer', entities: [], appliedActions: [], skipped: 0 });
        pill.collapse();
        document.querySelector('[data-testid="nlq-pill-receipt-open"]').click();
        expect(pill.state).toBe('answered');
        expect(document.querySelector('[data-testid="nlq-pill-answer"]')).not.toBeNull();
    });

    it('Esc collapses from loading and from answered', () => {
        const pill = new NlqPill({ mountId: 'nlqPillMount' });
        pill.mount();
        pill.expand();
        pill.setLoading();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(pill.state).toBe('collapsed');

        pill.expand();
        pill.setAnswer({ summary: 'x', entities: [], appliedActions: [], skipped: 0 });
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(pill.state).toBe('collapsed');
    });
});
