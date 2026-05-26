"""Third-party app token authorization.

Implements revocable Bearer tokens (`dscg_<base64url>`) that authorize third-party
apps (e.g. GRUVAX kiosk) to call scoped endpoints. Plaintext is shown ONCE at mint
time; only the SHA-256 hex hash is persisted. Revoked rows are tombstones — never
deleted — so the audit trail is preserved.

Schema: see schema-init/postgres_schema.py — table `app_tokens`.
Contract artifact: docs/specs/v2-gruvax-integration.md (written in P7).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import logging
import secrets
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row


if TYPE_CHECKING:
    from uuid import UUID


logger = logging.getLogger(__name__)


# Plaintext token format. `dscg_` prefix is visually distinctive so a leaked token
# in logs/screenshots is recognizable; 32 random bytes (base64url-encoded) give
# 256 bits of entropy — collision-resistant well beyond the SHA-256 ceiling.
TOKEN_PREFIX = "dscg_"  # nosec B105  # noqa: S105
TOKEN_ENTROPY_BYTES = 32

_security = HTTPBearer(auto_error=False)
_pool: Any = None

# Strong references to fire-and-forget background tasks so the event loop
# doesn't garbage-collect them mid-flight (RUF006 / asyncio docs).
_background_tasks: set[asyncio.Task[None]] = set()


def configure(pool: Any) -> None:
    """Wire the PG pool from api.api startup."""
    global _pool
    _pool = pool


@dataclass(frozen=True, slots=True)
class AppTokenAuth:
    """Resolved authentication context for an app-token request."""

    user_id: str
    token_id: str
    name: str
    scopes: list[str]


def generate_plaintext_token() -> str:
    """Mint a fresh plaintext token. Caller is responsible for showing it ONCE."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_token(plaintext: str) -> str:
    """SHA-256 hex digest of the plaintext. 64 chars, matches token_hash VARCHAR(64)."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def mint_token(user_id: str, name: str, scopes: list[str]) -> tuple[UUID, str]:
    """Insert a new app_tokens row and return `(token_id, plaintext)`.

    The plaintext MUST be returned to the caller exactly once — it is not recoverable
    from the database.
    """
    if _pool is None:
        raise RuntimeError("app_tokens.configure(pool) was not called")
    plaintext = generate_plaintext_token()
    token_hash = hash_token(plaintext)
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO app_tokens (user_id, name, scope, token_hash)
            VALUES (%s::uuid, %s, %s, %s)
            RETURNING id
            """,
            (user_id, name, scopes, token_hash),
        )
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING returned no row")
    return row["id"], plaintext


async def list_user_tokens(user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return `(active, revoked)` rows for the given user. token_hash is NEVER returned."""
    if _pool is None:
        raise RuntimeError("app_tokens.configure(pool) was not called")
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, name, scope, created_at, last_used_at, revoked_at
            FROM app_tokens
            WHERE user_id = %s::uuid
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    active = [r for r in rows if r["revoked_at"] is None]
    revoked = [r for r in rows if r["revoked_at"] is not None]
    return active, revoked


async def revoke_token(token_id: str, user_id: str) -> bool:
    """Set revoked_at=NOW() for the row if owned by user_id and not already revoked.

    Returns True on revoke, False if no such active token exists for that user.
    Tombstone preserved — never deletes the row.
    """
    if _pool is None:
        raise RuntimeError("app_tokens.configure(pool) was not called")
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE app_tokens
            SET revoked_at = NOW()
            WHERE id = %s::uuid AND user_id = %s::uuid AND revoked_at IS NULL
            """,
            (token_id, user_id),
        )
        return bool(cur.rowcount > 0)


async def _touch_last_used_at(token_id: str) -> None:
    """Best-effort fire-and-forget update of last_used_at. Failures MUST NOT propagate."""
    if _pool is None:
        return
    try:
        async with _pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "UPDATE app_tokens SET last_used_at = NOW() WHERE id = %s::uuid",
                (token_id,),
            )
    except Exception:
        # Best-effort — never fail the request because the bookkeeping update failed.
        logger.exception("⚠️ Failed to bump last_used_at on row id=%s", token_id)


def _parse_bearer(credentials: HTTPAuthorizationCredentials | None) -> str:
    """Extract the Bearer token plaintext from credentials, or raise 401."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # FastAPI's HTTPBearer already enforces the "Bearer " scheme; reject anything
    # without our prefix (cheap pre-DB filter to skip obviously bogus values).
    plaintext = credentials.credentials
    if not plaintext.startswith(TOKEN_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid app token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return plaintext


async def _lookup_active_token(token_hash: str) -> dict[str, Any] | None:
    """Fetch the active row for a token_hash, or None if missing/revoked."""
    if _pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="App-token auth not enabled",
        )
    async with _pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, user_id, name, scope
            FROM app_tokens
            WHERE token_hash = %s AND revoked_at IS NULL
            """,
            (token_hash,),
        )
        row: dict[str, Any] | None = await cur.fetchone()
        return row


def require_app_token(scopes: list[str]) -> Any:
    """FastAPI dependency factory.

    Usage:
        @router.get("/api/...", dependencies=[Depends(require_app_token(["collection:read"]))])

    Or, to consume the resolved auth context:
        async def endpoint(auth: Annotated[AppTokenAuth, Depends(require_app_token(["collection:read"]))]):
            user_id = auth.user_id

    Failure modes:
        - Missing/malformed Authorization header → 401
        - Token not in DB or revoked → 401
        - Token valid but lacks any of the requested scopes → 403
        - Bookkeeping (last_used_at) failure → request still succeeds, error logged
    """
    required = list(scopes)

    async def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
    ) -> AppTokenAuth:
        plaintext = _parse_bearer(credentials)
        token_hash = hash_token(plaintext)
        row = await _lookup_active_token(token_hash)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked app token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Defense in depth: hmac.compare_digest on the canonical hash even though
        # the WHERE clause already filtered. Guards against any future fast-path
        # that bypasses the index (e.g. column rename, query restructure).
        stored_hash = hash_token(plaintext)
        if not hmac.compare_digest(stored_hash, token_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid app token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        granted_scopes = list(row.get("scope") or [])
        missing = [s for s in required if s not in granted_scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"App token missing required scope(s): {', '.join(missing)}",
            )

        # Fire-and-forget last_used_at update — explicit task so a slow PG round
        # trip never blocks the request. Reference held in _background_tasks
        # so the event loop does not garbage-collect the coroutine mid-flight.
        task = asyncio.create_task(_touch_last_used_at(str(row["id"])))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return AppTokenAuth(
            user_id=str(row["user_id"]),
            token_id=str(row["id"]),
            name=str(row["name"]),
            scopes=granted_scopes,
        )

    return dependency
