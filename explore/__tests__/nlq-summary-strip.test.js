import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NlqSummaryStrip } from '../static/js/nlq-summary-strip.js';

describe('NlqSummaryStrip', () => {
    let container;

    beforeEach(() => {
        document.body.replaceChildren();
        container = document.createElement('div');
        document.body.appendChild(container);
    });

    it('renders summary text and action log', () => {
        const strip = new NlqSummaryStrip({ container });
        strip.show({
            summary: '**Kraftwerk** released albums.',
            entities: [{ name: 'Kraftwerk', type: 'artist' }],
            appliedActions: ['seed_graph', 'highlight_path'],
            skipped: 0,
        });
        expect(container.querySelector('strong')).not.toBeNull();
        expect(container.textContent).toContain('seed_graph');
        expect(container.textContent).toContain('highlight_path');
    });

    it('shows skipped count when nonzero', () => {
        const strip = new NlqSummaryStrip({ container });
        strip.show({ summary: 'x', entities: [], appliedActions: [], skipped: 2 });
        expect(container.textContent).toContain('2 action(s) skipped');
    });

    it('dismiss button clears the strip', () => {
        const strip = new NlqSummaryStrip({ container });
        strip.show({ summary: 'x', entities: [], appliedActions: [], skipped: 0 });
        container.querySelector('[data-testid="nlq-strip-dismiss"]').click();
        expect(container.querySelector('[data-testid="nlq-strip"]')).toBeNull();
    });

    it('undo button fires onUndo', () => {
        const onUndo = vi.fn();
        const strip = new NlqSummaryStrip({ container, onUndo });
        strip.show({ summary: 'x', entities: [], appliedActions: ['seed_graph'], skipped: 0 });
        container.querySelector('[data-testid="nlq-strip-undo"]').click();
        expect(onUndo).toHaveBeenCalledTimes(1);
    });
});
