"""Mock-based tests for the user-facing /api/digger router."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient

from api.queries.digger_queries import UserDiggerSettings


def _settings() -> UserDiggerSettings:
    return UserDiggerSettings(
        user_id=uuid.uuid4(),
        enabled=True,
        country_code="US",
        currency="USD",
        scheduled_cadence="weekly",
        preferred_model="sonnet",
        daily_token_cap_interactive=200000,
        daily_token_cap_scheduled=100000,
    )


def test_settings_requires_auth(test_client: TestClient) -> None:
    r = test_client.get("/api/digger/settings")
    assert r.status_code in (401, 403)


def test_get_settings_404_when_not_enabled(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger.q.get_user_settings", AsyncMock(return_value=None)):
        r = test_client.get("/api/digger/settings", headers=auth_headers)
    assert r.status_code == 404


def test_get_settings_returns_settings(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger.q.get_user_settings", AsyncMock(return_value=_settings())):
        r = test_client.get("/api/digger/settings", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert r.json()["scheduled_cadence"] == "weekly"


def test_put_settings_204_and_calls_upsert(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    mock_upsert = AsyncMock()
    with patch("api.routers.digger.q.upsert_user_settings", mock_upsert):
        r = test_client.put(
            "/api/digger/settings",
            headers=auth_headers,
            json={
                "enabled": True,
                "country_code": "US",
                "currency": "USD",
                "scheduled_cadence": "weekly",
                "preferred_model": "sonnet",
            },
        )
    assert r.status_code == 204
    mock_upsert.assert_awaited_once()


def test_put_settings_preserves_explicit_zero_token_cap(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    mock_upsert = AsyncMock()
    with patch("api.routers.digger.q.upsert_user_settings", mock_upsert):
        r = test_client.put(
            "/api/digger/settings",
            headers=auth_headers,
            json={
                "enabled": True,
                "country_code": "US",
                "currency": "USD",
                "scheduled_cadence": "weekly",
                "preferred_model": "sonnet",
                "daily_token_cap_interactive": 0,
            },
        )
    assert r.status_code == 204
    assert mock_upsert.await_args.kwargs["daily_token_cap_interactive"] == 0


def test_get_wantlist_returns_items(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    rows = [
        {
            "release_id": 123,
            "tier": "must",
            "min_media_condition": "VG",
            "min_sleeve_condition": "VG",
            "max_price_cents": None,
            "active_listings": 2,
            "last_scraped_at": datetime(2026, 5, 1, tzinfo=UTC),
            "title": "Some Title",
            "artist": "Some Artist",
            "year": 1999,
        }
    ]
    with patch("api.routers.digger.q.get_wantlist_with_listings_counts", AsyncMock(return_value=rows)):
        r = test_client.get("/api/digger/wantlist", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert {"release_id", "tier", "active_listings"} <= set(item)
    assert item["active_listings"] == 2
    assert item["last_scraped_at"].startswith("2026-05-01")
    assert "cover_image_url" not in item


def test_bulk_set_tier(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    with patch("api.routers.digger.q.bulk_set_tier", AsyncMock(return_value=1)):
        r = test_client.post(
            "/api/digger/wantlist/bulk-tier",
            headers=auth_headers,
            json={"release_ids": [123], "tier": "must"},
        )
    assert r.status_code == 200
    assert r.json()["updated"] == 1


def test_set_priority_204(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    mock_set = AsyncMock()
    with patch("api.routers.digger.q.set_wantlist_priority", mock_set):
        r = test_client.put(
            "/api/digger/wantlist/123/priority",
            headers=auth_headers,
            json={"tier": "nice"},
        )
    assert r.status_code == 204
    mock_set.assert_awaited_once()
