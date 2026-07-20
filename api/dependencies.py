"""Shared FastAPI dependency functions for API routers."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row

from api.app_tokens import (
    TOKEN_PREFIX as _APP_TOKEN_PREFIX,
    AppTokenAuth,  # noqa: F401  — re-exported for callers
    _lookup_active_token,
    hash_token,
    require_app_token,  # noqa: F401  — re-exported for callers
)
from api.auth import decode_token


_security = HTTPBearer(auto_error=False)
_jwt_secret: str | None = None
_redis: Any = None
_pool: Any = None


def configure(jwt_secret: str | None, redis: Any = None, pool: Any = None) -> None:
    global _jwt_secret, _redis, _pool
    _jwt_secret = jwt_secret
    _redis = redis
    _pool = pool


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any] | None:
    if credentials is None or _jwt_secret is None:
        return None
    try:
        payload = decode_token(credentials.credentials, _jwt_secret)
    except ValueError:
        return None
    # Allowlist: only pure access tokens (no `type` claim) resolve to a user.
    # Admin and 2FA challenge tokens must not be treated as an authenticated user.
    if payload.get("type") is not None:
        return None
    # Check JTI revocation
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            return None
    # Check password-changed revocation
    user_id = payload.get("sub")
    if user_id and _redis:
        pw_changed = await _redis.get(f"password_changed:{user_id}")
        if pw_changed:
            issued_at = payload.get("iat", 0)
            if issued_at <= int(pw_changed):
                return None
    return payload


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    if _jwt_secret is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personalized endpoints not enabled")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    # Reject admin tokens on user endpoints
    if payload.get("type") == "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin tokens cannot be used for user endpoints")
    # Allowlist: only pure access tokens (which carry NO `type` claim) may
    # authenticate user endpoints. A 2FA challenge token (type="2fa_challenge")
    # proves only the password — it must NOT grant access before TOTP is verified.
    if payload.get("type") is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    # Validate sub claim presence
    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    # Check JTI revocation
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked", headers={"WWW-Authenticate": "Bearer"})
    if user_id and _redis:
        pw_changed = await _redis.get(f"password_changed:{user_id}")
        if pw_changed:
            issued_at = payload.get("iat", 0)
            if issued_at <= int(pw_changed):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalidated by password change", headers={"WWW-Authenticate": "Bearer"}
                )
    return payload


@dataclass(frozen=True, slots=True)
class UnifiedAuth:
    """Resolved authentication context — populated by either JWT or app-token path.

    Endpoints that accept both first-party and third-party tokens consume this
    so they don't need to branch on auth path in the handler body.
    """

    user_id: str
    via: Literal["jwt", "app_token"]
    token_id: str | None  # set only when via == "app_token"
    scopes: list[str]  # empty for JWT (no scope vocabulary on first-party auth)


def require_user_or_app_token(scopes: list[str]) -> Any:
    """Dependency factory that accepts EITHER a first-party JWT OR an app token.

    Used by endpoints exposed to third-party apps (GRUVAX, MCP) where the same
    behavior should be reachable via the user's own login session OR via a
    delegated, scoped app token.

    Routing rule: if the Bearer credential starts with the app-token prefix
    (`dscg_`), it goes through app-token auth + scope check. Otherwise it goes
    through the existing `require_user` flow. This keeps the JWT path
    1:1 with the existing behavior — no surprise drift for existing clients.

    Returns a `UnifiedAuth` so the handler reads `auth.user_id` regardless of path.
    """
    required_scopes = list(scopes)

    async def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
    ) -> UnifiedAuth:
        # ─── App-token path ─────────────────────────────────────────────────
        # Only routes here when the caller explicitly presents an app token.
        # No credentials, JWT, or anything else falls through to require_user
        # so the JWT path's 503/401 ordering and revocation checks are preserved
        # byte-for-byte for existing clients.
        if credentials is not None and credentials.credentials.startswith(_APP_TOKEN_PREFIX):
            row = await _lookup_active_token(hash_token(credentials.credentials))
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or revoked app token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            granted = list(row.get("scope") or [])
            missing = [s for s in required_scopes if s not in granted]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"App token missing required scope(s): {', '.join(missing)}",
                )
            return UnifiedAuth(
                user_id=str(row["user_id"]),
                via="app_token",
                token_id=str(row["id"]),
                scopes=granted,
            )

        # ─── JWT path ───────────────────────────────────────────────────────
        # Delegated entirely to require_user so behavior is identical to before:
        # _jwt_secret is None → 503; missing credentials → 401; invalid → 401;
        # admin token → 403; jti / password-changed revocation → 401.
        payload = await require_user(credentials)
        user_id_value = payload.get("sub")
        if not user_id_value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return UnifiedAuth(
            user_id=str(user_id_value),
            via="jwt",
            token_id=None,
            scopes=[],
        )

    return dependency


async def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> dict[str, Any]:
    """Require a valid admin JWT token. Rejects non-admin tokens with 403."""
    if _jwt_secret is None:
        raise HTTPException(status_code=503, detail="Admin endpoints not configured")
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_token(credentials.credentials, _jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if payload.get("type") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # Validate sub claim presence
    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    # Check token revocation in Redis
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")
    # Check password-changed revocation
    if _redis:
        pw_changed = await _redis.get(f"password_changed:{user_id}")
        if pw_changed:
            issued_at = payload.get("iat", 0)
            if issued_at <= int(pw_changed):
                raise HTTPException(status_code=401, detail="Token invalidated by password change")
    # DB verification: confirm user exists and is_admin=True
    if _pool is not None:
        async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT is_admin FROM users WHERE id = %s AND is_active = true",
                (payload["sub"],),
            )
            row = await cur.fetchone()
        if row is None or not row["is_admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
    return payload
