"""Tests for the digger proposals router (list / approve / reject)."""

from unittest.mock import AsyncMock, patch
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest


def test_list_proposals_empty(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_proposals.q.list_pending_proposals", AsyncMock(return_value=[])):
        r = test_client.get("/api/digger/proposals", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_list_proposals_returns_items(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    pid = str(uuid.uuid4())
    item = {
        "proposal_id": pid,
        "created_at": "2026-05-21T00:00:00+00:00",
        "status": "pending",
        "payload": [{"release_id": 1, "current_tier": "nice", "proposed_tier": "must", "reason": "rare"}],
    }
    with patch("api.routers.digger_proposals.q.list_pending_proposals", AsyncMock(return_value=[item])):
        r = test_client.get("/api/digger/proposals", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["proposal_id"] == pid
    assert body["items"][0]["payload"][0]["proposed_tier"] == "must"


def test_approve_returns_applied_count(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_proposals.q.approve_proposal", AsyncMock(return_value=2)):
        r = test_client.post(f"/api/digger/proposals/{uuid.uuid4()}/approve", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["applied"] == 2


def test_approve_404_when_missing(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_proposals.q.approve_proposal", AsyncMock(return_value=None)):
        r = test_client.post(f"/api/digger/proposals/{uuid.uuid4()}/approve", headers=auth_headers)
    assert r.status_code == 404


def test_reject_204(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_proposals.q.reject_proposal", AsyncMock(return_value=True)):
        r = test_client.post(f"/api/digger/proposals/{uuid.uuid4()}/reject", headers=auth_headers)
    assert r.status_code == 204


def test_reject_404_when_missing(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_proposals.q.reject_proposal", AsyncMock(return_value=False)):
        r = test_client.post(f"/api/digger/proposals/{uuid.uuid4()}/reject", headers=auth_headers)
    assert r.status_code == 404


def test_proposals_require_auth(test_client: TestClient) -> None:
    r = test_client.get("/api/digger/proposals")
    assert r.status_code == 401


def test_get_pool_raises_when_unconfigured() -> None:
    import api.routers.digger_proposals as mod

    saved = mod._pool
    mod._pool = None
    try:
        with pytest.raises(HTTPException):
            mod._get_pool()
    finally:
        mod._pool = saved
