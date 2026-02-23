"""API microservice for discogsography — user accounts and JWT authentication."""

import base64
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from pydantic import BaseModel
import redis.asyncio as aioredis
import structlog
import uvicorn

from api.models import LoginRequest, RegisterRequest
from api.services.discogs import (
    DISCOGS_AUTHORIZE_URL,
    REDIS_OAUTH_STATE_TTL,
    REDIS_STATE_PREFIX,
    DiscogsOAuthError,
    exchange_oauth_verifier,
    fetch_discogs_identity,
    request_oauth_token,
)
from common import AsyncPostgreSQLPool, HealthServer, setup_logging
from common.config import ApiConfig


logger = structlog.get_logger(__name__)

# Module-level state
_pool: AsyncPostgreSQLPool | None = None
_config: ApiConfig | None = None
_redis: aioredis.Redis | None = None
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


def _b64url_encode(data: bytes) -> str:
    """Base64url encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """Base64url decode a string, adding padding as needed."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 with a random salt.

    Returns a string in format: <hex_salt>:<hex_key>
    """
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + key.hex()


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its PBKDF2-SHA256 hash."""
    try:
        salt_hex, key_hex = hashed_password.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        actual_key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(actual_key, expected_key)
    except (ValueError, TypeError):
        return False


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
    }

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = _b64url_encode(hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest())
    token = f"{header}.{body}.{signature}"
    return token, expire_minutes * 60


def _decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a HS256 JWT token."""
    if _config is None:
        raise ValueError("Service not initialized")

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")

    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    expected_sig = _b64url_encode(hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest())

    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid token signature")

    payload: dict[str, Any] = json.loads(_b64url_decode(body_b64))
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(int(exp), UTC) < datetime.now(UTC):
        raise ValueError("Token has expired")

    return payload


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
        payload = _decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Manage API service lifecycle."""
    global _pool, _config, _redis

    logger.info("🚀 API service starting...")
    _config = ApiConfig.from_env()

    # Start health server on separate port
    health_srv = HealthServer(API_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("🏥 Health server started", port=API_HEALTH_PORT)

    # Parse postgres address (format: host:port)
    host, port_str = _config.postgres_address.rsplit(":", 1)
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

    # Initialize Redis for OAuth state storage
    _redis = await aioredis.from_url(_config.redis_url, decode_responses=True)
    logger.info("🔴 Redis connected", url=_config.redis_url)

    logger.info("✅ API service ready", port=API_PORT)

    yield

    logger.info("🔧 API service shutting down...")
    if _pool:
        await _pool.close()
    if _redis:
        await _redis.aclose()
    health_srv.stop()
    logger.info("✅ API service stopped")


app = FastAPI(
    title="Discogsography API",
    version="0.1.0",
    description="User authentication and Discogs OAuth integration for Discogsography",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> ORJSONResponse:
    """Service health check endpoint."""
    return ORJSONResponse(content=get_health_data())


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest) -> ORJSONResponse:
    """Register a new user account."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    hashed_password = _hash_password(request.password)

    try:
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                    INSERT INTO users (email, hashed_password)
                    VALUES (%s, %s)
                    RETURNING id, email, is_active, created_at
                    """,
                (request.email, hashed_password),
            )
            row = await cur.fetchone()
    except Exception as exc:
        exc_str = str(exc).lower()
        if "unique" in exc_str or "duplicate" in exc_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email address already registered",
            ) from exc
        logger.error("❌ Registration failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        ) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        )

    logger.info("✅ User registered", email=request.email)
    return ORJSONResponse(
        content={
            "id": str(row["id"]),
            "email": row["email"],
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat(),
        },
        status_code=status.HTTP_201_CREATED,
    )


@app.post("/api/auth/login")
async def login(request: LoginRequest) -> ORJSONResponse:
    """Authenticate and receive a JWT access token."""
    if _pool is None or _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, email, hashed_password, is_active FROM users WHERE email = %s",
            (request.email,),
        )
        user = await cur.fetchone()

    if user is None or not user["is_active"] or not _verify_password(request.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = _create_access_token(str(user["id"]), user["email"])
    logger.info("✅ User logged in", email=request.email)

    return ORJSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",  # nosec B105
            "expires_in": expires_in,
        }
    )


