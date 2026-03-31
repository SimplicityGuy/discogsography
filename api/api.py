"""API microservice for discogsography — user accounts and JWT authentication."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from pydantic import BaseModel
import redis.asyncio as aioredis
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import structlog
import uvicorn

from api.auth import (
    b64url_encode,
    decode_token,
    decrypt_oauth_token,
    encrypt_oauth_token,
    get_oauth_encryption_key,
)
import api.dependencies as _dependencies
from api.limiter import limiter
from api.metrics_collector import MetricsBuffer, normalize_path, run_collector
from api.notifications import BrevoNotificationChannel, LogNotificationChannel
from api.queries.search_queries import ALL_TYPES, execute_search
import api.routers.admin as _admin_router
import api.routers.auth as _auth_router
import api.routers.collection as _collection_router
import api.routers.credits as _credits_router
import api.routers.explore as _explore_router
import api.routers.insights as _insights_router
import api.routers.insights_compute as _insights_compute_router
import api.routers.label_dna as _label_dna_router
import api.routers.musicbrainz as _musicbrainz_router
import api.routers.network as _network_router
import api.routers.nlq as _nlq_router
import api.routers.rarity as _rarity_router
import api.routers.recommend as _recommend_router
import api.routers.search as _search_router
import api.routers.snapshot as _snapshot_router
import api.routers.sync as _sync_router
import api.routers.taste as _taste_router
import api.routers.user as _user_router
from api.services.discogs import (
    DISCOGS_AUTHORIZE_URL,
    REDIS_OAUTH_STATE_TTL,
    REDIS_STATE_PREFIX,
    DiscogsOAuthError,
    exchange_oauth_verifier,
    fetch_discogs_identity,
    request_oauth_token,
)
from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver, HealthServer, setup_logging
from common.config import ApiConfig
from common.query_debug import execute_sql


logger = structlog.get_logger(__name__)

# Module-level state
_pool: AsyncPostgreSQLPool | None = None
_config: ApiConfig | None = None
_redis: aioredis.Redis | None = None
_neo4j: AsyncResilientNeo4jDriver | None = None
_running_syncs: dict[str, asyncio.Task[Any]] = {}
_security = HTTPBearer()


class OAuthVerifyRequest(BaseModel):
    """Request body for completing Discogs OAuth verification."""

    state: str  # The state token (maps to redis key for request token)
    oauth_verifier: str  # Verification code from Discogs


API_PORT = 8004
API_HEALTH_PORT = 8005


def get_health_data() -> dict[str, Any]:
    """Return health status for the API service."""
    return {
        "status": "healthy" if _pool else "starting",
        "service": "api",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _create_access_token(user_id: str, email: str) -> tuple[str, int]:
    """Create a HS256 JWT access token. Returns (token, expires_in_seconds)."""
    if _config is None:
        raise RuntimeError("Service not initialized")

    expire_minutes = _config.jwt_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
        "jti": secrets.token_hex(16),
    }

    header = b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = b64url_encode(hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest())
    token = f"{header}.{body}.{signature}"
    return token, expire_minutes * 60


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    """Validate JWT token and return user payload."""
    if _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )
    try:
        payload = decode_token(credentials.credentials, _config.jwt_secret_key)
        # Reject admin tokens — they must not be used as regular user tokens
        if payload.get("type") == "admin":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        # Check jti blacklist (revoked tokens via logout)
        jti: str | None = payload.get("jti")
        if jti and _redis:
            revoked = await _redis.get(f"revoked:jti:{jti}")
            if revoked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        # Check if password was changed after token was issued
        if user_id and _redis:
            pw_changed = await _redis.get(f"password_changed:{user_id}")
            if pw_changed:
                iat = payload.get("iat")
                if iat and int(iat) < int(pw_changed):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# Common search terms that produce high-cardinality FTS results (~9s for "Rock").
# Pre-warming the Redis cache on startup ensures users never wait for cold cache.
_PREWARM_SEARCH_TERMS = ["Rock", "Electronic", "Jazz", "Pop", "Punk", "Hip Hop", "Trance", "Blues", "Country", "Metal"]


async def _prewarm_search_cache() -> None:  # pragma: no cover
    """Pre-warm Redis search cache for common high-cardinality terms.

    Runs as a background task after startup. Each term is searched with
    default parameters, populating the Redis cache (1h TTL). Errors are
    logged and swallowed — pre-warming is best-effort.
    """
    if not _pool or not _redis:
        return
    for term in _PREWARM_SEARCH_TERMS:
        try:
            await execute_search(_pool, _redis, term, ALL_TYPES, [], None, None, 20, 0)
            logger.debug("🔥 Search cache pre-warmed", term=term)
        except Exception:
            logger.debug("⚠️ Search pre-warm failed", term=term)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:  # pragma: no cover
    """Manage API service lifecycle."""
    global _pool, _config, _redis, _neo4j

    logger.info("🚀 API service starting...")
    _config = ApiConfig.from_env()

    # Start health server on separate port
    health_srv = HealthServer(API_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("🏥 Health server started", port=API_HEALTH_PORT)

    # Parse postgres address (format: host:port)
    host, port_str = _config.postgres_host.rsplit(":", 1)
    _pool = AsyncPostgreSQLPool(
        connection_params={
            "host": host,
            "port": int(port_str),
            "dbname": _config.postgres_database,
            "user": _config.postgres_username,
            "password": _config.postgres_password,
        },
        max_connections=10,
        min_connections=2,
    )
    await _pool.initialize()
    logger.info("💾 Database pool initialized")

    # Initialize Redis for OAuth state storage and token blacklist
    _redis = await aioredis.from_url(_config.redis_host, decode_responses=True)
    redis_host = _config.redis_host.split("@")[-1] if "@" in _config.redis_host else _config.redis_host.split("://")[-1]
    logger.info("✅ Redis connected", host=redis_host)

    if _config.neo4j_host and _config.neo4j_username and _config.neo4j_password:
        _neo4j = AsyncResilientNeo4jDriver(
            uri=_config.neo4j_host,
            auth=(_config.neo4j_username, _config.neo4j_password),
            max_retries=5,
            encrypted=False,  # M3: Set encrypted=True in production with TLS-enabled Neo4j
        )
        logger.info("🔗 Neo4j driver initialized")
    jwt_secret_for_neo4j = _config.jwt_secret_key if _config.neo4j_host else None
    _dependencies.configure(jwt_secret_for_neo4j, _redis, pool=_pool)
    _sync_router.configure(_pool, _neo4j, _config, _running_syncs, _redis)
    _explore_router.configure(_neo4j, jwt_secret_for_neo4j, _redis)
    _user_router.configure(_neo4j, jwt_secret_for_neo4j)
    _taste_router.configure(_neo4j, jwt_secret_for_neo4j)
    _collection_router.configure(_neo4j, _pool, jwt_secret_for_neo4j)
    _credits_router.configure(_neo4j, _redis)
    _label_dna_router.configure(_neo4j, _redis)
    _recommend_router.configure(_neo4j, jwt_secret_for_neo4j, _redis)
    _search_router.configure(_pool, _redis)
    _insights_compute_router.configure(_neo4j, _pool, _redis)
    _admin_router.configure(_pool, _redis, _config, neo4j_driver=_neo4j)
    _musicbrainz_router.configure(_pool, _neo4j)
    _network_router.configure(_neo4j, _redis)
    _rarity_router.configure(_neo4j, _pool, _redis)
    _auth_router.configure(
        _pool,
        _redis,
        _config,
        _get_current_user,
        _create_access_token,
        notification_channel=BrevoNotificationChannel(
            api_key=_config.brevo_api_key,
            sender_email=_config.brevo_sender_email,
            sender_name=_config.brevo_sender_name,
        )
        if _config.brevo_api_key
        else LogNotificationChannel(),
    )
    _snapshot_router.configure(
        jwt_secret=_config.jwt_secret_key,
        redis_client=_redis,
        ttl_days=_config.snapshot_ttl_days,
        max_nodes=_config.snapshot_max_nodes,
    )
    from api.nlq.config import NLQConfig as _NLQConfig  # noqa: PLC0415

    nlq_config = _NLQConfig.from_env()
    nlq_engine = None
    if nlq_config.is_available:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        from api.nlq.engine import NLQEngine  # noqa: PLC0415
        from api.nlq.tools import NLQToolRunner  # noqa: PLC0415

        anthropic_client = AsyncAnthropic(api_key=nlq_config.api_key)
        tool_runner = NLQToolRunner(neo4j_driver=_neo4j, pg_pool=_pool, redis=_redis)
        nlq_engine = NLQEngine(config=nlq_config, client=anthropic_client, tool_runner=tool_runner)
        logger.info("🧠 NLQ engine initialized", model=nlq_config.model)
    _nlq_router.configure(nlq_config, nlq_engine, _redis, jwt_secret=_config.jwt_secret_key)
    logger.info("✅ API service ready", port=API_PORT)

    # Pre-warm search cache for common high-cardinality terms in background.
    # Store reference on app.state to prevent garbage collection (RUF006).
    _app.state.prewarm_task = asyncio.create_task(_prewarm_search_cache())

    # Start background metrics collector
    metrics_buffer = MetricsBuffer()
    _app.state.metrics_buffer = metrics_buffer
    _app.state.collector_task = asyncio.create_task(run_collector(_pool, _config, metrics_buffer))
    logger.info("📊 Metrics collector started", interval=_config.metrics_collection_interval)

    yield

    logger.info("🔧 API service shutting down...")
    for task in _running_syncs.values():
        task.cancel()
    if _running_syncs:
        await asyncio.gather(*_running_syncs.values(), return_exceptions=True)
    for task in _admin_router._tracking_tasks.values():
        task.cancel()
    if _admin_router._tracking_tasks:
        await asyncio.gather(*_admin_router._tracking_tasks.values(), return_exceptions=True)
    if hasattr(_app.state, "collector_task"):
        _app.state.collector_task.cancel()
        await asyncio.gather(_app.state.collector_task, return_exceptions=True)
    if _neo4j:
        await _neo4j.close()
    if _pool:
        await _pool.close()
    if _redis:
        await _redis.aclose()
    health_srv.stop()
    logger.info("✅ API service stopped")


# Read CORS origins at module load time (config not available yet at this point)
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else None

app = FastAPI(
    title="Discogsography API",
    version="0.1.0",
    description="User authentication and Discogs OAuth integration for Discogsography",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3000", "http://localhost:8003"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: Any) -> Any:
    """Record per-request timing for endpoint performance metrics."""
    import time as _time  # noqa: PLC0415

    path = normalize_path(request.url.path)
    start = _time.monotonic()
    response = await call_next(request)
    elapsed_ms = (_time.monotonic() - start) * 1000
    if hasattr(app.state, "metrics_buffer"):
        app.state.metrics_buffer.record(path, response.status_code, elapsed_ms)
    return response


app.include_router(_auth_router.router)
app.include_router(_sync_router.router)
app.include_router(_explore_router.router)
app.include_router(_insights_router.router)
app.include_router(_insights_compute_router.router)
app.include_router(_credits_router.router)
app.include_router(_label_dna_router.router)
app.include_router(_search_router.router)
app.include_router(_snapshot_router.router)
app.include_router(_user_router.router)
app.include_router(_taste_router.router)
app.include_router(_collection_router.router)
app.include_router(_recommend_router.router)
app.include_router(_admin_router.router)
app.include_router(_nlq_router.router)
app.include_router(_rarity_router.router)
app.include_router(_network_router.router)
app.include_router(_musicbrainz_router.router)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Service health check endpoint."""
    return JSONResponse(content=get_health_data())


