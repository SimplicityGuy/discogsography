import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = [
    'strong', 'em', 'code', 'p', 'br',
    'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'blockquote', 'pre',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'hr',
];
const ALLOWED_ATTR = [];

marked.setOptions({ gfm: true, breaks: true });

/**
 * Render a markdown summary into `container`, injecting entity links.
 * Never uses innerHTML — DOMPurify returns a DocumentFragment directly.
 *
 * @param {HTMLElement} container
 * @param {string} summary - Markdown text from the agent.
 * @param {Array<{name:string,type:string}>} entities
 * @param {(name:string,type:string) => void} [onEntityClick]
 */
export function renderSummary(container, summary, entities, onEntityClick) {
    while (container.firstChild) container.removeChild(container.firstChild);

    const dirtyHtml = marked.parse(summary || '');
    const fragment = DOMPurify.sanitize(dirtyHtml, {
        ALLOWED_TAGS,
        ALLOWED_ATTR,
        RETURN_DOM_FRAGMENT: true,
    });

    _injectEntities(fragment, entities || [], onEntityClick);
    container.appendChild(fragment);
}

function _injectEntities(root, entities, onEntityClick) {
    if (entities.length === 0) return;
    const sorted = [...entities].sort((a, b) => (b.name || '').length - (a.name || '').length);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) textNodes.push(node);
    for (const textNode of textNodes) {
        _wrapEntitiesInTextNode(textNode, sorted, onEntityClick);
    }
}

function _wrapEntitiesInTextNode(textNode, entities, onEntityClick) {
    const text = textNode.nodeValue || '';
    const matches = [];
    for (const entity of entities) {
        if (!entity.name) continue;
        let searchFrom = 0;
        while (searchFrom < text.length) {
            const idx = text.indexOf(entity.name, searchFrom);
            if (idx === -1) break;
            const end = idx + entity.name.length;
            const overlaps = matches.some((m) => idx < m.end && end > m.start);
            if (!overlaps) matches.push({ start: idx, end, entity });
            searchFrom = idx + 1;
        }
    }
    if (matches.length === 0) return;
    matches.sort((a, b) => a.start - b.start);

    const parent = textNode.parentNode;
    const fragment = document.createDocumentFragment();
    let cursor = 0;
    for (const match of matches) {
        if (match.start > cursor) {
            fragment.appendChild(document.createTextNode(text.slice(cursor, match.start)));
        }
        const link = document.createElement('a');
        link.textContent = match.entity.name;
        link.className = 'nlq-entity-link';
        link.setAttribute('data-entity-name', match.entity.name);
        link.setAttribute('data-entity-type', match.entity.type || 'artist');
        link.setAttribute('href', '#');
        link.addEventListener('click', (e) => {
            e.preventDefault();
            if (onEntityClick) onEntityClick(match.entity.name, match.entity.type || 'artist');
        });
        fragment.appendChild(link);
        cursor = match.end;
    }
    if (cursor < text.length) {
        fragment.appendChild(document.createTextNode(text.slice(cursor)));
    }
    parent.replaceChild(fragment, textNode);
}
