"""Mock-based tests for the service-token-gated internal Digger router."""

from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient

from api.queries.digger_queries import WantlistPriorityRow


def test_wantlist_snapshot_requires_service_token(test_client: TestClient) -> None:
    r = test_client.get("/api/internal/digger/wantlist-snapshot/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401


def test_wantlist_snapshot_rejects_wrong_token(test_client: TestClient) -> None:
    r = test_client.get(
        "/api/internal/digger/wantlist-snapshot/00000000-0000-0000-0000-000000000000",
        headers={"X-Service-Token": "wrong-token"},
    )
    assert r.status_code == 401


def test_wantlist_snapshot_returns_grouped_priorities(test_client: TestClient, service_token_headers: dict[str, str]) -> None:
    uid = uuid.uuid4()
    rows = [
        WantlistPriorityRow(release_id=1, tier="must", min_media_condition="VG", min_sleeve_condition="VG", max_price_cents=None),
        WantlistPriorityRow(release_id=2, tier="nice", min_media_condition="NM", min_sleeve_condition="VG+", max_price_cents=5000),
    ]
    with patch("api.routers.internal_digger.q.list_wantlist_priorities", AsyncMock(return_value=rows)):
        r = test_client.get(f"/api/internal/digger/wantlist-snapshot/{uid}", headers=service_token_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(uid)
    assert "must" in body and "nice" in body and "eventually" in body
    assert body["must"][0]["release_id"] == 1
    assert body["nice"][0]["max_price_cents"] == 5000
    assert body["eventually"] == []


def test_users_due_for_report(test_client: TestClient, service_token_headers: dict[str, str]) -> None:
    uid = uuid.uuid4()
    rows = [{"user_id": uid, "scheduled_cadence": "weekly"}]
    with patch("api.routers.internal_digger.q.list_users_due_for_report", AsyncMock(return_value=rows)):
        r = test_client.get("/api/internal/digger/users-due-for-report", headers=service_token_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["users"][0]["user_id"] == str(uid)
    assert body["users"][0]["cadence"] == "weekly"
