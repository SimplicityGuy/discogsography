"""Tests for the MCP server tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_neo4j():
    """Mock AsyncResilientNeo4jDriver."""
    driver = AsyncMock()
    return driver


@pytest.fixture()
def mock_pg():
    """Mock AsyncPostgreSQLPool."""
    pool = AsyncMock()
    return pool


@pytest.fixture()
def app_ctx(mock_neo4j, mock_pg):
    """Create an AppContext with mocked drivers."""
    from mcp_server.server import AppContext

    return AppContext(neo4j=mock_neo4j, pg=mock_pg)


@pytest.fixture()
def mock_context(app_ctx):
    """Create a mock MCP Context whose lifespan_context is our AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


# ---------------------------------------------------------------------------
# Tool: search
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_context, mock_pg):
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

        with patch("mcp_server.server.execute_search", new_callable=AsyncMock, return_value=fake_response) as mock_exec:
            result = await search(query="miles", ctx=mock_context)

        assert result["total"] == 1
        assert result["results"][0]["name"] == "Miles Davis"
        mock_exec.assert_called_once()
        call_kwargs = mock_exec.call_args
        assert call_kwargs.kwargs["q"] == "miles"
        assert call_kwargs.kwargs["pool"] is mock_pg

    @pytest.mark.asyncio
    async def test_search_invalid_type(self, mock_context):
        from mcp_server.server import search

        result = await search(query="test", types="invalid", ctx=mock_context)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_clamps_limit(self, mock_context):
        from mcp_server.server import search

        with patch("mcp_server.server.execute_search", new_callable=AsyncMock, return_value={"total": 0, "results": []}) as mock_exec:
            await search(query="test", limit=999, ctx=mock_context)

        assert mock_exec.call_args.kwargs["limit"] == 100


# ---------------------------------------------------------------------------
# Tools: entity details
# ---------------------------------------------------------------------------


class TestGetArtistDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context):
        from mcp_server.server import get_artist_details

        fake = {"id": "1", "name": "Miles Davis", "genres": ["Jazz"], "styles": ["Modal"], "release_count": 500, "groups": []}
        with patch("mcp_server.server._get_artist", new_callable=AsyncMock, return_value=fake):
            result = await get_artist_details(artist_id="1", ctx=mock_context)

        assert result["name"] == "Miles Davis"
        assert result["genres"] == ["Jazz"]

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context):
        from mcp_server.server import get_artist_details

        with patch("mcp_server.server._get_artist", new_callable=AsyncMock, return_value=None):
            result = await get_artist_details(artist_id="999", ctx=mock_context)

        assert "error" in result


class TestGetLabelDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context):
        from mcp_server.server import get_label_details

        fake = {"id": "1", "name": "Blue Note", "release_count": 5000}
        with patch("mcp_server.server._get_label", new_callable=AsyncMock, return_value=fake):
            result = await get_label_details(label_id="1", ctx=mock_context)

        assert result["name"] == "Blue Note"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context):
        from mcp_server.server import get_label_details

        with patch("mcp_server.server._get_label", new_callable=AsyncMock, return_value=None):
            result = await get_label_details(label_id="999", ctx=mock_context)

        assert "error" in result


class TestGetReleaseDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context):
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
        with patch("mcp_server.server._get_release", new_callable=AsyncMock, return_value=fake):
            result = await get_release_details(release_id="1", ctx=mock_context)

        assert result["name"] == "Kind of Blue"
        assert result["year"] == 1959

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context):
        from mcp_server.server import get_release_details

        with patch("mcp_server.server._get_release", new_callable=AsyncMock, return_value=None):
            result = await get_release_details(release_id="999", ctx=mock_context)

        assert "error" in result


class TestGetGenreDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context):
        from mcp_server.server import get_genre_details

        fake = {"id": "Jazz", "name": "Jazz", "artist_count": 50000}
        with patch("mcp_server.server._get_genre", new_callable=AsyncMock, return_value=fake):
            result = await get_genre_details(genre_name="Jazz", ctx=mock_context)

        assert result["name"] == "Jazz"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context):
        from mcp_server.server import get_genre_details

        with patch("mcp_server.server._get_genre", new_callable=AsyncMock, return_value=None):
            result = await get_genre_details(genre_name="Nonexistent", ctx=mock_context)

        assert "error" in result


class TestGetStyleDetails:
    @pytest.mark.asyncio
    async def test_found(self, mock_context):
        from mcp_server.server import get_style_details

        fake = {"id": "Acid Jazz", "name": "Acid Jazz", "artist_count": 2000}
        with patch("mcp_server.server._get_style", new_callable=AsyncMock, return_value=fake):
            result = await get_style_details(style_name="Acid Jazz", ctx=mock_context)

        assert result["name"] == "Acid Jazz"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_context):
        from mcp_server.server import get_style_details

        with patch("mcp_server.server._get_style", new_callable=AsyncMock, return_value=None):
            result = await get_style_details(style_name="Nonexistent", ctx=mock_context)

        assert "error" in result


# ---------------------------------------------------------------------------
# Tool: find_path
# ---------------------------------------------------------------------------


