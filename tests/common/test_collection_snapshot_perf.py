"""Standalone authenticated perf scenarios fail explicitly and never report secrets."""

import json
import logging
from typing import Any

import httpx
import pytest

from tests.perftest.run_perftest import run_collection_snapshot_perf


def test_owned_performance_contract_and_reports_do_not_include_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DGS_PERF_COLLECTION_TOKEN", "synthetic-auth-secret")
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer synthetic-auth-secret"
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "snapshot_token": "synthetic-cursor-secret",
                "snapshot_generation": "owned-generation",
                "snapshot_expires_at": "2026-12-01T00:00:00.000000Z",
                "snapshot_source": "completed_collection_sync",
                "total": 2,
                "releases": [{"id": "1"}],
            },
        )

    logger = logging.getLogger("httpx")
    prior = logger.disabled
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = run_collection_snapshot_perf(client, "http://owned", {"collection_snapshot": {"limit": 1}}, 2)
    assert logger.disabled == prior
    assert len(calls) == 4 and calls[0].url.params["snapshot"] == "new"
    assert calls[1].url.params["snapshot"] == "synthetic-cursor-secret"
    assert calls[1].url.params["snapshot_generation"] == "owned-generation"
    report = json.dumps(result)
    assert "synthetic-auth-secret" not in report and "synthetic-cursor-secret" not in report
    assert all(case["errors"] == 0 and case["iterations"] == 2 for case in result)


@pytest.mark.parametrize(
    "invalid",
    [
        {"total": 0, "releases": []},
        {
            "snapshot_token": "cursor",
            "snapshot_generation": "generation",
            "snapshot_expires_at": "expiry",
            "snapshot_source": "completed_collection_sync",
            "releases": [],
        },
    ],
)
def test_missing_strict_envelope_never_records_a_success(monkeypatch: pytest.MonkeyPatch, invalid: dict[str, Any]) -> None:
    monkeypatch.setenv("DGS_PERF_COLLECTION_TOKEN", "synthetic-auth-secret")
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=invalid))) as client,
        pytest.raises(ValueError, match="request or contract failed"),
    ):
        run_collection_snapshot_perf(client, "http://owned", {}, 1)


def test_missing_credentials_zero_iterations_and_secret_http_error_fail_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(410))) as client:
        monkeypatch.delenv("DGS_PERF_COLLECTION_TOKEN", raising=False)
        with pytest.raises(ValueError, match="environment-supplied token"):
            run_collection_snapshot_perf(client, "http://owned", {}, 1)
        monkeypatch.setenv("DGS_PERF_COLLECTION_TOKEN", "synthetic-auth-secret")
        with pytest.raises(ValueError, match="iterations must be positive"):
            run_collection_snapshot_perf(client, "http://owned", {}, 0)
        with pytest.raises(ValueError) as failure:
            run_collection_snapshot_perf(client, "http://owned?secret=must-not-echo", {}, 1)
        assert "must-not-echo" not in str(failure.value) and "synthetic-auth-secret" not in str(failure.value)
