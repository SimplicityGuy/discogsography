"""Tests for utilities/monitor_queues.py — the real-time queue monitor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from utilities import monitor_queues


def _response(payload: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_get_queue_stats_success() -> None:
    payload = [{"name": "discogsography-discogs-graphinator-artists"}]
    with patch.object(monitor_queues.requests, "get", return_value=_response(payload)) as get:
        result = monitor_queues.get_queue_stats(base_url="http://rmq", username="u", password="p")  # noqa: S106
    assert result == payload
    get.assert_called_once()
    assert get.call_args.kwargs["timeout"] == 10
    assert get.call_args.args[0] == "http://rmq/api/queues"


def test_get_queue_stats_request_error(capsys) -> None:
    with patch.object(monitor_queues.requests, "get", side_effect=requests.RequestException("down")):
        assert monitor_queues.get_queue_stats() is None
    assert "Error connecting to RabbitMQ" in capsys.readouterr().out


def test_monitor_queues_renders_then_stops(capsys) -> None:
    payload = [
        {"name": "discogsography-discogs-graphinator-artists", "messages_ready": 4, "messages_unacknowledged": 2, "messages": 6},
        {"name": "discogsography-musicbrainz-tableinator-releases", "messages_ready": 1, "messages_unacknowledged": 0, "messages": 1},
        {"name": "ignored-queue", "messages_ready": 9, "messages_unacknowledged": 9, "messages": 9},
    ]
    with (
        patch.object(monitor_queues, "get_queue_stats", return_value=payload),
        patch.object(monitor_queues.time, "sleep", side_effect=KeyboardInterrupt),
        patch.object(monitor_queues.time, "strftime", return_value="2026-01-01 00:00:00"),
    ):
        monitor_queues.monitor_queues(interval=1)

    out = capsys.readouterr().out
    assert "graphinator-artists" in out
    assert "tableinator-releases" in out
    assert "ignored-queue" not in out
    assert "Total messages across all queues: 7" in out
    assert "Monitoring stopped." in out


def test_monitor_queues_handles_empty_fetch(capsys) -> None:
    # First loop: no data -> "Failed to fetch" -> sleep -> continue; second loop
    # interrupts. Sleep is a no-op so the ``continue`` branch is exercised.
    with (
        patch.object(monitor_queues, "get_queue_stats", side_effect=[None, KeyboardInterrupt]),
        patch.object(monitor_queues.time, "sleep", return_value=None),
    ):
        monitor_queues.monitor_queues(interval=1)
    out = capsys.readouterr().out
    assert "Failed to fetch queue data" in out
    assert "Monitoring stopped." in out