@app.get("/api/auth/me")
async def get_me(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    """Get the current authenticated user's information."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, email, is_active, created_at FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return ORJSONResponse(
        content={
            "id": str(user["id"]),
            "email": user["email"],
            "is_active": user["is_active"],
            "created_at": user["created_at"].isoformat(),
        }
    )


async def _get_app_config(key: str) -> str | None:
    """Fetch a value from the app_config table."""
    if _pool is None:
        return None
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT value FROM app_config WHERE key = %s", (key,))
        row = await cur.fetchone()
    return row["value"] if row else None


@app.get("/api/oauth/authorize/discogs")
async def authorize_discogs(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
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

    consumer_key = await _get_app_config("discogs_consumer_key")
    consumer_secret = await _get_app_config("discogs_consumer_secret")

    if not consumer_key or not consumer_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discogs app credentials not configured. Ask an admin to set them via /api/admin/config.",
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
    await _redis.setex(redis_key, REDIS_OAUTH_STATE_TTL, token_data["oauth_token_secret"])

    authorize_url = f"{DISCOGS_AUTHORIZE_URL}?oauth_token={state}"
    logger.info("🔐 Discogs OAuth flow started", user_id=current_user.get("sub"))

    return ORJSONResponse(
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
) -> ORJSONResponse:
    """Complete the Discogs OAuth flow by exchanging the verifier code.

    The user pastes the verifier code shown on Discogs into the app.
    This exchanges the verifier for a permanent access token and stores it.
    """
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    consumer_key = await _get_app_config("discogs_consumer_key")
    consumer_secret = await _get_app_config("discogs_consumer_secret")

    if not consumer_key or not consumer_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discogs app credentials not configured",
        )

    # Retrieve request token secret from Redis
    redis_key = f"{REDIS_STATE_PREFIX}{request.state}"
    token_secret = await _redis.get(redis_key)

    if not token_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state not found or expired. Please restart the OAuth flow.",
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verifier code or OAuth flow failed",
        ) from exc

    # Clean up state from Redis
    await _redis.delete(redis_key)

    user_id = current_user.get("sub")
    discogs_username = identity.get("username", "")
    discogs_user_id = str(identity.get("id", ""))

    # Upsert oauth_tokens record
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
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
                access_data["oauth_token"],
                access_data["oauth_token_secret"],
                discogs_username,
                discogs_user_id,
            ),
        )

    logger.info("✅ Discogs account connected", user_id=user_id, discogs_username=discogs_username)
    return ORJSONResponse(
        content={
            "connected": True,
            "discogs_username": discogs_username,
            "discogs_user_id": discogs_user_id,
        }
    )


@app.get("/api/oauth/status/discogs")
async def discogs_status(
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    """Check if the current user has a connected Discogs account."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
                SELECT provider_username, provider_user_id, updated_at
                FROM oauth_tokens
                WHERE user_id = %s::uuid AND provider = 'discogs'
                """,
            (user_id,),
        )
        token = await cur.fetchone()

    if token is None:
        return ORJSONResponse(content={"connected": False})

    return ORJSONResponse(
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
) -> ORJSONResponse:
    """Disconnect the current user's Discogs account."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    user_id = current_user.get("sub")
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM oauth_tokens WHERE user_id = %s::uuid AND provider = 'discogs'",
            (user_id,),
        )

    logger.info("✅ Discogs account disconnected", user_id=user_id)
    return ORJSONResponse(content={"revoked": True})


@app.put("/api/admin/config/{key}")
async def set_app_config(
    key: str,
    body: dict[str, str],
    current_user: Annotated[dict[str, Any], Depends(_get_current_user)],
) -> ORJSONResponse:
    """Set an admin configuration value (e.g., Discogs consumer key/secret).

    Allowed keys: discogs_consumer_key, discogs_consumer_secret
    """
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    allowed_keys = {"discogs_consumer_key", "discogs_consumer_secret"}
    if key not in allowed_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown config key. Allowed keys: {', '.join(sorted(allowed_keys))}",
        )

    value = body.get("value", "")
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'value' field is required",
        )

    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
                INSERT INTO app_config (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = NOW()
                """,
            (key, value),
        )

    logger.info("✅ App config updated", key=key, user_id=current_user.get("sub"))
    return ORJSONResponse(content={"key": key, "updated": True})


def main() -> None:
    """Entry point for the API service."""
    setup_logging("api", log_file=Path("/logs/api.log"))
    print(
        r"""
    _____  _
   |  __ \(_)
   | |  | |_ ___  ___ ___   __ _ ___  ___   __ _ _ __ __ _ _ __ | |__  _   _
   | |  | | / __|/ __/ _ \ / _` / __|/ _ \ / _` | '__/ _` | '_ \| '_ \| | | |
   | |__| | \__ \ (_| (_) | (_| \__ \  __/| (_| | | | (_| | |_) | | | | |_| |
   |_____/|_|___/\___\___/ \__, |___/\___| \__, |_|  \__,_| .__/|_| |_|\__, |
                            |___/           |___/           |_|          |___/

    API Service — User Accounts & JWT Authentication
    """
    )
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)  # noqa: S104  # nosec B104


if __name__ == "__main__":
    main()
