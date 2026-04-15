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
