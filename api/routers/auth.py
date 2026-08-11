"""Auth router — register, login, logout, current-user, password reset, and 2FA endpoints."""

from datetime import UTC, datetime
import json
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
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
    token_revocation_reason,
    verify_totp_code,
)
from api.limiter import limiter
from api.models import (
    ChangePasswordRequest,
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


async def _reject_stale_challenge(payload: dict[str, Any]) -> None:
    """Reject a 2FA challenge that the user's credentials have outlived.

    A challenge token proves knowledge of the password that was current when it
    was minted, and it stays redeemable for its full 5-minute TTL. Redeeming it
    mints a fresh access token whose `iat` is necessarily AFTER the
    `password_changed:{user_id}` marker, so the marker — enforced only at
    access-token validation — could never invalidate it. The invariant ("no
    credential derived from the pre-change password may be honored") has to be
    enforced at the MINT site too, against the challenge's own `iat`
    (discogsography-jxmn).
    """
    if await token_revocation_reason(payload, _redis) is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Challenge invalidated by password change",
        )


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

    logger.info("✅ User registered", user_id=str(row["id"]))
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

    # Stamped BEFORE the password is read, and used as the `iat` of whatever
    # credential this login mints. _verify_password is deliberately slow
    # (PBKDF2, 100k iterations); a password change committing inside that window
    # must invalidate this login, which the `iat <= password_changed` predicate
    # can only see if `iat` predates the marker (discogsography-jxmn).
    credential_issued_at = int(datetime.now(UTC).timestamp())

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
    if not password_ok or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # If TOTP 2FA is enabled, return a challenge instead of an access token
    if user.get("totp_enabled"):
        if _redis is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service not ready (Redis required for 2FA)",
            )
        challenge = create_challenge_token(str(user["id"]), user["email"], _config.jwt_secret_key, issued_at=credential_issued_at)
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

    access_token, expires_in = _create_access_token_fn(str(user["id"]), user["email"], issued_at=credential_issued_at)
    logger.info("✅ User logged in", user_id=str(user["id"]))

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


async def _process_reset_request(user: dict[str, Any] | None) -> None:
    """Mint the reset token, write it to Redis, and send the email — OFF the request path.

    Scheduled unconditionally by the caller (whether or not the account
    exists) and only does real work when ``user`` is truthy. This means the
    HTTP response for reset-request returns after nothing but the initial
    SELECT on both branches, so response timing carries no signal about
    account existence — the Redis `setex` and the outbound Resend HTTP call
    (the actual timing oracle) both happen after the client already has the
    response (discogsography-0lof).
    """
    if not user or _redis is None or _config is None:
        return
    token = secrets.token_urlsafe(32)
    await _redis.setex(
        f"reset:{token}",
        900,  # 15 min TTL
        json.dumps({"user_id": str(user["id"]), "email": user["email"]}),
    )
    # Must be absolute: this link is emailed, and a mail client has no base
    # URL to resolve a relative href against.
    reset_url = f"{_config.app_base_url}/?reset_token={token}"
    if _notification_channel:
        await _notification_channel.send_password_reset(user["email"], reset_url)


@router.post("/api/auth/reset-request")
@limiter.limit("3/minute")
async def reset_request(request: Request, body: ResetRequestModel, background_tasks: BackgroundTasks) -> JSONResponse:  # noqa: ARG001
    """Request a password reset. Same response whether email exists or not."""
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(cur, "SELECT id, email FROM users WHERE email = %s", (body.email,))
        user = await cur.fetchone()

    # Scheduled on BOTH branches — see _process_reset_request docstring.
    background_tasks.add_task(_process_reset_request, user)

    return JSONResponse(content={"message": "If an account exists for that email, a reset link has been sent"})


