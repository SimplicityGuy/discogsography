"""Tests for the admin-setup CLI tool (api/admin_setup.py).

Covers connection-string construction, the add/list admin operations, and the
argparse-driven ``main`` entry point. All DB and config boundaries are mocked —
no real PostgreSQL connection is ever opened.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from api import admin_setup


@contextmanager
def _cm(value: Any):
    """Minimal synchronous context manager yielding ``value``."""
    yield value


def _mock_connect(cursor: MagicMock) -> MagicMock:
    """Build a ``psycopg.connect``-style mock whose cursor() yields ``cursor``."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=_cm(cursor))
    connect = MagicMock(return_value=conn)
    return connect


# --------------------------------------------------------------------------- #
# _build_conninfo
# --------------------------------------------------------------------------- #
def test_build_conninfo_uses_env_and_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com:6432")
    monkeypatch.setenv("POSTGRES_DATABASE", "mydb")
    monkeypatch.setattr(admin_setup, "get_secret", lambda name: {"POSTGRES_USERNAME": "alice", "POSTGRES_PASSWORD": "s3cret"}[name])

    conninfo = admin_setup._build_conninfo()

    assert "host=db.example.com" in conninfo
    assert "port=6432" in conninfo
    assert "user=alice" in conninfo
    assert "password=s3cret" in conninfo
    assert "dbname=mydb" in conninfo


def test_build_conninfo_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DATABASE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(admin_setup, "get_secret", lambda _name: None)

    conninfo = admin_setup._build_conninfo()

    assert "host=localhost" in conninfo
    assert "port=5432" in conninfo
    assert "user=postgres" in conninfo
    assert "password=postgres" in conninfo
    assert "dbname=discogsography" in conninfo


def test_build_conninfo_blank_port_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PORT", "")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setattr(admin_setup, "get_secret", lambda _name: None)

    conninfo = admin_setup._build_conninfo()

    assert "port=5432" in conninfo


# --------------------------------------------------------------------------- #
# add_admin
# --------------------------------------------------------------------------- #
def test_add_admin_rejects_short_password() -> None:
    with pytest.raises(ValueError, match="at least 8 characters"):
        admin_setup.add_admin("conninfo", "admin@example.com", "short")


def test_add_admin_upserts_and_normalizes_email(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cursor = MagicMock()
    connect = _mock_connect(cursor)
    monkeypatch.setattr(admin_setup.psycopg, "connect", connect)
    monkeypatch.setattr(admin_setup, "_hash_password", lambda pw: f"hashed:{pw}")

    admin_setup.add_admin("conninfo-str", "  Admin@Example.COM  ", "longenoughpw")

    connect.assert_called_once_with("conninfo-str")
    sql, params = cursor.execute.call_args[0]
    assert "INSERT INTO users" in sql
    assert "ON CONFLICT (email)" in sql
    # Email is stripped + lowercased; password is hashed.
    assert params == ("admin@example.com", "hashed:longenoughpw")
    assert "created/updated successfully" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# list_admins
# --------------------------------------------------------------------------- #
def test_list_admins_no_rows(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    monkeypatch.setattr(admin_setup.psycopg, "connect", _mock_connect(cursor))

    admin_setup.list_admins("conninfo")

    assert "No admin accounts found." in capsys.readouterr().out


def test_list_admins_renders_rows(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("a@example.com", True, "2026-01-01"),
        ("b@example.com", False, "2026-02-02"),
    ]
    monkeypatch.setattr(admin_setup.psycopg, "connect", _mock_connect(cursor))

    admin_setup.list_admins("conninfo")

    out = capsys.readouterr().out
    assert "a@example.com" in out
    assert "Yes" in out  # active account
    assert "No" in out  # inactive account
    assert "b@example.com" in out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(admin_setup.sys, "argv", ["admin-setup", *argv])
    monkeypatch.setattr(admin_setup, "_build_conninfo", lambda: "fake-conninfo")


def test_main_no_args_prints_help_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    _run_main(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        admin_setup.main()
    assert exc.value.code == 1


def test_main_short_password_exits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _run_main(monkeypatch, ["--email", "a@example.com", "--password", "short"])
    with pytest.raises(SystemExit) as exc:
        admin_setup.main()
    assert exc.value.code == 1
    assert "at least 8 characters" in capsys.readouterr().out


def test_main_list_calls_list_admins(monkeypatch: pytest.MonkeyPatch) -> None:
    _run_main(monkeypatch, ["--list"])
    with patch.object(admin_setup, "list_admins") as list_admins:
        admin_setup.main()
    list_admins.assert_called_once_with("fake-conninfo")


def test_main_add_calls_add_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _run_main(monkeypatch, ["--email", "a@example.com", "--password", "longenoughpw"])
    with patch.object(admin_setup, "add_admin") as add_admin:
        admin_setup.main()
    add_admin.assert_called_once_with("fake-conninfo", "a@example.com", "longenoughpw")
