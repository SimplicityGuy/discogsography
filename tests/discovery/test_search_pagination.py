"""Tests for search endpoint cursor-based pagination."""

from unittest.mock import AsyncMock

import pytest

from discovery.pagination import encode_cursor


def create_mock_search_results(offset: int = 0, limit: int = 10, total: int = 25) -> dict:  # type: ignore[type-arg]
    """Helper to create paginated mock search results."""
    from discovery.pagination import OffsetPagination

    # Simulate a dataset of 'total' artists
    all_artists = [{"id": f"artist_{i}", "name": f"Artist {i}", "real_name": None} for i in range(total)]

    # Get the appropriate slice
    artists = all_artists[offset : offset + limit]

    # Determine if there are more results
    has_more = offset + len(artists) < total
    next_cursor = None
    if has_more:
        next_cursor = OffsetPagination.create_next_cursor(offset, limit)

    return {
        "items": {"artists": artists, "releases": [], "labels": []},
        "total": None,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "page_info": {"query": "artist", "type": "artist", "offset": offset},
    }


@pytest.mark.asyncio
async def test_search_first_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test first page of search results without cursor."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_search_results(offset=0, limit=10)
    playground_api.search = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/search?q=artist&type=artist&limit=10")

    assert response.status_code == 200
    data = response.json()

    # Check paginated response structure
    assert "items" in data
    assert "has_more" in data
    assert "next_cursor" in data
    assert "page_info" in data

    # Check items contain results
    assert "artists" in data["items"]
    assert len(data["items"]["artists"]) == 10

    # Check pagination metadata
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_search_second_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test second page of search results with cursor."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 10})
    mock_result = create_mock_search_results(offset=10, limit=10)
    playground_api.search = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/search?q=artist&type=artist&limit=10&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check items are from second page
    assert "artists" in data["items"]
    assert len(data["items"]["artists"]) == 10
    assert data["items"]["artists"][0]["id"] == "artist_10"

    # Check pagination metadata
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 10


@pytest.mark.asyncio
async def test_search_last_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test last page of search results."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 20})
    mock_result = create_mock_search_results(offset=20, limit=10, total=25)
    playground_api.search = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/search?q=artist&type=artist&limit=10&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check items are from last page (only 5 items)
    assert "artists" in data["items"]
    assert len(data["items"]["artists"]) == 5

    # Check pagination metadata - no more pages
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert data["page_info"]["offset"] == 20


