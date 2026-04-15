import { describe, it, expect, beforeEach, vi } from 'vitest';
import { NlqSuggestions } from '../static/js/nlq-suggestions.js';

describe('NlqSuggestions', () => {
    let container;

    beforeEach(() => {
        document.body.replaceChildren();
        container = document.createElement('div');
        document.body.appendChild(container);
        localStorage.clear();
    });

    it('renders fetched suggestions as chips', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Query A', 'Query B'] });
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore', focus: 'Kraftwerk', focusType: 'artist' });
        const chips = container.querySelectorAll('[data-testid="nlq-suggestion-chip"]');
        expect(chips.length).toBe(2);
        expect(chips[0].textContent).toContain('Query A');
    });

    it('renders recent chips from localStorage', async () => {
        localStorage.setItem('nlq.history', JSON.stringify(['Recent 1', 'Recent 2']));
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: [] });
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore' });
        const recents = container.querySelectorAll('[data-testid="nlq-recent-chip"]');
        expect(recents.length).toBe(2);
    });

    it('calls onPick with the chip text', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: ['Query A'] });
        const onPick = vi.fn();
        const sug = new NlqSuggestions({ container, fetchFn, onPick });
        await sug.render({ pane: 'explore' });
        container.querySelector('[data-testid="nlq-suggestion-chip"]').click();
        expect(onPick).toHaveBeenCalledWith('Query A');
    });

    it('falls back to recent only when fetch fails', async () => {
        localStorage.setItem('nlq.history', JSON.stringify(['Recent 1']));
        const fetchFn = vi.fn().mockRejectedValue(new Error('boom'));
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore' });
        expect(container.querySelectorAll('[data-testid="nlq-suggestion-chip"]').length).toBe(0);
        expect(container.querySelectorAll('[data-testid="nlq-recent-chip"]').length).toBe(1);
    });

    it('prepends a query via addRecent and caps history at 5', () => {
        NlqSuggestions.addRecent('Q1');
        NlqSuggestions.addRecent('Q2');
        NlqSuggestions.addRecent('Q3');
        NlqSuggestions.addRecent('Q4');
        NlqSuggestions.addRecent('Q5');
        NlqSuggestions.addRecent('Q6');
        const history = JSON.parse(localStorage.getItem('nlq.history'));
        expect(history).toEqual(['Q6', 'Q5', 'Q4', 'Q3', 'Q2']);
    });

    it('resets corrupt history silently', () => {
        localStorage.setItem('nlq.history', 'not json');
        const history = NlqSuggestions.loadRecent();
        expect(history).toEqual([]);
    });

    it('resets non-array history and returns empty array', () => {
        localStorage.setItem('nlq.history', JSON.stringify({ not: 'an array' }));
        const history = NlqSuggestions.loadRecent();
        expect(history).toEqual([]);
        expect(localStorage.getItem('nlq.history')).toBeNull();
    });

    it('addRecent ignores empty string', () => {
        NlqSuggestions.addRecent('');
        expect(localStorage.getItem('nlq.history')).toBeNull();
    });

    it('_renderChipRow skips empty items array', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ suggestions: [] });
        const sug = new NlqSuggestions({ container, fetchFn });
        await sug.render({ pane: 'explore' });
        // Neither suggestion row nor recent row should exist when both are empty
        const rows = container.querySelectorAll('.nlq-chip-row');
        expect(rows.length).toBe(0);
    });
});
