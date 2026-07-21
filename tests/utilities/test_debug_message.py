"""Tests for utilities/debug_message.py — the queue message peeker/analyzer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from utilities import debug_message


def _fake_connection(body: bytes | None) -> MagicMock:
    """Build a pika BlockingConnection mock; ``body=None`` means empty queue."""
    connection = MagicMock()
    connection.is_closed = False
    channel = MagicMock()
    connection.channel.return_value = channel
    if body is None:
        channel.basic_get.return_value = (None, None, None)
    else:
        method = MagicMock()
        method.delivery_tag = 42
        channel.basic_get.return_value = (method, MagicMock(), body)
    return connection


# --------------------------------------------------------------------------- #
# get_message_from_queue
# --------------------------------------------------------------------------- #
def test_get_message_returns_and_requeues() -> None:
    conn = _fake_connection(json.dumps({"id": "1", "title": "x"}).encode())
    with patch.object(debug_message.pika, "BlockingConnection", return_value=conn):
        msg = debug_message.get_message_from_queue("q", username="u", password="p")  # noqa: S106

    assert msg == {"id": "1", "title": "x"}
    channel = conn.channel.return_value
    channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=True)
    conn.close.assert_called_once()


def test_get_message_empty_queue() -> None:
    conn = _fake_connection(None)
    with patch.object(debug_message.pika, "BlockingConnection", return_value=conn):
        assert debug_message.get_message_from_queue("q") is None
    conn.close.assert_called_once()


def test_get_message_handles_exception(capsys) -> None:
    with patch.object(debug_message.pika, "BlockingConnection", side_effect=RuntimeError("nope")):
        assert debug_message.get_message_from_queue("q") is None
    assert "Error: nope" in capsys.readouterr().out


def test_get_message_skips_close_when_already_closed() -> None:
    conn = _fake_connection(json.dumps({"id": "1"}).encode())
    conn.is_closed = True
    with patch.object(debug_message.pika, "BlockingConnection", return_value=conn):
        debug_message.get_message_from_queue("q")
    conn.close.assert_not_called()


# --------------------------------------------------------------------------- #
# analyze_message
# --------------------------------------------------------------------------- #
def test_analyze_message_none(capsys) -> None:
    debug_message.analyze_message(None, "masters")
    assert "No message available in queue" in capsys.readouterr().out


def test_analyze_masters_complete(capsys) -> None:
    message = {
        "id": "123",
        "title": "A Record",
        "sha256": "abcdef0123456789abcdef",
        "genres": ["rock"],
        "artists": {"name": "artist"},
        "year": 1999,
    }
    debug_message.analyze_message(message, "masters")
    out = capsys.readouterr().out
    assert "Message ID: 123" in out
    assert "✓ title" in out
    assert "✓ genres" in out  # list optional field
    assert "✓ artists" in out  # dict optional field
    assert "- members: not present" not in out  # members not an optional for masters
    assert "No obvious issues detected" in out


def test_analyze_masters_missing_required(capsys) -> None:
    debug_message.analyze_message({"title": "no id here"}, "masters")
    out = capsys.readouterr().out
    assert "✗ id: MISSING" in out
    assert "Missing required fields: id, sha256" in out


def test_analyze_masters_nested_artist_issues(capsys) -> None:
    message = {
        "id": "1",
        "title": "t",
        "sha256": "s",
        "artists": {"artist": [{"id": "a"}, {"name": "no-id"}]},
    }
    debug_message.analyze_message(message, "masters")
    assert "Artist 1 missing 'id' field" in capsys.readouterr().out


def test_analyze_masters_single_artist_missing_id(capsys) -> None:
    message = {"id": "1", "title": "t", "sha256": "s", "artists": {"artist": {"name": "solo"}}}
    debug_message.analyze_message(message, "masters")
    assert "Single artist missing 'id' field" in capsys.readouterr().out


@pytest.mark.parametrize("mtype", ["artists", "labels", "releases", "unknown"])
def test_analyze_other_types(mtype: str, capsys) -> None:
    message = {"id": "1", "name": "n", "title": "t", "sha256": "s"}
    debug_message.analyze_message(message, mtype)
    assert "Message Analysis" in capsys.readouterr().out


def test_analyze_truncates_large_message(capsys) -> None:
    message = {"id": "1", "sha256": "s", "blob": "x" * 5000}
    debug_message.analyze_message(message, "unknown")
    assert "..." in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def test_main_no_args_exits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(debug_message.sys, "argv", ["debug_message.py"])
    with pytest.raises(SystemExit) as exc:
        debug_message.main()
    assert exc.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_invalid_queue_type(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(debug_message.sys, "argv", ["debug_message.py", "bogus"])
    with pytest.raises(SystemExit) as exc:
        debug_message.main()
    assert exc.value.code == 1
    assert "Invalid queue type" in capsys.readouterr().out


def test_main_invalid_consumer(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(debug_message.sys, "argv", ["debug_message.py", "artists", "bogus"])
    with pytest.raises(SystemExit) as exc:
        debug_message.main()
    assert exc.value.code == 1
    assert "Invalid consumer" in capsys.readouterr().out


def test_main_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(debug_message.sys, "argv", ["debug_message.py", "artists", "tableinator"])
    with (
        patch.object(debug_message, "get_message_from_queue", return_value={"id": "1"}) as getter,
        patch.object(debug_message, "analyze_message") as analyzer,
    ):
        debug_message.main()

    getter.assert_called_once()
    # Queue name is composed from the tableinator prefix + type.
    assert getter.call_args.args[0].endswith("-artists")
    analyzer.assert_called_once_with({"id": "1"}, "artists")
