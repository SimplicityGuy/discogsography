"""Tests for the digger reports CRUD router."""

from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient


def test_list_reports_empty(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_reports.q.list_reports", AsyncMock(return_value=[])):
        r = test_client.get("/api/digger/reports", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_create_report_returns_201_with_id(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    rid = uuid.uuid4()
    payload = {
        "title": "Test bundle",
        "kind": "interactive",
        "summary": {"wantlist_size": 5},
        "bundles": [],
        "watching": [],
        "change_flag": "first_run",
        "shipping_confidence": "high",
    }
    with patch("api.routers.digger_reports.q.insert_report", AsyncMock(return_value=rid)):
        r = test_client.post("/api/digger/reports", headers=auth_headers, json=payload)
    assert r.status_code == 201
    assert r.json()["report_id"] == str(rid)


def test_get_report_404_when_missing(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_reports.q.get_report", AsyncMock(return_value=None)):
        r = test_client.get(f"/api/digger/reports/{uuid.uuid4()}", headers=auth_headers)
    assert r.status_code == 404


def test_get_report_returns_report(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    rid = uuid.uuid4()
    report = {
        "report_id": str(rid),
        "user_id": str(uuid.uuid4()),
        "kind": "interactive",
        "generated_at": "2026-05-21T00:00:00+00:00",
        "read_at": None,
        "title": "My report",
        "summary": {},
        "bundles": [],
        "watching": [],
        "change_flag": "first_run",
        "shipping_confidence": "high",
    }
    with patch("api.routers.digger_reports.q.get_report", AsyncMock(return_value=report)):
        r = test_client.get(f"/api/digger/reports/{rid}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["title"] == "My report"


def test_mark_read_204(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_reports.q.mark_read", AsyncMock(return_value=True)):
        r = test_client.post(f"/api/digger/reports/{uuid.uuid4()}/read", headers=auth_headers)
    assert r.status_code == 204


def test_mark_read_404_when_missing(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger_reports.q.mark_read", AsyncMock(return_value=False)):
        r = test_client.post(f"/api/digger/reports/{uuid.uuid4()}/read", headers=auth_headers)
    assert r.status_code == 404


def test_reports_require_auth(test_client: TestClient) -> None:
    r = test_client.get("/api/digger/reports")
    assert r.status_code == 401
