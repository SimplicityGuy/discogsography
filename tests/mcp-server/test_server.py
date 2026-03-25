"""Tests for the MCP server tools.

All tools now call the Discogsography API via httpx instead of
accessing databases directly. Tests mock httpx responses.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_ctx():
    """Create an AppContext with a mocked httpx client."""
    from mcp_server.server import AppContext

    client = MagicMock(spec=httpx.AsyncClient)
    return AppContext(client=client, base_url="http://test-api:8004")


@pytest.fixture()
def mock_context(app_ctx):
    """Create a mock MCP Context whose lifespan_context is our AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


def _mock_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    """Build a mock httpx.Response with the given JSON body."""
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    resp.status_code = status_code
    return resp


# ---------------------------------------------------------------------------
# Tool: search
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_context, app_ctx):
        from mcp_server.server import search

        fake_response = {
            "query": "miles",
            "total": 1,
            "facets": {"type": {"artist": 1}, "genre": {}, "decade": {}},
            "results": [
                {"type": "artist", "id": "23755", "name": "Miles Davis", "highlight": "<b>Miles</b> Davis", "relevance": 0.9, "metadata": {}}
            ],
            "pagination": {"limit": 20, "offset": 0, "has_more": False},
        }

        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await search(query="miles", ctx=mock_context)

        assert result["total"] == 1
        assert result["results"][0]["name"] == "Miles Davis"
        app_ctx.client.get.assert_called_once()
        call_args = app_ctx.client.get.call_args
        assert "/api/search" in call_args.args[0]
        assert call_args.kwargs["params"]["q"] == "miles"

    @pytest.mark.asyncio
    async def test_search_invalid_type(self, mock_context):
        from mcp_server.server import search

        result = await search(query="test", types="invalid", ctx=mock_context)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_clamps_limit(self, mock_context, app_ctx):
        from mcp_server.server import search

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"total": 0, "results": []}))

        await search(query="test", limit=999, ctx=mock_context)

        call_params = app_ctx.client.get.call_args.kwargs["params"]
        assert call_params["limit"] == 100


# ---------------------------------------------------------------------------
# Tools: entity details
# ---------------------------------------------------------------------------


class TestGetArtistDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context, app_ctx):
        from mcp_server.server import get_artist_details

        fake = {"id": "1", "name": "Miles Davis", "genres": ["Jazz"], "styles": ["Modal"], "release_count": 500, "groups": []}
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake))

        result = await get_artist_details(artist_id="1", ctx=mock_context)

        assert result["name"] == "Miles Davis"
        assert result["genres"] == ["Jazz"]

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context, app_ctx):
        from mcp_server.server import get_artist_details

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "not found"}, status_code=404))

        result = await get_artist_details(artist_id="999", ctx=mock_context)

        assert "error" in result


class TestGetLabelDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context, app_ctx):
        from mcp_server.server import get_label_details

        fake = {"id": "1", "name": "Blue Note", "release_count": 5000}
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake))

        result = await get_label_details(label_id="1", ctx=mock_context)

        assert result["name"] == "Blue Note"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context, app_ctx):
        from mcp_server.server import get_label_details

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "not found"}, status_code=404))

        result = await get_label_details(label_id="999", ctx=mock_context)

        assert "error" in result


class TestGetReleaseDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context, app_ctx):
        from mcp_server.server import get_release_details

        fake = {
            "id": "1",
            "name": "Kind of Blue",
            "year": 1959,
            "artists": ["Miles Davis"],
            "labels": ["Columbia"],
            "genres": ["Jazz"],
            "styles": ["Modal"],
        }
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake))

        result = await get_release_details(release_id="1", ctx=mock_context)

        assert result["name"] == "Kind of Blue"
        assert result["year"] == 1959

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context, app_ctx):
        from mcp_server.server import get_release_details

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "not found"}, status_code=404))

        result = await get_release_details(release_id="999", ctx=mock_context)

        assert "error" in result


class TestGetGenreDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context, app_ctx):
        from mcp_server.server import get_genre_details

        fake = {"id": "Jazz", "name": "Jazz", "artist_count": 50000}
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake))

        result = await get_genre_details(genre_name="Jazz", ctx=mock_context)

        assert result["name"] == "Jazz"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context, app_ctx):
        from mcp_server.server import get_genre_details

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "not found"}, status_code=404))

        result = await get_genre_details(genre_name="Nonexistent", ctx=mock_context)

        assert "error" in result


class TestGetStyleDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context, app_ctx):
        from mcp_server.server import get_style_details

        fake = {"id": "Acid Jazz", "name": "Acid Jazz", "artist_count": 2000}
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake))

        result = await get_style_details(style_name="Acid Jazz", ctx=mock_context)

        assert result["name"] == "Acid Jazz"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context, app_ctx):
        from mcp_server.server import get_style_details

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "not found"}, status_code=404))

        result = await get_style_details(style_name="Nonexistent", ctx=mock_context)

        assert "error" in result


# ---------------------------------------------------------------------------
# Tool: find_path
# ---------------------------------------------------------------------------


class TestFindPath:
    @pytest.mark.asyncio
    async def test_path_found(self, mock_context, app_ctx):
        from mcp_server.server import find_path

        fake_response = {
            "found": True,
            "length": 2,
            "path": [
                {"id": "1", "name": "Miles Davis", "type": "artist", "rel": None},
                {"id": "201", "name": "Kind of Blue", "type": "release", "rel": "BY"},
                {"id": "2", "name": "Daft Punk", "type": "artist", "rel": "BY"},
            ],
        }

        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await find_path(from_name="Miles Davis", from_type="artist", to_name="Daft Punk", to_type="artist", ctx=mock_context)

        assert result["found"] is True
        assert result["length"] == 2
        assert len(result["path"]) == 3
        assert result["path"][0]["name"] == "Miles Davis"
        assert result["path"][0]["rel"] is None
        assert result["path"][1]["rel"] == "BY"

    @pytest.mark.asyncio
    async def test_path_not_found(self, mock_context, app_ctx):
        from mcp_server.server import find_path

        fake_response = {"found": False, "length": None, "path": []}
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await find_path(from_name="A", from_type="artist", to_name="B", to_type="artist", ctx=mock_context)

        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_invalid_from_type(self, mock_context):
        from mcp_server.server import find_path

        result = await find_path(from_name="X", from_type="invalid", to_name="Y", to_type="artist", ctx=mock_context)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_entity_not_found(self, mock_context, app_ctx):
        from mcp_server.server import find_path

        fake_response = {"error": "Artist 'Nobody' not found"}
        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response, status_code=404))

        result = await find_path(from_name="Nobody", from_type="artist", to_name="Y", to_type="artist", ctx=mock_context)

        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tool: get_trends
# ---------------------------------------------------------------------------


class TestGetTrends:
    @pytest.mark.asyncio
    async def test_returns_data(self, mock_context, app_ctx):
        from mcp_server.server import get_trends

        fake_response = {
            "name": "Miles Davis",
            "type": "artist",
            "data": [{"year": 1959, "count": 3}, {"year": 1960, "count": 5}],
        }

        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await get_trends(name="Miles Davis", entity_type="artist", ctx=mock_context)

        assert result["name"] == "Miles Davis"
        assert result["type"] == "artist"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_type(self, mock_context):
        from mcp_server.server import get_trends

        result = await get_trends(name="X", entity_type="invalid", ctx=mock_context)
        assert "error" in result


# ---------------------------------------------------------------------------
# Tool: get_graph_stats
# ---------------------------------------------------------------------------


