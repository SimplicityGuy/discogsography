"""Tests for trends endpoint cursor-based pagination."""

from unittest.mock import AsyncMock

import pytest

from discovery.pagination import encode_cursor


def create_mock_trends_results(trend_type: str = "genre", offset: int = 0, limit: int = 20, total_years: int = 50) -> dict[str, any]:  # type: ignore[type-arg]
    """Helper to create paginated mock trends results."""
    from discovery.pagination import OffsetPagination

    # Simulate a dataset of 'total_years' years
    start_year = 1950
    all_trends = []
    for i in range(total_years):
        year = start_year + i
        if trend_type == "genre":
            all_trends.append(
                {
                    "year": year,
                    "data": [
                        {"genre": f"Genre {j}", "count": 100 - j}
                        for j in range(5)  # Top 5 genres per year
                    ],
                }
            )
        else:  # artist
            all_trends.append(
                {
                    "year": year,
                    "data": [
                        {"artist": f"Artist {j}", "releases": 20 - j}
                        for j in range(5)  # Top 5 artists per year
                    ],
                }
            )

    # Get the appropriate slice
    trends = all_trends[offset : offset + limit]

    # Determine if there are more results
    has_more = offset + len(trends) < total_years
    next_cursor = None
    if has_more:
        next_cursor = OffsetPagination.create_next_cursor(offset, limit)

    return {
        "trends": trends,
        "type": trend_type,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "page_info": {"type": trend_type, "start_year": 1950, "end_year": 2024, "offset": offset},
    }


@pytest.mark.asyncio
async def test_trends_first_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test first page of trends results without cursor."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_trends_results(trend_type="genre", offset=0, limit=20)
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/trends?type=genre&start_year=1950&end_year=2024&limit=20")

    assert response.status_code == 200
    data = response.json()

    # Check paginated response structure
    assert "trends" in data
    assert "has_more" in data
    assert "next_cursor" in data
    assert "page_info" in data

    # Check data
    assert len(data["trends"]) == 20
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_trends_second_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test second page of trends results with cursor."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 20})
    mock_result = create_mock_trends_results(trend_type="genre", offset=20, limit=20)
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/trends?type=genre&start_year=1950&end_year=2024&limit=20&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check trends are from second page
    assert len(data["trends"]) == 20
    assert data["trends"][0]["year"] == 1970  # 1950 + 20
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["page_info"]["offset"] == 20


