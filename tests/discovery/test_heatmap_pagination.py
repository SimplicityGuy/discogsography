"""Tests for heatmap endpoint cursor-based pagination."""

from unittest.mock import AsyncMock

import pytest

from discovery.pagination import encode_cursor


def create_mock_heatmap_results(heatmap_type: str = "genre", offset: int = 0, limit: int = 100, total_pairs: int = 250) -> dict[str, any]:  # type: ignore[type-arg]
    """Helper to create paginated mock heatmap results."""
    from discovery.pagination import OffsetPagination

    # Simulate a dataset of 'total_pairs' artist pairs
    all_data = []
    artists = set()
    for i in range(total_pairs):
        artist1 = f"Artist {i // 10}"
        artist2 = f"Artist {(i // 10) + 1}"
        value = 10 - (i % 10) if heatmap_type == "genre" else 1  # Shared genres count or collaborated (binary)

        all_data.append({"x": artist1, "y": artist2, "value": value})
        artists.add(artist1)
        artists.add(artist2)

    # Get the appropriate slice
    data = all_data[offset : offset + limit]

    # Determine if there are more results
    has_more = offset + len(data) < total_pairs
    next_cursor = None
    if has_more:
        next_cursor = OffsetPagination.create_next_cursor(offset, limit)

    # Extract artists from the current page
    page_artists = set()
    for item in data:
        page_artists.add(item["x"])
        page_artists.add(item["y"])

    return {
        "heatmap": data,
        "labels": sorted(page_artists),
        "type": heatmap_type,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "page_info": {"type": heatmap_type, "top_n": 20, "offset": offset},
    }


@pytest.mark.asyncio
async def test_heatmap_first_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test first page of heatmap results without cursor."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_heatmap_results(heatmap_type="genre", offset=0, limit=100)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/heatmap?type=genre&top_n=20&limit=100")

    assert response.status_code == 200
    data = response.json()

    # Check paginated response structure
    assert "heatmap" in data
    assert "labels" in data
    assert "has_more" in data
    assert "next_cursor" in data
    assert "page_info" in data

    # Check data
    assert len(data["heatmap"]) == 100
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_heatmap_second_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test second page of heatmap results with cursor."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 100})
    mock_result = create_mock_heatmap_results(heatmap_type="genre", offset=100, limit=100)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/heatmap?type=genre&top_n=20&limit=100&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check heatmap data is from second page
    assert len(data["heatmap"]) == 100
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 100


@pytest.mark.asyncio
async def test_heatmap_last_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test last page of heatmap results."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 200})
    mock_result = create_mock_heatmap_results(heatmap_type="genre", offset=200, limit=100, total_pairs=250)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/heatmap?type=genre&top_n=20&limit=100&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check last page (only 50 pairs left)
    assert len(data["heatmap"]) == 50
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert data["page_info"]["offset"] == 200


