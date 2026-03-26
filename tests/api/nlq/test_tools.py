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
    """Extract entities from explore_entity results (center node)."""
    result: dict[str, Any] = {
        "center": {"id": "a1", "name": "Radiohead", "type": "artist"},
        "connections": [],
    }
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


def test_extract_entities_returns_empty_on_error(runner: NLQToolRunner) -> None:
    """Error results should produce an empty entity list."""
    result: dict[str, Any] = {"error": "Something went wrong"}
    entities = runner.extract_entities("search", result)
    assert entities == []
