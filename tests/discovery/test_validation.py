"""Tests for input validation and sanitization."""

import pytest
from fastapi import HTTPException

from discovery.validation import (
    ALLOWED_HEATMAP_TYPES,
    ALLOWED_TREND_TYPES,
    ALLOWED_TYPES,
    validate_depth,
    validate_integer,
    validate_limit,
    validate_node_id,
    validate_search_query,
    validate_top_n,
    validate_type,
    validate_year,
)


def test_validate_search_query_valid() -> None:
    """Test validation of valid search queries."""
    assert validate_search_query("The Beatles") == "The Beatles"
    assert validate_search_query("Miles Davis & Friends") == "Miles Davis & Friends"
    assert validate_search_query("Rock & Roll!") == "Rock & Roll!"


def test_validate_search_query_empty() -> None:
    """Test validation of empty search query."""
    with pytest.raises(HTTPException) as exc_info:
        validate_search_query("")

    assert exc_info.value.status_code == 400
    assert "cannot be empty" in str(exc_info.value.detail)


def test_validate_search_query_too_long() -> None:
    """Test validation of too long search query."""
    long_query = "a" * 501

    with pytest.raises(HTTPException) as exc_info:
        validate_search_query(long_query)

    assert exc_info.value.status_code == 400
    assert "exceeds maximum length" in str(exc_info.value.detail)


def test_validate_search_query_invalid_characters() -> None:
    """Test validation of search query with invalid characters."""
    with pytest.raises(HTTPException) as exc_info:
        validate_search_query("SELECT * FROM users;<script>alert('xss')</script>")

    assert exc_info.value.status_code == 400
    assert "invalid characters" in str(exc_info.value.detail)


def test_validate_node_id_valid() -> None:
    """Test validation of valid node IDs."""
    assert validate_node_id("artist_123") == "artist_123"
    assert validate_node_id("release-456") == "release-456"
    assert validate_node_id("ABC123def") == "ABC123def"


def test_validate_node_id_empty() -> None:
    """Test validation of empty node ID."""
    with pytest.raises(HTTPException) as exc_info:
        validate_node_id("")

    assert exc_info.value.status_code == 400
    assert "cannot be empty" in str(exc_info.value.detail)


def test_validate_node_id_too_long() -> None:
    """Test validation of too long node ID."""
    long_id = "a" * 101

    with pytest.raises(HTTPException) as exc_info:
        validate_node_id(long_id)

    assert exc_info.value.status_code == 400
    assert "exceeds maximum length" in str(exc_info.value.detail)


def test_validate_node_id_invalid_characters() -> None:
    """Test validation of node ID with invalid characters."""
    with pytest.raises(HTTPException) as exc_info:
        validate_node_id("artist/123")

    assert exc_info.value.status_code == 400
    assert "invalid characters" in str(exc_info.value.detail)


def test_validate_type_valid() -> None:
    """Test validation of valid type parameters."""
    assert validate_type("artist", ALLOWED_TYPES) == "artist"
    assert validate_type("ARTIST", ALLOWED_TYPES) == "artist"
    assert validate_type("  all  ", ALLOWED_TYPES) == "all"


def test_validate_type_invalid() -> None:
    """Test validation of invalid type parameter."""
    with pytest.raises(HTTPException) as exc_info:
        validate_type("invalid_type", ALLOWED_TYPES)

    assert exc_info.value.status_code == 400
    assert "Invalid type" in str(exc_info.value.detail)


def test_validate_limit_valid() -> None:
    """Test validation of valid limit values."""
    assert validate_limit(10) == 10
    assert validate_limit(1) == 1
    assert validate_limit(1000) == 1000


def test_validate_limit_too_small() -> None:
    """Test validation of limit below minimum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_limit(0)

    assert exc_info.value.status_code == 400
    assert "must be at least 1" in str(exc_info.value.detail)


def test_validate_limit_too_large() -> None:
    """Test validation of limit above maximum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_limit(1001)

    assert exc_info.value.status_code == 400
    assert "cannot exceed 1000" in str(exc_info.value.detail)


def test_validate_depth_valid() -> None:
    """Test validation of valid depth values."""
    assert validate_depth(1) == 1
    assert validate_depth(3) == 3
    assert validate_depth(5) == 5


def test_validate_depth_too_small() -> None:
    """Test validation of depth below minimum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_depth(0)

    assert exc_info.value.status_code == 400
    assert "must be at least 1" in str(exc_info.value.detail)


def test_validate_depth_too_large() -> None:
    """Test validation of depth above maximum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_depth(6)

    assert exc_info.value.status_code == 400
    assert "cannot exceed 5" in str(exc_info.value.detail)


def test_validate_year_valid() -> None:
    """Test validation of valid year values."""
    assert validate_year(1950) == 1950
    assert validate_year(2024) == 2024
    assert validate_year(1900) == 1900


def test_validate_year_too_early() -> None:
    """Test validation of year below minimum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_year(1899)

    assert exc_info.value.status_code == 400
    assert "must be at least 1900" in str(exc_info.value.detail)


def test_validate_year_too_late() -> None:
    """Test validation of year above maximum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_year(2101)

    assert exc_info.value.status_code == 400
    assert "cannot exceed 2100" in str(exc_info.value.detail)


def test_validate_top_n_valid() -> None:
    """Test validation of valid top_n values."""
    assert validate_top_n(10) == 10
    assert validate_top_n(1) == 1
    assert validate_top_n(100) == 100


def test_validate_top_n_too_small() -> None:
    """Test validation of top_n below minimum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_top_n(0)

    assert exc_info.value.status_code == 400
    assert "must be at least 1" in str(exc_info.value.detail)


def test_validate_top_n_too_large() -> None:
    """Test validation of top_n above maximum."""
    with pytest.raises(HTTPException) as exc_info:
        validate_top_n(101)

    assert exc_info.value.status_code == 400
    assert "cannot exceed 100" in str(exc_info.value.detail)


def test_validate_integer_with_custom_params() -> None:
    """Test integer validation with custom parameters."""
    # Valid value within range
    assert validate_integer(50, min_value=0, max_value=100, param_name="custom") == 50

    # Below minimum
    with pytest.raises(HTTPException) as exc_info:
        validate_integer(-1, min_value=0, max_value=100, param_name="custom")

    assert exc_info.value.status_code == 400
    assert "custom must be at least 0" in str(exc_info.value.detail)

    # Above maximum
    with pytest.raises(HTTPException) as exc_info:
        validate_integer(101, min_value=0, max_value=100, param_name="custom")

    assert exc_info.value.status_code == 400
    assert "custom cannot exceed 100" in str(exc_info.value.detail)


def test_allowed_types_constants() -> None:
    """Test that allowed types constants are properly defined."""
    assert "all" in ALLOWED_TYPES
    assert "artist" in ALLOWED_TYPES
    assert "label" in ALLOWED_TYPES

    assert "artist" in ALLOWED_TREND_TYPES
    assert "label" in ALLOWED_TREND_TYPES
    assert "genre" in ALLOWED_TREND_TYPES

    assert "artist" in ALLOWED_HEATMAP_TYPES
    assert "label" in ALLOWED_HEATMAP_TYPES
    assert "country" in ALLOWED_HEATMAP_TYPES
    assert "year" in ALLOWED_HEATMAP_TYPES
