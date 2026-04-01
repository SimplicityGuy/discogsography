"""Shared FastAPI dependency functions for API routers."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row

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
    # Check JTI revocation
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked", headers={"WWW-Authenticate": "Bearer"})
    # Check password-changed revocation
    user_id = payload.get("sub")
    if user_id and _redis:
        pw_changed = await _redis.get(f"password_changed:{user_id}")
        if pw_changed:
            issued_at = payload.get("iat", 0)
            if issued_at <= int(pw_changed):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalidated by password change", headers={"WWW-Authenticate": "Bearer"}
                )
    return payload


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
    # Check token revocation in Redis
    jti: str | None = payload.get("jti")
    if jti and _redis:
        revoked = await _redis.get(f"revoked:jti:{jti}")
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")
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
