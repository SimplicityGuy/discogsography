import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript, createMockFetch } from './helpers.js';

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

        it('should return null on failure', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 503 }));
            const result = await window.apiClient.askNlq('test');
            expect(result).toBeNull();
        });
    });
});
