"""Auth router — register, login, logout, current-user, password reset, and 2FA endpoints."""

from datetime import UTC, datetime
import json
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
import structlog

from api.auth import (
    _DUMMY_HASH,
    _hash_password,
    _verify_password,
    create_challenge_token,
    decode_token,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    get_totp_encryption_key,
    hash_recovery_code,
    verify_totp_code,
)
from api.limiter import limiter
from api.models import (
    LoginRequest,
    RegisterRequest,
    ResetConfirmModel,
    ResetRequestModel,
    TwoFactorCodeModel,
    TwoFactorDisableModel,
    TwoFactorRecoveryModel,
    TwoFactorSetupResponse,
    TwoFactorVerifyModel,
)
from common.config import ApiConfig
from common.query_debug import execute_sql


logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state (set via configure())
_pool: Any = None
_redis: Any = None
_config: ApiConfig | None = None
_get_current_user_fn: Any = None
_create_access_token_fn: Any = None
_notification_channel: Any = None

_security = HTTPBearer()


def configure(
    pool: Any,
    redis: Any,
    config: ApiConfig,
    get_current_user: Any,
    create_access_token: Any,
    *,
    notification_channel: Any = None,
) -> None:
    """Initialise module state — called once during app lifespan startup."""
    global _pool, _redis, _config, _get_current_user_fn, _create_access_token_fn, _notification_channel
    _pool = pool
    _redis = redis
    _config = config
    _get_current_user_fn = get_current_user
    _create_access_token_fn = create_access_token
    _notification_channel = notification_channel