@pytest.mark.asyncio
async def test_heatmap_invalid_cursor(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test heatmap with invalid cursor falls back to first page."""
    from discovery.playground_api import playground_api

    invalid_cursor = "invalid_base64!@#"
    mock_result = create_mock_heatmap_results(heatmap_type="genre", offset=0, limit=100)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/heatmap?type=genre&top_n=20&limit=100&cursor={invalid_cursor}")

    assert response.status_code == 200
    data = response.json()

    # Should fall back to first page (offset 0)
    assert data["page_info"]["offset"] == 0
    assert len(data["heatmap"]) == 100


@pytest.mark.asyncio
async def test_heatmap_empty_results(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test heatmap with no data."""
    from discovery.playground_api import playground_api

    empty_result = {
        "heatmap": [],
        "labels": [],
        "type": "genre",
        "has_more": False,
        "next_cursor": None,
        "page_info": {"type": "genre", "top_n": 20, "offset": 0},
    }
    playground_api.get_heatmap = AsyncMock(return_value=empty_result)

    response = discovery_client.get("/api/heatmap?type=genre&top_n=20&limit=100")

    assert response.status_code == 200
    data = response.json()

    # Check empty results
    assert len(data["heatmap"]) == 0
    assert len(data["labels"]) == 0
    assert data["has_more"] is False
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_heatmap_pagination_with_different_limits(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test pagination with different page sizes."""
    from discovery.playground_api import playground_api

    # First page with limit=50
    playground_api.get_heatmap = AsyncMock(return_value=create_mock_heatmap_results(offset=0, limit=50))
    response = discovery_client.get("/api/heatmap?type=genre&top_n=20&limit=50")
    assert response.status_code == 200
    data = response.json()

    assert len(data["heatmap"]) == 50
    assert data["has_more"] is True

    # Second page
    cursor = data["next_cursor"]
    playground_api.get_heatmap = AsyncMock(return_value=create_mock_heatmap_results(offset=50, limit=50))
    response = discovery_client.get(f"/api/heatmap?type=genre&top_n=20&limit=50&cursor={cursor}")
    assert response.status_code == 200
    data = response.json()

    assert len(data["heatmap"]) == 50
    # Verify data is different (different artist pairs)
    assert data["heatmap"][0]["x"] == "Artist 5"  # offset 50 -> i=50 -> 50//10 = 5


@pytest.mark.asyncio
async def test_heatmap_pagination_preserves_params(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that pagination preserves query parameters in page_info."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_heatmap_results(heatmap_type="collab", offset=0, limit=100)
    mock_result["page_info"]["type"] = "collab"
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/heatmap?type=collab&top_n=30&limit=100")

    assert response.status_code == 200
    data = response.json()

    # Check page_info contains query parameters
    assert data["page_info"]["type"] == "collab"
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_heatmap_cursor_encoding(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that cursor properly encodes and decodes offset."""
    from discovery.pagination import decode_cursor
    from discovery.playground_api import playground_api

    mock_result = create_mock_heatmap_results(offset=0, limit=100)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/heatmap?type=genre&top_n=20&limit=100")
    data = response.json()

    cursor = data["next_cursor"]
    assert cursor is not None

    # Decode cursor to verify it contains correct offset
    cursor_data = decode_cursor(cursor)
    assert cursor_data["offset"] == 100


@pytest.mark.asyncio
async def test_heatmap_collab_type(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test heatmap with collaboration type."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_heatmap_results(heatmap_type="collab", offset=0, limit=100)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/heatmap?type=collab&top_n=20&limit=100")

    assert response.status_code == 200
    data = response.json()

    # Check collab data structure
    assert data["type"] == "collab"
    assert len(data["heatmap"]) == 100
    assert "x" in data["heatmap"][0]
    assert "y" in data["heatmap"][0]
    assert "value" in data["heatmap"][0]
    assert data["heatmap"][0]["value"] == 1  # Collaboration is binary


@pytest.mark.asyncio
async def test_heatmap_ordering_consistency(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that heatmap results maintain consistent ordering across pages."""
    from discovery.playground_api import playground_api

    # First page
    playground_api.get_heatmap = AsyncMock(return_value=create_mock_heatmap_results(offset=0, limit=100))
    response1 = discovery_client.get("/api/heatmap?type=genre&top_n=20&limit=100")
    data1 = response1.json()
    first_page_last_pair = data1["heatmap"][-1]

    # Second page
    cursor = data1["next_cursor"]
    playground_api.get_heatmap = AsyncMock(return_value=create_mock_heatmap_results(offset=100, limit=100))
    response2 = discovery_client.get(f"/api/heatmap?type=genre&top_n=20&limit=100&cursor={cursor}")
    data2 = response2.json()
    second_page_first_pair = data2["heatmap"][0]

    # Verify no overlap (consistent ordering)
    # First page ends at index 99, second page starts at index 100
    assert first_page_last_pair["x"] == "Artist 9"  # 99//10 = 9
    assert second_page_first_pair["x"] == "Artist 10"  # 100//10 = 10


@pytest.mark.asyncio
async def test_heatmap_labels_structure(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that labels are properly extracted from heatmap data."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_heatmap_results(offset=0, limit=100)
    playground_api.get_heatmap = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/heatmap?type=genre&top_n=20&limit=100")
    data = response.json()

    # Check labels structure
    assert isinstance(data["labels"], list)
    assert all(isinstance(label, str) for label in data["labels"])
    # Labels should be sorted
    assert data["labels"] == sorted(data["labels"])