class TestGetGraphStats:
    @pytest.mark.asyncio
    async def test_returns_counts(self, mock_context, app_ctx):
        from mcp_server.server import get_graph_stats

        fake_response = {
            "total_entities": 8815,
            "counts": {
                "artists": 1000,
                "labels": 500,
                "releases": 5000,
                "masters": 2000,
                "genres": 15,
                "styles": 300,
            },
        }

        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await get_graph_stats(ctx=mock_context)

        assert result["total_entities"] == 8815
        assert result["counts"]["artists"] == 1000
        assert result["counts"]["releases"] == 5000
        assert result["counts"]["genres"] == 15


# ---------------------------------------------------------------------------
# Tool: get_collaborators
# ---------------------------------------------------------------------------


class TestGetCollaborators:
    @pytest.mark.asyncio
    async def test_returns_collaborators(self, mock_context, app_ctx):
        from mcp_server.server import get_collaborators

        fake_response = {
            "artist_id": "1",
            "artist_name": "Miles Davis",
            "collaborators": [
                {"artist_id": "2", "artist_name": "John Coltrane", "release_count": 5},
            ],
            "total": 42,
        }

        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await get_collaborators(artist_id="1", ctx=mock_context)

        assert result["artist_name"] == "Miles Davis"
        assert result["total"] == 42
        assert len(result["collaborators"]) == 1

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context, app_ctx):
        from mcp_server.server import get_collaborators

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"error": "not found"}, status_code=404))

        result = await get_collaborators(artist_id="999", ctx=mock_context)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_clamps_limit(self, mock_context, app_ctx):
        from mcp_server.server import get_collaborators

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"collaborators": [], "total": 0}))

        await get_collaborators(artist_id="1", limit=999, ctx=mock_context)

        call_params = app_ctx.client.get.call_args.kwargs["params"]
        assert call_params["limit"] == 100


# ---------------------------------------------------------------------------
# Tool: get_genre_tree
# ---------------------------------------------------------------------------


class TestGetGenreTree:
    @pytest.mark.asyncio
    async def test_returns_tree(self, mock_context, app_ctx):
        from mcp_server.server import get_genre_tree

        fake_response = {
            "genres": [
                {"name": "Rock", "release_count": 1000, "styles": [{"name": "Punk", "release_count": 200}]},
                {"name": "Jazz", "release_count": 500, "styles": []},
            ],
        }

        app_ctx.client.get = AsyncMock(return_value=_mock_response(fake_response))

        result = await get_genre_tree(ctx=mock_context)

        assert len(result["genres"]) == 2
        assert result["genres"][0]["name"] == "Rock"
        assert result["genres"][0]["styles"][0]["name"] == "Punk"


# ---------------------------------------------------------------------------
# Helper: _api_get
# ---------------------------------------------------------------------------


class TestApiGet:
    @pytest.mark.asyncio
    async def test_api_get_constructs_url(self, app_ctx):
        from mcp_server.server import _api_get

        app_ctx.client.get = AsyncMock(return_value=_mock_response({"ok": True}))

        await _api_get(app_ctx, "/api/test", {"key": "value"})

        app_ctx.client.get.assert_called_once_with(
            "http://test-api:8004/api/test",
            params={"key": "value"},
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_parses_transport(self):
        """Verify main() parses --transport and calls mcp.run()."""
        from mcp_server.server import main

        with patch("mcp_server.server.mcp") as mock_mcp, patch("sys.argv", ["discogsography-mcp", "--transport", "streamable-http"]):
            main()
            mock_mcp.run.assert_called_once_with(transport="streamable-http")

    def test_main_default_stdio(self):
        from mcp_server.server import main

        with patch("mcp_server.server.mcp") as mock_mcp, patch("sys.argv", ["discogsography-mcp"]):
            main()
            mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_main_transport_equals_syntax(self):
        from mcp_server.server import main

        with patch("mcp_server.server.mcp") as mock_mcp, patch("sys.argv", ["discogsography-mcp", "--transport=streamable-http"]):
            main()
            mock_mcp.run.assert_called_once_with(transport="streamable-http")
