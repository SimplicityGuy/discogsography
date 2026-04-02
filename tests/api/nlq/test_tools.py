"""Tests for NLQ tool schemas and NLQToolRunner."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.nlq.tools import (
    NLQToolRunner,
    get_authenticated_tool_schemas,
    get_public_tool_schemas,
)


# ── Schema tests ──────────────────────────────────────────────────────────


EXPECTED_PUBLIC_NAMES = {
    "search",
    "autocomplete",
    "explore_entity",
    "find_path",
    "get_collaborators",
    "get_similar_artists",
    "get_label_dna",
    "get_trends",
    "get_genre_tree",
    "get_graph_stats",
}

EXPECTED_AUTH_NAMES = {
    "get_collection_gaps",
    "get_taste_fingerprint",
    "get_taste_blindspots",
    "get_collection_stats",
}


def test_public_tools_returns_10_schemas() -> None:
    """Public tool schemas should contain exactly 10 tools with correct names."""
    schemas = get_public_tool_schemas()
    assert len(schemas) == 10
    names = {s["name"] for s in schemas}
    assert names == EXPECTED_PUBLIC_NAMES


def test_authenticated_tools_returns_4_schemas() -> None:
    """Authenticated tool schemas should contain exactly 4 tools with correct names."""
    schemas = get_authenticated_tool_schemas()
    assert len(schemas) == 4
    names = {s["name"] for s in schemas}
    assert names == EXPECTED_AUTH_NAMES


def test_all_schemas_have_required_fields() -> None:
    """Every schema must have name, description, and input_schema with type=object."""
    all_schemas = get_public_tool_schemas() + get_authenticated_tool_schemas()
    for schema in all_schemas:
        assert "name" in schema, f"Schema missing 'name': {schema}"
        assert "description" in schema, f"Schema {schema.get('name')} missing 'description'"
        assert "input_schema" in schema, f"Schema {schema['name']} missing 'input_schema'"
        assert schema["input_schema"]["type"] == "object", f"Schema {schema['name']} input_schema type != object"


# ── Runner tests ──────────────────────────────────────────────────────────


@pytest.fixture
def runner(mock_neo4j_driver: MagicMock, mock_pg_pool: MagicMock, mock_redis_client: AsyncMock) -> NLQToolRunner:
    """Create an NLQToolRunner with mocked dependencies."""
    return NLQToolRunner(mock_neo4j_driver, mock_pg_pool, mock_redis_client)


@pytest.mark.asyncio
async def test_execute_search(runner: NLQToolRunner) -> None:
    """Search tool should delegate to execute_search and return the result."""
    fake_result: dict[str, Any] = {
        "query": "radiohead",
        "total": 1,
        "results": [{"type": "artist", "id": "a1", "name": "Radiohead", "highlight": "Radiohead", "relevance": 1.0, "metadata": {}}],
        "facets": {"type": {}, "genre": {}, "decade": {}},
        "pagination": {"limit": 10, "offset": 0, "has_more": False},
    }
    with patch("api.queries.search_queries.execute_search", new_callable=AsyncMock, return_value=fake_result):
        result = await runner.execute("search", {"q": "radiohead"})
    assert result == fake_result


@pytest.mark.asyncio
async def test_execute_autocomplete(runner: NLQToolRunner) -> None:
    """Autocomplete tool should dispatch via AUTOCOMPLETE_DISPATCH and wrap results."""
    ac_items = [{"id": "a1", "name": "Radiohead"}]
    with patch(
        "api.queries.neo4j_queries.AUTOCOMPLETE_DISPATCH",
        {
            "artist": AsyncMock(return_value=ac_items),
            "genre": AsyncMock(),
            "label": AsyncMock(),
            "style": AsyncMock(),
        },
    ):
        result = await runner.execute("autocomplete", {"type": "artist", "query": "radio"})
    assert result["results"] == ac_items


@pytest.mark.asyncio
async def test_execute_explore_entity(runner: NLQToolRunner) -> None:
    """Explore entity tool should delegate to EXPLORE_DISPATCH and return the flat dict."""
    fake_result: dict[str, Any] = {"id": "a1", "name": "Radiohead", "release_count": 42}
    with patch(
        "api.queries.neo4j_queries.EXPLORE_DISPATCH",
        {"artist": AsyncMock(return_value=fake_result)},
    ):
        result = await runner.execute("explore_entity", {"type": "artist", "name": "Radiohead"})
    assert result.get("name") == "Radiohead"
    assert result.get("id") == "a1"
    assert result.get("_entity_type") == "artist"


@pytest.mark.asyncio
async def test_execute_explore_entity_not_found(runner: NLQToolRunner) -> None:
    """Explore entity returns error when entity not found (None result)."""
    with patch(
        "api.queries.neo4j_queries.EXPLORE_DISPATCH",
        {"artist": AsyncMock(return_value=None)},
    ):
        result = await runner.execute("explore_entity", {"type": "artist", "name": "Nobody"})
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_execute_explore_entity_unknown_type(runner: NLQToolRunner) -> None:
    """Explore entity returns error for unknown entity type."""
    with patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", {}):
        result = await runner.execute("explore_entity", {"type": "unknown_type", "name": "X"})
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_find_path(runner: NLQToolRunner) -> None:
    """Find path tool should return nodes and rels."""
    fake_result: dict[str, Any] = {
        "nodes": [{"id": "a1", "name": "Radiohead", "type": "artist"}],
        "rels": ["RELEASED_ON"],
    }
    with patch("api.queries.neo4j_queries.find_shortest_path", new_callable=AsyncMock, return_value=fake_result):
        result = await runner.execute("find_path", {"from_id": "a1", "to_id": "l1"})
    assert "nodes" in result


@pytest.mark.asyncio
async def test_execute_find_path_no_path(runner: NLQToolRunner) -> None:
    """Find path returns error when no path found (None result)."""
    with patch("api.queries.neo4j_queries.find_shortest_path", new_callable=AsyncMock, return_value=None):
        result = await runner.execute("find_path", {"from_id": "a1", "to_id": "l1"})
    assert "error" in result
    assert "No path found" in result["error"]


@pytest.mark.asyncio
async def test_execute_find_path_name_resolution_both(runner: NLQToolRunner) -> None:
    """Find path resolves both from_id and to_id names via EXPLORE_DISPATCH when types are provided."""
    fake_path: dict[str, Any] = {
        "nodes": [{"id": "123", "name": "Radiohead", "type": "artist"}, {"id": "456", "name": "XL", "type": "label"}],
        "rels": ["ON"],
    }
    artist_handler = AsyncMock(return_value={"id": 123, "name": "Radiohead"})
    label_handler = AsyncMock(return_value={"id": 456, "name": "XL Recordings"})
    with (
        patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", {"artist": artist_handler, "label": label_handler}),
        patch("api.queries.neo4j_queries.find_shortest_path", new_callable=AsyncMock, return_value=fake_path) as mock_fsp,
    ):
        result = await runner.execute("find_path", {"from_id": "Radiohead", "from_type": "artist", "to_id": "XL", "to_type": "label"})
    assert "nodes" in result
    # Verify resolved IDs were passed to find_shortest_path
    mock_fsp.assert_awaited_once()
    call_kwargs = mock_fsp.call_args[1]
    assert call_kwargs["from_id"] == "123"
    assert call_kwargs["to_id"] == "456"


@pytest.mark.asyncio
async def test_execute_find_path_name_resolution_from_not_found(runner: NLQToolRunner) -> None:
    """Find path returns error when from_id name cannot be resolved."""
    artist_handler = AsyncMock(return_value=None)
    with patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", {"artist": artist_handler}):
        result = await runner.execute("find_path", {"from_id": "Unknown Artist", "from_type": "artist", "to_id": "456"})
    assert "error" in result
    assert "artist" in result["error"]
    assert "Unknown Artist" in result["error"]


@pytest.mark.asyncio
async def test_execute_find_path_name_resolution_to_not_found(runner: NLQToolRunner) -> None:
    """Find path returns error when to_id name cannot be resolved."""
    artist_handler = AsyncMock(return_value={"id": 123, "name": "Radiohead"})
    label_handler = AsyncMock(return_value=None)
    with patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", {"artist": artist_handler, "label": label_handler}):
        result = await runner.execute("find_path", {"from_id": "Radiohead", "from_type": "artist", "to_id": "No Such Label", "to_type": "label"})
    assert "error" in result
    assert "label" in result["error"]
    assert "No Such Label" in result["error"]


@pytest.mark.asyncio
async def test_execute_find_path_numeric_id_skips_resolution(runner: NLQToolRunner) -> None:
    """Find path skips name resolution when IDs are purely numeric, even if types are provided."""
    fake_path: dict[str, Any] = {"nodes": [{"id": "123", "type": "artist"}], "rels": []}
    with patch("api.queries.neo4j_queries.find_shortest_path", new_callable=AsyncMock, return_value=fake_path) as mock_fsp:
        result = await runner.execute("find_path", {"from_id": "12345", "from_type": "artist", "to_id": "67890", "to_type": "label"})
    assert "nodes" in result
    # IDs should be passed through unchanged — no EXPLORE_DISPATCH called
    call_kwargs = mock_fsp.call_args[1]
    assert call_kwargs["from_id"] == "12345"
    assert call_kwargs["to_id"] == "67890"


@pytest.mark.asyncio
async def test_execute_find_path_name_resolution_only_from(runner: NLQToolRunner) -> None:
    """Find path resolves only from_id when only from_type is provided; to_id passes through."""
    fake_path: dict[str, Any] = {"nodes": [], "rels": []}
    artist_handler = AsyncMock(return_value={"id": 999, "name": "Radiohead"})
    with (
        patch("api.queries.neo4j_queries.EXPLORE_DISPATCH", {"artist": artist_handler}),
        patch("api.queries.neo4j_queries.find_shortest_path", new_callable=AsyncMock, return_value=fake_path) as mock_fsp,
    ):
        await runner.execute("find_path", {"from_id": "Radiohead", "from_type": "artist", "to_id": "l1"})
    call_kwargs = mock_fsp.call_args[1]
    assert call_kwargs["from_id"] == "999"
    assert call_kwargs["to_id"] == "l1"


@pytest.mark.asyncio
async def test_execute_get_collaborators(runner: NLQToolRunner) -> None:
    """Get collaborators tool should return collaborators list."""
    fake_collabs = [{"id": "a2", "name": "Thom Yorke", "shared_releases": 5}]
    with patch("api.queries.collaborator_queries.get_collaborators", new_callable=AsyncMock, return_value=fake_collabs):
        result = await runner.execute("get_collaborators", {"artist_id": "a1"})
    assert result["collaborators"] == fake_collabs


@pytest.mark.asyncio
async def test_execute_get_similar_artists(runner: NLQToolRunner) -> None:
    """Get similar artists tool should gather profile + candidates and rank."""
    fake_profile = {"genres": {"rock": 1.0}}
    fake_candidates = [{"id": "a2", "genres": {"rock": 0.9}}]
    fake_ranked = [{"id": "a2", "name": "Muse", "similarity": 0.95}]
    with (
        patch("api.queries.recommend_queries.get_artist_profile", new_callable=AsyncMock, return_value=fake_profile),
        patch("api.queries.recommend_queries.get_candidate_artists", new_callable=AsyncMock, return_value=fake_candidates),
        patch("api.queries.recommend_queries.compute_similar_artists", return_value=fake_ranked),
    ):
        result = await runner.execute("get_similar_artists", {"artist_id": "a1"})
    assert result["artist_id"] == "a1"
    assert result["similar"] == fake_ranked


@pytest.mark.asyncio
async def test_execute_get_label_dna(runner: NLQToolRunner) -> None:
    """Get label DNA tool should return the label profile."""
    fake_dna: dict[str, Any] = {"label_id": "l1", "genres": {"electronic": 0.8}, "eras": {}}
    with patch("api.queries.label_dna_queries.get_label_full_profile", new_callable=AsyncMock, return_value=fake_dna):
        result = await runner.execute("get_label_dna", {"label_id": "l1"})
    assert result["label_id"] == "l1"


@pytest.mark.asyncio
async def test_execute_get_label_dna_not_found(runner: NLQToolRunner) -> None:
    """Get label DNA returns error when label not found."""
    with patch("api.queries.label_dna_queries.get_label_full_profile", new_callable=AsyncMock, return_value=None):
        result = await runner.execute("get_label_dna", {"label_id": "l999"})
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_get_trends(runner: NLQToolRunner) -> None:
    """Get trends tool should delegate to TRENDS_DISPATCH and wrap results."""
    fake_trends = [{"year": 2020, "count": 5}]
    with patch(
        "api.queries.neo4j_queries.TRENDS_DISPATCH",
        {"artist": AsyncMock(return_value=fake_trends)},
    ):
        result = await runner.execute("get_trends", {"type": "artist", "name": "Radiohead"})
    assert result["trends"] == fake_trends


@pytest.mark.asyncio
async def test_execute_get_trends_unknown_type(runner: NLQToolRunner) -> None:
    """Get trends returns error for unknown entity type."""
    with patch("api.queries.neo4j_queries.TRENDS_DISPATCH", {}):
        result = await runner.execute("get_trends", {"type": "unknown", "name": "X"})
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_get_genre_tree(runner: NLQToolRunner) -> None:
    """Get genre tree tool should return the genre hierarchy."""
    fake_tree = [{"name": "Electronic", "children": ["Techno", "House"]}]
    with patch("api.queries.genre_tree_queries.get_genre_tree", new_callable=AsyncMock, return_value=fake_tree):
        result = await runner.execute("get_genre_tree", {})
    assert result["genres"] == fake_tree


@pytest.mark.asyncio
async def test_execute_get_graph_stats(runner: NLQToolRunner) -> None:
    """Get graph stats tool should return node counts."""
    fake_stats: dict[str, Any] = {"artists": 100, "labels": 50, "releases": 500}
    with patch("api.queries.neo4j_queries.get_graph_stats", new_callable=AsyncMock, return_value=fake_stats):
        result = await runner.execute("get_graph_stats", {})
    assert result["artists"] == 100


@pytest.mark.asyncio
async def test_execute_get_collection_gaps(runner: NLQToolRunner) -> None:
    """Get collection gaps tool (label) should return gaps and total."""
    fake_gaps = [{"id": "r1", "title": "OK Computer"}]
    with patch("api.queries.gap_queries.get_label_gaps", new_callable=AsyncMock, return_value=(fake_gaps, 1)):
        result = await runner.execute("get_collection_gaps", {"entity_type": "label", "entity_id": "l1"}, user_id="u1")
    assert result["gaps"] == fake_gaps
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_execute_get_collection_gaps_artist(runner: NLQToolRunner) -> None:
    """Get collection gaps tool (artist) should delegate to get_artist_gaps."""
    fake_gaps = [{"id": "r2", "title": "In Rainbows"}]
    with patch("api.queries.gap_queries.get_artist_gaps", new_callable=AsyncMock, return_value=(fake_gaps, 1)):
        result = await runner.execute("get_collection_gaps", {"entity_type": "artist", "entity_id": "a1"}, user_id="u1")
    assert result["gaps"] == fake_gaps


@pytest.mark.asyncio
async def test_execute_get_collection_gaps_unknown_type(runner: NLQToolRunner) -> None:
    """Get collection gaps returns error for unknown entity type."""
    result = await runner.execute("get_collection_gaps", {"entity_type": "master", "entity_id": "m1"}, user_id="u1")
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_get_taste_fingerprint(runner: NLQToolRunner) -> None:
    """Get taste fingerprint returns heatmap cells and total."""
    fake_cells = [{"genre": "Rock", "decade": "2000s", "count": 10}]
    with patch("api.queries.taste_queries.get_taste_heatmap", new_callable=AsyncMock, return_value=(fake_cells, 42)):
        result = await runner.execute("get_taste_fingerprint", {}, user_id="u1")
    assert result["heatmap"] == fake_cells
    assert result["total"] == 42


@pytest.mark.asyncio
async def test_execute_get_taste_blindspots(runner: NLQToolRunner) -> None:
    """Get taste blindspots returns blind_spots list."""
    fake_spots = [{"genre": "Jazz", "score": 0.8}]
    with patch("api.queries.taste_queries.get_blind_spots", new_callable=AsyncMock, return_value=fake_spots):
        result = await runner.execute("get_taste_blindspots", {"limit": 3}, user_id="u1")
    assert result["blind_spots"] == fake_spots


@pytest.mark.asyncio
async def test_execute_get_collection_stats(runner: NLQToolRunner) -> None:
    """Get collection stats returns collection_count."""
    with patch("api.queries.taste_queries.get_collection_count", new_callable=AsyncMock, return_value=123):
        result = await runner.execute("get_collection_stats", {}, user_id="u1")
    assert result["collection_count"] == 123


@pytest.mark.asyncio
async def test_execute_tool_exception_returns_error(runner: NLQToolRunner) -> None:
    """When a tool handler raises an exception, execute returns an error dict."""
    with patch("api.queries.search_queries.execute_search", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        result = await runner.execute("search", {"q": "test"})
    assert "error" in result
    assert "failed" in result["error"]


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error(runner: NLQToolRunner) -> None:
    """Unknown tool names should return an error dict."""
    result = await runner.execute("nonexistent_tool", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_auth_tool_without_user_returns_error(runner: NLQToolRunner) -> None:
    """Auth-required tools should return error when user_id is None."""
    result = await runner.execute("get_collection_gaps", {"entity_type": "label", "entity_id": "l1"})
    assert "error" in result
    assert "auth" in result["error"].lower()


# ── Entity extraction tests ──────────────────────────────────────────────


def test_extract_entities_from_search(runner: NLQToolRunner) -> None:
    """Extract entities from search results list."""
    result: dict[str, Any] = {
        "results": [
            {"type": "artist", "id": "a1", "name": "Radiohead", "highlight": "...", "relevance": 1.0},
            {"type": "label", "id": "l1", "name": "XL Recordings", "highlight": "...", "relevance": 0.8},
        ],
    }
    entities = runner.extract_entities("search", result)
    assert len(entities) == 2
    assert entities[0] == {"id": "a1", "name": "Radiohead", "type": "artist"}
    assert entities[1] == {"id": "l1", "name": "XL Recordings", "type": "label"}


def test_extract_entities_from_autocomplete(runner: NLQToolRunner) -> None:
    """Extract entities from autocomplete results."""
    result: dict[str, Any] = {
        "results": [
            {"id": "a1", "name": "Radiohead"},
            {"id": "a2", "name": "Radioactive Man"},
        ],
    }
    entities = runner.extract_entities("autocomplete", result)
    assert len(entities) == 2
    assert entities[0]["name"] == "Radiohead"


def test_extract_entities_from_explore(runner: NLQToolRunner) -> None:
    """Extract entities from explore_entity results (flat dict from explore handlers)."""
    result: dict[str, Any] = {"id": "a1", "name": "Radiohead", "release_count": 42, "_entity_type": "artist"}
    entities = runner.extract_entities("explore_entity", result)
    assert len(entities) == 1
    assert entities[0] == {"id": "a1", "name": "Radiohead", "type": "artist"}


def test_extract_entities_from_path(runner: NLQToolRunner) -> None:
    """Extract entities from find_path results (nodes list)."""
    result: dict[str, Any] = {
        "nodes": [
            {"id": "a1", "name": "Radiohead", "type": "artist"},
            {"id": "l1", "name": "XL Recordings", "type": "label"},
        ],
        "rels": ["ON"],
    }
    entities = runner.extract_entities("find_path", result)
    assert len(entities) == 2


def test_extract_entities_autocomplete_with_type_key(runner: NLQToolRunner) -> None:
    """Autocomplete items that include a 'type' key should use it."""
    result: dict[str, Any] = {
        "results": [
            {"id": "a1", "name": "Radiohead", "type": "artist"},
        ],
    }
    entities = runner.extract_entities("autocomplete", result)
    assert len(entities) == 1
    assert entities[0]["type"] == "artist"


def test_extract_entities_returns_empty_on_error(runner: NLQToolRunner) -> None:
    """Error results should produce an empty entity list."""
    result: dict[str, Any] = {"error": "Something went wrong"}
    entities = runner.extract_entities("search", result)
    assert entities == []


@pytest.mark.asyncio
async def test_autocomplete_unknown_type(runner: NLQToolRunner) -> None:
    """Autocomplete with invalid entity type returns error."""
    result = await runner.execute("autocomplete", {"type": "invalid_type", "query": "test"})
    assert "error" in result
