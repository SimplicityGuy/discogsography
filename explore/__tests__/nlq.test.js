import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { loadScript, createMockFetch } from './helpers.js';

// ---------------------------------------------------------------------------
// api-client.js — NLQ methods
// ---------------------------------------------------------------------------

describe('ApiClient NLQ', () => {
    beforeEach(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        loadScript('api-client.js');
    });

    describe('checkNlqStatus', () => {
        it('should return enabled status', async () => {
            const mockFetch = createMockFetch({
                '/api/nlq/status': { data: { enabled: true } },
            });
            vi.stubGlobal('fetch', mockFetch);
            const result = await window.apiClient.checkNlqStatus();
            expect(result).toEqual({ enabled: true });
        });

        it('should return disabled on error', async () => {
            const mockFetch = createMockFetch({
                '/api/nlq/status': { status: 500, data: {} },
            });
            vi.stubGlobal('fetch', mockFetch);
            const result = await window.apiClient.checkNlqStatus();
            expect(result).toEqual({ enabled: false });
        });

        it('should return disabled when fetch throws', async () => {
            vi.stubGlobal('fetch', async () => { throw new Error('network error'); });
            const result = await window.apiClient.checkNlqStatus();
            expect(result).toEqual({ enabled: false });
        });
    });

    describe('askNlq', () => {
        it('should POST query and return result', async () => {
            const mockResult = {
                summary: 'Found Miles Davis.',
                entities: [{ id: '123', name: 'Miles Davis', type: 'artist' }],
                tools_used: ['search'],
                cached: false,
            };
            let capturedBody;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedBody = JSON.parse(options.body);
                return { ok: true, json: async () => mockResult };
            });
            const result = await window.apiClient.askNlq('Find Miles Davis');
            expect(result.summary).toBe('Found Miles Davis.');
            expect(capturedBody.query).toBe('Find Miles Davis');
        });

        it('should pass context when provided', async () => {
            let capturedBody;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedBody = JSON.parse(options.body);
                return { ok: true, json: async () => ({ summary: 'ok', entities: [], tools_used: [] }) };
            });
            await window.apiClient.askNlq('Tell me more', {
                current_entity_id: '123',
                current_entity_type: 'artist',
            });
            expect(capturedBody.context.current_entity_id).toBe('123');
        });

        it('should not include context key when context is null', async () => {
            let capturedBody;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedBody = JSON.parse(options.body);
                return { ok: true, json: async () => ({ summary: 'ok', entities: [], tools_used: [] }) };
            });
            await window.apiClient.askNlq('test query', null);
            expect(capturedBody.context).toBeUndefined();
        });

        it('should return null on failure', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 503 }));
            const result = await window.apiClient.askNlq('test');
            expect(result).toBeNull();
        });

        it('should return null when fetch throws', async () => {
            vi.stubGlobal('fetch', async () => { throw new Error('network error'); });
            const result = await window.apiClient.askNlq('test');
            expect(result).toBeNull();
        });
    });

    describe('askNlqStream', () => {
        it('should call onError with status when response is not ok', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 503 }));
            const onError = vi.fn();
            window.apiClient.askNlqStream('test', null, vi.fn(), vi.fn(), onError);
            // Wait for async fetch to complete
            await new Promise(resolve => setTimeout(resolve, 10));
            expect(onError).toHaveBeenCalledWith(503);
        });

        it('should call onError when fetch throws', async () => {
            const networkErr = new Error('network error');
            vi.stubGlobal('fetch', async () => { throw networkErr; });
            const onError = vi.fn();
            window.apiClient.askNlqStream('test', null, vi.fn(), vi.fn(), onError);
            await new Promise(resolve => setTimeout(resolve, 10));
            expect(onError).toHaveBeenCalledWith(networkErr);
        });

        it('should POST to /api/nlq/query with Accept: text/event-stream', async () => {
            let capturedUrl;
            let capturedOptions;
            // Minimal streaming response: immediate done
            const readerMock = {
                read: vi.fn().mockResolvedValue({ done: true, value: undefined }),
            };
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return {
                    ok: true,
                    body: { getReader: () => readerMock },
                };
            });
            window.apiClient.askNlqStream('Who is Miles Davis?', null, vi.fn(), vi.fn(), vi.fn());
            await new Promise(resolve => setTimeout(resolve, 10));
            expect(capturedUrl).toBe('/api/nlq/query');
            expect(capturedOptions.headers['Accept']).toBe('text/event-stream');
            expect(JSON.parse(capturedOptions.body).query).toBe('Who is Miles Davis?');
        });

        it('should pass context in POST body when provided', async () => {
            let capturedBody;
            const readerMock = {
                read: vi.fn().mockResolvedValue({ done: true, value: undefined }),
            };
            vi.stubGlobal('fetch', async (url, options) => {
                capturedBody = JSON.parse(options.body);
                return { ok: true, body: { getReader: () => readerMock } };
            });
            window.apiClient.askNlqStream(
                'Tell me more',
                { current_entity_id: 'abc', current_entity_type: 'artist' },
                vi.fn(), vi.fn(), vi.fn(),
            );
            await new Promise(resolve => setTimeout(resolve, 10));
            expect(capturedBody.context.current_entity_id).toBe('abc');
        });

        it('should call onStatus for status SSE events', async () => {
            const sseChunk = 'event: status\ndata: {"step":"searching","message":"Looking..."}\n\n';
            const encoder = new TextEncoder();
            const encoded = encoder.encode(sseChunk);
            let callCount = 0;
            const readerMock = {
                read: vi.fn().mockImplementation(() => {
                    callCount++;
                    if (callCount === 1) return Promise.resolve({ done: false, value: encoded });
                    return Promise.resolve({ done: true, value: undefined });
                }),
            };
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                body: { getReader: () => readerMock },
            }));
            const onStatus = vi.fn();
            window.apiClient.askNlqStream('test', null, onStatus, vi.fn(), vi.fn());
            await new Promise(resolve => setTimeout(resolve, 30));
            expect(onStatus).toHaveBeenCalledWith({ step: 'searching', message: 'Looking...' });
        });

        it('should call onResult for result SSE events', async () => {
            const resultData = { summary: 'Found it.', entities: [], tools_used: ['search'] };
            const sseChunk = `event: result\ndata: ${JSON.stringify(resultData)}\n\n`;
            const encoder = new TextEncoder();
            const encoded = encoder.encode(sseChunk);
            let callCount = 0;
            const readerMock = {
                read: vi.fn().mockImplementation(() => {
                    callCount++;
                    if (callCount === 1) return Promise.resolve({ done: false, value: encoded });
                    return Promise.resolve({ done: true, value: undefined });
                }),
            };
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                body: { getReader: () => readerMock },
            }));
            const onResult = vi.fn();
            window.apiClient.askNlqStream('test', null, vi.fn(), onResult, vi.fn());
            await new Promise(resolve => setTimeout(resolve, 30));
            expect(onResult).toHaveBeenCalledWith(resultData);
        });

        it('should handle malformed JSON in SSE data lines gracefully', async () => {
            const sseChunk = 'event: result\ndata: {not valid json}\n\n';
            const encoder = new TextEncoder();
            const encoded = encoder.encode(sseChunk);
            let callCount = 0;
            const readerMock = {
                read: vi.fn().mockImplementation(() => {
                    callCount++;
                    if (callCount === 1) return Promise.resolve({ done: false, value: encoded });
                    return Promise.resolve({ done: true, value: undefined });
                }),
            };
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                body: { getReader: () => readerMock },
            }));
            const onResult = vi.fn();
            const onError = vi.fn();
            // Should not throw — parse errors are silently ignored
            expect(() => {
                window.apiClient.askNlqStream('test', null, vi.fn(), onResult, onError);
            }).not.toThrow();
            await new Promise(resolve => setTimeout(resolve, 30));
            expect(onResult).not.toHaveBeenCalled();
            expect(onError).not.toHaveBeenCalled();
        });
    });
});