async def _require_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> dict[str, Any]:
    """Validate JWT and return user payload."""
    if _get_current_user_fn is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    result: dict[str, Any] = await _get_current_user_fn(credentials)
    return result


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@router.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(request: Request, body: RegisterRequest) -> JSONResponse:  # noqa: ARG001
    """Register a new user account."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    hashed_password = _hash_password(body.password)

    try:
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await execute_sql(
                cur,
                """
                    INSERT INTO users (email, hashed_password)
                    VALUES (%s, %s)
                    RETURNING id, email, is_active, created_at
                    """,
                (body.email, hashed_password),
            )
            row = await cur.fetchone()
    except Exception as exc:
        exc_str = str(exc).lower()
        if "unique" in exc_str or "duplicate" in exc_str:
            # L1: Return same response for duplicate email to prevent user enumeration
            logger.info("📋 Registration attempt for existing email (blind)")
            return JSONResponse(
                content={"message": "Registration processed"},
                status_code=status.HTTP_201_CREATED,
            )
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

    logger.info("✅ User registered", email=body.email)
    return JSONResponse(
        content={"message": "Registration processed"},
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/api/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest) -> JSONResponse:  # noqa: ARG001
    """Authenticate and receive a JWT access token."""
    if _pool is None or _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT id, email, hashed_password, is_active, totp_enabled FROM users WHERE email = %s",
            (body.email,),
        )
        user = await cur.fetchone()

    # H4: Constant-time check to prevent user enumeration via timing
    if user is None:
        _verify_password(body.password, _DUMMY_HASH)  # consume same time as real verify
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    password_ok = _verify_password(body.password, user["hashed_password"])
    if not user["is_active"] or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # If TOTP 2FA is enabled, return a challenge instead of an access token
    if user.get("totp_enabled"):
        challenge = create_challenge_token(str(user["id"]), user["email"], _config.jwt_secret_key)
        challenge_payload = decode_token(challenge, _config.jwt_secret_key)
        jti = challenge_payload["jti"]
        # Store challenge JTI in Redis with 5 min TTL
        await _redis.setex(f"2fa_challenge:{jti}", 300, str(user["id"]))
        return JSONResponse(
            content={
                "requires_2fa": True,
                "challenge_token": challenge,
                "message": "TOTP verification required",
            }
        )

    access_token, expires_in = _create_access_token_fn(str(user["id"]), user["email"])
    logger.info("✅ User logged in", email=body.email)

    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",  # nosec B105
            "expires_in": expires_in,
        }
    )


@router.post("/api/auth/logout")
async def logout(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
) -> JSONResponse:
    """Logout and revoke the current JWT token."""
    if _redis:
        jti: str | None = current_user.get("jti")
        exp: int | None = current_user.get("exp")
        if jti:
            now = int(datetime.now(UTC).timestamp())
            ttl = max((exp - now), 60) if exp else 3600
            await _redis.setex(f"revoked:jti:{jti}", ttl, "1")
    return JSONResponse(content={"logged_out": True})


@router.get("/api/auth/me")
async def get_me(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
) -> JSONResponse:
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
        await execute_sql(
            cur,
            "SELECT id, email, is_active, created_at, totp_enabled FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return JSONResponse(
        content={
            "id": str(user["id"]),
            "email": user["email"],
            "is_active": user["is_active"],
            "created_at": user["created_at"].isoformat(),
            "totp_enabled": bool(user.get("totp_enabled", False)),
        }
    )


# ---------------------------------------------------------------------------
# Password reset endpoints
# ---------------------------------------------------------------------------


@router.post("/api/auth/reset-request")
@limiter.limit("3/minute")
async def reset_request(request: Request, body: ResetRequestModel) -> JSONResponse:  # noqa: ARG001
    """Request a password reset. Same response whether email exists or not."""
    if _pool is None or _redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, "SELECT id, email FROM users WHERE email = %s", (body.email,))
        user = await cur.fetchone()

    if user:
        token = secrets.token_urlsafe(32)
        await _redis.setex(
            f"reset:{token}",
            900,  # 15 min TTL
            json.dumps({"user_id": str(user["id"]), "email": user["email"]}),
        )
        reset_url = f"/reset?token={token}"
        if _notification_channel:
            await _notification_channel.send_password_reset(user["email"], reset_url)

    return JSONResponse(content={"message": "If an account exists for that email, a reset link has been sent"})


@router.post("/api/auth/reset-confirm")
@limiter.limit("5/minute")
async def reset_confirm(request: Request, body: ResetConfirmModel) -> JSONResponse:  # noqa: ARG001
    """Confirm a password reset with a valid token and new password."""
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    raw = await _redis.get(f"reset:{body.token}")
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    token_data = json.loads(raw)
    user_id = token_data["user_id"]
    hashed_password = _hash_password(body.new_password)
    now_ts = int(datetime.now(UTC).timestamp())

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET hashed_password = %s, password_changed_at = NOW(), updated_at = NOW() WHERE id = %s::uuid",
            (hashed_password, user_id),
        )

    # Invalidate all existing sessions
    await _redis.setex(f"password_changed:{user_id}", _config.jwt_expire_minutes * 60, str(now_ts))
    # Delete the used reset token (single-use)
    await _redis.delete(f"reset:{body.token}")

    logger.info("✅ Password reset completed", user_id=user_id)
    return JSONResponse(content={"message": "Password has been reset"})


# ---------------------------------------------------------------------------
# Two-Factor Authentication (2FA) endpoints
# ---------------------------------------------------------------------------


@router.post("/api/auth/2fa/setup")
async def twofa_setup(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
) -> JSONResponse:
    """Set up TOTP 2FA for the current user — returns secret, QR URI, and recovery codes."""
    if _pool is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    totp_key = get_totp_encryption_key(_config.encryption_master_key)
    if not totp_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encryption not configured")

    user_id = current_user.get("sub")
    email = current_user.get("email", "")

    # Generate TOTP secret and encrypt it
    secret = generate_totp_secret()
    encrypted_secret = encrypt_totp_secret(secret, totp_key)

    # Generate recovery codes
    plaintext_codes, hashed_codes = generate_recovery_codes()

    # Store encrypted secret and hashed recovery codes (but do NOT enable TOTP yet)
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            UPDATE users
            SET totp_secret = %s, totp_recovery_codes = %s, updated_at = NOW()
            WHERE id = %s::uuid
            """,
            (encrypted_secret, json.dumps(hashed_codes), user_id),
        )

    otpauth_uri = f"otpauth://totp/Discogsography:{email}?secret={secret}&issuer=Discogsography"

    logger.info("🔐 2FA setup initiated", user_id=user_id)
    return JSONResponse(
        content=TwoFactorSetupResponse(
            secret=secret,
            otpauth_uri=otpauth_uri,
            recovery_codes=plaintext_codes,
        ).model_dump()
    )


@router.post("/api/auth/2fa/confirm")
async def twofa_confirm(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    body: TwoFactorCodeModel,
) -> JSONResponse:
    """Confirm 2FA setup by verifying a TOTP code — enables TOTP on the account."""
    if _pool is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    totp_key = get_totp_encryption_key(_config.encryption_master_key)
    if not totp_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encryption not configured")

    user_id = current_user.get("sub")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT totp_secret FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        row = await cur.fetchone()

    if not row or not row.get("totp_secret"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA not set up — call /api/auth/2fa/setup first")

    secret = decrypt_totp_secret(row["totp_secret"], totp_key)
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    # Enable TOTP
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET totp_enabled = TRUE, updated_at = NOW() WHERE id = %s::uuid",
            (user_id,),
        )

    logger.info("✅ 2FA enabled", user_id=user_id)
    return JSONResponse(content={"message": "2FA has been enabled"})


