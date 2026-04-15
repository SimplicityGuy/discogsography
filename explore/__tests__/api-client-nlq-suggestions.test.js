import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { loadScript } from './helpers.js';

describe('apiClient.fetchNlqSuggestions', () => {
    beforeEach(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        loadScript('api-client.js');
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('calls the suggestions endpoint with context params', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ suggestions: ['a', 'b'] }),
        });
        const result = await window.apiClient.fetchNlqSuggestions({ pane: 'explore', focus: 'K', focusType: 'artist' });
        expect(result.suggestions).toEqual(['a', 'b']);
        const calledUrl = global.fetch.mock.calls[0][0];
        expect(calledUrl).toContain('/api/nlq/suggestions');
        expect(calledUrl).toContain('pane=explore');
        expect(calledUrl).toContain('focus=K');
    });

    it('includes focus_type param when focusType is provided', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ suggestions: [] }),
        });
        await window.apiClient.fetchNlqSuggestions({ pane: 'search', focus: 'Beatles', focusType: 'artist' });
        const calledUrl = global.fetch.mock.calls[0][0];
        expect(calledUrl).toContain('focus_type=artist');
    });

    it('omits focus and focus_type when null', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ suggestions: [] }),
        });
        await window.apiClient.fetchNlqSuggestions({ pane: 'explore' });
        const calledUrl = global.fetch.mock.calls[0][0];
        expect(calledUrl).toContain('pane=explore');
        expect(calledUrl).not.toContain('focus=');
        expect(calledUrl).not.toContain('focus_type=');
    });

    it('throws when response is not ok', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: false,
            status: 500,
        });
        await expect(window.apiClient.fetchNlqSuggestions({ pane: 'explore' })).rejects.toThrow('Suggestions fetch failed: 500');
    });
});
