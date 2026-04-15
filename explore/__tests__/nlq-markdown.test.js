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

    it('renders GFM pipe tables as <table>', () => {
        const container = document.createElement('div');
        const md = [
            '| Label | Trance Releases |',
            '|---|---|',
            '| Anjunabeats | 3923 |',
            '| Armada | 2100 |',
        ].join('\n');
        renderSummary(container, md, []);
        const table = container.querySelector('table');
        expect(table).not.toBeNull();
        const headers = table.querySelectorAll('th');
        expect(headers.length).toBe(2);
        expect(headers[0].textContent.trim()).toBe('Label');
        const rows = table.querySelectorAll('tbody tr');
        expect(rows.length).toBe(2);
        expect(rows[0].textContent).toContain('Anjunabeats');
    });

    it('renders unordered lists', () => {
        const container = document.createElement('div');
        renderSummary(container, '- one\n- two\n- three', []);
        const ul = container.querySelector('ul');
        expect(ul).not.toBeNull();
        expect(ul.querySelectorAll('li').length).toBe(3);
    });

    it('renders ordered lists', () => {
        const container = document.createElement('div');
        renderSummary(container, '1. first\n2. second', []);
        const ol = container.querySelector('ol');
        expect(ol).not.toBeNull();
        expect(ol.querySelectorAll('li').length).toBe(2);
    });

    it('renders headings', () => {
        const container = document.createElement('div');
        renderSummary(container, '# Title\n## Subtitle', []);
        expect(container.querySelector('h1')).not.toBeNull();
        expect(container.querySelector('h2')).not.toBeNull();
    });

    it('strips <iframe> tags', () => {
        const container = document.createElement('div');
        renderSummary(container, '<iframe src="evil"></iframe>after', []);
        expect(container.querySelector('iframe')).toBeNull();
        expect(container.textContent).toContain('after');
    });

    it('strips onclick attributes from otherwise-allowed tags', () => {
        const container = document.createElement('div');
        renderSummary(container, '<strong onclick="alert(1)">hi</strong>', []);
        const strong = container.querySelector('strong');
        expect(strong).not.toBeNull();
        expect(strong.getAttribute('onclick')).toBeNull();
    });

    it('injects entity links into table cells', () => {
        const container = document.createElement('div');
        const md = '| Artist | Score |\n|---|---|\n| Kraftwerk | 99 |';
        renderSummary(container, md, [{ name: 'Kraftwerk', type: 'artist' }]);
        const link = container.querySelector('td a[data-entity-name="Kraftwerk"]');
        expect(link).not.toBeNull();
    });
});
