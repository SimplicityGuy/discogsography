"""NLQ tool schemas and runner for Claude tool-use API.

Defines tool schemas for public and authenticated tools, and the NLQToolRunner
class that dispatches tool calls to existing query functions.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog


logger = structlog.get_logger(__name__)


# ── Tool Schemas ──────────────────────────────────────────────────────────


def get_public_tool_schemas() -> list[dict[str, Any]]:
    """Return 10 tool schemas available to all users (no auth required)."""
    return [
        {
            "name": "search",
            "description": "Full-text search across artists, labels, masters, and releases. Returns ranked results with highlights and facets.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query text"},
                    "types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["artist", "label", "master", "release"]},
                        "description": "Entity types to search (default: all)",
                    },
                    "genres": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter results by genre names",
                    },
                    "year_min": {"type": "integer", "description": "Minimum year filter"},
                    "year_max": {"type": "integer", "description": "Maximum year filter"},
                    "limit": {"type": "integer", "description": "Max results to return (default: 10)"},
                    "offset": {"type": "integer", "description": "Pagination offset (default: 0)"},
                },
                "required": ["q"],
            },
        },
        {
            "name": "autocomplete",
            "description": "Fast prefix-based autocomplete for entity names. Returns matching names with IDs.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["artist", "genre", "label", "style"],
                        "description": "Entity type to autocomplete",
                    },
                    "query": {"type": "string", "description": "Prefix text to match"},
                    "limit": {"type": "integer", "description": "Max suggestions (default: 10)"},
                },
                "required": ["type", "query"],
            },
        },
        {
            "name": "explore_entity",
            "description": "Get detailed information about an entity and its graph connections.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["artist", "genre", "label", "style"],
                        "description": "Entity type to explore",
                    },
                    "name": {"type": "string", "description": "Entity name to look up"},
                },
                "required": ["type", "name"],
            },
        },
        {
            "name": "find_path",
            "description": "Find the shortest path between two entities in the knowledge graph.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_id": {"type": "string", "description": "Starting entity ID or name"},
                    "to_id": {"type": "string", "description": "Target entity ID or name"},
                    "from_type": {
                        "type": "string",
                        "enum": ["artist", "genre", "label", "style"],
                        "description": "Type of the starting entity",
                    },
                    "to_type": {
                        "type": "string",
                        "enum": ["artist", "genre", "label", "style"],
                        "description": "Type of the target entity",
                    },
                    "max_depth": {"type": "integer", "description": "Maximum path length (default: 6)"},
                },
                "required": ["from_id", "to_id"],
            },
        },
        {
            "name": "get_collaborators",
            "description": "Find artists who have collaborated with a given artist through shared releases.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "artist_id": {"type": "string", "description": "The artist ID to find collaborators for"},
                    "limit": {"type": "integer", "description": "Max collaborators to return (default: 20)"},
                },
                "required": ["artist_id"],
            },
        },
        {
            "name": "get_similar_artists",
            "description": "Find artists with similar genre, style, label, and collaborator profiles using cosine similarity.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "artist_id": {"type": "string", "description": "The artist ID to find similar artists for"},
                    "limit": {"type": "integer", "description": "Max similar artists to return (default: 20)"},
                },
                "required": ["artist_id"],
            },
        },
        {
            "name": "get_label_dna",
            "description": "Get a record label's DNA fingerprint: genre/style profiles, era distribution, and artist diversity.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "label_id": {"type": "string", "description": "The label ID to profile"},
                },
                "required": ["label_id"],
            },
        },
        {
            "name": "get_trends",
            "description": "Get release count trends over time for an entity (yearly release counts).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["artist", "genre", "label", "style"],
                        "description": "Entity type",
                    },
                    "name": {"type": "string", "description": "Entity name"},
                },
                "required": ["type", "name"],
            },
        },
        {
            "name": "get_genre_tree",
            "description": "Get the full genre/style hierarchy derived from release co-occurrence data.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "get_graph_stats",
            "description": "Get aggregate node counts for each entity type in the knowledge graph.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


def get_authenticated_tool_schemas() -> list[dict[str, Any]]:
    """Return 4 tool schemas that require user authentication."""
    return [
        {
            "name": "get_collection_gaps",
            "description": "Find releases on a label or by an artist that the user does not own.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["label", "artist"],
                        "description": "Whether to find gaps for a label or artist",
                    },
                    "entity_id": {"type": "string", "description": "The label or artist ID"},
                    "limit": {"type": "integer", "description": "Max results (default: 50)"},
                },
                "required": ["entity_type", "entity_id"],
            },
        },
        {
            "name": "get_taste_fingerprint",
            "description": "Get the user's genre x decade heatmap showing their collection distribution.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "get_taste_blindspots",
            "description": "Find genres the user's favourite artists release in but the user hasn't collected.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max blind spots to return (default: 5)"},
                },
            },
        },
        {
            "name": "get_collection_stats",
            "description": "Get the total number of releases in the user's collection.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


# ── Tool names requiring authentication ───────────────────────────────────

_AUTH_TOOLS = {"get_collection_gaps", "get_taste_fingerprint", "get_taste_blindspots", "get_collection_stats"}


# ── NLQToolRunner ─────────────────────────────────────────────────────────


class NLQToolRunner:
    """Dispatches NLQ tool calls to existing query functions.

    Each tool handler is a thin wrapper that validates params and calls
    the appropriate query function with the correct arguments.
    """

    def __init__(self, neo4j_driver: Any, pg_pool: Any, redis: Any) -> None:
        self._driver = neo4j_driver
        self._pool = pg_pool
        self._redis = redis

    async def execute(self, tool_name: str, params: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        """Execute a tool by name with the given parameters.

        Returns the tool result as a dict, or ``{"error": "..."}`` on failure.
        Auth-required tools check that ``user_id is not None``.
        """
        if tool_name in _AUTH_TOOLS and user_id is None:
            return {"error": "Authentication required for this tool"}

        handler = self._get_handler(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            result: dict[str, Any] = await handler(params, user_id)
            return result
        except Exception:
            logger.exception("❌ Tool execution failed", tool=tool_name)
            return {"error": f"Tool '{tool_name}' failed"}

    def _get_handler(self, tool_name: str) -> Any:
        """Return the async handler for a tool name, or None."""
        handlers: dict[str, Any] = {
            "search": self._handle_search,
            "autocomplete": self._handle_autocomplete,
            "explore_entity": self._handle_explore_entity,
            "find_path": self._handle_find_path,
            "get_collaborators": self._handle_get_collaborators,
            "get_similar_artists": self._handle_get_similar_artists,
            "get_label_dna": self._handle_get_label_dna,
            "get_trends": self._handle_get_trends,
            "get_genre_tree": self._handle_get_genre_tree,
            "get_graph_stats": self._handle_get_graph_stats,
            "get_collection_gaps": self._handle_get_collection_gaps,
            "get_taste_fingerprint": self._handle_get_taste_fingerprint,
            "get_taste_blindspots": self._handle_get_taste_blindspots,
            "get_collection_stats": self._handle_get_collection_stats,
        }
        return handlers.get(tool_name)

    def extract_entities(self, tool_name: str, result: dict[str, Any], entity_type: str = "") -> list[dict[str, str]]:
        """Extract ``{id, name, type}`` entity dicts from a tool result.

        Returns an empty list for error results or unrecognized structures.
        ``entity_type`` is used by ``explore_entity`` to tag the flat result.
        """
        if "error" in result:
            return []

        entities: list[dict[str, str]] = []

        if tool_name == "search":
            for item in result.get("results", []):
                entities.append({"id": item.get("id", ""), "name": item.get("name", ""), "type": item.get("type", "")})

        elif tool_name == "autocomplete":
            entity_type = "unknown"
            for item in result.get("results", []):
                entity: dict[str, str] = {"id": item.get("id", ""), "name": item.get("name", "")}
                if "type" in item:
                    entity["type"] = item["type"]
                else:
                    entity["type"] = entity_type
                entities.append(entity)

        elif tool_name == "explore_entity":
            # explore handlers return a flat dict with id/name (no "center" wrapper)
            etype = entity_type or result.get("_entity_type", "")
            if result.get("id") and result.get("name"):
                entities.append({"id": result.get("id", ""), "name": result.get("name", ""), "type": etype})

        elif tool_name == "find_path":
            for node in result.get("nodes", []):
                entities.append(
                    {
                        "id": node.get("id", ""),
                        "name": node.get("name", ""),
                        "type": node.get("type", node.get("labels", [""])[0] if node.get("labels") else ""),
                    }
                )

        return entities

    # ── Tool handlers ─────────────────────────────────────────────────────

    async def _handle_search(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import search_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.search(
            pool=self._pool,
            redis=self._redis,
            q=params.get("q", ""),
            types=params.get("types", ["artist", "label", "master", "release"]),
            genres=params.get("genres", []),
            year_min=params.get("year_min"),
            year_max=params.get("year_max"),
            limit=params.get("limit", 10),
            offset=params.get("offset", 0),
            search_fn=search_queries.execute_search,
        )

    async def _handle_autocomplete(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415

        entity_type = params.get("type", "artist")
        query = params.get("query", "")
        limit = params.get("limit", 10)
        handler = neo4j_queries.AUTOCOMPLETE_DISPATCH.get(entity_type)
        if handler is None:
            return {"error": f"Unknown autocomplete type: {entity_type}"}
        results = await handler(self._driver, query, limit)
        return {"results": results}

    async def _handle_explore_entity(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        entity_type = params.get("type", "artist")
        handler = neo4j_queries.EXPLORE_DISPATCH.get(entity_type)
        if handler is None:
            return {"error": f"Unknown explore type: {entity_type}"}

        tool_fn = {
            "artist": agent_tools.get_artist_details,
            "label": agent_tools.get_label_details,
            "genre": agent_tools.get_genre_details,
            "style": agent_tools.get_style_details,
            "release": agent_tools.get_release_details,
        }.get(entity_type)
        if tool_fn is None:
            return {"error": f"Unknown explore type: {entity_type}"}

        return await tool_fn(driver=self._driver, name=params.get("name", ""), handler=handler)

    async def _handle_find_path(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        async def resolve_name(driver: Any, name: str, entity_type: str) -> dict[str, Any] | None:
            if name and name.isdigit():
                return {"id": name}
            if not entity_type:
                # No type provided — treat the value as a raw node ID
                return {"id": name}
            handler = neo4j_queries.EXPLORE_DISPATCH.get(entity_type)
            if handler is None:
                return None
            result: dict[str, Any] | None = await handler(driver, name)
            return result

        return await agent_tools.find_path(
            driver=self._driver,
            from_name=params.get("from_id", ""),
            from_type=params.get("from_type", ""),
            to_name=params.get("to_id", ""),
            to_type=params.get("to_type", ""),
            max_depth=params.get("max_depth", 6),
            resolve_name=resolve_name,
            find_shortest_path_fn=neo4j_queries.find_shortest_path,
        )

    async def _handle_get_collaborators(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import collaborator_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.get_collaborators(
            driver=self._driver,
            artist_id=params.get("artist_id", ""),
            limit=params.get("limit", 20),
            collaborators_fn=collaborator_queries.get_collaborators,
        )

    async def _handle_get_similar_artists(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries.recommend_queries import compute_similar_artists, get_artist_profile, get_candidate_artists  # noqa: PLC0415

        artist_id = params.get("artist_id", "")
        limit = params.get("limit", 20)

        target_profile, candidates = await asyncio.gather(
            get_artist_profile(self._driver, artist_id),
            get_candidate_artists(self._driver, artist_id),
        )
        ranked = compute_similar_artists(target_profile, candidates, limit=limit)
        return {"artist_id": artist_id, "similar": ranked}

    async def _handle_get_label_dna(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import label_dna_queries  # noqa: PLC0415

        label_id = params.get("label_id", "")
        result = await label_dna_queries.get_label_full_profile(self._driver, label_id)
        if result is None:
            return {"error": f"Label '{label_id}' not found"}
        return result

    async def _handle_get_trends(self, params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        entity_type = params.get("type", "artist")
        handler = neo4j_queries.TRENDS_DISPATCH.get(entity_type)
        return await agent_tools.get_trends(
            driver=self._driver,
            entity_type=entity_type,
            name=params.get("name", ""),
            handler=handler,
        )

    async def _handle_get_genre_tree(self, _params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import genre_tree_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.get_genre_tree(driver=self._driver, tree_fn=genre_tree_queries.get_genre_tree)

    async def _handle_get_graph_stats(self, _params: dict[str, Any], _user_id: str | None) -> dict[str, Any]:
        from api.queries import neo4j_queries  # noqa: PLC0415
        from common import agent_tools  # noqa: PLC0415

        return await agent_tools.get_graph_stats(driver=self._driver, stats_fn=neo4j_queries.get_graph_stats)

    async def _handle_get_collection_gaps(self, params: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        from api.queries import gap_queries  # noqa: PLC0415

        entity_type = params.get("entity_type", "label")
        entity_id = params.get("entity_id", "")
        limit = params.get("limit", 50)

        if entity_type == "label":
            gaps, total = await gap_queries.get_label_gaps(self._driver, user_id, entity_id, limit=limit)  # type: ignore[arg-type]
        elif entity_type == "artist":
            gaps, total = await gap_queries.get_artist_gaps(self._driver, user_id, entity_id, limit=limit)  # type: ignore[arg-type]
        else:
            return {"error": f"Unknown gap entity type: {entity_type}"}
        return {"gaps": gaps, "total": total}

    async def _handle_get_taste_fingerprint(self, _params: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        from api.queries import taste_queries  # noqa: PLC0415

        cells, total = await taste_queries.get_taste_heatmap(self._driver, user_id)  # type: ignore[arg-type]
        return {"heatmap": cells, "total": total}

    async def _handle_get_taste_blindspots(self, params: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        from api.queries import taste_queries  # noqa: PLC0415

        limit = params.get("limit", 5)
        spots = await taste_queries.get_blind_spots(self._driver, user_id, limit=limit)  # type: ignore[arg-type]
        return {"blind_spots": spots}

    async def _handle_get_collection_stats(self, _params: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        from api.queries import taste_queries  # noqa: PLC0415

        count = await taste_queries.get_collection_count(self._driver, user_id)  # type: ignore[arg-type]
        return {"collection_count": count}
