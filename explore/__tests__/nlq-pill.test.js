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