@router.post("/api/auth/reset-confirm")
@limiter.limit("5/minute")
async def reset_confirm(request: Request, body: ResetConfirmModel) -> JSONResponse:  # noqa: ARG001
    """Confirm a password reset with a valid token and new password."""
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    # Atomically consume the token to prevent concurrent reuse (TOCTOU)
    raw = await _redis.getdel(f"reset:{body.token}")
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
        # Bulk-revoke third-party app tokens too. password_changed:{user_id} only
        # gates JWT validation and TTLs out after jwt_expire_minutes, so it can
        # never durably revoke app tokens (which carry no expiry by design) —
        # revoking the rows themselves is the only correct fix
        # (discogsography-ci4a).
        await execute_sql(
            cur,
            "UPDATE app_tokens SET revoked_at = NOW() WHERE user_id = %s::uuid AND revoked_at IS NULL",
            (user_id,),
        )

    # Invalidate all existing sessions
    await _redis.setex(f"password_changed:{user_id}", _config.jwt_expire_minutes * 60, str(now_ts))

    logger.info("✅ Password reset completed", user_id=user_id)
    return JSONResponse(content={"message": "Password has been reset"})


@router.post("/api/auth/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,  # noqa: ARG001
    current_user: Annotated[dict[str, Any], Depends(_require_user)],
    body: ChangePasswordRequest,
) -> JSONResponse:
    """Change password for the currently authenticated user."""
    if _pool is None or _redis is None or _config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    user_id = current_user.get("sub")

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT hashed_password FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        user = await cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not _verify_password(body.current_password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password")

    hashed_password = _hash_password(body.new_password)
    now_ts = int(datetime.now(UTC).timestamp())

    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET hashed_password = %s, password_changed_at = NOW(), updated_at = NOW() WHERE id = %s::uuid",
            (hashed_password, user_id),
        )
        # Bulk-revoke third-party app tokens too (same pattern as reset-confirm;
        # see discogsography-ci4a for why the Redis password_changed marker
        # alone cannot cover app tokens).
        await execute_sql(
            cur,
            "UPDATE app_tokens SET revoked_at = NOW() WHERE user_id = %s::uuid AND revoked_at IS NULL",
            (user_id,),
        )

    # Invalidate all existing sessions (same pattern as reset-confirm)
    await _redis.setex(f"password_changed:{user_id}", _config.jwt_expire_minutes * 60, str(now_ts))

    logger.info("✅ Password changed", user_id=user_id)
    return JSONResponse(content={"message": "Password has been changed"})


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

    # Refuse to overwrite a LIVE 2FA configuration. When totp_enabled is already
    # TRUE, regenerating totp_secret / totp_recovery_codes would silently orphan
    # the user's authenticator app and printed recovery codes while login still
    # demands 2FA — a permanent lockout. Require an explicit disable first
    # (mirrors the totp_enabled guard in twofa_disable).
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "SELECT totp_enabled FROM users WHERE id = %s::uuid",
            (user_id,),
        )
        existing = await cur.fetchone()

    if existing and existing.get("totp_enabled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled — disable it first before setting up again",
        )

    # Generate TOTP secret and encrypt it
    secret = generate_totp_secret()
    encrypted_secret = encrypt_totp_secret(secret, totp_key)

    # Generate recovery codes
    plaintext_codes, hashed_codes = generate_recovery_codes()

    # Store encrypted secret and hashed recovery codes (but do NOT enable TOTP yet).
    # Guarded WHERE totp_enabled IS NOT TRUE so a concurrent enable cannot be raced.
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            UPDATE users
            SET totp_secret = %s, totp_recovery_codes = %s, updated_at = NOW()
            WHERE id = %s::uuid AND totp_enabled IS NOT TRUE
            """,
            (encrypted_secret, json.dumps(hashed_codes), user_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="2FA is already enabled — disable it first before setting up again",
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

    # Enable TOTP — guarded on the EXACT secret whose code was just verified
    # (bound as `row["totp_secret"]`, read above), not a blind write. Without
    # this guard, a concurrent twofa_disable committing between our SELECT and
    # this UPDATE would land as totp_enabled=TRUE with totp_secret/
    # totp_recovery_codes NULLed — login demands 2FA but neither twofa_verify
    # nor twofa_recovery can ever satisfy it, a permanent lockout
    # (discogsography-8vlp). rowcount 0 means the setup state changed
    # underneath us (disabled, or re-setup with a new secret) — treat that as
    # a conflict rather than silently reporting success.
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET totp_enabled = TRUE, updated_at = NOW() WHERE id = %s::uuid AND totp_secret = %s",
            (user_id, row["totp_secret"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="2FA setup state changed — restart 2FA setup",
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

    await _reject_stale_challenge(payload)

    # Verify challenge exists (without consuming) before checking lockout,
    # so locked-out users don't waste their challenge token.
    challenge_key = f"2fa_challenge:{jti}"
    challenge_data = await _redis.get(challenge_key)
    if not challenge_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge expired or already used")

    user_id = payload["sub"]
    email = payload.get("email", "")

    # The lockout GATE and the failed-attempt INCREMENT must be atomic with
    # each other — not just internally consistent. Previously the lockout
    # check read a plain SELECT (no lock held past that statement, per this
    # repo's autocommit=True pool contract), so N concurrent requests could
    # all read "not locked" before any of them committed the lock, each
    # getting a free TOTP guess (discogsography-vjod). `SELECT ... FOR UPDATE`
    # inside an explicit transaction takes a row lock that concurrent verify
    # attempts for the SAME user serialize on: the second request's SELECT
    # blocks until the first request's transaction (lock check + increment)
    # commits, so it always observes the POST-increment state.
    configured = False
    locked = False
    encryption_missing = False
    code_ok = False
    failed_attempts: int | None = None
    async with _pool.connection() as conn:
        await conn.set_autocommit(False)
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await execute_sql(
                cur,
                "SELECT totp_secret, totp_failed_attempts, totp_locked_until FROM users WHERE id = %s::uuid FOR UPDATE",
                (user_id,),
            )
            user = await cur.fetchone()

            if user and user.get("totp_secret"):
                configured = True
                locked_until = user.get("totp_locked_until")
                if locked_until and locked_until.tzinfo is None:
                    locked_until = locked_until.replace(tzinfo=UTC)
                locked = bool(locked_until and locked_until > datetime.now(UTC))

            totp_key = get_totp_encryption_key(_config.encryption_master_key) if configured and not locked else None
            if configured and not locked and not totp_key:
                encryption_missing = True

            if totp_key:
                secret = decrypt_totp_secret(user["totp_secret"], totp_key)
                # NOTE: the challenge is intentionally NOT consumed until AFTER a
                # successful verification (see success branch below). Consuming it
                # here would burn the challenge on a single mistyped digit, forcing
                # a full re-login for every typo.
                code_ok = verify_totp_code(secret, body.code)
                if not code_ok:
                    # Derive the lock from the freshly-computed value in the SAME
                    # statement, still holding the row lock taken above. When a
                    # previous lock window has already elapsed (totp_locked_until
                    # is set but in the past — the gate above let us through), the
                    # counter resets so each post-expiry window starts fresh
                    # instead of instantly re-locking at 5+1.
                    lock_sql = """
                        UPDATE users
                        SET totp_failed_attempts = CASE
                                WHEN totp_locked_until IS NOT NULL AND totp_locked_until <= NOW() THEN 1
                                ELSE COALESCE(totp_failed_attempts, 0) + 1
                            END,
                            totp_locked_until = CASE
                                WHEN (CASE
                                        WHEN totp_locked_until IS NOT NULL AND totp_locked_until <= NOW() THEN 1
                                        ELSE COALESCE(totp_failed_attempts, 0) + 1
                                      END) >= 5
                                    THEN NOW() + INTERVAL '15 minutes'
                                WHEN totp_locked_until IS NOT NULL AND totp_locked_until <= NOW()
                                    THEN NULL
                                ELSE totp_locked_until
                            END,
                            updated_at = NOW()
                        WHERE id = %s::uuid
                        RETURNING totp_failed_attempts
                    """
                    await execute_sql(cur, lock_sql, (user_id,))
                    updated = await cur.fetchone()
                    failed_attempts = updated["totp_failed_attempts"] if updated else None
        # Transaction commits here (releasing the row lock) before we raise —
        # a locked-out or failed attempt must still be durably recorded even
        # though the HTTP response is an error.

    if not configured:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA not configured")

    if locked:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Account temporarily locked due to failed 2FA attempts")

    if encryption_missing:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encryption not configured")

    if not code_ok:
        logger.warning("⚠️ Failed 2FA attempt", user_id=user_id, attempts=failed_attempts)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    # Success — consume the challenge NOW (only after a correct code) to prevent
    # replay. getdel is atomic, so concurrent requests replaying the same valid
    # challenge race here and exactly one wins; the loser gets None -> 401.
    consumed = await _redis.getdel(challenge_key)
    if not consumed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge expired or already used")

    # Reset attempts
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            "UPDATE users SET totp_failed_attempts = 0, totp_locked_until = NULL, updated_at = NOW() WHERE id = %s::uuid",
            (user_id,),
        )

    # Issue access token, stamped with the CHALLENGE's iat: the credential this
    # token derives from is the password proven at login, so a password change
    # after that moment must invalidate it too (discogsography-jxmn).
    access_token, expires_in = _create_access_token_fn(user_id, email, issued_at=payload.get("iat"))
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

    await _reject_stale_challenge(payload)

    # Verify the challenge EXISTS (without consuming) before validating the code,
    # so a mistyped recovery code does not burn the challenge token. The challenge
    # is consumed only after the recovery code is successfully redeemed below.
    challenge_key = f"2fa_challenge:{jti}"
    challenge_data = await _redis.get(challenge_key)
    if not challenge_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge expired or already used")

    user_id = payload["sub"]
    email = payload.get("email", "")

    submitted_hash = hash_recovery_code(body.code)

    # Consume the recovery code ATOMICALLY in a single guarded statement. Recovery
    # codes are one-time by contract; a Python read-modify-write across two
    # autocommit round-trips loses updates under concurrency, letting a used code
    # be resurrected (last-writer-wins) or the same code be redeemed twice.
    #
    # `totp_recovery_codes ? %s` guards that the hash is still present, and
    # `totp_recovery_codes - %s` removes it in the same UPDATE. Under Postgres
    # row locking, concurrent redemptions serialize and the WHERE qual is
    # re-evaluated against the committed row, so only one redemption of a given
    # code can ever match (rowcount 1); the rest match nothing (rowcount 0).
    # Recovery is an equally strong proof of account control as a correct TOTP
    # code (password + a one-time recovery code), so its success path must
    # reset the failed-attempt/lockout columns exactly like twofa_verify's
    # success path does — folded into this same guarded UPDATE so it only
    # fires when the code actually matched (discogsography-cflq). Without
    # this, stale lockout state from before the recovery login survives it
    # and can 429 a CORRECT TOTP code on the very next login.
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await execute_sql(
            cur,
            """
            UPDATE users
            SET totp_recovery_codes = totp_recovery_codes - %s,
                totp_failed_attempts = 0,
                totp_locked_until = NULL,
                updated_at = NOW()
            WHERE id = %s::uuid
              AND totp_recovery_codes IS NOT NULL
              AND totp_recovery_codes ? %s
            RETURNING totp_recovery_codes
            """,
            (submitted_hash, user_id, submitted_hash),
        )
        updated = await cur.fetchone()

    if not updated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid recovery code")

    remaining: list[str] = (
        json.loads(updated["totp_recovery_codes"]) if isinstance(updated["totp_recovery_codes"], str) else (updated["totp_recovery_codes"] or [])
    )

    # Recovery code redeemed — now consume the challenge so it cannot be replayed.
    # getdel is atomic, so concurrent requests replaying the same challenge
    # (with different recovery codes) race here and exactly one wins; the
    # loser must be rejected — mirrors twofa_verify's identical check
    # (discogsography-kqw4). The recovery code redeemed above is *not*
    # un-spent on this path; that's an accepted, bounded trade (same one
    # twofa_verify's loser already takes on its TOTP code).
    consumed = await _redis.getdel(challenge_key)
    if not consumed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge expired or already used")

    # Issue access token, stamped with the CHALLENGE's iat (see twofa_verify).
    access_token, expires_in = _create_access_token_fn(user_id, email, issued_at=payload.get("iat"))
    logger.info("✅ 2FA recovery code used", user_id=user_id, remaining_codes=len(remaining))

    content: dict[str, Any] = {
        "access_token": access_token,
        "token_type": "bearer",  # nosec B105
        "expires_in": expires_in,
    }

    if len(remaining) == 0:
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
