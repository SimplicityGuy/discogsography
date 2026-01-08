"""Tests for graph endpoint cursor-based pagination."""

from unittest.mock import AsyncMock

import pytest

from discovery.pagination import encode_cursor


def create_mock_graph_results(offset: int = 0, limit: int = 50, total_nodes: int = 100) -> dict:  # type: ignore[type-arg]
    """Helper to create paginated mock graph results."""
    from discovery.pagination import OffsetPagination

    # Simulate a graph with total_nodes nodes
    all_nodes = [
        {
            "id": f"node_{i}",
            "name": f"Node {i}",
            "type": "artist",
            "properties": {"created": "2020-01-01"},
        }
        for i in range(total_nodes)
    ]

    # Get the appropriate slice
    nodes = all_nodes[offset : offset + limit]

    # Create links between consecutive nodes
    links = []
    for i in range(len(nodes) - 1):
        links.append(
            {
                "source": nodes[i]["id"],
                "target": nodes[i + 1]["id"],
                "type": "collaborates_with",
                "properties": {},
            }
        )

    # Determine if there are more results
    has_more = offset + len(nodes) < total_nodes
    next_cursor = None
    if has_more:
        next_cursor = OffsetPagination.create_next_cursor(offset, limit)

    return {
        "nodes": nodes,
        "links": links,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "page_info": {"node_id": "artist_1", "depth": 2, "offset": offset, "limit": limit},
    }


@pytest.mark.asyncio
async def test_graph_first_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test first page of graph results without cursor."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_graph_results(offset=0, limit=50)
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/graph?node_id=artist_1&depth=2&limit=50")

    assert response.status_code == 200
    data = response.json()

    # Check paginated response structure
    assert "nodes" in data
    assert "links" in data
    assert "has_more" in data
    assert "next_cursor" in data
    assert "page_info" in data

    # Check data
    assert len(data["nodes"]) == 50
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_graph_second_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test second page of graph results with cursor."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 50})
    mock_result = create_mock_graph_results(offset=50, limit=50)
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/graph?node_id=artist_1&depth=2&limit=50&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check nodes are from second page
    assert len(data["nodes"]) == 50
    assert data["nodes"][0]["id"] == "node_50"
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert data["page_info"]["offset"] == 50


