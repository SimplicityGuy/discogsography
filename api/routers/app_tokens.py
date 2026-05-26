"""User-facing endpoints for managing app tokens (third-party app authorization).

All endpoints here are gated by `require_user` (first-party JWT). The actual
token-authenticated endpoints are wired in P5 — this router only deals with
the *management* surface: mint, list, revoke.

The plaintext token is returned EXACTLY ONCE from POST /api/user/app-tokens
and is never recoverable thereafter — only its SHA-256 hex hash is persisted.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
import structlog

from api.app_tokens import (
    list_user_tokens as _list_user_tokens,
    mint_token as _mint_token,
    revoke_token as _revoke_token,
)
from api.dependencies import require_user
from api.models import MintAppTokenRequest


logger = structlog.get_logger(__name__)

router = APIRouter()


# Public scope vocabulary. Centralized here so future scopes are added in one place
# and the settings UI can enumerate options without hardcoding.
ALLOWED_SCOPES = frozenset({"collection:read"})


@router.post("/api/user/app-tokens", status_code=status.HTTP_201_CREATED)
async def mint_app_token(
    body: MintAppTokenRequest,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    """Mint a new app token. Plaintext is returned ONCE — never recoverable."""
    unknown = [s for s in body.scopes if s not in ALLOWED_SCOPES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown scope(s): {', '.join(unknown)}",
        )

    user_id: str = current_user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name must be non-empty")

    token_id, plaintext = await _mint_token(user_id=user_id, name=name, scopes=list(body.scopes))

    # Re-read the row to surface server-generated created_at — saves us a SELECT race.
    active, _revoked = await _list_user_tokens(user_id)
    created_at = next((str(t["created_at"]) for t in active if str(t["id"]) == str(token_id)), None)

    logger.info("🔐 app token minted", user_id=user_id, token_id=str(token_id), scopes=list(body.scopes))
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "id": str(token_id),
            "name": name,
            "scopes": list(body.scopes),
            "token": plaintext,
            "created_at": created_at,
        },
    )


@router.get("/api/user/app-tokens")
async def list_app_tokens(
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> JSONResponse:
    """Return the current user's active + revoked (tombstone) tokens. token_hash is never returned."""
    user_id: str = current_user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    active, revoked = await _list_user_tokens(user_id)

    def _shape_active(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "scopes": list(row.get("scope") or []),
            "created_at": _isoformat(row.get("created_at")),
            "last_used_at": _isoformat(row.get("last_used_at")),
        }

    def _shape_revoked(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "revoked_at": _isoformat(row.get("revoked_at")),
        }

    return JSONResponse(
        content={
            "active": [_shape_active(r) for r in active],
            "revoked": [_shape_revoked(r) for r in revoked],
        }
    )


@router.delete("/api/user/app-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_app_token(
    token_id: str,
    current_user: Annotated[dict[str, Any], Depends(require_user)],
) -> Response:
    """Revoke (tombstone) the named token. 404 if not owned by the caller."""
    user_id: str = current_user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    success = await _revoke_token(token_id=token_id, user_id=user_id)
    if not success:
        # Owner-scoped check happens inside revoke_token's WHERE clause; failure here
        # could mean: wrong owner, unknown id, or already-revoked. We don't disclose
        # which to avoid leaking token-existence info to other users.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    logger.info("🔐 app token revoked", user_id=user_id, token_id=token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _isoformat(value: Any) -> str | None:
    """Best-effort ISO-8601 stringification for timestamps, preserving null."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
