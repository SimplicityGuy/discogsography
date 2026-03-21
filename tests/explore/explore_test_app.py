"""Test application factory for Explore service E2E tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
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

# Mock auth data
MOCK_USER: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "email": "test@example.com",
    "is_active": True,
    "created_at": "2026-01-01T00:00:00",
}

MOCK_TOKEN = "mock-test-access-token-abc123"  # nosec B105

MOCK_COLLECTION: dict[str, Any] = {
    "releases": [
        {"id": "10", "title": "OK Computer", "artist": "Radiohead", "label": "Parlophone", "year": 1997},
        {"id": "11", "title": "Kid A", "artist": "Radiohead", "label": "Parlophone", "year": 2000},
    ],
    "total": 2,
    "offset": 0,
    "limit": 50,
    "has_more": False,
}

MOCK_WANTLIST: dict[str, Any] = {
    "releases": [
        {"id": "20", "title": "In Rainbows", "artist": "Radiohead", "label": "Self-released", "year": 2007},
    ],
    "total": 1,
    "offset": 0,
    "limit": 50,
    "has_more": False,
}

MOCK_RECOMMENDATIONS: dict[str, Any] = {
    "recommendations": [
        {"id": "30", "title": "Pablo Honey", "artist": "Radiohead", "year": 1993, "score": 0.85},
        {"id": "31", "title": "The Bends", "artist": "Radiohead", "year": 1995, "score": 0.72},
    ],
    "total": 2,
}

MOCK_COLLECTION_STATS: dict[str, Any] = {
    "total_releases": 42,
    "unique_artists": 15,
    "unique_labels": 8,
    "average_rating": 4.2,
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
        default_response_class=JSONResponse,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check() -> JSONResponse:
        return JSONResponse(
            content={
                "status": "healthy",
                "service": "explore",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    # ------------------------------------------------------------------ #
    # Auth endpoints
    # ------------------------------------------------------------------ #

    @app.post("/api/auth/register", status_code=201)
    async def auth_register(request: Request) -> JSONResponse:
        """Accept any well-formed registration request."""
        body = await request.json()
        if not body.get("email") or not body.get("password"):
            return JSONResponse(content={"error": "Invalid request"}, status_code=422)
        return JSONResponse(content={"message": "Registration processed"}, status_code=201)

    @app.post("/api/auth/login")
    async def auth_login(request: Request) -> JSONResponse:
        """Accept test@example.com / testpassword; reject everything else."""
        body = await request.json()
        email = body.get("email", "")
        password = body.get("password", "")
        if email == "test@example.com" and password == "testpassword":
            return JSONResponse(
                content={
                    "access_token": MOCK_TOKEN,
                    "token_type": "bearer",
                    "expires_in": 3600,
                }
            )
        return JSONResponse(content={"detail": "Invalid credentials"}, status_code=401)

    @app.post("/api/auth/logout")
    async def auth_logout(authorization: str | None = Header(default=None)) -> JSONResponse:  # noqa: ARG001
        """Accept any Bearer token and confirm logout."""
        return JSONResponse(content={"logged_out": True})

    @app.get("/api/auth/me")
    async def auth_me(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Return mock user for any Bearer token."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content=MOCK_USER)

    # ------------------------------------------------------------------ #
    # Discogs OAuth endpoints
    # ------------------------------------------------------------------ #

    @app.get("/api/oauth/authorize/discogs")
    async def oauth_authorize_discogs(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Return a mock Discogs authorization URL."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(
            content={
                "authorize_url": "https://www.discogs.com/oauth/authorize?oauth_token=mock_token",
                "state": "mock-oauth-state-abc123",
                "expires_in": 3600,
            }
        )

    @app.post("/api/oauth/verify/discogs")
    async def oauth_verify_discogs(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """Accept verifier '12345678'; reject all others."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        body = await request.json()
        verifier = body.get("oauth_verifier", "")
        if verifier == "12345678":
            return JSONResponse(content={"connected": True, "discogs_username": "testuser", "discogs_user_id": "99999"})
        return JSONResponse(content={"detail": "Invalid verifier"}, status_code=400)

    @app.get("/api/oauth/status/discogs")
    async def oauth_status_discogs(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Return disconnected status by default."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content={"connected": False})

    @app.delete("/api/oauth/revoke/discogs")
    async def oauth_revoke_discogs(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Confirm Discogs account disconnection."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content={"revoked": True})

    # ------------------------------------------------------------------ #
    # User data endpoints
    # ------------------------------------------------------------------ #

    @app.get("/api/user/collection")
    async def user_collection(
        authorization: str | None = Header(default=None),
        limit: int = Query(50, ge=1, le=200),  # noqa: ARG001
        offset: int = Query(0, ge=0),  # noqa: ARG001
    ) -> JSONResponse:
        """Return mock collection for any authenticated user."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content=MOCK_COLLECTION)

    @app.get("/api/user/wantlist")
    async def user_wantlist(
        authorization: str | None = Header(default=None),
        limit: int = Query(50, ge=1, le=200),  # noqa: ARG001
        offset: int = Query(0, ge=0),  # noqa: ARG001
    ) -> JSONResponse:
        """Return mock wantlist for any authenticated user."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content=MOCK_WANTLIST)

    @app.get("/api/user/recommendations")
    async def user_recommendations(
        authorization: str | None = Header(default=None),
        limit: int = Query(20, ge=1, le=100),  # noqa: ARG001
    ) -> JSONResponse:
        """Return mock recommendations for any authenticated user."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content=MOCK_RECOMMENDATIONS)

    @app.get("/api/user/collection/stats")
    async def user_collection_stats(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Return mock collection stats for any authenticated user."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content=MOCK_COLLECTION_STATS)

    @app.get("/api/user/status")
    async def user_release_status(
        ids: str = Query(...),
        authorization: str | None = Header(default=None),  # noqa: ARG001
    ) -> JSONResponse:
        """Return empty ownership status (works for authenticated and anonymous users)."""
        release_ids = [rid.strip() for rid in ids.split(",") if rid.strip()]
        return JSONResponse(content={"status": {rid: {"in_collection": False, "in_wantlist": False} for rid in release_ids}})

    # ------------------------------------------------------------------ #
    # Sync endpoints
    # ------------------------------------------------------------------ #

    @app.post("/api/sync", status_code=202)
    async def trigger_sync(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Acknowledge a sync request."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content={"status": "started", "job_id": "mock-job-id-xyz"}, status_code=202)

    @app.get("/api/sync/status")
    async def sync_status(authorization: str | None = Header(default=None)) -> JSONResponse:
        """Return mock sync status."""
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(content={"detail": "Not authenticated"}, status_code=401)
        return JSONResponse(content={"status": "idle", "last_sync": None})

    # ------------------------------------------------------------------ #
    # Existing explore/graph endpoints
    # ------------------------------------------------------------------ #

    @app.get("/api/autocomplete")
    async def autocomplete(
        q: str = Query(..., min_length=2),
        type: str = Query("artist"),
        limit: int = Query(10, ge=1, le=50),
    ) -> JSONResponse:
        entity_type = type.lower()
        results = MOCK_AUTOCOMPLETE_RESULTS.get(entity_type, [])
        filtered = [r for r in results if q.lower() in r["name"].lower()][:limit]
        return JSONResponse(content={"results": filtered})

    @app.get("/api/explore")
    async def explore(
        name: str = Query(...),  # noqa: ARG001
        type: str = Query("artist"),
    ) -> JSONResponse:
        entity_type = type.lower()
        result = MOCK_EXPLORE_RESULTS.get(entity_type)
        if not result:
            return JSONResponse(content={"error": "Not found"}, status_code=404)

        from api.routers.explore import _build_categories

        categories = _build_categories(entity_type, result)
        return JSONResponse(
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
    ) -> JSONResponse:
        return JSONResponse(
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
    ) -> JSONResponse:
        return JSONResponse(
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
    ) -> JSONResponse:
        return JSONResponse(
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

    @app.get("/api/collaborators/{artist_id}")
    async def get_collaborators(
        artist_id: str,
        limit: int = Query(20, ge=1, le=100),  # noqa: ARG001
    ) -> JSONResponse:
        return JSONResponse(
            content={
                "artist_id": artist_id,
                "artist_name": "Radiohead",
                "collaborators": [
                    {
                        "artist_id": "456",
                        "artist_name": "Thom Yorke",
                        "release_count": 5,
                        "first_year": 1993,
                        "last_year": 2011,
                        "yearly_counts": [
                            {"year": 1993, "count": 1},
                            {"year": 1997, "count": 2},
                            {"year": 2011, "count": 2},
                        ],
                    },
                    {
                        "artist_id": "789",
                        "artist_name": "Jonny Greenwood",
                        "release_count": 3,
                        "first_year": 1995,
                        "last_year": 2007,
                        "yearly_counts": [
                            {"year": 1995, "count": 1},
                            {"year": 2007, "count": 2},
                        ],
                    },
                ],
                "total": 2,
            }
        )

    @app.get("/api/genre-tree")
    async def genre_tree() -> JSONResponse:
        return JSONResponse(
            content={
                "genres": [
                    {
                        "name": "Rock",
                        "release_count": 98000,
                        "styles": [
                            {"name": "Alternative Rock", "release_count": 15000},
                            {"name": "Punk", "release_count": 9500},
                        ],
                    },
                    {
                        "name": "Electronic",
                        "release_count": 75000,
                        "styles": [
                            {"name": "House", "release_count": 20000},
                            {"name": "Techno", "release_count": 18000},
                        ],
                    },
                ]
            }
        )

    # Serve static files from explore module (html=True serves index.html at root)
    static_dir = Path(__file__).parent.parent.parent / "explore" / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
