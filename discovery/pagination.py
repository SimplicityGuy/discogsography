"""Pagination utilities for Discovery API endpoints."""

import base64
import json
from typing import Any, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters for API requests."""

    limit: int = Field(default=20, ge=1, le=100, description="Number of items per page")
    cursor: str | None = Field(default=None, description="Cursor for next page")


class PaginatedResponse(BaseModel):
    """Paginated API response."""

    items: list[Any] = Field(description="List of items in current page")
    total: int | None = Field(default=None, description="Total number of items (optional)")
    has_more: bool = Field(description="Whether there are more items available")
    next_cursor: str | None = Field(default=None, description="Cursor for next page")
    page_info: dict[str, Any] = Field(default_factory=dict, description="Additional page metadata")


def encode_cursor(data: dict[str, Any]) -> str:
    """Encode pagination cursor from data dictionary.

    Args:
        data: Dictionary containing cursor data (e.g., last_id, offset, etc.)

    Returns:
        Base64-encoded cursor string
    """
    json_str = json.dumps(data, sort_keys=True)
    return base64.urlsafe_b64encode(json_str.encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode pagination cursor to data dictionary.

    Args:
        cursor: Base64-encoded cursor string

    Returns:
        Dictionary containing cursor data

    Raises:
        ValueError: If cursor is invalid
    """
    try:
        json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
        result: dict[str, Any] = json.loads(json_str)
        return result
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid cursor: {e}") from e


def create_paginated_response(
    items: list[Any],
    limit: int,
    cursor_data: dict[str, Any] | None = None,
    total: int | None = None,
    page_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a paginated response dictionary.

    Args:
        items: List of items for current page
        limit: Items per page
        cursor_data: Data to encode in next cursor (if more items exist)
        total: Optional total count of all items
        page_info: Optional additional page metadata

    Returns:
        Dictionary with paginated response structure
    """
    has_more = len(items) >= limit
    next_cursor = None

    if has_more and cursor_data:
        next_cursor = encode_cursor(cursor_data)

    return {
        "items": items,
        "total": total,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "page_info": page_info or {},
    }


class OffsetPagination:
    """Offset-based pagination helper (SKIP/LIMIT pattern).

    Use for smaller datasets or when order is important.
    Less efficient for large datasets compared to cursor pagination.
    """

    @staticmethod
    def get_offset_from_cursor(cursor: str | None) -> int:
        """Extract offset from cursor.

        Args:
            cursor: Encoded cursor string

        Returns:
            Offset value (0 if no cursor)
        """
        if not cursor:
            return 0

        try:
            data = decode_cursor(cursor)
            offset: int = data.get("offset", 0)
            return offset
        except ValueError:
            return 0

    @staticmethod
    def create_next_cursor(offset: int, limit: int) -> str:
        """Create cursor for next page.

        Args:
            offset: Current offset
            limit: Items per page

        Returns:
            Encoded cursor for next page
        """
        return encode_cursor({"offset": offset + limit})


class IDCursorPagination:
    """ID-based cursor pagination helper.

    More efficient for large datasets. Uses the last seen ID as cursor.
    Requires items to have a stable, sortable ID field.
    """

    @staticmethod
    def get_last_id_from_cursor(cursor: str | None, default: Any = None) -> Any:
        """Extract last seen ID from cursor.

        Args:
            cursor: Encoded cursor string
            default: Default value if no cursor

        Returns:
            Last seen ID or default
        """
        if not cursor:
            return default

        try:
            data = decode_cursor(cursor)
            return data.get("last_id", default)
        except ValueError:
            return default

    @staticmethod
    def create_next_cursor(last_id: Any, extra_data: dict[str, Any] | None = None) -> str:
        """Create cursor for next page using last item's ID.

        Args:
            last_id: ID of last item in current page
            extra_data: Optional additional cursor data

        Returns:
            Encoded cursor for next page
        """
        data = {"last_id": last_id}
        if extra_data:
            data.update(extra_data)
        return encode_cursor(data)