// ---------------------------------------------------------------------------
// NLQPanel class
// ---------------------------------------------------------------------------

/**
 * Build a minimal mock DOM for the NLQ panel.
 * Returns the element map so tests can inspect state.
 */
function buildNlqDom() {
    const elements = {
        nlqPanel: { style: { display: 'none' }, firstChild: null, removeChild: vi.fn() },
        nlqInput: { value: '', disabled: false, addEventListener: vi.fn(), focus: vi.fn() },
        nlqSubmit: { disabled: false, addEventListener: vi.fn() },
        nlqStatus: { textContent: '', style: { display: 'none' } },
        nlqResult: {
            firstChild: null,
            removeChild: vi.fn(),
            appendChild: vi.fn(),
            querySelectorAll: vi.fn(() => []),
        },
        nlqExamples: {
            style: { display: '' },
            addEventListener: vi.fn(),
            querySelectorAll: vi.fn(() => []),
        },
    };

    globalThis.document = {
        getElementById: vi.fn((id) => elements[id] ?? null),
        createElement: vi.fn((tag) => ({
            tagName: tag.toUpperCase(),
            textContent: '',
            className: '',
            style: {},
            setAttribute: vi.fn(),
            addEventListener: vi.fn(),
            appendChild: vi.fn(),
        })),
        createTextNode: vi.fn((text) => ({ textContent: text, nodeType: 3 })),
        addEventListener: vi.fn(),
    };

    return elements;
}

