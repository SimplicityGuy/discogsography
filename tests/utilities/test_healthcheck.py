"""Tests for utilities/healthcheck.py — the container process healthcheck."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psutil
import pytest

from utilities import healthcheck


def _proc(cmdline: list[str] | None, pid: int = 4242) -> MagicMock:
    proc = MagicMock()
    proc.info = {"pid": pid, "name": "python", "cmdline": cmdline}
    return proc


# Tests below patch _excluded_pids() to an empty set: they are exercising the
# cmdline-matching logic in isolation, decoupled from the real OS process tree
# (the mock pids here are arbitrary and must not accidentally collide with a
# real ancestor pid of the pytest worker — see the self-exclusion tests below
# for that behavior specifically).


def test_check_process_found() -> None:
    with (
        patch.object(healthcheck, "_excluded_pids", return_value=set()),
        patch.object(healthcheck.psutil, "process_iter", return_value=[_proc(["python", "graphinator/main.py"])]),
    ):
        assert healthcheck.check_process("graphinator") is True


def test_check_process_not_found() -> None:
    with (
        patch.object(healthcheck, "_excluded_pids", return_value=set()),
        patch.object(healthcheck.psutil, "process_iter", return_value=[_proc(["python", "other.py"])]),
    ):
        assert healthcheck.check_process("graphinator") is False


def test_check_process_empty_cmdline_skipped() -> None:
    with (
        patch.object(healthcheck, "_excluded_pids", return_value=set()),
        patch.object(healthcheck.psutil, "process_iter", return_value=[_proc(None), _proc([])]),
    ):
        assert healthcheck.check_process("graphinator") is False


def test_check_process_swallows_psutil_errors() -> None:
    bad = MagicMock()
    type(bad).info = property(lambda _self: (_ for _ in ()).throw(psutil.NoSuchProcess(1)))
    with (
        patch.object(healthcheck, "_excluded_pids", return_value=set()),
        patch.object(healthcheck.psutil, "process_iter", return_value=[bad]),
    ):
        assert healthcheck.check_process("graphinator") is False


class TestSelfExclusion:
    """Regression for discogsography-pyt3: check_process() must not match its own
    (or an ancestor's) process — its own cmdline is
    ['python', 'healthcheck.py', '<process_name>'], where argv[1] IS the search
    string, so without exclusion it always matched itself and the healthcheck
    could never report a dead service.
    """

    def test_own_process_is_excluded_even_though_cmdline_matches(self) -> None:
        own_pid = 4321
        self_proc = _proc(["python", "utilities/healthcheck.py", "graphinator"], pid=own_pid)
        with (
            patch.object(healthcheck, "_excluded_pids", return_value={own_pid}),
            patch.object(healthcheck.psutil, "process_iter", return_value=[self_proc]),
        ):
            assert healthcheck.check_process("graphinator") is False

    def test_ancestor_process_is_excluded(self) -> None:
        """Under `uv run` the parent chain is deeper than one hop (uv -> python),
        so every ancestor — not just the immediate parent — must be excluded."""
        ancestor_pid = 1111
        ancestor_proc = _proc(["uv", "run", "healthcheck.py", "graphinator"], pid=ancestor_pid)
        with (
            patch.object(healthcheck, "_excluded_pids", return_value={4321, ancestor_pid}),
            patch.object(healthcheck.psutil, "process_iter", return_value=[ancestor_proc]),
        ):
            assert healthcheck.check_process("graphinator") is False

    def test_unrelated_process_with_same_name_still_matches(self) -> None:
        """Exclusion is by pid, not by name — a genuinely running target process
        (a different pid than self/ancestors) must still be found."""
        real_proc = _proc(["python", "-m", "graphinator.graphinator"], pid=9999)
        with (
            patch.object(healthcheck, "_excluded_pids", return_value={4321, 1111}),
            patch.object(healthcheck.psutil, "process_iter", return_value=[real_proc]),
        ):
            assert healthcheck.check_process("graphinator") is True

    def test_excluded_pids_includes_self_and_real_ancestors(self) -> None:
        """_excluded_pids() must include os.getpid() and walk psutil's real
        parents() chain (not just the immediate parent)."""
        import os

        fake_parent = MagicMock()
        fake_parent.pid = 111
        fake_grandparent = MagicMock()
        fake_grandparent.pid = 1
        fake_self = MagicMock()
        fake_self.parents.return_value = [fake_parent, fake_grandparent]

        with patch.object(healthcheck.psutil, "Process", return_value=fake_self):
            result = healthcheck._excluded_pids()

        assert os.getpid() in result
        assert 111 in result
        assert 1 in result

    def test_excluded_pids_swallows_psutil_errors(self) -> None:
        """If the process tree can't be walked (e.g. AccessDenied), fall back to
        excluding just this process rather than raising."""
        import os

        with patch.object(healthcheck.psutil, "Process", side_effect=psutil.NoSuchProcess(os.getpid())):
            result = healthcheck._excluded_pids()

        assert result == {os.getpid()}


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