async def _get_app_config(key: str) -> str | None:
    """Fetch a value from the app_config table."""
    if _pool is None:
        return None
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, "SELECT value FROM app_config WHERE key = %s", (key,))
        row = await cur.fetchone()
    return row["value"] if row else None


async def _get_discogs_app_config() -> tuple[str | None, str | None]:
    """Fetch both Discogs app credentials in a single query."""
    if _pool is None:
        return None, None
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, "SELECT key, value FROM app_config WHERE key IN ('discogs_consumer_key', 'discogs_consumer_secret')")
        rows = await cur.fetchall()
    config = {row["key"]: row["value"] for row in rows}
    return config.get("discogs_consumer_key"), config.get("discogs_consumer_secret")


@app.get("/api/oauth/authorize/discogs")
async def authorize_discogs(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> JSONResponse:
    """Start the Discogs OAuth 1.0a OOB flow.

    Returns the Discogs authorization URL and a state token.
    The frontend should open the URL in a popup and ask the user to paste
    the verifier code, then call /api/oauth/verify/discogs.
    """
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    consumer_key, consumer_secret = await _get_discogs_app_config()
    try:
        if consumer_key:
            consumer_key = decrypt_oauth_token(consumer_key, get_oauth_encryption_key(_config.encryption_master_key))
        if consumer_secret:
            consumer_secret = decrypt_oauth_token(consumer_secret, get_oauth_encryption_key(_config.encryption_master_key))
    except ValueError:
        logger.error("❌ Failed to decrypt Discogs app credentials — re-run discogs-setup")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discogs app credentials could not be decrypted. Ask an admin to re-run discogs-setup on the API container.",
        ) from None

    if not consumer_key or not consumer_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discogs app credentials not configured. Ask an admin to run discogs-setup on the API container.",
        )

    try:
        token_data = await request_oauth_token(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            user_agent=_config.discogs_user_agent,
        )
    except DiscogsOAuthError as exc:
        logger.error("❌ Failed to get Discogs request token", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to initiate Discogs OAuth",
        ) from exc

    # Store request token in Redis (keyed by state = request_token itself)
    # This acts as both a CSRF token and a lookup key for the token secret
    state = token_data["oauth_token"]
    redis_key = f"{REDIS_STATE_PREFIX}{state}"
    # Store both the token secret and the initiating user_id to prevent cross-user OAuth binding
    state_data = json.dumps({"secret": token_data["oauth_token_secret"], "user_id": current_user.get("sub")})
    await _redis.setex(redis_key, REDIS_OAUTH_STATE_TTL, state_data)

    authorize_url = f"{DISCOGS_AUTHORIZE_URL}?oauth_token={state}"
    logger.info("🔐 Discogs OAuth flow started", user_id=current_user.get("sub"))

    return JSONResponse(
        content={
            "authorize_url": authorize_url,
            "state": state,
            "expires_in": REDIS_OAUTH_STATE_TTL,
        }
    )


