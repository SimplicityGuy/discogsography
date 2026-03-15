import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript, createMockFetch } from './helpers.js';

describe('ApiClient', () => {
    beforeEach(() => {
        // Reset the global instance before each test
        delete globalThis.window;
        globalThis.window = globalThis;
        loadScript('api-client.js');
    });

    describe('autocomplete', () => {
        it('should build correct URL params and return results', async () => {
            const mockFetch = createMockFetch({
                '/api/autocomplete': {
                    data: { results: [{ name: 'Radiohead', type: 'artist' }] },
                },
            });
            vi.stubGlobal('fetch', mockFetch);

            const results = await window.apiClient.autocomplete('radio', 'artist', 5);
            expect(results).toEqual([{ name: 'Radiohead', type: 'artist' }]);
        });

        it('should return empty array on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/autocomplete': { status: 500, data: {} },
            });
            vi.stubGlobal('fetch', mockFetch);

            const results = await window.apiClient.autocomplete('test', 'artist');
            expect(results).toEqual([]);
        });

        it('should return empty array when results field is missing', async () => {
            const mockFetch = createMockFetch({
                '/api/autocomplete': { data: {} },
            });
            vi.stubGlobal('fetch', mockFetch);

            const results = await window.apiClient.autocomplete('test', 'artist');
            expect(results).toEqual([]);
        });
    });

    describe('explore', () => {
        it('should return explore data on success', async () => {
            const exploreData = { center: { id: 'Radiohead', type: 'artist' }, categories: [] };
            const mockFetch = createMockFetch({
                '/api/explore': { data: exploreData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.explore('Radiohead', 'artist');
            expect(result).toEqual(exploreData);
        });

        it('should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/explore': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.explore('Radiohead', 'artist');
            expect(result).toBeNull();
        });
    });

    describe('expand', () => {
        it('should include beforeYear param when provided', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ children: [], total: 0 }) };
            });

            await window.apiClient.expand('Radiohead', 'artist', 'releases', 50, 0, 1995);
            expect(capturedUrl).toContain('before_year=1995');
        });

        it('should omit beforeYear param when null', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ children: [], total: 0 }) };
            });

            await window.apiClient.expand('Radiohead', 'artist', 'releases', 50, 0, null);
            expect(capturedUrl).not.toContain('before_year');
        });

        it('should return fallback object on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/expand': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.expand('Radiohead', 'artist', 'releases');
            expect(result).toEqual({ children: [], total: 0, offset: 0, limit: 50, has_more: false });
        });
    });

    describe('getNodeDetails', () => {
        it('should URL-encode the node ID', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ name: 'A/B' }) };
            });

            await window.apiClient.getNodeDetails('A/B', 'artist');
            expect(capturedUrl).toContain('/api/node/A%2FB');
        });
    });

    describe('findPath', () => {
        it('should return notFound object on 404', async () => {
            const mockFetch = createMockFetch({
                '/api/path': { status: 404, data: { error: 'Entity not found' } },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.findPath('A', 'artist', 'B', 'artist');
            expect(result).toEqual({ notFound: true, error: 'Entity not found' });
        });

        it('should return null on server error', async () => {
            const mockFetch = createMockFetch({
                '/api/path': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.findPath('A', 'artist', 'B', 'artist');
            expect(result).toBeNull();
        });
    });

    describe('search', () => {
        it('should include type and genre filters in params', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ results: [], total: 0 }) };
            });

            await window.apiClient.search('test', ['artist', 'label'], ['Rock'], 1990, 2000, 20, 0);
            expect(capturedUrl).toContain('types=artist%2Clabel');
            expect(capturedUrl).toContain('genres=Rock');
            expect(capturedUrl).toContain('year_min=1990');
            expect(capturedUrl).toContain('year_max=2000');
        });

        it('should omit optional params when not provided', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ results: [], total: 0 }) };
            });

            await window.apiClient.search('test');
            expect(capturedUrl).not.toContain('types=');
            expect(capturedUrl).not.toContain('genres=');
            expect(capturedUrl).not.toContain('year_min');
            expect(capturedUrl).not.toContain('year_max');
        });
    });

    describe('auth methods', () => {
        it('login should return token data on success', async () => {
            const mockFetch = createMockFetch({
                '/api/auth/login': { data: { token: 'jwt-token' } },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.login('user@test.com', 'pass');
            expect(result).toEqual({ token: 'jwt-token' });
        });

        it('login should return null on failure', async () => {
            const mockFetch = createMockFetch({
                '/api/auth/login': { status: 401 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.login('user@test.com', 'wrong');
            expect(result).toBeNull();
        });

        it('register should return true on 201', async () => {
            const mockFetch = createMockFetch({
                '/api/auth/register': { status: 201 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.register('user@test.com', 'pass');
            expect(result).toBe(true);
        });

        it('register should return false on conflict', async () => {
            const mockFetch = createMockFetch({
                '/api/auth/register': { status: 409 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.register('user@test.com', 'pass');
            expect(result).toBe(false);
        });

        it('logout should not throw when token is null', async () => {
            vi.stubGlobal('fetch', vi.fn());
            await window.apiClient.logout(null);
            expect(fetch).not.toHaveBeenCalled();
        });

        it('getMe should return null when token is null', async () => {
            const result = await window.apiClient.getMe(null);
            expect(result).toBeNull();
        });

        it('getMe should send Authorization header', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({ id: 1, email: 'user@test.com' }) };
            });

            await window.apiClient.getMe('my-token');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });
    });

    describe('user data methods', () => {
        it('getUserCollection should return null without token', async () => {
            const result = await window.apiClient.getUserCollection(null);
            expect(result).toBeNull();
        });

        it('getUserStatus should send IDs as comma-separated param', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getUserStatus([1, 2, 3], 'token');
            expect(capturedUrl).toContain('ids=1%2C2%2C3');
        });
    });

    describe('collection gap analysis', () => {
        it('getCollectionGaps should handle format array and excludeWantlist', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getCollectionGaps('token', 'artist', 'Radiohead', {
                limit: 10,
                offset: 5,
                excludeWantlist: true,
                formats: ['Vinyl', 'CD'],
            });

            expect(capturedUrl).toContain('limit=10');
            expect(capturedUrl).toContain('offset=5');
            expect(capturedUrl).toContain('exclude_wantlist=true');
            expect(capturedUrl).toContain('formats=Vinyl');
            expect(capturedUrl).toContain('formats=CD');
            expect(capturedUrl).toContain('/api/collection/gaps/artist/Radiohead');
        });
    });

    describe('insights methods', () => {
        it('getInsightsTopArtists should include limit param', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ items: [] }) };
            });

            await window.apiClient.getInsightsTopArtists(5);
            expect(capturedUrl).toContain('limit=5');
        });

        it('getInsightsGenreTrends should include genre param', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ trends: [] }) };
            });

            await window.apiClient.getInsightsGenreTrends('Rock');
            expect(capturedUrl).toContain('genre=Rock');
        });
    });

    describe('snapshot methods', () => {
        it('saveSnapshot should include auth header when token provided', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({ token: 'snap-123' }) };
            });

            await window.apiClient.saveSnapshot([{ id: 'A', type: 'artist' }], { id: 'A', type: 'artist' }, 'jwt');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer jwt');
            expect(capturedOptions.method).toBe('POST');
        });

        it('saveSnapshot should omit auth header when no token', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({ token: 'snap-123' }) };
            });

            await window.apiClient.saveSnapshot([], {}, null);
            expect(capturedOptions.headers['Authorization']).toBeUndefined();
        });
    });
});
