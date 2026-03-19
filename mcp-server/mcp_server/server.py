"""MCP server exposing the Discogsography knowledge graph to AI assistants.

Provides 9 tools for searching, exploring, and analyzing music data:
  search, get_artist_details, get_label_details, get_release_details,
  get_genre_details, get_style_details, find_path, get_trends, get_graph_stats

Transports: stdio (default, for Claude Desktop) or streamable-http (hosted).

Configuration via environment variables:
  NEO4J_HOST      Neo4j hostname        (default: localhost)
  NEO4J_USERNAME  Neo4j username        (required)
  NEO4J_PASSWORD  Neo4j password        (required)
  POSTGRES_HOST   PostgreSQL hostname   (default: localhost)
  POSTGRES_USER   PostgreSQL username   (default: discogsography)
  POSTGRES_PASS   PostgreSQL password   (default: discogsography)
  POSTGRES_DB     PostgreSQL database   (default: discogsography)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from os import getenv
import sys
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
import structlog

from api.queries.neo4j_queries import (
    EXPLORE_DISPATCH,
    TRENDS_DISPATCH,
    find_shortest_path,
    get_artist_details as _get_artist,
    get_genre_details as _get_genre,
    get_label_details as _get_label,
    get_release_details as _get_release,
    get_style_details as _get_style,
)
from api.queries.search_queries import ALL_TYPES, execute_search
from common import AsyncResilientNeo4jDriver
from common.config import get_secret
from common.postgres_resilient import AsyncPostgreSQLPool


logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: manage Neo4j + PostgreSQL connections
# ---------------------------------------------------------------------------


@dataclass
class AppContext:
    """Typed lifespan context holding database connections."""

    neo4j: AsyncResilientNeo4jDriver
    pg: AsyncPostgreSQLPool


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001
    """Initialize database connections on startup, close on shutdown."""
    neo4j_host = getenv("NEO4J_HOST", "localhost")
    neo4j_uri = f"bolt://{neo4j_host}:7687"
    neo4j_user = getenv("NEO4J_USERNAME", "neo4j")
    neo4j_pass = get_secret("NEO4J_PASSWORD", "neo4j")

    neo4j = AsyncResilientNeo4jDriver(
        uri=neo4j_uri,
        auth=(neo4j_user, neo4j_pass),
    )

    pg_host = getenv("POSTGRES_HOST", "localhost")
    pg_user = getenv("POSTGRES_USER", "discogsography")
    pg_pass = get_secret("POSTGRES_PASS", "discogsography")
    pg_db = getenv("POSTGRES_DB", "discogsography")

    pg = AsyncPostgreSQLPool(
        connection_params={
            "host": pg_host,
            "port": 5432,
            "user": pg_user,
            "password": pg_pass,
            "dbname": pg_db,
        },
    )
    await pg.initialize()

    logger.info("🚀 MCP server ready", neo4j=neo4j_uri, pg_host=pg_host)
    try:
        yield AppContext(neo4j=neo4j, pg=pg)
    finally:
        await pg.close()
        await neo4j.close()
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
        "'get_trends' for timelines, and 'get_graph_stats' for an overview."
    ),
)


# ---------------------------------------------------------------------------
# Helper: extract lifespan context
# ---------------------------------------------------------------------------


def _ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


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
    app = _ctx(ctx)
    requested = [t.strip().lower() for t in types.split(",") if t.strip()]
    if not requested:
        requested = list(ALL_TYPES)
    invalid = [t for t in requested if t not in ALL_TYPES]
    if invalid:
        return {"error": f"Invalid type(s): {', '.join(invalid)}. Valid: {', '.join(ALL_TYPES)}"}

    return await execute_search(
        pool=app.pg,
        redis=None,
        q=query,
        types=requested,
        genres=[],
        year_min=None,
        year_max=None,
        limit=min(max(limit, 1), 100),
        offset=0,
    )


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
    result = await _get_artist(_ctx(ctx).neo4j, artist_id)
    return result if result else {"error": f"Artist '{artist_id}' not found"}


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
    result = await _get_label(_ctx(ctx).neo4j, label_id)
    return result if result else {"error": f"Label '{label_id}' not found"}


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
    result = await _get_release(_ctx(ctx).neo4j, release_id)
    return result if result else {"error": f"Release '{release_id}' not found"}


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
    result = await _get_genre(_ctx(ctx).neo4j, genre_name)
    return result if result else {"error": f"Genre '{genre_name}' not found"}


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
    result = await _get_style(_ctx(ctx).neo4j, style_name)
    return result if result else {"error": f"Style '{style_name}' not found"}


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
    neo4j = _ctx(ctx).neo4j
    valid_types = frozenset(EXPLORE_DISPATCH.keys())

    from_type_lower = from_type.lower()
    to_type_lower = to_type.lower()

    if from_type_lower not in valid_types:
        return {"error": f"Invalid from_type: {from_type}. Must be one of: {', '.join(sorted(valid_types))}"}
    if to_type_lower not in valid_types:
        return {"error": f"Invalid to_type: {to_type}. Must be one of: {', '.join(sorted(valid_types))}"}

    from_node = await EXPLORE_DISPATCH[from_type_lower](neo4j, from_name)
    to_node = await EXPLORE_DISPATCH[to_type_lower](neo4j, to_name)

    if not from_node:
        return {"error": f"{from_type.capitalize()} '{from_name}' not found"}
    if not to_node:
        return {"error": f"{to_type.capitalize()} '{to_name}' not found"}

    depth = min(max(int(max_depth), 1), 15)
    raw = await find_shortest_path(neo4j, str(from_node["id"]), str(to_node["id"]), max_depth=depth)

    if raw is None:
        return {"found": False, "length": None, "path": []}

    raw_nodes: list[dict[str, Any]] = raw["nodes"]
    raw_rels: list[str] = raw["rels"]

    def _label_to_type(labels: list[str]) -> str:
        for label in labels:
            lower = label.lower()
            if lower in valid_types:
                return lower
        return labels[0].lower() if labels else "unknown"

    path = [
        {
            "id": str(n["id"]),
            "name": str(n["name"]),
            "type": _label_to_type(n["labels"]),
            "rel": raw_rels[i - 1] if i > 0 else None,
        }
        for i, n in enumerate(raw_nodes)
    ]

    return {"found": True, "length": len(raw_rels), "path": path}


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
    if entity_type_lower not in TRENDS_DISPATCH:
        return {"error": f"Invalid type: {entity_type}. Must be artist, genre, label, or style"}

    data = await TRENDS_DISPATCH[entity_type_lower](_ctx(ctx).neo4j, name)
    return {"name": name, "type": entity_type_lower, "data": data}


# ---------------------------------------------------------------------------
# Tool 9: get_graph_stats
# ---------------------------------------------------------------------------


async def _graph_stats(driver: AsyncResilientNeo4jDriver) -> dict[str, Any]:
    """Query aggregate node and relationship counts from Neo4j."""
    cypher = """
    CALL {
        MATCH (a:Artist) RETURN 'artists' AS label, count(a) AS cnt
        UNION ALL
        MATCH (l:Label) RETURN 'labels' AS label, count(l) AS cnt
        UNION ALL
        MATCH (r:Release) RETURN 'releases' AS label, count(r) AS cnt
        UNION ALL
        MATCH (m:Master) RETURN 'masters' AS label, count(m) AS cnt
        UNION ALL
        MATCH (g:Genre) RETURN 'genres' AS label, count(g) AS cnt
        UNION ALL
        MATCH (s:Style) RETURN 'styles' AS label, count(s) AS cnt
    }
    RETURN label, cnt
    """
    async with driver.session() as session:
        result = await session.run(cypher)
        counts = {record["label"]: int(record["cnt"]) async for record in result}
    return counts


@mcp.tool()
async def get_graph_stats(
    ctx: Context = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get an overview of the knowledge graph — total counts for each entity type.

    Returns counts for artists, labels, releases, masters, genres, and styles.
    Useful for understanding the size and scope of the database.
    """
    counts = await _graph_stats(_ctx(ctx).neo4j)
    return {
        "total_entities": sum(counts.values()),
        "counts": counts,
    }


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
