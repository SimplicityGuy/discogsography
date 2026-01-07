"""Unit tests for pagination module."""

import base64
from typing import Any

import pytest

from discovery.pagination import (
    create_paginated_response,
    decode_cursor,
    encode_cursor,
)


class TestEncodeDecode:
    """Test cursor encoding and decoding."""

    def test_encode_decode_round_trip(self) -> None:
        """Test encoding and decoding a cursor."""
        data = {"offset": 10, "limit": 20, "filters": {"genre": "rock"}}

        cursor = encode_cursor(data)
        decoded = decode_cursor(cursor)

        assert decoded == data

    def test_decode_invalid_base64(self) -> None:
        """Test decoding an invalid base64 cursor raises ValueError."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_invalid_json(self) -> None:
        """Test decoding invalid JSON raises ValueError."""
        # Create a valid base64 string with invalid JSON
        invalid_json = base64.urlsafe_b64encode(b"{invalid json}").decode()

        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(invalid_json)


class TestCreatePaginatedResponse:
    """Test paginated response creation."""

    def test_create_paginated_response_no_more_items(self) -> None:
        """Test paginated response when there are no more items."""
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        limit = 10  # More than items, so no more items

        response = create_paginated_response(items, limit)

        assert response["items"] == items
        assert response["total"] is None
        assert response["has_more"] is False
        assert response["next_cursor"] is None
        assert response["page_info"] == {}

    def test_create_paginated_response_has_more(self) -> None:
        """Test paginated response when there are more items."""
        items = [{"id": i} for i in range(10)]  # Exactly limit items
        limit = 10
        cursor_data = {"offset": 10, "limit": 10}

        response = create_paginated_response(items, limit, cursor_data=cursor_data)

        assert response["items"] == items
        assert response["has_more"] is True
        assert response["next_cursor"] is not None
        # Verify cursor can be decoded
        decoded = decode_cursor(response["next_cursor"])
        assert decoded == cursor_data

    def test_create_paginated_response_has_more_no_cursor(self) -> None:
        """Test has_more=True but no cursor_data provided."""
        items = [{"id": i} for i in range(10)]
        limit = 10

        response = create_paginated_response(items, limit)

        assert response["has_more"] is True
        assert response["next_cursor"] is None  # No cursor since cursor_data is None

    def test_create_paginated_response_with_total(self) -> None:
        """Test paginated response with total count."""
        items = [{"id": i} for i in range(5)]
        limit = 5
        total = 100

        response = create_paginated_response(items, limit, total=total)

        assert response["total"] == 100
        assert response["has_more"] is True  # items >= limit (5 >= 5)

    def test_create_paginated_response_with_page_info(self) -> None:
        """Test paginated response with custom page_info."""
        items = [{"id": 1}]
        limit = 10
        page_info: dict[str, Any] = {"query": "test", "type": "artist"}

        response = create_paginated_response(items, limit, page_info=page_info)

        assert response["page_info"] == page_info

    def test_create_paginated_response_edge_case_limit_equals_items(self) -> None:
        """Test when items exactly equals limit."""
        items = [{"id": i} for i in range(5)]
        limit = 5
        cursor_data = {"offset": 5}

        response = create_paginated_response(items, limit, cursor_data=cursor_data)

        # With limit=5 and 5 items, has_more=True (>= check)
        assert response["has_more"] is True
        assert response["next_cursor"] is not None
