"""Tests for utilities/system_monitor.py — the whole-system status dashboard.

Pins the CLAUDE.md subprocess-timeout contract (every ``subprocess.run`` passes
``timeout=`` and both ``CalledProcessError`` and ``TimeoutExpired`` are caught)
and the split extractor service names used when scanning logs.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import requests

from utilities import system_monitor


def _completed(stdout: str) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    return result


# --------------------------------------------------------------------------- #
# get_docker_stats
# --------------------------------------------------------------------------- #
def test_get_docker_stats_json_array() -> None:
    payload = '[{"Name": "a"}, {"Name": "b"}]'
    with patch.object(system_monitor.subprocess, "run", return_value=_completed(payload)) as run:
        result = system_monitor.get_docker_stats()
    assert result == [{"Name": "a"}, {"Name": "b"}]
    assert run.call_args.kwargs["timeout"] == 60


def test_get_docker_stats_json_lines() -> None:
    payload = '{"Name": "a"}\n{"Name": "b"}\n'
    with patch.object(system_monitor.subprocess, "run", return_value=_completed(payload)):
        result = system_monitor.get_docker_stats()
    assert result == [{"Name": "a"}, {"Name": "b"}]


def test_get_docker_stats_called_process_error() -> None:
    with patch.object(system_monitor.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["docker"])):
        assert system_monitor.get_docker_stats() == []


def test_get_docker_stats_timeout() -> None:
    with patch.object(system_monitor.subprocess, "run", side_effect=subprocess.TimeoutExpired(["docker"], 60)):
        assert system_monitor.get_docker_stats() == []


# --------------------------------------------------------------------------- #
# get_queue_stats
# --------------------------------------------------------------------------- #
def test_get_queue_stats_success() -> None:
    resp = MagicMock()
    resp.json.return_value = [{"name": "q"}]
    resp.raise_for_status.return_value = None
    with patch.object(system_monitor.requests, "get", return_value=resp) as get:
        result = system_monitor.get_queue_stats(base_url="http://rmq", username="u", password="p")  # noqa: S106
    assert result == [{"name": "q"}]
    assert get.call_args.kwargs["timeout"] == 10


def test_get_queue_stats_error() -> None:
    with patch.object(system_monitor.requests, "get", side_effect=requests.RequestException()):
        assert system_monitor.get_queue_stats() is None


# --------------------------------------------------------------------------- #
# get_service_logs
# --------------------------------------------------------------------------- #
def test_get_service_logs_success() -> None:
    with patch.object(system_monitor.subprocess, "run", return_value=_completed("log line")) as run:
        assert system_monitor.get_service_logs("graphinator", 5) == "log line"
    assert run.call_args.kwargs["timeout"] == 60
    assert "--tail=5" in run.call_args.args[0]


def test_get_service_logs_error() -> None:
    with patch.object(system_monitor.subprocess, "run", side_effect=subprocess.TimeoutExpired(["docker"], 60)):
        assert system_monitor.get_service_logs("graphinator") == ""


# --------------------------------------------------------------------------- #
# check_neo4j_status / check_postgres_status
# --------------------------------------------------------------------------- #
def test_check_neo4j_status_success() -> None:
    with patch.object(system_monitor.subprocess, "run", return_value=_completed("label | count")) as run:
        assert system_monitor.check_neo4j_status() == "label | count"
    assert run.call_args.kwargs["timeout"] == 60


def test_check_neo4j_status_error_with_stderr() -> None:
    exc = subprocess.CalledProcessError(1, ["docker"], stderr="boom")
    with patch.object(system_monitor.subprocess, "run", side_effect=exc):
        assert system_monitor.check_neo4j_status() == "Error: boom"


def test_check_neo4j_status_error_without_stderr() -> None:
    exc = subprocess.TimeoutExpired(["docker"], 60)
    with patch.object(system_monitor.subprocess, "run", side_effect=exc):
        assert system_monitor.check_neo4j_status().startswith("Error:")


def test_check_postgres_status_success() -> None:
    with patch.object(system_monitor.subprocess, "run", return_value=_completed("relname | size")):
        assert system_monitor.check_postgres_status() == "relname | size"


def test_check_postgres_status_error_with_stderr() -> None:
    exc = subprocess.CalledProcessError(1, ["docker"], stderr="db down")
    with patch.object(system_monitor.subprocess, "run", side_effect=exc):
        assert system_monitor.check_postgres_status() == "Error: db down"


def test_check_postgres_status_error_without_stderr() -> None:
    with patch.object(system_monitor.subprocess, "run", side_effect=subprocess.TimeoutExpired(["docker"], 60)):
        assert system_monitor.check_postgres_status().startswith("Error:")


# --------------------------------------------------------------------------- #
# monitor_system (integration over the mocked collectors)
# --------------------------------------------------------------------------- #
def test_monitor_system_all_healthy(capsys) -> None:
    containers = [{"Name": "discogsography-graphinator", "State": "running", "Health": "healthy"}]
    queues = [{"name": "discogsography-discogs-artists", "messages_ready": 2, "messages_unacknowledged": 1, "messages": 3}]
    with (
        patch.object(system_monitor, "get_docker_stats", return_value=containers),
        patch.object(system_monitor, "get_queue_stats", return_value=queues),
        patch.object(system_monitor, "check_neo4j_status", return_value="neo4j ok"),
        patch.object(system_monitor, "check_postgres_status", return_value="pg ok"),
        patch.object(system_monitor, "get_service_logs", return_value="INFO all good"),
    ):
        system_monitor.monitor_system()

    out = capsys.readouterr().out
    assert "discogsography-graphinator" in out
    assert "Total messages: 3" in out
    assert "neo4j ok" in out
    assert "pg ok" in out
    assert "No recent errors found" in out


def test_monitor_system_all_unavailable(capsys) -> None:
    def fake_logs(service: str, _lines: int = 20) -> str:
        return "ERROR something Failed badly" if service == "graphinator" else ""

    with (
        patch.object(system_monitor, "get_docker_stats", return_value=[]),
        patch.object(system_monitor, "get_queue_stats", return_value=None),
        patch.object(system_monitor, "check_neo4j_status", return_value="Error: no neo4j"),
        patch.object(system_monitor, "check_postgres_status", return_value="Error: no pg"),
        patch.object(system_monitor, "get_service_logs", side_effect=fake_logs),
    ):
        system_monitor.monitor_system()

    out = capsys.readouterr().out
    assert "Unable to fetch container status" in out
    assert "Unable to fetch queue data" in out
    assert "Unable to connect to Neo4j" in out
    assert "Unable to connect to PostgreSQL" in out
    assert "graphinator:" in out  # error section rendered


def test_monitor_system_scans_split_extractor_services() -> None:
    """CLAUDE.md contract: the error scan uses both split extractor services."""
    seen: list[str] = []

    def record(service: str, _lines: int = 20) -> str:
        seen.append(service)
        return ""

    with (
        patch.object(system_monitor, "get_docker_stats", return_value=[]),
        patch.object(system_monitor, "get_queue_stats", return_value=None),
        patch.object(system_monitor, "check_neo4j_status", return_value="Error:"),
        patch.object(system_monitor, "check_postgres_status", return_value="Error:"),
        patch.object(system_monitor, "get_service_logs", side_effect=record),
    ):
        system_monitor.monitor_system()

    assert "extractor-discogs" in seen
    assert "extractor-musicbrainz" in seen
    assert "extractor" not in seen