@pytest.mark.asyncio
async def test_trends_last_page(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test last page of trends results."""
    from discovery.playground_api import playground_api

    cursor = encode_cursor({"offset": 40})
    mock_result = create_mock_trends_results(trend_type="genre", offset=40, limit=20, total_years=50)
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/trends?type=genre&start_year=1950&end_year=2024&limit=20&cursor={cursor}")

    assert response.status_code == 200
    data = response.json()

    # Check last page (only 10 years left)
    assert len(data["trends"]) == 10
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert data["page_info"]["offset"] == 40


@pytest.mark.asyncio
async def test_trends_invalid_cursor(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test trends with invalid cursor falls back to first page."""
    from discovery.playground_api import playground_api

    invalid_cursor = "invalid_base64!@#"
    mock_result = create_mock_trends_results(trend_type="genre", offset=0, limit=20)
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get(f"/api/trends?type=genre&start_year=1950&end_year=2024&limit=20&cursor={invalid_cursor}")

    assert response.status_code == 200
    data = response.json()

    # Should fall back to first page (offset 0)
    assert data["page_info"]["offset"] == 0
    assert len(data["trends"]) == 20


@pytest.mark.asyncio
async def test_trends_empty_results(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test trends with no data."""
    from discovery.playground_api import playground_api

    empty_result = {
        "trends": [],
        "type": "genre",
        "has_more": False,
        "next_cursor": None,
        "page_info": {"type": "genre", "start_year": 1950, "end_year": 2024, "offset": 0},
    }
    playground_api.get_trends = AsyncMock(return_value=empty_result)

    response = discovery_client.get("/api/trends?type=genre&start_year=1950&end_year=2024&limit=20")

    assert response.status_code == 200
    data = response.json()

    # Check empty results
    assert len(data["trends"]) == 0
    assert data["has_more"] is False
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_trends_pagination_with_different_limits(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test pagination with different page sizes."""
    from discovery.playground_api import playground_api

    # First page with limit=10
    playground_api.get_trends = AsyncMock(return_value=create_mock_trends_results(offset=0, limit=10))
    response = discovery_client.get("/api/trends?type=genre&start_year=1950&end_year=2024&limit=10")
    assert response.status_code == 200
    data = response.json()

    assert len(data["trends"]) == 10
    assert data["has_more"] is True

    # Second page
    cursor = data["next_cursor"]
    playground_api.get_trends = AsyncMock(return_value=create_mock_trends_results(offset=10, limit=10))
    response = discovery_client.get(f"/api/trends?type=genre&start_year=1950&end_year=2024&limit=10&cursor={cursor}")
    assert response.status_code == 200
    data = response.json()

    assert len(data["trends"]) == 10
    assert data["trends"][0]["year"] == 1960  # 1950 + 10


@pytest.mark.asyncio
async def test_trends_pagination_preserves_params(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that pagination preserves query parameters in page_info."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_trends_results(trend_type="artist", offset=0, limit=20)
    mock_result["page_info"]["type"] = "artist"
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/trends?type=artist&start_year=1980&end_year=2020&limit=20")

    assert response.status_code == 200
    data = response.json()

    # Check page_info contains query parameters
    assert data["page_info"]["type"] == "artist"
    assert data["page_info"]["offset"] == 0


@pytest.mark.asyncio
async def test_trends_cursor_encoding(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that cursor properly encodes and decodes offset."""
    from discovery.pagination import decode_cursor
    from discovery.playground_api import playground_api

    mock_result = create_mock_trends_results(offset=0, limit=20)
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/trends?type=genre&start_year=1950&end_year=2024&limit=20")
    data = response.json()

    cursor = data["next_cursor"]
    assert cursor is not None

    # Decode cursor to verify it contains correct offset
    cursor_data = decode_cursor(cursor)
    assert cursor_data["offset"] == 20


@pytest.mark.asyncio
async def test_trends_artist_type(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test trends with artist type."""
    from discovery.playground_api import playground_api

    mock_result = create_mock_trends_results(trend_type="artist", offset=0, limit=20)
    playground_api.get_trends = AsyncMock(return_value=mock_result)

    response = discovery_client.get("/api/trends?type=artist&start_year=1950&end_year=2024&limit=20")

    assert response.status_code == 200
    data = response.json()

    # Check artist data structure
    assert data["type"] == "artist"
    assert len(data["trends"]) == 20
    assert "artist" in data["trends"][0]["data"][0]
    assert "releases" in data["trends"][0]["data"][0]


@pytest.mark.asyncio
async def test_trends_ordering_consistency(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that trends results maintain consistent ordering across pages."""
    from discovery.playground_api import playground_api

    # First page
    playground_api.get_trends = AsyncMock(return_value=create_mock_trends_results(offset=0, limit=20))
    response1 = discovery_client.get("/api/trends?type=genre&start_year=1950&end_year=2024&limit=20")
    data1 = response1.json()
    first_page_last_year = data1["trends"][-1]["year"]

    # Second page
    cursor = data1["next_cursor"]
    playground_api.get_trends = AsyncMock(return_value=create_mock_trends_results(offset=20, limit=20))
    response2 = discovery_client.get(f"/api/trends?type=genre&start_year=1950&end_year=2024&limit=20&cursor={cursor}")
    data2 = response2.json()
    second_page_first_year = data2["trends"][0]["year"]

    # Verify no overlap (consistent ordering)
    assert first_page_last_year == 1969  # 1950 + 19
    assert second_page_first_year == 1970  # 1950 + 20


@pytest.mark.asyncio
async def test_trends_year_range_validation(discovery_client) -> None:  # type: ignore[no-untyped-def]
    """Test that year range is validated."""
    response = discovery_client.get("/api/trends?type=genre&start_year=2024&end_year=1950&limit=20")

    assert response.status_code == 400
    data = response.json()
    assert "start_year must be less than or equal to end_year" in data["detail"]
