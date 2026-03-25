"""MCP server exposing the Discogsography knowledge graph to AI assistants.

Provides 11 tools for searching, exploring, and analyzing music data:
  search, get_artist_details, get_label_details, get_release_details,
  get_genre_details, get_style_details, find_path, get_trends,
  get_graph_stats, get_collaborators, get_genre_tree

All data is fetched via the Discogsography API — no direct database access.

Transports: stdio (default, for Claude Desktop) or streamable-http (hosted).

Configuration via environment variables:
  API_BASE_URL    Base URL for the Discogsography API (default: http://localhost:8004)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from os import getenv
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
import structlog


logger = structlog.get_logger(__name__)

_VALID_ENTITY_TYPES = frozenset({"artist", "genre", "label", "style"})
_VALID_SEARCH_TYPES = frozenset({"artist", "label", "master", "release"})


# ---------------------------------------------------------------------------
# Lifespan: manage HTTP client
# ---------------------------------------------------------------------------


@dataclass
class AppContext:
    """Typed lifespan context holding the HTTP client and API base URL."""

    client: httpx.AsyncClient
    base_url: str


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001
    """Initialize HTTP client on startup, close on shutdown."""
    base_url = getenv("API_BASE_URL", "http://localhost:8004")

    async with httpx.AsyncClient(timeout=30.0) as client:
        logger.info("🚀 MCP server ready", api_base_url=base_url)
        yield AppContext(client=client, base_url=base_url)
        logger.info("👋 MCP server shut down")


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Discogsography",
    lifespan=app_lifespan,
    instructions=(
        "Music knowledge graph server. Use 'search' to find entities, "
        "'get_*_details' for deep info, 'find_path' for connections, "
        "'get_trends' for timelines, 'get_graph_stats' for an overview, "
        "'get_collaborators' for artist collaboration networks, and "
        "'get_genre_tree' for the full genre/style hierarchy."
    ),
)


# ---------------------------------------------------------------------------
# Helper: extract lifespan context + API call
# ---------------------------------------------------------------------------


def _ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


async def _api_get(app: AppContext, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """Make a GET request to the Discogsography API."""
    url = f"{app.base_url}{path}"
    return await app.client.get(url, params=params)


# ---------------------------------------------------------------------------
# Tool 1: search
# ---------------------------------------------------------------------------


@mcp.tool()
async def search(
    query: str,
    types: str = "artist,label,master,release",
    limit: int = 20,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Search the music database across artists, labels, masters, and releases.

    Uses full-text search with relevance ranking. Returns matching entities
    with highlights and facet counts (by type, genre, decade).

    Args:
        query: Search terms (minimum 3 characters).
        types: Comma-separated entity types to search (artist, label, master, release).
        limit: Maximum results to return (1-100, default 20).
    """
    requested = [t.strip().lower() for t in types.split(",") if t.strip()]
    if not requested:
        requested = list(_VALID_SEARCH_TYPES)
    invalid = [t for t in requested if t not in _VALID_SEARCH_TYPES]
    if invalid:
        return {"error": f"Invalid type(s): {', '.join(invalid)}. Valid: {', '.join(_VALID_SEARCH_TYPES)}"}

    app = _ctx(ctx)
    resp = await _api_get(
        app,
        "/api/search",
        {
            "q": query,
            "types": ",".join(requested),
            "limit": min(max(limit, 1), 100),
        },
    )
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tools 2-6: entity details
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_artist_details(
    artist_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get detailed information about an artist.

    Returns the artist's name, genres, styles, release count, and group memberships.
    Use 'search' first to find the artist's ID.

    Args:
        artist_id: The Discogs artist ID (numeric string).
    """
    app = _ctx(ctx)
    resp = await _api_get(app, f"/api/node/{artist_id}", {"type": "artist"})
    if resp.status_code == 404:
        return {"error": f"Artist '{artist_id}' not found"}
    return resp.json()  # type: ignore[no-any-return]


@mcp.tool()
async def get_label_details(
    label_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get detailed information about a record label.

    Returns the label's name and total release count.
    Use 'search' first to find the label's ID.

    Args:
        label_id: The Discogs label ID (numeric string).
    """
    app = _ctx(ctx)
    resp = await _api_get(app, f"/api/node/{label_id}", {"type": "label"})
    if resp.status_code == 404:
        return {"error": f"Label '{label_id}' not found"}
    return resp.json()  # type: ignore[no-any-return]


@mcp.tool()
async def get_release_details(
    release_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get detailed information about a release (album, single, etc.).

    Returns the title, year, artists, labels, genres, and styles.
    Use 'search' first to find the release's ID.

    Args:
        release_id: The Discogs release ID (numeric string).
    """
    app = _ctx(ctx)
    resp = await _api_get(app, f"/api/node/{release_id}", {"type": "release"})
    if resp.status_code == 404:
        return {"error": f"Release '{release_id}' not found"}
    return resp.json()  # type: ignore[no-any-return]


@mcp.tool()
async def get_genre_details(
    genre_name: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get detailed information about a music genre.

    Returns the genre name and the number of artists associated with it.

    Args:
        genre_name: Exact genre name (e.g. "Jazz", "Electronic", "Rock").
    """
    app = _ctx(ctx)
    resp = await _api_get(app, f"/api/node/{genre_name}", {"type": "genre"})
    if resp.status_code == 404:
        return {"error": f"Genre '{genre_name}' not found"}
    return resp.json()  # type: ignore[no-any-return]


@mcp.tool()
async def get_style_details(
    style_name: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get detailed information about a music style (sub-genre).

    Returns the style name and the number of artists associated with it.

    Args:
        style_name: Exact style name (e.g. "Acid Jazz", "Ambient", "Punk").
    """
    app = _ctx(ctx)
    resp = await _api_get(app, f"/api/node/{style_name}", {"type": "style"})
    if resp.status_code == 404:
        return {"error": f"Style '{style_name}' not found"}
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tool 7: find_path
# ---------------------------------------------------------------------------


@mcp.tool()
async def find_path(
    from_name: str,
    from_type: str,
    to_name: str,
    to_type: str,
    max_depth: int = 10,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Find the shortest path between two entities in the knowledge graph.

    Discovers how two artists, labels, genres, or styles are connected
    through releases and relationships.

    Args:
        from_name: Name of the starting entity.
        from_type: Type of starting entity (artist, genre, label, style).
        to_name: Name of the destination entity.
        to_type: Type of destination entity (artist, genre, label, style).
        max_depth: Maximum path length to search (1-15, default 10).
    """
    from_type_lower = from_type.lower()
    to_type_lower = to_type.lower()

    if from_type_lower not in _VALID_ENTITY_TYPES:
        return {"error": f"Invalid from_type: {from_type}. Must be one of: {', '.join(sorted(_VALID_ENTITY_TYPES))}"}
    if to_type_lower not in _VALID_ENTITY_TYPES:
        return {"error": f"Invalid to_type: {to_type}. Must be one of: {', '.join(sorted(_VALID_ENTITY_TYPES))}"}

    app = _ctx(ctx)
    resp = await _api_get(
        app,
        "/api/path",
        {
            "from_name": from_name,
            "from_type": from_type_lower,
            "to_name": to_name,
            "to_type": to_type_lower,
            "max_depth": min(max(int(max_depth), 1), 15),
        },
    )

    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tool 8: get_trends
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_trends(
    name: str,
    entity_type: str = "artist",
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get the release timeline for an entity (releases per year).

    Useful for understanding an artist's, label's, or genre's activity over time.

    Args:
        name: Exact name of the entity.
        entity_type: Type of entity (artist, genre, label, style).
    """
    entity_type_lower = entity_type.lower()
    if entity_type_lower not in _VALID_ENTITY_TYPES:
        return {"error": f"Invalid type: {entity_type}. Must be artist, genre, label, or style"}

    app = _ctx(ctx)
    resp = await _api_get(
        app,
        "/api/trends",
        {
            "name": name,
            "type": entity_type_lower,
        },
    )
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tool 9: get_graph_stats
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_graph_stats(
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get an overview of the knowledge graph — total counts for each entity type.

    Returns counts for artists, labels, releases, masters, genres, and styles.
    Useful for understanding the size and scope of the database.
    """
    app = _ctx(ctx)
    resp = await _api_get(app, "/api/graph/stats")
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tool 10: get_collaborators
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_collaborators(
    artist_id: str,
    limit: int = 20,
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Find artists who collaborate with a given artist through shared releases.

    Returns collaborators ranked by number of shared releases, with temporal
    data showing when collaborations occurred.

    Args:
        artist_id: The Discogs artist ID (numeric string). Use 'search' to find it.
        limit: Maximum collaborators to return (1-100, default 20).
    """
    app = _ctx(ctx)
    resp = await _api_get(
        app,
        f"/api/collaborators/{artist_id}",
        {"limit": min(max(limit, 1), 100)},
    )
    if resp.status_code == 404:
        return {"error": f"Artist '{artist_id}' not found"}
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tool 11: get_genre_tree
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_genre_tree(
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get the full genre/style hierarchy from the knowledge graph.

    Returns all genres with their nested styles and release counts,
    derived from release co-occurrence. Useful for understanding the
    taxonomy of music in the database.
    """
    app = _ctx(ctx)
    resp = await _api_get(app, "/api/genre-tree")
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_VALID_TRANSPORTS = {"stdio", "sse", "streamable-http"}


def main() -> None:
    """Run the MCP server. Use --transport to select transport (default: stdio)."""
    transport = "stdio"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg in ("--transport", "-t") and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
            break
        if arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
            break

    if transport not in _VALID_TRANSPORTS:
        transport = "stdio"

    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