@router.post("/api/auth/2fa/verify")
@limiter.limit("10/minute")
async def twofa_verify(request: Request, body: TwoFactorVerifyModel) -> JSONResponse:  # noqa: ARG001
    """Verify a TOTP code during login using a challenge token."""
    if _pool is None or _config is None or _redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    # Validate challenge token
    try:
        payload = decode_token(body.challenge_token, _config.jwt_secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired challenge token") from exc

    if payload.get("type") != "2fa_challenge":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token type")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token")

    # Check challenge exists in Redis
    challenge_data = await _redis.get(f"2fa_challenge:{jti}")
    if not challenge_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge expired or already used")

    user_id = payload["sub"]
    email = payload.get("email", "")

    # Fetch user TOTP data
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT totp_secret, totp_failed_attempts, totp_locked_until FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if not user or not user.get("totp_secret"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA not configured")

    # Check lockout
    locked_until = user.get("totp_locked_until")
    if locked_until and locked_until > datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Account temporarily locked due to failed 2FA attempts")

    totp_key = get_totp_encryption_key(_config.encryption_master_key)
    if not totp_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encryption not configured")

    secret = decrypt_totp_secret(user["totp_secret"], totp_key)

    if not verify_totp_code(secret, body.code):
        # Increment failed attempts
        failed = (user.get("totp_failed_attempts") or 0) + 1
        lock_sql = "UPDATE users SET totp_failed_attempts = %s, updated_at = NOW()"
        params: list[Any] = [failed]
        if failed >= 5:
            lock_sql += ", totp_locked_until = NOW() + INTERVAL '15 minutes'"
        lock_sql += " WHERE id = %s::uuid"
        params.append(user_id)

        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await execute_sql(cur, lock_sql, tuple(params))

        logger.warning("⚠️ Failed 2FA attempt", user_id=user_id, attempts=failed)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    # Success — reset attempts and delete challenge
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET totp_failed_attempts = 0, totp_locked_until = NULL, updated_at = NOW() WHERE id = %s::uuid",
            (user_id,),
        )
    await _redis.delete(f"2fa_challenge:{jti}")

    # Issue access token
    access_token, expires_in = _create_access_token_fn(user_id, email)
    logger.info("✅ 2FA verification successful", user_id=user_id)
    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",  # nosec B105
            "expires_in": expires_in,
        }
    )


@router.post("/api/auth/2fa/recovery")
@limiter.limit("5/minute")
async def twofa_recovery(request: Request, body: TwoFactorRecoveryModel) -> JSONResponse:  # noqa: ARG001
    """Use a recovery code to complete 2FA login."""
    if _pool is None or _config is None or _redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    # Validate challenge token
    try:
        payload = decode_token(body.challenge_token, _config.jwt_secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired challenge token") from exc

    if payload.get("type") != "2fa_challenge":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token type")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token")

    challenge_data = await _redis.get(f"2fa_challenge:{jti}")
    if not challenge_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge expired or already used")

    user_id = payload["sub"]
    email = payload.get("email", "")

    # Fetch recovery codes
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT totp_recovery_codes FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if not user or not user.get("totp_recovery_codes"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No recovery codes available")

    stored_hashes: list[str] = (
        json.loads(user["totp_recovery_codes"]) if isinstance(user["totp_recovery_codes"], str) else user["totp_recovery_codes"]
    )
    submitted_hash = hash_recovery_code(body.code)

    if submitted_hash not in stored_hashes:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid recovery code")

    # Remove used code
    stored_hashes.remove(submitted_hash)

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET totp_recovery_codes = %s, updated_at = NOW() WHERE id = %s::uuid",
            (json.dumps(stored_hashes), user_id),
        )
    await _redis.delete(f"2fa_challenge:{jti}")

    # Issue access token
    access_token, expires_in = _create_access_token_fn(user_id, email)
    logger.info("✅ 2FA recovery code used", user_id=user_id, remaining_codes=len(stored_hashes))

    content: dict[str, Any] = {
        "access_token": access_token,
        "token_type": "bearer",  # nosec B105
        "expires_in": expires_in,
    }

    if len(stored_hashes) == 0:
        content["warning"] = "This was your last recovery code. Please set up new recovery codes."

    return JSONResponse(content=content)


@router.post("/api/auth/2fa/disable")
async def twofa_disable(
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    body: TwoFactorDisableModel,
) -> JSONResponse:
    """Disable 2FA — requires both password and current TOTP code."""
    if _pool is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    user_id = current_user.get("sub")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT hashed_password, totp_secret, totp_enabled FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Verify password
    if not _verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    # Verify TOTP code
    if not user.get("totp_enabled") or not user.get("totp_secret"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")

    totp_key = get_totp_encryption_key(_config.encryption_master_key)
    if not totp_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encryption not configured")

    secret = decrypt_totp_secret(user["totp_secret"], totp_key)
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    # Clear all TOTP fields
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            UPDATE users
            SET totp_secret = NULL, totp_enabled = FALSE, totp_recovery_codes = NULL,
                totp_failed_attempts = 0, totp_locked_until = NULL, updated_at = NOW()
            WHERE id = %s::uuid
            """,
            (user_id,),
        )

    logger.info("🔐 2FA disabled", user_id=user_id)
    return JSONResponse(content={"message": "2FA has been disabled"})
