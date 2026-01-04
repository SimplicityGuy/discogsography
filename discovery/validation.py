"""Input validation and sanitization for API endpoints."""

import re

from fastapi import HTTPException


# Allowed characters for search queries (alphanumeric, spaces, basic punctuation)
SEARCH_QUERY_PATTERN = re.compile(r"^[a-zA-Z0-9\s\-_.,!?\'\"&()]+$")

# Allowed characters for node IDs (alphanumeric, hyphens, underscores)
NODE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9\-_]+$")

# Allowed values for type parameters
ALLOWED_TYPES = {"all", "artist", "label", "master", "release"}
ALLOWED_TREND_TYPES = {"artist", "label", "genre"}
ALLOWED_HEATMAP_TYPES = {"genre", "collab"}


def sanitize_string(value: str, max_length: int = 1000, pattern: re.Pattern[str] | None = None) -> str:
    """Sanitize string input.

    Args:
        value: String to sanitize
        max_length: Maximum allowed length
        pattern: Optional regex pattern to validate against

    Returns:
        Sanitized string

    Raises:
        HTTPException: If validation fails
    """
    if not value:
        raise HTTPException(status_code=400, detail="Value cannot be empty")

    # Remove leading/trailing whitespace
    sanitized = value.strip()

    # Check length
    if len(sanitized) > max_length:
        raise HTTPException(status_code=400, detail=f"Value exceeds maximum length of {max_length}")

    # Validate against pattern if provided
    if pattern and not pattern.match(sanitized):
        raise HTTPException(status_code=400, detail="Value contains invalid characters")

    return sanitized


def validate_integer(
    value: int,
    min_value: int | None = None,
    max_value: int | None = None,
    param_name: str = "value",
) -> int:
    """Validate integer input.

    Args:
        value: Integer to validate
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        param_name: Parameter name for error messages

    Returns:
        Validated integer

    Raises:
        HTTPException: If validation fails
    """
    if min_value is not None and value < min_value:
        raise HTTPException(status_code=400, detail=f"{param_name} must be at least {min_value}")

    if max_value is not None and value > max_value:
        raise HTTPException(status_code=400, detail=f"{param_name} cannot exceed {max_value}")

    return value


def validate_search_query(query: str) -> str:
    """Validate and sanitize search query.

    Args:
        query: Search query string

    Returns:
        Sanitized query

    Raises:
        HTTPException: If validation fails
    """
    return sanitize_string(query, max_length=500, pattern=SEARCH_QUERY_PATTERN)


def validate_node_id(node_id: str) -> str:
    """Validate and sanitize node ID.

    Args:
        node_id: Node identifier

    Returns:
        Sanitized node ID

    Raises:
        HTTPException: If validation fails
    """
    return sanitize_string(node_id, max_length=100, pattern=NODE_ID_PATTERN)


def validate_type(type_value: str, allowed_types: set[str]) -> str:
    """Validate type parameter.

    Args:
        type_value: Type value to validate
        allowed_types: Set of allowed type values

    Returns:
        Validated type value

    Raises:
        HTTPException: If validation fails
    """
    sanitized = type_value.strip().lower()

    if sanitized not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type '{type_value}'. Must be one of: {', '.join(sorted(allowed_types))}",
        )

    return sanitized


def validate_limit(limit: int) -> int:
    """Validate limit parameter.

    Args:
        limit: Limit value

    Returns:
        Validated limit

    Raises:
        HTTPException: If validation fails
    """
    return validate_integer(limit, min_value=1, max_value=1000, param_name="limit")


def validate_depth(depth: int) -> int:
    """Validate graph depth parameter.

    Args:
        depth: Depth value

    Returns:
        Validated depth

    Raises:
        HTTPException: If validation fails
    """
    return validate_integer(depth, min_value=1, max_value=5, param_name="depth")


def validate_year(year: int) -> int:
    """Validate year parameter.

    Args:
        year: Year value

    Returns:
        Validated year

    Raises:
        HTTPException: If validation fails
    """
    return validate_integer(year, min_value=1900, max_value=2100, param_name="year")


def validate_top_n(top_n: int) -> int:
    """Validate top_n parameter.

    Args:
        top_n: Top N value

    Returns:
        Validated top_n

    Raises:
        HTTPException: If validation fails
    """
    return validate_integer(top_n, min_value=1, max_value=100, param_name="top_n")