@pytest.mark.asyncio
async def test_search_invalid_cursor(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test search with invalid cursor falls back to first page."""
    from discovery.playground_api import playground_api

    invalid_cursor = "invalid_base64!@#"
    mock_result = create_mock_search_results(offset=0, limit=10)
    playground_api.search = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/search?q=artist&type=artist&limit=10&cursor={invalid_cursor}")

    assert response.status_code == 200
    data = response.json()

    # Should fall back to first page (offset 0)
    assert data["page_info"]["offset"] == 0
    assert len(data["items"]["artists"]) == 10


@pytest.mark.asyncio
async def test_search_empty_results(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test search with no results."""
    from discovery.playground_api import playground_api

    empty_result = {
        "items": {"artists": [], "releases": [], "labels": []},
        "total": None,
        "has_more": False,
        "next_cursor": None,
        "page_info": {"query": "nonexistent", "type": "artist", "offset": 0},
    }
    playground_api.search = AsyncMock(return_value=empty_result)

    response = discovery_client.get("/api/search?q=nonexistent&type=artist&limit=10")

    assert response.status_code == 200
    data = response.json()

    # Check empty results
    assert len(data["items"]["artists"]) == 0
    assert data["has_more"] is False
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_search_pagination_with_limit(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test pagination with different page sizes."""
    from discovery.playground_api import playground_api

    # First page with limit=5
    playground_api.search = AsyncMock(return_value=create_mock_search_results(offset=0, limit=5))
    response = discovery_client.get("/api/search?q=artist&type=artist&limit=5")
    assert response.status_code == 200
    data = response.json()

    assert len(data["items"]["artists"]) == 5
    assert data["has_more"] is True

    # Use cursor for next page
    cursor = data["next_cursor"]
    playground_api.search = AsyncMock(return_value=create_mock_search_results(offset=5, limit=5))
    response = discovery_client.get(f"/api/search?q=artist&type=artist&limit=5&cursor={cursor}")
    assert response.status_code == 200
    data = response.json()

    assert len(data["items"]["artists"]) == 5
    assert data["items"]["artists"][0]["id"] == "artist_5"


@pytest.mark.asyncio
async def test_search_pagination_preserves_query_params(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that pagination preserves query parameters in page_info."""
    from discovery.playground_api import playground_api

    mock_result = {
        "items": {"artists": [{"id": "1", "name": "Beatles"}], "releases": [], "labels": []},
        "total": None,
        "has_more": False,
        "next_cursor": None,
        "page_info": {"query": "Beatles", "type": "artist", "offset": 0},
    }
    playground_api.search = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/search?q=Beatles&type=artist&limit=10")

    assert response.status_code == 200
    data = response.json()

    # Check page_info contains query parameters
    assert data["page_info"]["query"] == "Beatles"
    assert data["page_info"]["type"] == "artist"
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_search_cursor_decoding(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that cursor properly encodes and decodes offset."""
    from discovery.pagination import decode_cursor
    from discovery.playground_api import playground_api

    mock_result = create_mock_search_results(offset=0, limit=10)
    playground_api.search = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/search?q=artist&type=artist&limit=10")
    data = response.json()

    cursor = data["next_cursor"]
    assert cursor is not None

    # Decode cursor to verify it contains correct offset
    cursor_data = decode_cursor(cursor)
    assert cursor_data["offset"] == 10


@pytest.mark.asyncio
async def test_search_multi_type_pagination(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test pagination with multi-type search (all)."""
    from discovery.pagination import OffsetPagination
    from discovery.playground_api import playground_api

    # Create results with 5 items per type (total 15 items >= limit of 10)
    multi_result = {
        "items": {
            "artists": [{"id": f"artist_{i}", "name": f"Artist {i}"} for i in range(5)],
            "releases": [{"id": f"release_{i}", "title": f"Release {i}"} for i in range(5)],
            "labels": [{"id": f"label_{i}", "name": f"Label {i}"} for i in range(5)],
        },
        "total": None,
        "has_more": True,  # 15 items >= 10 limit
        "next_cursor": OffsetPagination.create_next_cursor(0, 10),
        "page_info": {"query": "test", "type": "all", "offset": 0},
    }
    playground_api.search = AsyncMock(return_value=multi_result)

    response = discovery_client.get("/api/search?q=test&type=all&limit=10")
    data = response.json()

    # Check all types returned
    assert "artists" in data["items"]
    assert "releases" in data["items"]
    assert "labels" in data["items"]

    # Combined results should trigger pagination
    total_items = len(data["items"]["artists"]) + len(data["items"]["releases"]) + len(data["items"]["labels"])
    assert total_items == 15  # 5 items per type
    assert data["has_more"] is True


@pytest.mark.asyncio
async def test_search_ordering_consistency(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that search results maintain consistent ordering across pages."""
    from discovery.playground_api import playground_api

    # First page
    playground_api.search = AsyncMock(return_value=create_mock_search_results(offset=0, limit=10))
    response1 = discovery_client.get("/api/search?q=artist&type=artist&limit=10")
    data1 = response1.json()
    first_page_last_item = data1["items"]["artists"][-1]["id"]

    # Second page
    cursor = data1["next_cursor"]
    playground_api.search = AsyncMock(return_value=create_mock_search_results(offset=10, limit=10))
    response2 = discovery_client.get(f"/api/search?q=artist&type=artist&limit=10&cursor={cursor}")
    data2 = response2.json()
    second_page_first_item = data2["items"]["artists"][0]["id"]

    # Verify no overlap (consistent ordering)
    assert first_page_last_item == "artist_9"
    assert second_page_first_item == "artist_10"


@pytest.mark.asyncio
async def test_pagination_utils() -> None:
    """Test pagination utility functions."""
    from discovery.pagination import IDCursorPagination, OffsetPagination, decode_cursor, encode_cursor

    # Test encode/decode cursor
    data = {"offset": 42, "extra": "field"}
    cursor = encode_cursor(data)
    decoded = decode_cursor(cursor)
    assert decoded == data

    # Test OffsetPagination
    assert OffsetPagination.get_offset_from_cursor(None) == 0
    cursor = OffsetPagination.create_next_cursor(10, 20)
    assert OffsetPagination.get_offset_from_cursor(cursor) == 30

    # Test IDCursorPagination
    assert IDCursorPagination.get_last_id_from_cursor(None, default="default") == "default"
    cursor = IDCursorPagination.create_next_cursor("id_123", {"extra": "data"})
    assert IDCursorPagination.get_last_id_from_cursor(cursor) == "id_123"
    decoded = decode_cursor(cursor)
    assert decoded["last_id"] == "id_123"
    assert decoded["extra"] == "data"