@app.post("/api/oauth/verify/discogs")
async def verify_discogs(
    request: OAuthVerifyRequest,
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> JSONResponse:
    """Complete the Discogs OAuth flow by exchanging the verifier code.

    The user pastes the verifier code shown on Discogs into the app.
    This exchanges the verifier for a permanent access token and stores it.
    """
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    consumer_key, consumer_secret = await _get_discogs_app_config()
    try:
        if consumer_key:
            consumer_key = decrypt_oauth_token(consumer_key, get_oauth_encryption_key(_config.encryption_master_key))
        if consumer_secret:
            consumer_secret = decrypt_oauth_token(consumer_secret, get_oauth_encryption_key(_config.encryption_master_key))
    except ValueError:
        logger.error("❌ Failed to decrypt Discogs app credentials — re-run discogs-setup")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discogs app credentials could not be decrypted. Ask an admin to re-run discogs-setup on the API container.",
        ) from None

    if not consumer_key or not consumer_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discogs app credentials not configured",
        )

    # Retrieve request token secret from Redis
    redis_key = f"{REDIS_STATE_PREFIX}{request.state}"
    raw_state_data = await _redis.get(redis_key)

    if not raw_state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state not found or expired. Please restart the OAuth flow.",
        )

    # Parse state data (contains secret + initiating user_id)
    try:
        state_data = json.loads(raw_state_data)
        token_secret = state_data["secret"]
        initiating_user_id = state_data.get("user_id")
    except (ValueError, KeyError, TypeError):
        # Backwards compat: raw string is just the secret
        token_secret = raw_state_data
        initiating_user_id = None

    # Verify the completing user matches the user who started the OAuth flow
    if initiating_user_id and initiating_user_id != current_user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OAuth flow was initiated by a different user",
        )

    try:
        access_data = await exchange_oauth_verifier(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            oauth_token=request.state,
            oauth_token_secret=token_secret,
            oauth_verifier=request.oauth_verifier,
            user_agent=_config.discogs_user_agent,
        )
        identity = await fetch_discogs_identity(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_data["oauth_token"],
            access_token_secret=access_data["oauth_token_secret"],
            user_agent=_config.discogs_user_agent,
        )
    except DiscogsOAuthError as exc:
        logger.error("❌ Discogs OAuth exchange failed", error=str(exc))
        # Clean up state so user can retry immediately
        await _redis.delete(redis_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verifier code or OAuth flow failed",
        ) from exc

    # Clean up state from Redis on success
    await _redis.delete(redis_key)

    user_id = current_user.get("sub")
    discogs_username = identity.get("username", "")
    discogs_user_id = str(identity.get("id", ""))

    _oauth_key = get_oauth_encryption_key(_config.encryption_master_key)

    # Upsert oauth_tokens record
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
                INSERT INTO oauth_tokens (user_id, provider, access_token, access_secret,
                                          provider_username, provider_user_id, updated_at)
                VALUES (%s::uuid, 'discogs', %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, provider) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    access_secret = EXCLUDED.access_secret,
                    provider_username = EXCLUDED.provider_username,
                    provider_user_id = EXCLUDED.provider_user_id,
                    updated_at = NOW()
                RETURNING id
                """,
            (
                user_id,
                encrypt_oauth_token(access_data["oauth_token"], _oauth_key) if _oauth_key else access_data["oauth_token"],
                encrypt_oauth_token(access_data["oauth_token_secret"], _oauth_key) if _oauth_key else access_data["oauth_token_secret"],
                discogs_username,
                discogs_user_id,
            ),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist OAuth token",
            )

    logger.info("✅ Discogs account connected", user_id=user_id, discogs_username=discogs_username)
    return JSONResponse(
        content={
            "connected": True,
            "discogs_username": discogs_username,
            "discogs_user_id": discogs_user_id,
        }
    )


@app.get("/api/oauth/status/discogs")
async def discogs_status(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> JSONResponse:
    """Check if the current user has a connected Discogs account."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
                SELECT provider_username, provider_user_id, updated_at
                FROM oauth_tokens
                WHERE user_id = %s::uuid AND provider = 'discogs'
                """,
            (user_id,),
        )
        token = await cur.fetchone()

    if token is None:
        return JSONResponse(content={"connected": False})

    return JSONResponse(
        content={
            "connected": True,
            "discogs_username": token["provider_username"],
            "discogs_user_id": token["provider_user_id"],
            "connected_at": token["updated_at"].isoformat(),
        }
    )


@app.delete("/api/oauth/revoke/discogs")
async def revoke_discogs(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> JSONResponse:
    """Disconnect the current user's Discogs account."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor() as cur:
        await execute_sql(
            cur,
            "DELETE FROM oauth_tokens WHERE user_id = %s::uuid AND provider = 'discogs'",
            (user_id,),
        )

    logger.info("✅ Discogs account disconnected", user_id=user_id)
    return JSONResponse(content={"revoked": True})


def main() -> None:  # pragma: no cover
    """Entry point for the API service."""
    setup_logging("api", log_file=Path("/logs/api.log"))
    # fmt: off
    print("██████╗ ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗")
    print("██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝ ██╔════╝")
    print("██║  ██║██║███████╗██║     ██║   ██║██║  ███╗███████╗")
    print("██║  ██║██║╚════██║██║     ██║   ██║██║   ██║╚════██║")
    print("██████╔╝██║███████║╚██████╗╚██████╔╝╚██████╔╝███████║")
    print("╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝")
    print()
    print(" █████╗ ██████╗ ██╗")
    print("██╔══██╗██╔══██╗██║")
    print("███████║██████╔╝██║")
    print("██╔══██║██╔═══╝ ██║")
    print("██║  ██║██║     ██║")
    print("╚═╝  ╚═╝╚═╝     ╚═╝")
    print()
    # fmt: on
    uvicorn.run(app, host="0.0.0.0", port=API_PORT, log_level=os.getenv("LOG_LEVEL", "INFO").lower())  # noqa: S104  # nosec B104


if __name__ == "__main__":
    main()
