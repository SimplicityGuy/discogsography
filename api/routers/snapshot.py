"""Snapshot endpoints — migrated from explore service."""

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from api.models import SnapshotRequest, SnapshotResponse, SnapshotRestoreResponse
from api.snapshot_store import SnapshotStore


router = APIRouter()
_snapshot_store = SnapshotStore()


@router.post("/api/snapshot", status_code=201)
async def save_snapshot(body: SnapshotRequest) -> ORJSONResponse:
    if len(body.nodes) > _snapshot_store.max_nodes:
        return ORJSONResponse(content={"error": f"Too many nodes: maximum is {_snapshot_store.max_nodes}"}, status_code=422)
    nodes = [n.model_dump() for n in body.nodes]
    center = body.center.model_dump()
    token, expires_at = _snapshot_store.save(nodes, center)
    response = SnapshotResponse(token=token, url=f"/snapshot/{token}", expires_at=expires_at.isoformat())
    return ORJSONResponse(content=response.model_dump(), status_code=201)


@router.get("/api/snapshot/{token}")
async def restore_snapshot(token: str) -> ORJSONResponse:
    entry = _snapshot_store.load(token)
    if entry is None:
        return ORJSONResponse(content={"error": "Snapshot not found or expired"}, status_code=404)
    response = SnapshotRestoreResponse(nodes=entry["nodes"], center=entry["center"], created_at=entry["created_at"])
    return ORJSONResponse(content=response.model_dump())
