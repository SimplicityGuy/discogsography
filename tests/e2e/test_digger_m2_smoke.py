"""M2 happy-path E2E smoke for the Digger optimizer + reports pipeline.

Unlike the M1 smoke (``tests/digger/test_digger_m1_smoke.py``), which wires the
real components together in-process against mock I/O boundaries, this smoke runs
against a **live stack** with a **real PostgreSQL** — the only place this repo
exercises real-DB behaviour. It is therefore marked ``e2e`` and is deselected by
the default ``-m 'not e2e'`` selection (``just test``); it only runs when an
operator points it at a running stack.

It mirrors the M1 smoke's structure (clear, contract-focused parts) at the
live-stack level, covering the two M2 user-facing surfaces end to end:

    Part 1 (recommend SSE):
        POST /api/digger/recommend streams refresh_started -> result -> done,
        proving the opportunistic-refresh + optimizer pipeline runs against real
        wantlist/listing/seller rows.
    Part 2 (reports CRUD):
        POST -> GET (list) -> GET (by id) -> POST .../read (204) -> 404 (one-shot),
        proving the reports inbox round-trips through the real router + query +
        digger.reports table.

Requirements (skips cleanly if absent):
  * JWT_SECRET_KEY            — signs a token the live API will accept.
  * DIGGER_E2E_POSTGRES_URL   — the live database, for idempotent seeding.
  * DIGGER_E2E_API_URL        — live API base URL (default http://localhost:8004).

Seeding reuses the perftest harness's idempotent seed + JWT mint so the
authenticated user, its enabled digger settings, a wantlist release with live
listings/sellers, and an unread report all exist before the flows run.
"""

from __future__ import annotations

import os

import httpx
import pytest

from tests.perftest.run_perftest import mint_perftest_jwt, seed_digger_perftest_data


_DEFAULT_API_URL = "http://localhost:8004"


@pytest.fixture(scope="session")
def digger_e2e() -> tuple[str, dict[str, str]]:
    """Seed the live database and return (api_base_url, auth_headers).

    Skips the whole module unless both the signing secret and a reachable
    database URL are provided, since this smoke is meaningless without a stack.
    """
    secret = os.getenv("JWT_SECRET_KEY")
    postgres_url = os.getenv("DIGGER_E2E_POSTGRES_URL")
    if not secret or not postgres_url:
        pytest.skip("Digger M2 E2E needs JWT_SECRET_KEY + DIGGER_E2E_POSTGRES_URL (live stack)")

    seed_digger_perftest_data(postgres_url)
    token = mint_perftest_jwt(secret=secret)
    base_url = os.getenv("DIGGER_E2E_API_URL", _DEFAULT_API_URL)
    return base_url, {"Authorization": f"Bearer {token}"}


@pytest.mark.e2e
def test_m2_smoke_recommend_streams_sse(digger_e2e: tuple[str, dict[str, str]]) -> None:
    """POST /api/digger/recommend streams the refresh -> result -> done SSE sequence."""
    base_url, headers = digger_e2e

    events: list[str] = []
    with (
        httpx.Client(timeout=30.0) as client,
        client.stream(
            "POST",
            f"{base_url}/api/digger/recommend",
            headers=headers,
            json={"deadline_seconds": 5},
        ) as resp,
    ):
        assert resp.status_code == 200
        for raw in resp.iter_lines():
            line = raw.strip()
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "done" in events or "error" in events:
                break

    # The seeded user is digger-enabled, so the optimizer path must run cleanly.
    assert "error" not in events, f"recommend emitted an error event: {events}"
    assert "refresh_started" in events
    assert "result" in events
    assert "done" in events


@pytest.mark.e2e
def test_m2_smoke_reports_crud_roundtrip(digger_e2e: tuple[str, dict[str, str]]) -> None:
    """A report can be created, listed, fetched, and marked read exactly once."""
    base_url, headers = digger_e2e

    with httpx.Client(timeout=30.0) as client:
        created = client.post(
            f"{base_url}/api/digger/reports",
            headers=headers,
            json={
                "title": "E2E smoke report",
                "kind": "interactive",
                "summary": {"note": "e2e"},
                "bundles": [],
                "watching": [],
                "change_flag": "first_run",
                "shipping_confidence": "low",
            },
        )
        assert created.status_code == 201, created.text
        report_id = created.json()["report_id"]

        listed = client.get(f"{base_url}/api/digger/reports", headers=headers)
        assert listed.status_code == 200
        listed_ids = {item["report_id"] for item in listed.json()["items"]}
        assert report_id in listed_ids

        fetched = client.get(f"{base_url}/api/digger/reports/{report_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["report_id"] == report_id

        first_read = client.post(f"{base_url}/api/digger/reports/{report_id}/read", headers=headers)
        assert first_read.status_code == 204
        # mark_read is one-shot (UPDATE ... WHERE read_at IS NULL): a second call 404s.
        second_read = client.post(f"{base_url}/api/digger/reports/{report_id}/read", headers=headers)
        assert second_read.status_code == 404


@pytest.mark.e2e
def test_m2_smoke_reports_require_authentication(digger_e2e: tuple[str, dict[str, str]]) -> None:
    """The reports inbox rejects an unauthenticated request."""
    base_url, _ = digger_e2e
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}/api/digger/reports")
    assert resp.status_code == 401
