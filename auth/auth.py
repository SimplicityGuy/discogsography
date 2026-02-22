"""Auth microservice for discogsography — user accounts and JWT authentication."""

import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row

from auth.models import LoginRequest, RegisterRequest
from common import AsyncPostgreSQLPool, HealthServer, setup_logging
from common.config import AuthConfig


logger = structlog.get_logger(__name__)

# Module-level state
_pool: AsyncPostgreSQLPool | None = None
_config: AuthConfig | None = None
_security = HTTPBearer()

AUTH_PORT = 8004
AUTH_HEALTH_PORT = 8005


def get_health_data() -> dict[str, Any]:
    """Return health status for the auth service."""
    return {
        "status": "healthy" if _pool else "starting",
        "service": "auth",
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
    signature = _b64url_encode(
        hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    )
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
    expected_sig = _b64url_encode(
        hmac.new(_config.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    )

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
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[misc]
    """Manage auth service lifecycle."""
    global _pool, _config

    logger.info("🚀 Auth service starting...")
    _config = AuthConfig.from_env()

    # Start health server on separate port
    health_srv = HealthServer(AUTH_HEALTH_PORT, get_health_data)
    health_srv.start_background()
    logger.info("🏥 Health server started", port=AUTH_HEALTH_PORT)

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
    logger.info("✅ Auth service ready", port=AUTH_PORT)

    yield

    logger.info("🔧 Auth service shutting down...")
    if _pool:
        await _pool.close()
    health_srv.stop()
    logger.info("✅ Auth service stopped")


app = FastAPI(
    title="Discogsography Auth",
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
        async with _pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
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
            )
        logger.error("❌ Registration failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        )

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

    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
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
            "token_type": "bearer",
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

    async with _pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
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


def main() -> None:
    """Entry point for the auth service."""
    setup_logging("auth", log_file=Path("/logs/auth.log"))
    print(  # noqa: T201
        r"""
    _____  _
   |  __ \(_)
   | |  | |_ ___  ___ ___   __ _ ___  ___   __ _ _ __ __ _ _ __ | |__  _   _
   | |  | | / __|/ __/ _ \ / _` / __|/ _ \ / _` | '__/ _` | '_ \| '_ \| | | |
   | |__| | \__ \ (_| (_) | (_| \__ \  __/| (_| | | | (_| | |_) | | | | |_| |
   |_____/|_|___/\___\___/ \__, |___/\___| \__, |_|  \__,_| .__/|_| |_|\__, |
                            |___/           |___/           |_|          |___/

    Auth Service — User Accounts & JWT Authentication
    """
    )
    uvicorn.run(app, host="0.0.0.0", port=AUTH_PORT)  # noqa: S104


if __name__ == "__main__":
    main()
