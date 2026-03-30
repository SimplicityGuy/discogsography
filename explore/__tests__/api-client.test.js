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

    describe('getCollaborators', () => {
        it('should return collaborator data on success', async () => {
            const collabData = {
                artist_id: '123',
                artist_name: 'Radiohead',
                collaborators: [{ artist_id: '456', artist_name: 'Thom Yorke', release_count: 5 }],
                total: 1,
            };
            const mockFetch = createMockFetch({
                '/api/collaborators/': { data: collabData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getCollaborators('123');
            expect(result).toEqual(collabData);
        });

        it('should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/collaborators/': { status: 404 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getCollaborators('999');
            expect(result).toBeNull();
        });

        it('should include limit param and URL-encode artist ID', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getCollaborators('A/B', 5);
            expect(capturedUrl).toContain('/api/collaborators/A%2FB');
            expect(capturedUrl).toContain('limit=5');
        });
    });

    describe('getGenreTree', () => {
        it('should return genre tree data on success', async () => {
            const treeData = {
                genres: [{ name: 'Rock', release_count: 98000, styles: [] }],
            };
            const mockFetch = createMockFetch({
                '/api/genre-tree': { data: treeData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getGenreTree();
            expect(result).toEqual(treeData);
        });

        it('should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/genre-tree': { status: 503 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getGenreTree();
            expect(result).toBeNull();
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

        it('saveSnapshot should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/snapshot': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.saveSnapshot([], {}, null);
            expect(result).toBeNull();
        });

        it('restoreSnapshot should return data on success', async () => {
            const snapshotData = { nodes: [{ id: 'A', type: 'artist' }], center: { id: 'A', type: 'artist' } };
            const mockFetch = createMockFetch({
                '/api/snapshot/': { data: snapshotData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.restoreSnapshot('snap-123');
            expect(result).toEqual(snapshotData);
        });

        it('restoreSnapshot should URL-encode the token', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.restoreSnapshot('token/with/slashes');
            expect(capturedUrl).toContain('/api/snapshot/token%2Fwith%2Fslashes');
        });

        it('restoreSnapshot should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/snapshot/': { status: 404 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.restoreSnapshot('bad-token');
            expect(result).toBeNull();
        });
    });

    describe('getTrends', () => {
        it('should return trends data on success', async () => {
            const trendsData = { name: 'Radiohead', years: [1993, 1995], counts: [1, 3] };
            const mockFetch = createMockFetch({
                '/api/trends': { data: trendsData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getTrends('Radiohead', 'artist');
            expect(result).toEqual(trendsData);
        });

        it('should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/trends': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getTrends('Radiohead', 'artist');
            expect(result).toBeNull();
        });

        it('should include name and type params', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getTrends('Radiohead', 'artist');
            expect(capturedUrl).toContain('name=Radiohead');
            expect(capturedUrl).toContain('type=artist');
        });
    });

    describe('getYearRange', () => {
        it('should return year range on success', async () => {
            const mockFetch = createMockFetch({
                '/api/explore/year-range': { data: { min_year: 1950, max_year: 2023 } },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getYearRange();
            expect(result).toEqual({ min_year: 1950, max_year: 2023 });
        });

        it('should return fallback on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/explore/year-range': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getYearRange();
            expect(result).toEqual({ min_year: null, max_year: null });
        });
    });

    describe('getGenreEmergence', () => {
        it('should return genre data on success', async () => {
            const data = { genres: [{ name: 'Rock' }], styles: [{ name: 'Punk' }] };
            const mockFetch = createMockFetch({
                '/api/explore/genre-emergence': { data },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getGenreEmergence(1990);
            expect(result).toEqual(data);
        });

        it('should include before_year param', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ genres: [], styles: [] }) };
            });

            await window.apiClient.getGenreEmergence(1985);
            expect(capturedUrl).toContain('before_year=1985');
        });

        it('should return fallback on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/explore/genre-emergence': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getGenreEmergence(1990);
            expect(result).toEqual({ genres: [], styles: [] });
        });
    });

    describe('getNodeDetails', () => {
        it('should return details on success', async () => {
            const details = { name: 'Radiohead', release_count: 42 };
            const mockFetch = createMockFetch({
                '/api/node/': { data: details },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getNodeDetails('Radiohead', 'artist');
            expect(result).toEqual(details);
        });

        it('should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/node/': { status: 404 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getNodeDetails('Unknown', 'artist');
            expect(result).toBeNull();
        });
    });

    describe('Discogs OAuth methods', () => {
        it('authorizeDiscogs should return null without token', async () => {
            const result = await window.apiClient.authorizeDiscogs(null);
            expect(result).toBeNull();
        });

        it('authorizeDiscogs should return auth data on success', async () => {
            const authData = { authorize_url: 'https://discogs.com/oauth', state: 'abc' };
            const mockFetch = createMockFetch({
                '/api/oauth/authorize/discogs': { data: authData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.authorizeDiscogs('my-token');
            expect(result).toEqual(authData);
        });

        it('authorizeDiscogs should send Authorization header', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.authorizeDiscogs('my-token');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });

        it('authorizeDiscogs should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/oauth/authorize/discogs': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.authorizeDiscogs('my-token');
            expect(result).toBeNull();
        });

        it('verifyDiscogs should return null without token', async () => {
            const result = await window.apiClient.verifyDiscogs(null, 'state', 'verifier');
            expect(result).toBeNull();
        });

        it('verifyDiscogs should send state and verifier in body', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({ connected: true }) };
            });

            await window.apiClient.verifyDiscogs('token', 'my-state', 'my-verifier');
            const body = JSON.parse(capturedOptions.body);
            expect(body.state).toBe('my-state');
            expect(body.oauth_verifier).toBe('my-verifier');
            expect(capturedOptions.method).toBe('POST');
        });

        it('verifyDiscogs should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/oauth/verify/discogs': { status: 400 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.verifyDiscogs('token', 'state', 'verifier');
            expect(result).toBeNull();
        });

        it('getDiscogsStatus should return null without token', async () => {
            const result = await window.apiClient.getDiscogsStatus(null);
            expect(result).toBeNull();
        });

        it('getDiscogsStatus should return status on success', async () => {
            const mockFetch = createMockFetch({
                '/api/oauth/status/discogs': { data: { connected: true, discogs_username: 'dj_test' } },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getDiscogsStatus('token');
            expect(result).toEqual({ connected: true, discogs_username: 'dj_test' });
        });

        it('revokeDiscogs should return null without token', async () => {
            const result = await window.apiClient.revokeDiscogs(null);
            expect(result).toBeNull();
        });

        it('revokeDiscogs should use DELETE method', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({ revoked: true }) };
            });

            await window.apiClient.revokeDiscogs('token');
            expect(capturedOptions.method).toBe('DELETE');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer token');
        });

        it('revokeDiscogs should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/oauth/revoke/discogs': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.revokeDiscogs('token');
            expect(result).toBeNull();
        });
    });

    describe('user data methods - extended', () => {
        it('getUserCollection should include pagination params', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ releases: [], total: 0 }) };
            });

            await window.apiClient.getUserCollection('token', 25, 50);
            expect(capturedUrl).toContain('limit=25');
            expect(capturedUrl).toContain('offset=50');
        });

        it('getUserCollection should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/user/collection': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getUserCollection('token');
            expect(result).toBeNull();
        });

        it('getUserWantlist should return null without token', async () => {
            const result = await window.apiClient.getUserWantlist(null);
            expect(result).toBeNull();
        });

        it('getUserWantlist should return data on success', async () => {
            const wantlistData = { releases: [{ title: 'Loveless' }], total: 1 };
            const mockFetch = createMockFetch({
                '/api/user/wantlist': { data: wantlistData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getUserWantlist('token');
            expect(result).toEqual(wantlistData);
        });

        it('getUserWantlist should include pagination params', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getUserWantlist('token', 10, 20);
            expect(capturedUrl).toContain('limit=10');
            expect(capturedUrl).toContain('offset=20');
        });

        it('getUserRecommendations should return null without token', async () => {
            const result = await window.apiClient.getUserRecommendations(null);
            expect(result).toBeNull();
        });

        it('getUserRecommendations should include limit param', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({ recommendations: [] }) };
            });

            await window.apiClient.getUserRecommendations('token', 30);
            expect(capturedUrl).toContain('limit=30');
        });

        it('getUserCollectionStats should return null without token', async () => {
            const result = await window.apiClient.getUserCollectionStats(null);
            expect(result).toBeNull();
        });

        it('getUserCollectionStats should return stats on success', async () => {
            const stats = { total_releases: 100, unique_artists: 50 };
            const mockFetch = createMockFetch({
                '/api/user/collection/stats': { data: stats },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getUserCollectionStats('token');
            expect(result).toEqual(stats);
        });

        it('getUserStatus should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/user/status': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getUserStatus([1], 'token');
            expect(result).toBeNull();
        });

        it('getUserStatus should work without token', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getUserStatus([1]);
            expect(capturedOptions.headers['Authorization']).toBeUndefined();
        });
    });

    describe('collection formats and gaps', () => {
        it('getCollectionFormats should return null without token', async () => {
            const result = await window.apiClient.getCollectionFormats(null);
            expect(result).toBeNull();
        });

        it('getCollectionFormats should return formats on success', async () => {
            const mockFetch = createMockFetch({
                '/api/collection/formats': { data: { formats: ['Vinyl', 'CD'] } },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getCollectionFormats('token');
            expect(result).toEqual({ formats: ['Vinyl', 'CD'] });
        });

        it('getCollectionGaps should return null without token', async () => {
            const result = await window.apiClient.getCollectionGaps(null, 'artist', 'id');
            expect(result).toBeNull();
        });

        it('getCollectionGaps should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/collection/gaps/': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getCollectionGaps('token', 'artist', 'Radiohead');
            expect(result).toBeNull();
        });

        it('getCollectionGaps should use default options', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.getCollectionGaps('token', 'artist', 'Radiohead');
            expect(capturedUrl).toContain('limit=50');
            expect(capturedUrl).toContain('offset=0');
        });
    });

    describe('sync methods', () => {
        it('triggerSync should return null without token', async () => {
            const result = await window.apiClient.triggerSync(null);
            expect(result).toBeNull();
        });

        it('triggerSync should use POST method', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, json: async () => ({ syncing: true }) };
            });

            await window.apiClient.triggerSync('token');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer token');
        });

        it('triggerSync should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/sync': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.triggerSync('token');
            expect(result).toBeNull();
        });

        it('getSyncStatus should return null without token', async () => {
            const result = await window.apiClient.getSyncStatus(null);
            expect(result).toBeNull();
        });

        it('getSyncStatus should return status on success', async () => {
            const mockFetch = createMockFetch({
                '/api/sync/status': { data: { status: 'idle', last_sync: '2024-01-01' } },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getSyncStatus('token');
            expect(result).toEqual({ status: 'idle', last_sync: '2024-01-01' });
        });
    });

    describe('taste fingerprint methods', () => {
        it('getTasteFingerprint should return null without token', async () => {
            const result = await window.apiClient.getTasteFingerprint(null);
            expect(result).toBeNull();
        });

        it('getTasteFingerprint should return data on success', async () => {
            const fpData = { obscurity: { score: 0.75 }, peak_decade: 1990 };
            const mockFetch = createMockFetch({
                '/api/user/taste/fingerprint': { data: fpData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getTasteFingerprint('token');
            expect(result).toEqual(fpData);
        });

        it('getTasteFingerprint should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/user/taste/fingerprint': { status: 422 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getTasteFingerprint('token');
            expect(result).toBeNull();
        });

        it('getTasteCard should return null without token', async () => {
            const result = await window.apiClient.getTasteCard(null);
            expect(result).toBeNull();
        });

        it('getTasteCard should return blob on success', async () => {
            const svgBlob = new Blob(['<svg></svg>'], { type: 'image/svg+xml' });
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                blob: async () => svgBlob,
            }));

            const result = await window.apiClient.getTasteCard('token');
            expect(result).toBeInstanceOf(Blob);
        });

        it('getTasteCard should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/user/taste/card': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getTasteCard('token');
            expect(result).toBeNull();
        });
    });

    describe('insights methods - extended', () => {
        it('getInsightsThisMonth should return data on success', async () => {
            const data = { highlights: ['New release'] };
            const mockFetch = createMockFetch({
                '/api/insights/this-month': { data },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsThisMonth();
            expect(result).toEqual(data);
        });

        it('getInsightsThisMonth should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/insights/this-month': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsThisMonth();
            expect(result).toBeNull();
        });

        it('getInsightsDataCompleteness should return data on success', async () => {
            const data = { completeness: 0.95 };
            const mockFetch = createMockFetch({
                '/api/insights/data-completeness': { data },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsDataCompleteness();
            expect(result).toEqual(data);
        });

        it('getInsightsDataCompleteness should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/insights/data-completeness': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsDataCompleteness();
            expect(result).toBeNull();
        });

        it('getInsightsStatus should return data on success', async () => {
            const data = { status: 'ready', last_computed: '2024-01-01' };
            const mockFetch = createMockFetch({
                '/api/insights/status': { data },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsStatus();
            expect(result).toEqual(data);
        });

        it('getInsightsStatus should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/insights/status': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsStatus();
            expect(result).toBeNull();
        });

        it('getInsightsTopArtists should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/insights/top-artists': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsTopArtists();
            expect(result).toBeNull();
        });

        it('getInsightsGenreTrends should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/insights/genre-trends': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.getInsightsGenreTrends('Rock');
            expect(result).toBeNull();
        });
    });

    describe('findPath - extended', () => {
        it('should return path data on success', async () => {
            const pathData = { found: true, length: 3, path: ['A', 'B', 'C'] };
            const mockFetch = createMockFetch({
                '/api/path': { data: pathData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.findPath('A', 'artist', 'C', 'artist');
            expect(result).toEqual(pathData);
        });

        it('should include max_depth param', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.findPath('A', 'artist', 'B', 'label', 5);
            expect(capturedUrl).toContain('max_depth=5');
        });

        it('should use default error message when 404 has no error field', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 404,
                json: async () => ({}),
            }));

            const result = await window.apiClient.findPath('A', 'artist', 'B', 'artist');
            expect(result).toEqual({ notFound: true, error: 'Entity not found' });
        });
    });

    describe('search - extended', () => {
        it('should return null on HTTP error', async () => {
            const mockFetch = createMockFetch({
                '/api/search': { status: 500 },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.search('test');
            expect(result).toBeNull();
        });

        it('should return search results on success', async () => {
            const searchData = { results: [{ name: 'Radiohead', type: 'artist' }], total: 1 };
            const mockFetch = createMockFetch({
                '/api/search': { data: searchData },
            });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.search('Radiohead');
            expect(result).toEqual(searchData);
        });
    });

    describe('logout - extended', () => {
        it('should send POST with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true };
            });

            await window.apiClient.logout('my-token');
            expect(capturedUrl).toContain('/api/auth/logout');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });
    });

    describe('password reset methods', () => {
        it('resetRequest should POST to /api/auth/reset-request with email', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({}) };
            });

            const response = await window.apiClient.resetRequest('user@test.com');
            expect(capturedUrl).toBe('/api/auth/reset-request');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
            expect(JSON.parse(capturedOptions.body)).toEqual({ email: 'user@test.com' });
            expect(response.ok).toBe(true);
        });

        it('resetRequest should return the raw response', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 429, json: async () => ({}) }));

            const response = await window.apiClient.resetRequest('user@test.com');
            expect(response.ok).toBe(false);
            expect(response.status).toBe(429);
        });

        it('resetConfirm should POST to /api/auth/reset-confirm with token and new_password', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({}) };
            });

            const response = await window.apiClient.resetConfirm('reset-token-abc', 'newpass123');
            expect(capturedUrl).toBe('/api/auth/reset-confirm');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
            expect(JSON.parse(capturedOptions.body)).toEqual({ token: 'reset-token-abc', new_password: 'newpass123' });
            expect(response.ok).toBe(true);
        });
    });

    describe('askNlqStream SSE streaming', () => {
        function makeReadableStream(chunks) {
            let index = 0;
            return {
                getReader() {
                    return {
                        read() {
                            if (index < chunks.length) {
                                const chunk = chunks[index++];
                                return Promise.resolve({
                                    done: false,
                                    value: new TextEncoder().encode(chunk),
                                });
                            }
                            return Promise.resolve({ done: true, value: undefined });
                        },
                    };
                },
            };
        }

        it('should flush buffer on stream completion (done=true with remaining data)', async () => {
            // The final chunk has data WITHOUT a trailing newline, so it stays in buffer
            // until done=true triggers the flush
            const stream = makeReadableStream([
                'event: result\ndata: {"answer":"hello"}',
            ]);

            vi.stubGlobal('fetch', async () => ({
                ok: true,
                body: stream,
            }));

            const onResult = vi.fn();
            window.apiClient.askNlqStream('test query', null, vi.fn(), onResult, vi.fn());

            // Wait for async stream processing
            await new Promise(r => setTimeout(r, 50));

            expect(onResult).toHaveBeenCalledWith({ answer: 'hello' });
        });

        it('should persist eventType across chunk boundaries', async () => {
            // event: line is in chunk 1, data: line is in chunk 2
            const stream = makeReadableStream([
                'event: status\n',
                'data: {"step":"thinking"}\n\n',
            ]);

            vi.stubGlobal('fetch', async () => ({
                ok: true,
                body: stream,
            }));

            const onStatus = vi.fn();
            window.apiClient.askNlqStream('test query', null, onStatus, vi.fn(), vi.fn());

            // Wait for async stream processing
            await new Promise(r => setTimeout(r, 50));

            expect(onStatus).toHaveBeenCalledWith({ step: 'thinking' });
        });
    });

    describe('2FA methods', () => {
        it('twoFactorSetup should POST to /api/auth/2fa/setup with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({ secret: 'ABCDEF', qr_uri: 'otpauth://...' }) };
            });

            const response = await window.apiClient.twoFactorSetup('my-jwt');
            expect(capturedUrl).toBe('/api/auth/2fa/setup');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-jwt');
            expect(response.ok).toBe(true);
        });

        it('twoFactorConfirm should POST to /api/auth/2fa/confirm with Authorization header and code', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.twoFactorConfirm('my-jwt', '123456');
            expect(capturedUrl).toBe('/api/auth/2fa/confirm');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-jwt');
            expect(JSON.parse(capturedOptions.body)).toEqual({ code: '123456' });
        });

        it('twoFactorVerify should POST to /api/auth/2fa/verify with challenge_token and code', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({ access_token: 'jwt' }) };
            });

            await window.apiClient.twoFactorVerify('challenge-xyz', '654321');
            expect(capturedUrl).toBe('/api/auth/2fa/verify');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
            expect(JSON.parse(capturedOptions.body)).toEqual({ challenge_token: 'challenge-xyz', code: '654321' });
        });

        it('twoFactorVerify should return the raw response', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 401, json: async () => ({}) }));

            const response = await window.apiClient.twoFactorVerify('bad-token', '000000');
            expect(response.ok).toBe(false);
        });

        it('twoFactorRecovery should POST to /api/auth/2fa/recovery with challenge_token and code', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({ access_token: 'jwt' }) };
            });

            await window.apiClient.twoFactorRecovery('challenge-xyz', 'RECOVERY-CODE-001');
            expect(capturedUrl).toBe('/api/auth/2fa/recovery');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
            expect(JSON.parse(capturedOptions.body)).toEqual({ challenge_token: 'challenge-xyz', code: 'RECOVERY-CODE-001' });
        });

        it('twoFactorDisable should POST to /api/auth/2fa/disable with Authorization header, code, and password', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, json: async () => ({}) };
            });

            await window.apiClient.twoFactorDisable('my-jwt', '123456', 'mypassword');
            expect(capturedUrl).toBe('/api/auth/2fa/disable');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-jwt');
            expect(JSON.parse(capturedOptions.body)).toEqual({ code: '123456', password: 'mypassword' });
        });

        it('twoFactorDisable should return the raw response', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 400, json: async () => ({}) }));

            const response = await window.apiClient.twoFactorDisable('my-jwt', 'wrong', 'pass');
            expect(response.ok).toBe(false);
        });
    });
});
