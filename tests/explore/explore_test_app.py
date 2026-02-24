"""Test application factory for Explore service E2E tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles


# Mock Neo4j data
MOCK_AUTOCOMPLETE_RESULTS: dict[str, list[dict[str, Any]]] = {
    "artist": [
        {"id": "1", "name": "Radiohead", "score": 9.5},
        {"id": "2", "name": "Radio Dept.", "score": 7.2},
    ],
    "genre": [
        {"id": "Rock", "name": "Rock", "score": 1.0},
        {"id": "Rockabilly", "name": "Rockabilly", "score": 1.0},
    ],
    "label": [
        {"id": "100", "name": "Warp Records", "score": 9.0},
        {"id": "101", "name": "Warp", "score": 7.0},
    ],
}

MOCK_EXPLORE_RESULTS: dict[str, dict[str, Any]] = {
    "artist": {
        "id": "1",
        "name": "Radiohead",
        "release_count": 42,
        "label_count": 5,
        "alias_count": 2,
    },
    "genre": {
        "id": "Rock",
        "name": "Rock",
        "artist_count": 1000,
        "label_count": 200,
        "style_count": 50,
    },
    "label": {
        "id": "100",
        "name": "Warp Records",
        "release_count": 500,
        "artist_count": 120,
    },
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage test app lifecycle."""
    yield


def create_test_app() -> FastAPI:
    """Create a test instance of the Explore FastAPI app."""
    app = FastAPI(
        title="Discogsography Explore Test",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check() -> ORJSONResponse:
        return ORJSONResponse(
            content={
                "status": "healthy",
                "service": "explore",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    @app.get("/api/autocomplete")
    async def autocomplete(
        q: str = Query(..., min_length=2),
        type: str = Query("artist"),
        limit: int = Query(10, ge=1, le=50),
    ) -> ORJSONResponse:
        entity_type = type.lower()
        results = MOCK_AUTOCOMPLETE_RESULTS.get(entity_type, [])
        filtered = [r for r in results if q.lower() in r["name"].lower()][:limit]
        return ORJSONResponse(content={"results": filtered})

    @app.get("/api/explore")
    async def explore(
        name: str = Query(...),  # noqa: ARG001
        type: str = Query("artist"),
    ) -> ORJSONResponse:
        entity_type = type.lower()
        result = MOCK_EXPLORE_RESULTS.get(entity_type)
        if not result:
            return ORJSONResponse(content={"error": "Not found"}, status_code=404)

        from api.routers.explore import _build_categories

        categories = _build_categories(entity_type, result)
        return ORJSONResponse(
            content={
                "center": {"id": str(result["id"]), "name": result["name"], "type": entity_type},
                "categories": categories,
            }
        )

    @app.get("/api/expand")
    async def expand(
        node_id: str = Query(...),  # noqa: ARG001
        type: str = Query(...),  # noqa: ARG001
        category: str = Query(...),  # noqa: ARG001
        limit: int = Query(50, ge=1, le=200),  # noqa: ARG001
    ) -> ORJSONResponse:
        return ORJSONResponse(
            content={
                "children": [
                    {"id": "10", "name": "OK Computer", "type": "release"},
                    {"id": "11", "name": "Kid A", "type": "release"},
                ]
            }
        )

    @app.get("/api/node/{node_id}")
    async def get_node_details(
        node_id: str,
        type: str = Query("artist"),  # noqa: ARG001
    ) -> ORJSONResponse:
        return ORJSONResponse(
            content={
                "id": node_id,
                "name": "Radiohead",
                "genres": ["Rock", "Electronic"],
                "styles": ["Alternative Rock", "Art Rock"],
                "release_count": 42,
                "groups": [],
            }
        )

    @app.get("/api/trends")
    async def get_trends(
        name: str = Query(...),
        type: str = Query("artist"),
    ) -> ORJSONResponse:
        return ORJSONResponse(
            content={
                "name": name,
                "type": type.lower(),
                "data": [
                    {"year": 1993, "count": 1},
                    {"year": 1995, "count": 2},
                    {"year": 1997, "count": 1},
                    {"year": 2000, "count": 1},
                    {"year": 2003, "count": 1},
                ],
            }
        )

    # Serve static files from explore module (html=True serves index.html at root)
    static_dir = Path(__file__).parent.parent.parent / "explore" / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
