"""Tests for utilities/healthcheck.py — the container process healthcheck."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psutil
import pytest

from utilities import healthcheck


def _proc(cmdline: list[str] | None) -> MagicMock:
    proc = MagicMock()
    proc.info = {"pid": 1, "name": "python", "cmdline": cmdline}
    return proc


def test_check_process_found() -> None:
    with patch.object(healthcheck.psutil, "process_iter", return_value=[_proc(["python", "graphinator/main.py"])]):
        assert healthcheck.check_process("graphinator") is True


def test_check_process_not_found() -> None:
    with patch.object(healthcheck.psutil, "process_iter", return_value=[_proc(["python", "other.py"])]):
        assert healthcheck.check_process("graphinator") is False


def test_check_process_empty_cmdline_skipped() -> None:
    with patch.object(healthcheck.psutil, "process_iter", return_value=[_proc(None), _proc([])]):
        assert healthcheck.check_process("graphinator") is False


def test_check_process_swallows_psutil_errors() -> None:
    bad = MagicMock()
    type(bad).info = property(lambda _self: (_ for _ in ()).throw(psutil.NoSuchProcess(1)))
    with patch.object(healthcheck.psutil, "process_iter", return_value=[bad]):
        assert healthcheck.check_process("graphinator") is False


def test_main_no_args_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(healthcheck.sys, "argv", ["healthcheck.py"])
    with pytest.raises(SystemExit) as exc:
        healthcheck.main()
    assert exc.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_process_running_exits_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(healthcheck.sys, "argv", ["healthcheck.py", "graphinator"])
    with patch.object(healthcheck, "check_process", return_value=True), pytest.raises(SystemExit) as exc:
        healthcheck.main()
    assert exc.value.code == 0


def test_main_process_missing_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(healthcheck.sys, "argv", ["healthcheck.py", "graphinator"])
    with patch.object(healthcheck, "check_process", return_value=False), pytest.raises(SystemExit) as exc:
        healthcheck.main()
    assert exc.value.code == 1
