"""Digger Reports inbox endpoints: list, read, and persist recommendation reports.

NOTE: `from __future__ import annotations` is intentionally NOT used here — the
`report_id: UUID` path params must resolve at runtime for FastAPI, and the
Pydantic request/response models need their field types available at runtime.
The `_pool` annotation is quoted so the TYPE_CHECKING-only import stays valid.
(Matches the api/routers/internal_digger.py pattern.)
"""

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import require_user
from api.queries import digger_reports as q


if TYPE_CHECKING:
    from common import AsyncPostgreSQLPool


router = APIRouter(prefix="/api/digger/reports", tags=["digger"])

_pool: "AsyncPostgreSQLPool | None" = None


def configure(pool: "AsyncPostgreSQLPool") -> None:
    """Inject the Postgres pool at application startup."""
    global _pool
    _pool = pool


def _get_pool() -> "AsyncPostgreSQLPool":
    if _pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")
    return _pool


class ReportListItem(BaseModel):
    report_id: str
    kind: str
    generated_at: str
    read_at: str | None
    title: str
    summary: dict[str, Any]
    change_flag: str


class ReportListResponse(BaseModel):
    items: list[ReportListItem]


class ReportCreateIn(BaseModel):
    title: str
    kind: str  # "interactive" | "scheduled"
    summary: dict[str, Any]
    bundles: list[Any]
    watching: list[int]
    change_flag: str  # "significant" | "none" | "first_run"
    shipping_confidence: str  # "high" | "low"


class ReportCreatedOut(BaseModel):
    report_id: str


@router.get("", response_model=ReportListResponse)
async def list_reports(current_user: Annotated[dict[str, Any], Depends(require_user)]) -> ReportListResponse:
    """Return the caller's report inbox, newest first."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    items = await q.list_reports(pool, user_id)
    return ReportListResponse(items=[ReportListItem(**it) for it in items])


@router.get("/{report_id}")
async def get_report(report_id: UUID, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> dict[str, Any]:
    """Return one full report owned by the caller."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    report = await q.get_report(pool, user_id, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return report


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ReportCreatedOut)
async def create_report(body: ReportCreateIn, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> ReportCreatedOut:
    """Persist a report for the caller (used by the interactive recommend flow)."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    report_id = await q.insert_report(
        pool,
        user_id,
        kind=body.kind,
        title=body.title,
        summary=body.summary,
        bundles=body.bundles,
        watching=body.watching,
        change_flag=body.change_flag,
        shipping_confidence=body.shipping_confidence,
    )
    return ReportCreatedOut(report_id=str(report_id))


@router.post("/{report_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(report_id: UUID, current_user: Annotated[dict[str, Any], Depends(require_user)]) -> None:
    """Mark a report read; 404 if it does not exist or was already read."""
    pool = _get_pool()
    user_id = UUID(current_user["sub"])
    ok = await q.mark_read(pool, user_id, report_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found or already read")