describe('NLQPanel', () => {
    let elements;

    beforeEach(() => {
        delete globalThis.window;
        globalThis.window = globalThis;

        elements = buildNlqDom();

        globalThis.apiClient = {
            checkNlqStatus: vi.fn(async () => ({ enabled: true })),
            askNlq: vi.fn(async () => ({ summary: 'test', entities: [], tools_used: [] })),
            askNlqStream: vi.fn(),
        };

        loadScript('nlq.js');
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe('constructor', () => {
        it('should bind to DOM elements via getElementById', () => {
            // Instantiate so the constructor runs and calls document.getElementById
            new window.NLQPanel();
            expect(globalThis.document.getElementById).toHaveBeenCalledWith('nlqPanel');
            expect(globalThis.document.getElementById).toHaveBeenCalledWith('nlqInput');
            expect(globalThis.document.getElementById).toHaveBeenCalledWith('nlqSubmit');
            expect(globalThis.document.getElementById).toHaveBeenCalledWith('nlqStatus');
            expect(globalThis.document.getElementById).toHaveBeenCalledWith('nlqResult');
            expect(globalThis.document.getElementById).toHaveBeenCalledWith('nlqExamples');
        });

        it('should set onExploreEntity to null', () => {
            const panel = new window.NLQPanel();
            expect(panel.onExploreEntity).toBeNull();
        });

        it('should register click listener on submitBtn', () => {
            new window.NLQPanel();
            expect(elements.nlqSubmit.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
        });

        it('should register keydown listener on input', () => {
            new window.NLQPanel();
            expect(elements.nlqInput.addEventListener).toHaveBeenCalledWith('keydown', expect.any(Function));
        });

        it('should register click listener on examplesEl', () => {
            new window.NLQPanel();
            expect(elements.nlqExamples.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
        });
    });

    describe('checkEnabled', () => {
        it('should return true when apiClient returns enabled: true', async () => {
            globalThis.apiClient.checkNlqStatus = vi.fn(async () => ({ enabled: true }));
            const panel = new window.NLQPanel();
            const result = await panel.checkEnabled();
            expect(result).toBe(true);
            expect(globalThis.apiClient.checkNlqStatus).toHaveBeenCalled();
        });

        it('should return false when apiClient returns enabled: false', async () => {
            globalThis.apiClient.checkNlqStatus = vi.fn(async () => ({ enabled: false }));
            const panel = new window.NLQPanel();
            const result = await panel.checkEnabled();
            expect(result).toBe(false);
        });

        it('should return falsy when apiClient returns null', async () => {
            globalThis.apiClient.checkNlqStatus = vi.fn(async () => null);
            const panel = new window.NLQPanel();
            const result = await panel.checkEnabled();
            expect(result).toBeFalsy();
        });
    });

    describe('show', () => {
        it('should set panel display to empty string', () => {
            const panel = new window.NLQPanel();
            elements.nlqPanel.style.display = 'none';
            panel.show();
            expect(elements.nlqPanel.style.display).toBe('');
        });

        it('should be safe when panel element is null', () => {
            // Rebuild DOM without nlqPanel
            globalThis.document.getElementById = vi.fn((id) => {
                if (id === 'nlqPanel') return null;
                return elements[id] ?? null;
            });
            const panel = new window.NLQPanel();
            expect(() => panel.show()).not.toThrow();
        });
    });

    describe('hide', () => {
        it('should set panel display to none', () => {
            const panel = new window.NLQPanel();
            elements.nlqPanel.style.display = '';
            panel.hide();
            expect(elements.nlqPanel.style.display).toBe('none');
        });

        it('should be safe when panel element is null', () => {
            globalThis.document.getElementById = vi.fn((id) => {
                if (id === 'nlqPanel') return null;
                return elements[id] ?? null;
            });
            const panel = new window.NLQPanel();
            expect(() => panel.hide()).not.toThrow();
        });
    });

    describe('_submit', () => {
        it('should call askNlqStream with the input query', () => {
            elements.nlqInput.value = 'Who is Miles Davis?';
            const panel = new window.NLQPanel();
            panel._submit();
            expect(globalThis.apiClient.askNlqStream).toHaveBeenCalledWith(
                'Who is Miles Davis?',
                null,
                expect.any(Function),
                expect.any(Function),
                expect.any(Function),
            );
        });

        it('should not call askNlqStream when query is empty', () => {
            elements.nlqInput.value = '   ';
            const panel = new window.NLQPanel();
            panel._submit();
            expect(globalThis.apiClient.askNlqStream).not.toHaveBeenCalled();
        });

        it('should disable submit button while loading', () => {
            elements.nlqInput.value = 'test query';
            const panel = new window.NLQPanel();
            panel._submit();
            expect(elements.nlqSubmit.disabled).toBe(true);
        });

        it('should disable input while loading', () => {
            elements.nlqInput.value = 'test query';
            const panel = new window.NLQPanel();
            panel._submit();
            expect(elements.nlqInput.disabled).toBe(true);
        });

        it('should hide status element before streaming', () => {
            elements.nlqInput.value = 'test query';
            elements.nlqStatus.style.display = '';
            const panel = new window.NLQPanel();
            panel._submit();
            expect(elements.nlqStatus.style.display).toBe('none');
        });

        it('should re-enable button and show result on successful stream callback', () => {
            elements.nlqInput.value = 'test query';
            let onResultCallback;
            globalThis.apiClient.askNlqStream = vi.fn((q, ctx, onStatus, onResult, onError) => {
                onResultCallback = onResult;
            });
            const panel = new window.NLQPanel();
            panel._submit();

            // Simulate result arriving
            onResultCallback({ summary: 'Result!', entities: [], tools_used: [] });

            expect(elements.nlqSubmit.disabled).toBe(false);
        });

        it('should re-enable button and show error on error stream callback', () => {
            elements.nlqInput.value = 'test query';
            let onErrorCallback;
            globalThis.apiClient.askNlqStream = vi.fn((q, ctx, onStatus, onResult, onError) => {
                onErrorCallback = onError;
            });
            const panel = new window.NLQPanel();
            panel._submit();

            onErrorCallback(503);

            expect(elements.nlqSubmit.disabled).toBe(false);
        });
    });

    describe('_showStatus', () => {
        it('should show status element and set message text', () => {
            const panel = new window.NLQPanel();
            panel._showStatus({ message: 'Searching...', step: 'search' });
            expect(elements.nlqStatus.style.display).toBe('');
            expect(elements.nlqStatus.textContent).toBe('Searching...');
        });

        it('should fall back to step when message is not present', () => {
            const panel = new window.NLQPanel();
            panel._showStatus({ step: 'analyzing' });
            expect(elements.nlqStatus.textContent).toBe('analyzing');
        });

        it('should fall back to Thinking... when neither message nor step', () => {
            const panel = new window.NLQPanel();
            panel._showStatus({});
            expect(elements.nlqStatus.textContent).toBe('Thinking...');
        });
    });

    describe('_showResult', () => {
        it('should hide status element when showing result', () => {
            elements.nlqStatus.style.display = '';
            const panel = new window.NLQPanel();
            panel._showResult({ summary: 'Found something.', entities: [], tools_used: [] });
            expect(elements.nlqStatus.style.display).toBe('none');
        });

        it('should create a paragraph when data has no summary', () => {
            const panel = new window.NLQPanel();
            panel._showResult(null);
            expect(globalThis.document.createElement).toHaveBeenCalledWith('p');
            const appendCalls = elements.nlqResult.appendChild.mock.calls;
            // Should have appended the "No answer" paragraph
            expect(appendCalls.length).toBeGreaterThan(0);
        });

        it('should create a paragraph with summary text when entities are empty', () => {
            const panel = new window.NLQPanel();
            const fakeP = {
                tagName: 'P', textContent: '', className: '', appendChild: vi.fn(),
                setAttribute: vi.fn(), addEventListener: vi.fn(), style: {},
            };
            globalThis.document.createElement = vi.fn(() => fakeP);

            panel._showResult({ summary: 'A plain summary.', entities: [], tools_used: [] });
            expect(fakeP.textContent).toBe('A plain summary.');
            expect(elements.nlqResult.appendChild).toHaveBeenCalled();
        });

        it('should create tool pills for each tool used', () => {
            const panel = new window.NLQPanel();
            const createdElements = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdElements.push(el);
                return el;
            });

            panel._showResult({ summary: 'Found it.', entities: [], tools_used: ['search', 'graph_query'] });

            const toolPills = createdElements.filter(
                el => el.textContent === 'search' || el.textContent === 'graph_query',
            );
            expect(toolPills.length).toBeGreaterThanOrEqual(2);
        });

        it('should create a cached indicator when data.cached is true', () => {
            const panel = new window.NLQPanel();
            const createdElements = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdElements.push(el);
                return el;
            });

            panel._showResult({ summary: 'Cached result.', entities: [], tools_used: [], cached: true });

            const cachedEl = createdElements.find(el => el.textContent === ' (cached)');
            expect(cachedEl).toBeDefined();
        });

        it('should build entity links when entities are present', () => {
            const panel = new window.NLQPanel();
            const createdElements = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdElements.push(el);
                return el;
            });
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));

            panel._showResult({
                summary: 'Miles Davis is great.',
                entities: [{ name: 'Miles Davis', type: 'artist' }],
                tools_used: [],
            });

            // An anchor element should have been created for the entity
            const links = createdElements.filter(el => el.tagName === 'A');
            expect(links.length).toBeGreaterThan(0);
            expect(links[0].textContent).toBe('Miles Davis');
        });
    });

    describe('_showError', () => {
        it('should hide status element', () => {
            elements.nlqStatus.style.display = '';
            const panel = new window.NLQPanel();
            panel._showError(503);
            expect(elements.nlqStatus.style.display).toBe('none');
        });

        it('should show 503 unavailable message for status 503', () => {
            const panel = new window.NLQPanel();
            const createdEls = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdEls.push(el);
                return el;
            });

            panel._showError(503);

            const errorEl = createdEls.find(el => el.textContent.includes('unavailable'));
            expect(errorEl).toBeDefined();
        });

        it('should show generic error message for non-503 numeric status', () => {
            const panel = new window.NLQPanel();
            const createdEls = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdEls.push(el);
                return el;
            });

            panel._showError(500);

            const errorEl = createdEls.find(el => el.textContent.includes('status 500'));
            expect(errorEl).toBeDefined();
        });

        it('should show network error message for non-numeric error', () => {
            const panel = new window.NLQPanel();
            const createdEls = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdEls.push(el);
                return el;
            });

            panel._showError(new Error('network down'));

            const errorEl = createdEls.find(el => el.textContent.includes('Unable to reach'));
            expect(errorEl).toBeDefined();
        });
    });

    describe('_buildEntityLinkedText', () => {
        it('should return text nodes and anchor elements for entity names found in text', () => {
            const panel = new window.NLQPanel();
            const createdNodes = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdNodes.push(el);
                return el;
            });
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));

            const nodes = panel._buildEntityLinkedText(
                'Miles Davis played jazz.',
                [{ name: 'Miles Davis', type: 'artist' }],
            );

            // Should have: text-before (empty), link, text-after
            const link = nodes.find(n => n.tagName === 'A');
            expect(link).toBeDefined();
            expect(link.textContent).toBe('Miles Davis');
            expect(link.setAttribute).toHaveBeenCalledWith('data-entity-name', 'Miles Davis');
            expect(link.setAttribute).toHaveBeenCalledWith('data-entity-type', 'artist');
            expect(link.setAttribute).toHaveBeenCalledWith('href', '#');
        });

        it('should call onExploreEntity when entity link is clicked', () => {
            const panel = new window.NLQPanel();
            const callback = vi.fn();
            panel.onExploreEntity = callback;

            let clickHandler;
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(),
                    addEventListener: vi.fn((evt, fn) => {
                        if (evt === 'click') clickHandler = fn;
                    }),
                    appendChild: vi.fn(),
                };
                return el;
            });
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));

            panel._buildEntityLinkedText(
                'Miles Davis is amazing.',
                [{ name: 'Miles Davis', type: 'artist' }],
            );

            // Simulate click
            const fakeEvent = { preventDefault: vi.fn() };
            clickHandler(fakeEvent);

            expect(fakeEvent.preventDefault).toHaveBeenCalled();
            expect(callback).toHaveBeenCalledWith('Miles Davis', 'artist');
        });

        it('should not call onExploreEntity when it is null', () => {
            const panel = new window.NLQPanel();
            panel.onExploreEntity = null;

            let clickHandler;
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(),
                    addEventListener: vi.fn((evt, fn) => {
                        if (evt === 'click') clickHandler = fn;
                    }),
                    appendChild: vi.fn(),
                };
                return el;
            });
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));

            panel._buildEntityLinkedText(
                'Miles Davis',
                [{ name: 'Miles Davis', type: 'artist' }],
            );

            const fakeEvent = { preventDefault: vi.fn() };
            expect(() => clickHandler(fakeEvent)).not.toThrow();
        });

        it('should default entity type to artist when type is missing', () => {
            const panel = new window.NLQPanel();
            const createdNodes = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdNodes.push(el);
                return el;
            });
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));

            const nodes = panel._buildEntityLinkedText(
                'Miles Davis played.',
                [{ name: 'Miles Davis' }],
            );

            const link = nodes.find(n => n.tagName === 'A');
            expect(link.setAttribute).toHaveBeenCalledWith('data-entity-type', 'artist');
        });

        it('should handle text with no matching entities', () => {
            const panel = new window.NLQPanel();
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));
            globalThis.document.createElement = vi.fn((tag) => ({
                tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
            }));

            const nodes = panel._buildEntityLinkedText(
                'No entity here.',
                [{ name: 'Miles Davis', type: 'artist' }],
            );

            // Only the full text node, no links
            expect(nodes.every(n => n.nodeType === 3 || n.tagName !== 'A')).toBe(true);
        });

        it('should match longer entity names before shorter ones to avoid overlaps', () => {
            const panel = new window.NLQPanel();
            const createdNodes = [];
            globalThis.document.createElement = vi.fn((tag) => {
                const el = {
                    tagName: tag.toUpperCase(), textContent: '', className: '', style: {},
                    setAttribute: vi.fn(), addEventListener: vi.fn(), appendChild: vi.fn(),
                };
                createdNodes.push(el);
                return el;
            });
            globalThis.document.createTextNode = vi.fn((text) => ({ textContent: text, nodeType: 3 }));

            // "Miles Davis" is longer and should match, not "Miles" alone
            const nodes = panel._buildEntityLinkedText(
                'Miles Davis is a trumpeter.',
                [
                    { name: 'Miles', type: 'artist' },
                    { name: 'Miles Davis', type: 'artist' },
                ],
            );

            const links = nodes.filter(n => n.tagName === 'A');
            expect(links.length).toBe(1);
            expect(links[0].textContent).toBe('Miles Davis');
        });
    });

    describe('_bindEvents — Enter key submission', () => {
        it('should call _submit when Enter key is pressed on input', () => {
            // Instantiate to register event listeners
            new window.NLQPanel();
            // Get the keydown handler registered on nlqInput
            const keydownCall = elements.nlqInput.addEventListener.mock.calls.find(
                ([event]) => event === 'keydown',
            );
            expect(keydownCall).toBeDefined();
            const handler = keydownCall[1];

            elements.nlqInput.value = 'test query';
            handler({ key: 'Enter' });

            expect(globalThis.apiClient.askNlqStream).toHaveBeenCalled();
        });

        it('should not submit when a non-Enter key is pressed', () => {
            new window.NLQPanel();
            const keydownCall = elements.nlqInput.addEventListener.mock.calls.find(
                ([event]) => event === 'keydown',
            );
            const handler = keydownCall[1];

            elements.nlqInput.value = 'test query';
            handler({ key: 'a' });

            expect(globalThis.apiClient.askNlqStream).not.toHaveBeenCalled();
        });
    });

    describe('_bindEvents — example chip clicks', () => {
        it('should populate input and submit when example chip is clicked', () => {
            // Instantiate to register event listeners
            new window.NLQPanel();
            // Get the click handler registered on nlqExamples
            const clickCall = elements.nlqExamples.addEventListener.mock.calls.find(
                ([event]) => event === 'click',
            );
            expect(clickCall).toBeDefined();
            const handler = clickCall[1];

            // Simulate a click on an element with data-nlq-example attribute
            const fakeChip = {
                getAttribute: vi.fn(() => 'Who produced Kind of Blue?'),
            };
            handler({
                target: {
                    closest: vi.fn(() => fakeChip),
                },
            });

            expect(elements.nlqInput.value).toBe('Who produced Kind of Blue?');
            expect(globalThis.apiClient.askNlqStream).toHaveBeenCalled();
        });

        it('should do nothing when click is not on a chip element', () => {
            new window.NLQPanel();
            const clickCall = elements.nlqExamples.addEventListener.mock.calls.find(
                ([event]) => event === 'click',
            );
            const handler = clickCall[1];

            handler({
                target: { closest: vi.fn(() => null) },
            });

            expect(globalThis.apiClient.askNlqStream).not.toHaveBeenCalled();
        });
    });
});

// ---------------------------------------------------------------------------
// app.js NLQ wiring — tested via jsdom DOM interactions
// ---------------------------------------------------------------------------

/**
 * Build the minimal DOM required for NLQ toggle tests using safe DOM APIs.
 */
// Note: app.js NLQ wiring tests (toggle, keyboard shortcut) require a full
// jsdom environment with document.body. These behaviors are covered by E2E
// tests. The 57 unit tests above cover NLQPanel and ApiClient NLQ methods.
