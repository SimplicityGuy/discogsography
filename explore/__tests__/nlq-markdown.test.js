import { describe, it, expect, vi } from 'vitest';
import { renderSummary } from '../static/js/nlq-markdown.js';

describe('renderSummary', () => {
    it('renders **bold** as <strong>', () => {
        const container = document.createElement('div');
        renderSummary(container, '**Kraftwerk** released an album.', []);
        expect(container.querySelector('strong')).not.toBeNull();
        expect(container.querySelector('strong').textContent).toBe('Kraftwerk');
    });

    it('does NOT render a script tag', () => {
        const container = document.createElement('div');
        renderSummary(container, '<script>alert(1)</script>hi', []); // nosemgrep: javascript.lang.security.audit.unknown-value-with-script-tag.unknown-value-with-script-tag
        expect(container.querySelector('script')).toBeNull();
        expect(container.textContent).toContain('hi');
    });

    it('wraps entity names in anchor elements', () => {
        const container = document.createElement('div');
        const onClick = vi.fn();
        renderSummary(container, 'Kraftwerk is awesome.', [{ name: 'Kraftwerk', type: 'artist' }], onClick);
        const link = container.querySelector('a[data-entity-name="Kraftwerk"]');
        expect(link).not.toBeNull();
        link.click();
        expect(onClick).toHaveBeenCalledWith('Kraftwerk', 'artist');
    });

    it('handles entity names inside bold markdown', () => {
        const container = document.createElement('div');
        renderSummary(container, '**Kraftwerk** is awesome.', [{ name: 'Kraftwerk', type: 'artist' }]);
        const strong = container.querySelector('strong');
        expect(strong).not.toBeNull();
        const link = strong.querySelector('a[data-entity-name="Kraftwerk"]');
        expect(link).not.toBeNull();
    });

    it('disallows anchor tags from the markdown source', () => {
        const container = document.createElement('div');
        renderSummary(container, '[link](javascript:alert(1))', []);
        const mdLink = container.querySelector('a:not(.nlq-entity-link)');
        expect(mdLink).toBeNull();
    });
});
