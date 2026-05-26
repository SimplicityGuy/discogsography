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
        it('triggerSync should return not-ok envelope without token', async () => {
            const result = await window.apiClient.triggerSync(null);
            expect(result).toEqual({ ok: false, status: 0, body: null });
        });

        it('triggerSync should use POST method', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, status: 202, json: async () => ({ syncing: true }) };
            });

            const result = await window.apiClient.triggerSync('token');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer token');
            expect(result.ok).toBe(true);
            expect(result.status).toBe(202);
            expect(result.body).toEqual({ syncing: true });
        });

        it('triggerSync should surface 429 status and body', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 429,
                json: async () => ({ status: 'cooldown', message: 'Sync rate limited.' }),
            }));

            const result = await window.apiClient.triggerSync('token');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(429);
            expect(result.body).toEqual({ status: 'cooldown', message: 'Sync rate limited.' });
        });

        it('triggerSync should surface 500 status with null body', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 500,
                json: async () => { throw new Error('not json'); },
            }));

            const result = await window.apiClient.triggerSync('token');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(500);
            expect(result.body).toBeNull();
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

        it('should call onError when reader.read() rejects mid-stream', async () => {
            let readCount = 0;
            const stream = {
                getReader() {
                    return {
                        read() {
                            readCount++;
                            if (readCount === 1) {
                                return Promise.resolve({
                                    done: false,
                                    value: new TextEncoder().encode('event: status\ndata: {"step":"ok"}\n\n'),
                                });
                            }
                            return Promise.reject(new Error('stream aborted'));
                        },
                    };
                },
            };

            vi.stubGlobal('fetch', async () => ({
                ok: true,
                body: stream,
            }));

            const onError = vi.fn();
            window.apiClient.askNlqStream('test query', null, vi.fn(), vi.fn(), onError);

            await new Promise(r => setTimeout(r, 50));

            expect(onError).toHaveBeenCalled();
            expect(onError.mock.calls[0][0].message).toBe('stream aborted');
        });
    });

    describe('streamDiggerAgent SSE streaming', () => {
        function makeReadableStream(chunks) {
            let index = 0;
            return {
                getReader() {
                    return {
                        read() {
                            if (index < chunks.length) {
                                const chunk = chunks[index++];
                                return Promise.resolve({ done: false, value: new TextEncoder().encode(chunk) });
                            }
                            return Promise.resolve({ done: true, value: undefined });
                        },
                    };
                },
            };
        }

        it('forwards text and done events to callbacks', async () => {
            const stream = makeReadableStream([
                'event: text\ndata: {"delta":"hel"}\n\n',
                'event: text\ndata: {"delta":"lo"}\n\n',
                'event: done\ndata: {"session_id":"s1","usage":{"input":5,"output":2,"cache_read":0}}\n\n',
            ]);
            let capturedUrl;
            let capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, body: stream };
            });

            const onText = vi.fn();
            const onDone = vi.fn();
            window.apiClient.streamDiggerAgent('tok', { user_message: 'hi', session_id: null }, { onText, onDone });
            await new Promise((r) => setTimeout(r, 50));

            expect(capturedUrl).toBe('/api/digger/agent/message');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers.Authorization).toBe('Bearer tok');
            expect(JSON.parse(capturedOptions.body)).toEqual({ user_message: 'hi', session_id: null });
            expect(onText).toHaveBeenCalledTimes(2);
            expect(onText.mock.calls[0][0]).toEqual({ delta: 'hel' });
            expect(onDone).toHaveBeenCalledWith({ session_id: 's1', usage: { input: 5, output: 2, cache_read: 0 } });
        });

        it('forwards tool_call, tool_result, bundle_card, and proposal_card events', async () => {
            const stream = makeReadableStream([
                'event: tool_call\ndata: {"id":"t1","name":"compute_bundles","input":{}}\n\n',
                'event: tool_result\ndata: {"id":"t1","name":"compute_bundles","output":{"bundles":[]}}\n\n',
                'event: bundle_card\ndata: {"bundle":{"name":"cheapest"}}\n\n',
                'event: proposal_card\ndata: {"proposal":{"proposal_id":"p1","count":1}}\n\n',
                'event: done\ndata: {"session_id":"s1","usage":{"input":1,"output":1,"cache_read":0}}\n\n',
            ]);
            vi.stubGlobal('fetch', async () => ({ ok: true, body: stream }));

            const onToolCall = vi.fn();
            const onToolResult = vi.fn();
            const onBundleCard = vi.fn();
            const onProposalCard = vi.fn();
            window.apiClient.streamDiggerAgent('tok', {}, { onToolCall, onToolResult, onBundleCard, onProposalCard });
            await new Promise((r) => setTimeout(r, 50));

            expect(onToolCall).toHaveBeenCalledWith({ id: 't1', name: 'compute_bundles', input: {} });
            expect(onToolResult).toHaveBeenCalledWith({ id: 't1', name: 'compute_bundles', output: { bundles: [] } });
            expect(onBundleCard).toHaveBeenCalledWith({ bundle: { name: 'cheapest' } });
            expect(onProposalCard).toHaveBeenCalledWith({ proposal: { proposal_id: 'p1', count: 1 } });
        });

        it('forwards error events to onError', async () => {
            const stream = makeReadableStream(['event: error\ndata: {"reason":"daily token cap exceeded"}\n\n']);
            vi.stubGlobal('fetch', async () => ({ ok: true, body: stream }));

            const onError = vi.fn();
            window.apiClient.streamDiggerAgent('tok', {}, { onError });
            await new Promise((r) => setTimeout(r, 50));

            expect(onError).toHaveBeenCalledWith({ reason: 'daily token cap exceeded' });
        });

        it('calls onError with the status on a non-ok response', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 429, body: null }));
            const onError = vi.fn();
            window.apiClient.streamDiggerAgent('tok', {}, { onError });
            await new Promise((r) => setTimeout(r, 50));
            expect(onError).toHaveBeenCalledWith({ status: 429 });
        });

        it('calls onError when reader.read() rejects mid-stream', async () => {
            let readCount = 0;
            const stream = {
                getReader() {
                    return {
                        read() {
                            readCount++;
                            if (readCount === 1) {
                                return Promise.resolve({ done: false, value: new TextEncoder().encode('event: text\ndata: {"delta":"x"}\n\n') });
                            }
                            return Promise.reject(new Error('stream aborted'));
                        },
                    };
                },
            };
            vi.stubGlobal('fetch', async () => ({ ok: true, body: stream }));
            const onError = vi.fn();
            window.apiClient.streamDiggerAgent('tok', {}, { onError });
            await new Promise((r) => setTimeout(r, 50));
            expect(onError).toHaveBeenCalled();
            expect(onError.mock.calls[0][0].message).toBe('stream aborted');
        });

        it('flushes a trailing buffered event on stream completion', async () => {
            const stream = makeReadableStream(['event: done\ndata: {"session_id":"s2","usage":{"input":0,"output":0,"cache_read":0}}']);
            vi.stubGlobal('fetch', async () => ({ ok: true, body: stream }));
            const onDone = vi.fn();
            window.apiClient.streamDiggerAgent('tok', {}, { onDone });
            await new Promise((r) => setTimeout(r, 50));
            expect(onDone).toHaveBeenCalledWith({ session_id: 's2', usage: { input: 0, output: 0, cache_read: 0 } });
        });
    });

    describe('getDiggerAgentSessions', () => {
        it('GETs /api/digger/agent/sessions with auth header', async () => {
            let capturedUrl;
            let capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ items: [] }) };
            });
            const res = await window.apiClient.getDiggerAgentSessions('tok');
            expect(capturedUrl).toBe('/api/digger/agent/sessions');
            expect(capturedOptions.headers.Authorization).toBe('Bearer tok');
            expect(res).toEqual({ ok: true, status: 200, body: { items: [] } });
        });
    });

    describe('digger proposal methods', () => {
        it('getDiggerProposals GETs /api/digger/proposals with auth header', async () => {
            let capturedUrl;
            let capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ items: [] }) };
            });
            const res = await window.apiClient.getDiggerProposals('tok');
            expect(capturedUrl).toBe('/api/digger/proposals');
            expect(capturedOptions.headers.Authorization).toBe('Bearer tok');
            expect(res).toEqual({ ok: true, status: 200, body: { items: [] } });
        });

        it('approveDiggerProposal POSTs to the approve endpoint and returns the applied count', async () => {
            let capturedUrl;
            let capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ applied: 2 }) };
            });
            const res = await window.apiClient.approveDiggerProposal('tok', 'p1');
            expect(capturedUrl).toBe('/api/digger/proposals/p1/approve');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers.Authorization).toBe('Bearer tok');
            expect(res).toEqual({ ok: true, status: 200, body: { applied: 2 } });
        });

        it('rejectDiggerProposal POSTs to the reject endpoint (204 → body null)', async () => {
            let capturedUrl;
            let capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });
            const res = await window.apiClient.rejectDiggerProposal('tok', 'p1');
            expect(capturedUrl).toBe('/api/digger/proposals/p1/reject');
            expect(capturedOptions.method).toBe('POST');
            expect(res).toEqual({ ok: true, status: 204, body: null });
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

    describe('changePassword', () => {
        it('should send POST with auth header and credentials', async () => {
            const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ message: 'Password has been changed' }) });
            vi.stubGlobal('fetch', mockFetch);

            const result = await window.apiClient.changePassword('token123', 'old', 'newpass123');
            expect(result.ok).toBe(true);
            expect(mockFetch).toHaveBeenCalledWith('/api/auth/change-password', expect.objectContaining({
                method: 'POST',
                headers: expect.objectContaining({ 'Authorization': 'Bearer token123' }),
            }));
        });
    });

    // --- Digger ---

    describe('getDiggerSettings', () => {
        it('should GET /api/digger/settings with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ enabled: true, currency: 'USD' }) };
            });

            await window.apiClient.getDiggerSettings('my-token');
            expect(capturedUrl).toBe('/api/digger/settings');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });

        it('should return { ok:true, status:200, body } on success', async () => {
            const settingsData = {
                enabled: true,
                country_code: 'US',
                currency: 'USD',
                scheduled_cadence: 'weekly',
                preferred_model: 'haiku',
                daily_token_cap_interactive: 10000,
                daily_token_cap_scheduled: 50000,
            };
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                status: 200,
                json: async () => settingsData,
            }));

            const result = await window.apiClient.getDiggerSettings('token');
            expect(result.ok).toBe(true);
            expect(result.status).toBe(200);
            expect(result.body).toEqual(settingsData);
        });

        it('should return { ok:false, status:404, body } when digger not enabled', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 404,
                json: async () => ({ detail: 'Digger not enabled' }),
            }));

            const result = await window.apiClient.getDiggerSettings('token');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(404);
            expect(result.body).toEqual({ detail: 'Digger not enabled' });
        });

        it('should return body:null when json() throws (empty body)', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 500,
                json: async () => { throw new Error('not json'); },
            }));

            const result = await window.apiClient.getDiggerSettings('token');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(500);
            expect(result.body).toBeNull();
        });
    });

    describe('putDiggerSettings', () => {
        it('should PUT /api/digger/settings with Authorization and Content-Type headers', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });

            const settings = { enabled: true, currency: 'USD', scheduled_cadence: 'weekly', preferred_model: 'haiku' };
            await window.apiClient.putDiggerSettings('my-token', settings);
            expect(capturedUrl).toBe('/api/digger/settings');
            expect(capturedOptions.method).toBe('PUT');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
        });

        it('should serialize settings as JSON body', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });

            const settings = { enabled: false, country_code: 'GB', currency: 'GBP', scheduled_cadence: 'monthly', preferred_model: 'opus', daily_token_cap_interactive: null, daily_token_cap_scheduled: null };
            await window.apiClient.putDiggerSettings('token', settings);
            expect(JSON.parse(capturedOptions.body)).toEqual(settings);
        });

        it('should return { ok:true, status:204, body:null } on 204 No Content', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                status: 204,
                json: async () => { throw new Error('no body'); },
            }));

            const result = await window.apiClient.putDiggerSettings('token', { enabled: true });
            expect(result.ok).toBe(true);
            expect(result.status).toBe(204);
            expect(result.body).toBeNull();
        });

        it('should return { ok:false, status:422, body } on validation error', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 422,
                json: async () => ({ detail: 'Validation error' }),
            }));

            const result = await window.apiClient.putDiggerSettings('token', { enabled: 'bad' });
            expect(result.ok).toBe(false);
            expect(result.status).toBe(422);
            expect(result.body).toEqual({ detail: 'Validation error' });
        });
    });

    describe('getDiggerWantlist', () => {
        it('should GET /api/digger/wantlist with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ items: [] }) };
            });

            await window.apiClient.getDiggerWantlist('my-token');
            expect(capturedUrl).toBe('/api/digger/wantlist');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });

        it('should return { ok:true, status:200, body } with items array on success', async () => {
            const wantlistData = {
                items: [
                    {
                        release_id: 12345,
                        title: 'Loveless',
                        artist: 'My Bloody Valentine',
                        year: 1991,
                        tier: 'must',
                        min_media_condition: 'VG+',
                        min_sleeve_condition: 'VG',
                        max_price_cents: 5000,
                        active_listings: 3,
                        last_scraped_at: '2026-01-01T00:00:00Z',
                    },
                ],
            };
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                status: 200,
                json: async () => wantlistData,
            }));

            const result = await window.apiClient.getDiggerWantlist('token');
            expect(result.ok).toBe(true);
            expect(result.status).toBe(200);
            expect(result.body).toEqual(wantlistData);
        });

        it('should return { ok:false, status:401, body } on unauthorized', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 401,
                json: async () => ({ detail: 'Unauthorized' }),
            }));

            const result = await window.apiClient.getDiggerWantlist('bad-token');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(401);
            expect(result.body).toEqual({ detail: 'Unauthorized' });
        });

        it('should return body:null when json() throws', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 503,
                json: async () => { throw new Error('no body'); },
            }));

            const result = await window.apiClient.getDiggerWantlist('token');
            expect(result.body).toBeNull();
        });
    });

    describe('setDiggerPriority', () => {
        it('should PUT /api/digger/wantlist/{releaseId}/priority with Authorization and Content-Type headers', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });

            await window.apiClient.setDiggerPriority('my-token', 12345, { tier: 'must' });
            expect(capturedUrl).toBe('/api/digger/wantlist/12345/priority');
            expect(capturedOptions.method).toBe('PUT');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
        });

        it('should serialize the patch as JSON body', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });

            const patch = { tier: 'nice', min_media_condition: 'VG+', max_price_cents: 3000 };
            await window.apiClient.setDiggerPriority('token', 99, patch);
            expect(JSON.parse(capturedOptions.body)).toEqual(patch);
        });

        it('should build URL with integer releaseId', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });

            await window.apiClient.setDiggerPriority('token', 67890, {});
            expect(capturedUrl).toBe('/api/digger/wantlist/67890/priority');
        });

        it('should return { ok:true, status:204, body:null } on 204 No Content', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                status: 204,
                json: async () => { throw new Error('no body'); },
            }));

            const result = await window.apiClient.setDiggerPriority('token', 1, { tier: 'eventually' });
            expect(result.ok).toBe(true);
            expect(result.status).toBe(204);
            expect(result.body).toBeNull();
        });

        it('should return { ok:false, status:404, body } when release not in wantlist', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 404,
                json: async () => ({ detail: 'Release not in wantlist' }),
            }));

            const result = await window.apiClient.setDiggerPriority('token', 9999, { tier: 'must' });
            expect(result.ok).toBe(false);
            expect(result.status).toBe(404);
            expect(result.body).toEqual({ detail: 'Release not in wantlist' });
        });
    });

    describe('bulkSetDiggerTier', () => {
        it('should POST /api/digger/wantlist/bulk-tier with Authorization and Content-Type headers', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ updated: 3 }) };
            });

            await window.apiClient.bulkSetDiggerTier('my-token', [1, 2, 3], 'must');
            expect(capturedUrl).toBe('/api/digger/wantlist/bulk-tier');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
        });

        it('should serialize release_ids and tier as JSON body', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ updated: 2 }) };
            });

            await window.apiClient.bulkSetDiggerTier('token', [111, 222], 'nice');
            expect(JSON.parse(capturedOptions.body)).toEqual({ release_ids: [111, 222], tier: 'nice' });
        });

        it('should return { ok:true, status:200, body } with updated count on success', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: true,
                status: 200,
                json: async () => ({ updated: 5 }),
            }));

            const result = await window.apiClient.bulkSetDiggerTier('token', [1, 2, 3, 4, 5], 'eventually');
            expect(result.ok).toBe(true);
            expect(result.status).toBe(200);
            expect(result.body).toEqual({ updated: 5 });
            expect(result.body.updated).toBe(5);
        });

        it('should return { ok:false, status:422, body } on validation error', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 422,
                json: async () => ({ detail: 'Invalid tier' }),
            }));

            const result = await window.apiClient.bulkSetDiggerTier('token', [1], 'bad-tier');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(422);
            expect(result.body).toEqual({ detail: 'Invalid tier' });
        });

        it('should return body:null when json() throws', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false,
                status: 500,
                json: async () => { throw new Error('no body'); },
            }));

            const result = await window.apiClient.bulkSetDiggerTier('token', [], 'must');
            expect(result.body).toBeNull();
        });
    });

    describe('getDiggerReports', () => {
        it('should GET /api/digger/reports with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ items: [] }) };
            });

            await window.apiClient.getDiggerReports('my-token');
            expect(capturedUrl).toBe('/api/digger/reports');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });

        it('should return { ok:true, status:200, body } with items array on success', async () => {
            const data = {
                items: [
                    {
                        report_id: 'r1',
                        kind: 'scheduled',
                        generated_at: '2026-05-15T00:00:00Z',
                        read_at: null,
                        title: 'Weekly dig',
                        summary: { wantlist_size: 5 },
                        change_flag: 'significant',
                    },
                ],
            };
            vi.stubGlobal('fetch', async () => ({ ok: true, status: 200, json: async () => data }));

            const result = await window.apiClient.getDiggerReports('token');
            expect(result.ok).toBe(true);
            expect(result.status).toBe(200);
            expect(result.body).toEqual(data);
        });

        it('should return { ok:false, status:401, body } on unauthorized', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 401, json: async () => ({ detail: 'Unauthorized' }) }));

            const result = await window.apiClient.getDiggerReports('bad-token');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(401);
            expect(result.body).toEqual({ detail: 'Unauthorized' });
        });

        it('should return body:null when json() throws', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 503, json: async () => { throw new Error('no body'); } }));

            const result = await window.apiClient.getDiggerReports('token');
            expect(result.body).toBeNull();
        });
    });

    describe('getDiggerReport', () => {
        it('should GET /api/digger/reports/{id} with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 200, json: async () => ({ report_id: 'abc' }) };
            });

            await window.apiClient.getDiggerReport('my-token', 'abc');
            expect(capturedUrl).toBe('/api/digger/reports/abc');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });

        it('should URL-encode the report id', async () => {
            let capturedUrl;
            vi.stubGlobal('fetch', async (url) => {
                capturedUrl = url;
                return { ok: true, status: 200, json: async () => ({}) };
            });

            await window.apiClient.getDiggerReport('token', 'a/b c');
            expect(capturedUrl).toBe('/api/digger/reports/a%2Fb%20c');
        });

        it('should return { ok:true, status:200, body } with the full report on success', async () => {
            const report = {
                report_id: 'abc',
                title: 'Test report',
                summary: { wantlist_size: 5 },
                bundles: [{ name: 'cheapest' }],
                watching: [42],
                shipping_confidence: 'high',
                generated_at: '2026-05-15T00:00:00Z',
            };
            vi.stubGlobal('fetch', async () => ({ ok: true, status: 200, json: async () => report }));

            const result = await window.apiClient.getDiggerReport('token', 'abc');
            expect(result.ok).toBe(true);
            expect(result.body).toEqual(report);
        });

        it('should return { ok:false, status:404, body } when the report is missing', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 404, json: async () => ({ detail: 'report not found' }) }));

            const result = await window.apiClient.getDiggerReport('token', 'nope');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(404);
        });
    });

    describe('markDiggerReportRead', () => {
        it('should POST /api/digger/reports/{id}/read with Authorization header', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
            });

            await window.apiClient.markDiggerReportRead('my-token', 'abc');
            expect(capturedUrl).toBe('/api/digger/reports/abc/read');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
        });

        it('should return { ok:true, status:204, body:null } on 204 No Content', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, status: 204, json: async () => { throw new Error('no body'); } }));

            const result = await window.apiClient.markDiggerReportRead('token', 'abc');
            expect(result.ok).toBe(true);
            expect(result.status).toBe(204);
            expect(result.body).toBeNull();
        });

        it('should return { ok:false, status:404 } when already read or missing', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 404, json: async () => ({ detail: 'already read' }) }));

            const result = await window.apiClient.markDiggerReportRead('token', 'abc');
            expect(result.ok).toBe(false);
            expect(result.status).toBe(404);
        });
    });

    describe('runDiggerRecommend SSE streaming', () => {
        function makeReadableStream(chunks) {
            let index = 0;
            return {
                getReader() {
                    return {
                        read() {
                            if (index < chunks.length) {
                                const chunk = chunks[index++];
                                return Promise.resolve({ done: false, value: new TextEncoder().encode(chunk) });
                            }
                            return Promise.resolve({ done: true, value: undefined });
                        },
                    };
                },
            };
        }

        it('should POST /api/digger/recommend with auth + event-stream headers', async () => {
            let capturedUrl, capturedOptions;
            vi.stubGlobal('fetch', async (url, options) => {
                capturedUrl = url;
                capturedOptions = options;
                return { ok: true, body: makeReadableStream([]) };
            });

            window.apiClient.runDiggerRecommend('my-token', {}, {});
            await new Promise((r) => setTimeout(r, 30));

            expect(capturedUrl).toBe('/api/digger/recommend');
            expect(capturedOptions.method).toBe('POST');
            expect(capturedOptions.headers['Authorization']).toBe('Bearer my-token');
            expect(capturedOptions.headers['Accept']).toBe('text/event-stream');
            expect(capturedOptions.headers['Content-Type']).toBe('application/json');
        });

        it('should serialize deadline, budget, and excluded sellers in the body', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, body: makeReadableStream([]) };
            });

            window.apiClient.runDiggerRecommend('token', { deadline_seconds: 15, budget_cap_cents: 5000, excluded_sellers: [7] }, {});
            await new Promise((r) => setTimeout(r, 30));

            expect(JSON.parse(capturedOptions.body)).toEqual({ deadline_seconds: 15, budget_cap_cents: 5000, excluded_sellers: [7] });
        });

        it('should default deadline and excluded sellers when omitted', async () => {
            let capturedOptions;
            vi.stubGlobal('fetch', async (_url, options) => {
                capturedOptions = options;
                return { ok: true, body: makeReadableStream([]) };
            });

            window.apiClient.runDiggerRecommend('token', {}, {});
            await new Promise((r) => setTimeout(r, 30));

            const parsed = JSON.parse(capturedOptions.body);
            expect(parsed.deadline_seconds).toBe(30);
            expect(parsed.excluded_sellers).toEqual([]);
        });

        it('should invoke onRefreshStarted with the parsed event data', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, body: makeReadableStream(['event: refresh_started\ndata: {"stale_count":3}\n\n']) }));

            const onRefreshStarted = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onRefreshStarted });
            await new Promise((r) => setTimeout(r, 50));

            expect(onRefreshStarted).toHaveBeenCalledWith({ stale_count: 3 });
        });

        it('should invoke onRefreshProgress with the parsed event data', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, body: makeReadableStream(['event: refresh_progress\ndata: {"remaining":2,"status":"done"}\n\n']) }));

            const onRefreshProgress = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onRefreshProgress });
            await new Promise((r) => setTimeout(r, 50));

            expect(onRefreshProgress).toHaveBeenCalledWith({ remaining: 2, status: 'done' });
        });

        it('should invoke onResult with the optimizer output', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, body: makeReadableStream(['event: result\ndata: {"bundles":[],"watching":[1]}\n\n']) }));

            const onResult = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onResult });
            await new Promise((r) => setTimeout(r, 50));

            expect(onResult).toHaveBeenCalledWith({ bundles: [], watching: [1] });
        });

        it('should invoke onDone on the done event', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, body: makeReadableStream(['event: done\ndata: {}\n\n']) }));

            const onDone = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onDone });
            await new Promise((r) => setTimeout(r, 50));

            expect(onDone).toHaveBeenCalled();
        });

        it('should invoke onError with the parsed error event payload', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, body: makeReadableStream(['event: error\ndata: {"reason":"digger not enabled"}\n\n']) }));

            const onError = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onError });
            await new Promise((r) => setTimeout(r, 50));

            expect(onError).toHaveBeenCalledWith({ reason: 'digger not enabled' });
        });

        it('should invoke onError with the status when the response is not ok', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 503 }));

            const onError = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onError });
            await new Promise((r) => setTimeout(r, 50));

            expect(onError).toHaveBeenCalled();
            expect(onError.mock.calls[0][0]).toMatchObject({ status: 503 });
        });

        it('should invoke onError when the reader rejects mid-stream', async () => {
            let readCount = 0;
            const stream = {
                getReader() {
                    return {
                        read() {
                            readCount++;
                            if (readCount === 1) {
                                return Promise.resolve({ done: false, value: new TextEncoder().encode('event: refresh_started\ndata: {"stale_count":1}\n\n') });
                            }
                            return Promise.reject(new Error('stream aborted'));
                        },
                    };
                },
            };
            vi.stubGlobal('fetch', async () => ({ ok: true, body: stream }));

            const onError = vi.fn();
            window.apiClient.runDiggerRecommend('token', {}, { onError });
            await new Promise((r) => setTimeout(r, 50));

            expect(onError).toHaveBeenCalled();
            expect(onError.mock.calls[0][0].message).toBe('stream aborted');
        });
    });

    describe('listAppTokens', () => {
        it('returns parsed body on 200', async () => {
            const expected = { active: [{ id: 'a' }], revoked: [] };
            vi.stubGlobal('fetch', createMockFetch({ '/api/user/app-tokens': { data: expected } }));
            const result = await window.apiClient.listAppTokens('jwt-tok');
            expect(result).toEqual(expected);
        });

        it('returns null when token is falsy', async () => {
            const result = await window.apiClient.listAppTokens(null);
            expect(result).toBeNull();
        });

        it('returns null on non-2xx', async () => {
            vi.stubGlobal('fetch', createMockFetch({ '/api/user/app-tokens': { status: 401 } }));
            const result = await window.apiClient.listAppTokens('jwt-tok');
            expect(result).toBeNull();
        });

        it('sends Authorization header', async () => {
            const fetchSpy = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ active: [], revoked: [] }) }));
            vi.stubGlobal('fetch', fetchSpy);
            await window.apiClient.listAppTokens('jwt-tok');
            expect(fetchSpy.mock.calls[0][0]).toContain('/api/user/app-tokens');
            expect(fetchSpy.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-tok');
        });
    });

    describe('mintAppToken', () => {
        it('returns wrapped {ok, status, body} on 201', async () => {
            const body = { id: 'tok-1', name: 'kiosk', scopes: ['collection:read'], token: 'dscg_secret', created_at: '2026-05-26T00:00:00Z' };
            vi.stubGlobal('fetch', createMockFetch({ '/api/user/app-tokens': { status: 201, data: body } }));
            const result = await window.apiClient.mintAppToken('jwt-tok', 'kiosk', ['collection:read']);
            expect(result.ok).toBe(true);
            expect(result.status).toBe(201);
            expect(result.body).toEqual(body);
        });

        it('returns {ok:false, status:0, body:null} when token is falsy', async () => {
            const result = await window.apiClient.mintAppToken('', 'kiosk', ['collection:read']);
            expect(result).toEqual({ ok: false, status: 0, body: null });
        });

        it('returns wrapped error body on 4xx', async () => {
            const body = { detail: 'Unknown scope(s): foo' };
            vi.stubGlobal('fetch', createMockFetch({ '/api/user/app-tokens': { status: 400, data: body } }));
            const result = await window.apiClient.mintAppToken('jwt-tok', 'kiosk', ['foo']);
            expect(result.ok).toBe(false);
            expect(result.status).toBe(400);
            expect(result.body).toEqual(body);
        });

        it('sets body to null and still returns wrapper when JSON parsing throws', async () => {
            vi.stubGlobal('fetch', async () => ({
                ok: false, status: 500,
                json: async () => { throw new Error('bad json'); },
            }));
            const result = await window.apiClient.mintAppToken('jwt-tok', 'kiosk', ['collection:read']);
            expect(result.ok).toBe(false);
            expect(result.status).toBe(500);
            expect(result.body).toBeNull();
        });

        it('sends JSON body and Authorization header', async () => {
            const fetchSpy = vi.fn(async () => ({ ok: true, status: 201, json: async () => ({}) }));
            vi.stubGlobal('fetch', fetchSpy);
            await window.apiClient.mintAppToken('jwt-tok', 'GRUVAX kiosk', ['collection:read']);
            const [, opts] = fetchSpy.mock.calls[0];
            expect(opts.method).toBe('POST');
            expect(opts.headers.Authorization).toBe('Bearer jwt-tok');
            expect(opts.headers['Content-Type']).toBe('application/json');
            expect(JSON.parse(opts.body)).toEqual({ name: 'GRUVAX kiosk', scopes: ['collection:read'] });
        });
    });

    describe('revokeAppToken', () => {
        it('returns true on 204', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: true, status: 204, json: async () => ({}) }));
            const result = await window.apiClient.revokeAppToken('jwt-tok', 'tok-1');
            expect(result).toBe(true);
        });

        it('returns false on 404', async () => {
            vi.stubGlobal('fetch', async () => ({ ok: false, status: 404, json: async () => ({}) }));
            const result = await window.apiClient.revokeAppToken('jwt-tok', 'tok-1');
            expect(result).toBe(false);
        });

        it('returns false when token is falsy', async () => {
            const result = await window.apiClient.revokeAppToken(null, 'tok-1');
            expect(result).toBe(false);
        });

        it('returns false when tokenId is falsy', async () => {
            const result = await window.apiClient.revokeAppToken('jwt-tok', '');
            expect(result).toBe(false);
        });

        it('uri-encodes the tokenId path segment', async () => {
            const fetchSpy = vi.fn(async () => ({ ok: true, status: 204 }));
            vi.stubGlobal('fetch', fetchSpy);
            await window.apiClient.revokeAppToken('jwt-tok', 'has space & slash/?');
            expect(fetchSpy.mock.calls[0][0]).toContain('has%20space%20%26%20slash%2F%3F');
            expect(fetchSpy.mock.calls[0][1].method).toBe('DELETE');
        });
    });
});