@pytest.mark.asyncio
async def test_graph_empty_results(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test graph with no connected nodes."""
    from discovery.playground_api import playground_api

    empty_result = {
        "nodes": [],
        "links": [],
        "has_more": False,
        "next_cursor": None,
        "page_info": {"node_id": "isolated_node", "depth": 2, "offset": 0, "limit": 50},
    }
    playground_api.get_graph_data = AsyncMock(return_value=empty_result)

    response = discovery_client.get("/api/graph?node_id=isolated_node&depth=2&limit=50")

    assert response.status_code == 200
    data = response.json()

    # Check empty results
    assert len(data["nodes"]) == 0
    assert len(data["links"]) == 0
    assert data["has_more"] is False
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_graph_invalid_cursor(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test graph with invalid cursor falls back to first page."""
    from discovery.playground_api import playground_api

    invalid_cursor = "invalid_base64!@#"
    mock_result = create_mock_graph_results(offset=0, limit=50)
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/graph?node_id=artist_1&depth=2&limit=50&cursor={invalid_cursor}")

    assert response.status_code == 200
    data = response.json()

    # Should fall back to first page (offset 0)
    assert data["page_info"]["offset"] == 0
    assert len(data["nodes"]) == 50


@pytest.mark.asyncio
async def test_graph_pagination_with_different_limits(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test pagination with different page sizes."""
    from discovery.playground_api import playground_api

    # First page with limit=20
    playground_api.get_graph_data = AsyncMock(return_value=create_mock_graph_results(offset=0, limit=20))
    response = discovery_client.get("/api/graph?node_id=artist_1&depth=2&limit=20")
    assert response.status_code == 200
    data = response.json()

    assert len(data["nodes"]) == 20
    assert data["has_more"] is True

    # Second page
    cursor = data["next_cursor"]
    playground_api.get_graph_data = AsyncMock(return_value=create_mock_graph_results(offset=20, limit=20))
    response = discovery_client.get(f"/api/graph?node_id=artist_1&depth=2&limit=20&cursor={cursor}")
    assert response.status_code == 200
    data = response.json()

    assert len(data["nodes"]) == 20
    assert data["nodes"][0]["id"] == "node_20"


@pytest.mark.asyncio
async def test_graph_pagination_preserves_params(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that pagination preserves query parameters in page_info."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_graph_results(offset=0, limit=50)
    mock_result["page_info"]["node_id"] = "specific_artist"
    mock_result["page_info"]["depth"] = 3
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/graph?node_id=specific_artist&depth=3&limit=50")

    assert response.status_code == 200
    data = response.json()

    # Check page_info contains query parameters
    assert data["page_info"]["node_id"] == "specific_artist"
    assert data["page_info"]["depth"] == 3
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_graph_cursor_encoding(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that cursor properly encodes and decodes offset."""
    from discovery.pagination import decode_cursor
    from discovery.playground_api import playground_api

    mock_result = create_mock_graph_results(offset=0, limit=50)
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/graph?node_id=artist_1&depth=2&limit=50")
    data = response.json()

    cursor = data["next_cursor"]
    assert cursor is not None

    # Decode cursor to verify it contains correct offset
    cursor_data = decode_cursor(cursor)
    assert cursor_data["offset"] == 50


@pytest.mark.asyncio
async def test_graph_links_consistency(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that links are consistent with nodes returned."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_graph_results(offset=0, limit=10)
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/graph?node_id=artist_1&depth=2&limit=10")
    data = response.json()

    # Check links reference nodes in the result
    node_ids = {node["id"] for node in data["nodes"]}
    for link in data["links"]:
        assert link["source"] in node_ids
        assert link["target"] in node_ids


@pytest.mark.asyncio
async def test_graph_ordering_consistency(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that graph results maintain consistent ordering across pages."""
    from discovery.playground_api import playground_api

    # First page
    playground_api.get_graph_data = AsyncMock(return_value=create_mock_graph_results(offset=0, limit=50))
    response1 = discovery_client.get("/api/graph?node_id=artist_1&depth=2&limit=50")
    data1 = response1.json()
    first_page_last_node = data1["nodes"][-1]["id"]

    # Second page
    cursor = data1["next_cursor"]
    playground_api.get_graph_data = AsyncMock(return_value=create_mock_graph_results(offset=50, limit=50))
    response2 = discovery_client.get(f"/api/graph?node_id=artist_1&depth=2&limit=50&cursor={cursor}")
    data2 = response2.json()
    second_page_first_node = data2["nodes"][0]["id"]

    # Verify no overlap (consistent ordering)
    assert first_page_last_node == "node_49"
    assert second_page_first_node == "node_50"


@pytest.mark.asyncio
async def test_graph_different_depths(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test pagination with different depth parameters."""
    from discovery.playground_api import playground_api

    # Test depth 1
    mock_result_d1 = create_mock_graph_results(offset=0, limit=30)
    mock_result_d1["page_info"]["depth"] = 1
    playground_api.get_graph_data = AsyncMock(return_value=mock_result_d1)
    response1 = discovery_client.get("/api/graph?node_id=artist_1&depth=1&limit=30")
    data1 = response1.json()
    assert data1["page_info"]["depth"] == 1

    # Test depth 3
    mock_result_d3 = create_mock_graph_results(offset=0, limit=30)
    mock_result_d3["page_info"]["depth"] = 3
    playground_api.get_graph_data = AsyncMock(return_value=mock_result_d3)
    response3 = discovery_client.get("/api/graph?node_id=artist_1&depth=3&limit=30")
    data3 = response3.json()
    assert data3["page_info"]["depth"] == 3


@pytest.mark.asyncio
async def test_graph_last_page_partial(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test last page with partial results (less than limit)."""
    from discovery.playground_api import playground_api

    # Create a partial last page (25 nodes instead of 50)
    cursor = encode_cursor({"offset": 75})
    mock_result = create_mock_graph_results(offset=75, limit=50, total_nodes=100)
    playground_api.get_graph_data = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/graph?node_id=artist_1&depth=2&limit=50&cursor={cursor}")
    data = response.json()

    # Check partial results
    assert len(data["nodes"]) == 25
    assert data["has_more"] is False
    assert data["next_cursor"] is None
