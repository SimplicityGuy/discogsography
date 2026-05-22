"""M3 happy-path E2E smoke for the Digger LLM agent.

Like the M2 smoke (``tests/e2e/test_digger_m2_smoke.py``), this runs against a
**live stack** with a **real PostgreSQL** and a **real Anthropic key configured
on the API**. It is marked ``e2e`` (deselected by the default ``-m 'not e2e'``)
and additionally needs ``ANTHROPIC_API_KEY`` in the environment as the operator's
signal that the live API is key-configured — so it never runs in regular CI.

It covers the M3 user-facing surface end to end:

    Part 1 (agent chat SSE + session persistence):
        POST /api/digger/agent/message streams text / tool_call ... done, proving
        the agent loop runs against the real wantlist/optimizer; the turn then
        appears in GET /api/digger/agent/sessions.
    Part 2 (auth):
        the agent + proposals surfaces reject unauthenticated requests.

Seeding reuses the perftest harness's idempotent seed + JWT mint so the
authenticated, digger-enabled user (with a wantlist release + live listings)
exists before the flow runs.
"""

from __future__ import annotations

import os

import httpx
import pytest

from tests.perftest.run_perftest import mint_perftest_jwt, seed_digger_perftest_data


_DEFAULT_API_URL = "http://localhost:8004"


@pytest.fixture(scope="session")
def digger_m3_e2e() -> tuple[str, dict[str, str]]:
    """Seed the live database and return (api_base_url, auth_headers), or skip.

    Skips unless the signing secret, a reachable database, and an Anthropic key
    (the live API's agent dependency) are all present — the agent smoke is
    meaningless without a key-configured stack.
    """
    secret = os.getenv("JWT_SECRET_KEY")
    postgres_url = os.getenv("DIGGER_E2E_POSTGRES_URL")
    if not secret or not postgres_url or not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("Digger M3 E2E needs JWT_SECRET_KEY + DIGGER_E2E_POSTGRES_URL + ANTHROPIC_API_KEY (live key-configured stack)")

    seed_digger_perftest_data(postgres_url)
    token = mint_perftest_jwt(secret=secret)
    base_url = os.getenv("DIGGER_E2E_API_URL", _DEFAULT_API_URL)
    return base_url, {"Authorization": f"Bearer {token}"}


@pytest.mark.e2e
def test_m3_smoke_agent_chat_and_session(digger_m3_e2e: tuple[str, dict[str, str]]) -> None:
    """A chat turn streams to completion and is recorded as a session."""
    base_url, headers = digger_m3_e2e

    events: list[str] = []
    with (
        httpx.Client(timeout=60.0) as client,
        client.stream(
            "POST",
            f"{base_url}/api/digger/agent/message",
            headers=headers,
            json={"user_message": "Summarize my wantlist status."},
        ) as resp,
    ):
        assert resp.status_code == 200, resp.read()
        for raw in resp.iter_lines():
            line = raw.strip()
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "done" in events or "error" in events:
                break

    assert "error" not in events, f"agent emitted an error event: {events}"
    assert "done" in events
    assert "text" in events or "tool_call" in events

    # The completed turn created a session that the session list now surfaces.
    sessions = httpx.get(f"{base_url}/api/digger/agent/sessions", headers=headers, timeout=30.0)
    assert sessions.status_code == 200
    assert len(sessions.json()["items"]) >= 1


@pytest.mark.e2e
def test_m3_smoke_agent_surfaces_require_authentication(digger_m3_e2e: tuple[str, dict[str, str]]) -> None:
    """The agent session list and the proposals inbox reject anonymous requests."""
    base_url, _ = digger_m3_e2e
    with httpx.Client(timeout=10.0) as client:
        assert client.get(f"{base_url}/api/digger/agent/sessions").status_code == 401
        assert client.get(f"{base_url}/api/digger/proposals").status_code == 401
