import { describe, it, expect, beforeEach } from 'vitest';
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
