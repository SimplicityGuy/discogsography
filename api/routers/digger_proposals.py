"""Digger proposal endpoints: list pending, approve (apply tier changes), reject.

NOTE: `from __future__ import annotations` is intentionally NOT used here — the
`proposal_id: UUID` path params must resolve at runtime for FastAPI, and the
Pydantic response models need their field types available at runtime. The
`_pool` annotation is quoted so the TYPE_CHECKING-only import stays valid.
(Matches the api/routers/digger_reports.py pattern.)
"""

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import require_user
from api.queries import digger_proposals as q


if TYPE_CHECKING:  # pragma: no cover
    from common import AsyncPostgreSQLPool


router = APIRouter(prefix="/api/digger/proposals", tags=["digger"])

_pool: "AsyncPostgreSQLPool | None" = None


def configure(pool: "AsyncPostgreSQLPool") -> None:
    """Inject the Postgres pool at application startup."""
    global _pool
    _pool = pool


def _get_pool() -> "AsyncPostgreSQLPool":
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _pool


class ProposalItem(BaseModel):
    proposal_id: str
    created_at: str
    status: str
    payload: list[dict[str, Any]]


class ProposalList(BaseModel):
    items: list[ProposalItem]


@router.get("", response_model=ProposalList)
async def list_proposals(current_user: Annotated[dict[str, Any], Depends(require_user)]) -> ProposalList:
    """Return the caller's pending, unexpired proposals."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    items = await q.list_pending_proposals(pool, user_id)
    return ProposalList(items=[ProposalItem(**it) for it in items])


@router.post("/{proposal_id}/approve")
async def approve(proposal_id: UUID, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> dict[str, int]:
    """Approve a pending proposal, applying its tier changes; 404 if already resolved."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    applied = await q.approve_proposal(pool, proposal_id, user_id)
    if applied is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal not found or already resolved")
    return {"applied": applied}


@router.post("/{proposal_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject(proposal_id: UUID, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> None:
    """Reject a pending proposal; 404 if it does not exist or was already resolved."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    ok = await q.reject_proposal(pool, proposal_id, user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal not found or already resolved")