class TestFindPath:
    @pytest.mark.asyncio
    async def test_path_found(self, mock_context):
        from mcp_server.server import find_path

        fake_from = {"id": "1", "name": "Miles Davis"}
        fake_to = {"id": "2", "name": "Daft Punk"}
        fake_path = {
            "nodes": [
                {"id": "1", "name": "Miles Davis", "labels": ["Artist"]},
                {"id": "201", "name": "Kind of Blue", "labels": ["Release"]},
                {"id": "2", "name": "Daft Punk", "labels": ["Artist"]},
            ],
            "rels": ["BY", "BY"],
        }

        explore_mock = AsyncMock(side_effect=[fake_from, fake_to])
        dispatch = {"artist": explore_mock, "genre": AsyncMock(), "label": AsyncMock(), "style": AsyncMock()}

        with (
            patch("mcp_server.server.EXPLORE_DISPATCH", dispatch),
            patch("mcp_server.server.find_shortest_path", new_callable=AsyncMock, return_value=fake_path),
        ):
            result = await find_path(from_name="Miles Davis", from_type="artist", to_name="Daft Punk", to_type="artist", ctx=mock_context)

        assert result["found"] is True
        assert result["length"] == 2
        assert len(result["path"]) == 3
        assert result["path"][0]["name"] == "Miles Davis"
        assert result["path"][0]["rel"] is None
        assert result["path"][1]["rel"] == "BY"

    @pytest.mark.asyncio
    async def test_path_not_found(self, mock_context):
        from mcp_server.server import find_path

        fake_from = {"id": "1", "name": "A"}
        fake_to = {"id": "2", "name": "B"}

        explore_mock = AsyncMock(side_effect=[fake_from, fake_to])
        dispatch = {"artist": explore_mock, "genre": AsyncMock(), "label": AsyncMock(), "style": AsyncMock()}

        with (
            patch("mcp_server.server.EXPLORE_DISPATCH", dispatch),
            patch("mcp_server.server.find_shortest_path", new_callable=AsyncMock, return_value=None),
        ):
            result = await find_path(from_name="A", from_type="artist", to_name="B", to_type="artist", ctx=mock_context)

        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_invalid_from_type(self, mock_context):
        from mcp_server.server import find_path

        result = await find_path(from_name="X", from_type="invalid", to_name="Y", to_type="artist", ctx=mock_context)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_entity_not_found(self, mock_context):
        from mcp_server.server import find_path

        explore_mock = AsyncMock(return_value=None)
        dispatch = {"artist": explore_mock, "genre": AsyncMock(), "label": AsyncMock(), "style": AsyncMock()}

        with patch("mcp_server.server.EXPLORE_DISPATCH", dispatch):
            result = await find_path(from_name="Nobody", from_type="artist", to_name="Y", to_type="artist", ctx=mock_context)

        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tool: get_trends
# ---------------------------------------------------------------------------


class TestGetTrends:
    @pytest.mark.asyncio
    async def test_returns_data(self, mock_context):
        from mcp_server.server import get_trends

        fake_data = [{"year": 1959, "count": 3}, {"year": 1960, "count": 5}]

        trends_mock = AsyncMock(return_value=fake_data)
        dispatch = {"artist": trends_mock, "genre": AsyncMock(), "label": AsyncMock(), "style": AsyncMock()}

        with patch("mcp_server.server.TRENDS_DISPATCH", dispatch):
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
    async def test_returns_counts(self, mock_context, mock_neo4j):
        from mcp_server.server import get_graph_stats

        # Mock the Neo4j session and result
        mock_session = AsyncMock()

        mock_records = [
            {"label": "artists", "cnt": 1000},
            {"label": "labels", "cnt": 500},
            {"label": "releases", "cnt": 5000},
            {"label": "masters", "cnt": 2000},
            {"label": "genres", "cnt": 15},
            {"label": "styles", "cnt": 300},
        ]

        # Create async iterator for records
        async def async_iter():
            for r in mock_records:
                yield r

        mock_result = MagicMock()
        mock_result.__aiter__ = lambda _self: async_iter()

        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_neo4j.session = AsyncMock(return_value=mock_session)

        result = await get_graph_stats(ctx=mock_context)

        assert result["total_entities"] == 8815
        assert result["counts"]["artists"] == 1000
        assert result["counts"]["releases"] == 5000
        assert result["counts"]["genres"] == 15


# ---------------------------------------------------------------------------
# _graph_stats direct test
# ---------------------------------------------------------------------------


class TestGraphStatsQuery:
    @pytest.mark.asyncio
    async def test_graph_stats_query(self, mock_neo4j):
        from mcp_server.server import _graph_stats

        mock_session = AsyncMock()
        mock_records = [
            {"label": "artists", "cnt": 100},
            {"label": "labels", "cnt": 50},
        ]

        async def async_iter():
            for r in mock_records:
                yield r

        mock_result = MagicMock()
        mock_result.__aiter__ = lambda _self: async_iter()

        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_neo4j.session = AsyncMock(return_value=mock_session)

        result = await _graph_stats(mock_neo4j)

        assert result == {"artists": 100, "labels": 50}
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert "Artist" in cypher
        assert "Label" in cypher


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
