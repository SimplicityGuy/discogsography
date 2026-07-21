"""Tests for utilities/check_queues.py — the RabbitMQ consumer-queue reporter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from utilities import check_queues


def _response(payload: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_renders_consumer_queues(capsys) -> None:
    payload = [
        {
            "name": "discogsography-discogs-graphinator-artists",
            "messages": 10,
            "messages_ready": 7,
            "messages_unacknowledged": 3,
            "consumers": 1,
            "state": "running",
            "message_stats": {"ack_details": {"rate": 1.5}, "publish_details": {"rate": 2.25}},
            "consumer_details": [{"consumer_tag": "ctag-1", "channel_details": {"connection_name": "conn-1"}}],
        },
        {"name": "unrelated-queue", "messages": 5},
    ]
    with patch.object(check_queues.requests, "get", return_value=_response(payload)) as get:
        check_queues.check_rabbitmq_queues()

    out = capsys.readouterr().out
    assert "discogsography-discogs-graphinator-artists" in out
    assert "unrelated-queue" not in out  # filtered out
    assert "Ack Rate: 1.50 msg/s" in out
    assert "Publish Rate: 2.25 msg/s" in out
    assert "ctag-1" in out
    assert "conn-1" in out
    assert get.call_args.kwargs["timeout"] == 10


def test_no_consumer_queues(capsys) -> None:
    with patch.object(check_queues.requests, "get", return_value=_response([{"name": "other"}])):
        check_queues.check_rabbitmq_queues()
    assert "No consumer queues found!" in capsys.readouterr().out


def test_queue_without_stats_or_consumers(capsys) -> None:
    payload = [{"name": "discogsography-discogs-tableinator-artists", "messages": 0, "consumers": 0}]
    with patch.object(check_queues.requests, "get", return_value=_response(payload)):
        check_queues.check_rabbitmq_queues()
    out = capsys.readouterr().out
    assert "tableinator" in out
    assert "Ack Rate" not in out  # no message_stats
    assert "Consumer Details" not in out  # no consumers


def test_connection_error(capsys) -> None:
    with patch.object(check_queues.requests, "get", side_effect=requests.ConnectionError()):
        check_queues.check_rabbitmq_queues()
    out = capsys.readouterr().out
    assert "Could not connect to RabbitMQ" in out
    assert "Management plugin is enabled" in out


def test_http_error(capsys) -> None:
    err = requests.HTTPError()
    err.response = MagicMock(status_code=503)
    with patch.object(check_queues.requests, "get", side_effect=err):
        check_queues.check_rabbitmq_queues()
    assert "HTTP 503" in capsys.readouterr().out


def test_unexpected_error(capsys) -> None:
    with patch.object(check_queues.requests, "get", side_effect=ValueError("boom")):
        check_queues.check_rabbitmq_queues()
    assert "Unexpected error: boom" in capsys.readouterr().out
