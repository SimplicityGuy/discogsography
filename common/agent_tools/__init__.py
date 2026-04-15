"""Shared agent tool registry.

Pure async data-fetching functions shared between the NLQ engine and the
MCP server. No framework coupling — just typed params in, typed dicts out.
"""

from __future__ import annotations

from common.agent_tools.entities import (
    get_artist_details,
    get_genre_details,
    get_label_details,
    get_release_details,
    get_style_details,
)
from common.agent_tools.graph import find_path


__all__ = [
    "find_path",
    "get_artist_details",
    "get_genre_details",
    "get_label_details",
    "get_release_details",
    "get_style_details",
]
