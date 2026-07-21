"""Tests for utilities/check_errors.py — the service-log error scanner.

Also pins two CLAUDE.md contracts:
- ``subprocess.run`` is always called with ``timeout=`` and ``TimeoutExpired``
  is caught.
- The scanned service list uses the split extractor service names
  (``extractor-discogs`` / ``extractor-musicbrainz``), never a bare
  ``extractor``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from utilities import check_errors


if TYPE_CHECKING:
    import pytest


def _completed(stdout: str) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    return result


def test_check_service_errors_matches_patterns() -> None:
    logs = "\n".join(
        [
            "2026-01-01 graphinator ERROR Failed to process message 'id'",
            "2026-01-01 graphinator INFO everything fine",
            "2026-01-01 graphinator Traceback (most recent call last):",
        ]
    )
    with patch.object(check_errors.subprocess, "run", return_value=_completed(logs)) as run:
        errors = check_errors.check_service_errors("graphinator", 30)

    assert any("Failed to process message" in e for e in errors)
    assert any("Traceback" in e for e in errors)
    assert "everything fine" not in " ".join(errors)
    # Contract: timeout is always supplied and the window is passed through.
    kwargs = run.call_args.kwargs
    assert kwargs["timeout"] == 60
    assert "--since=30m" in run.call_args.args[0]


def test_check_service_errors_no_matches() -> None:
    with patch.object(check_errors.subprocess, "run", return_value=_completed("INFO all good\nDEBUG noop")):
        assert check_errors.check_service_errors("graphinator") == []


def test_check_service_errors_handles_called_process_error() -> None:
    exc = subprocess.CalledProcessError(1, ["docker"])
    with patch.object(check_errors.subprocess, "run", side_effect=exc):
        errors = check_errors.check_service_errors("graphinator")
    assert len(errors) == 1
    assert "Error getting logs" in errors[0]


def test_check_service_errors_handles_timeout() -> None:
    exc = subprocess.TimeoutExpired(["docker"], 60)
    with patch.object(check_errors.subprocess, "run", side_effect=exc):
        errors = check_errors.check_service_errors("graphinator")
    assert "Error getting logs" in errors[0]


def test_main_reports_grouped_errors(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(check_errors.sys, "argv", ["check_errors.py", "15"])

    def fake(service: str, _window: int) -> list[str]:
        if service == "graphinator":
            return [
                "ERROR Failed to process message 'id'",
                "ERROR Failed to process message 'id'",
                "2026 - svc - ERROR - some other failure",
                "ERROR bare error line without a hyphen group",
                "a plain line without markers",
            ]
        return []

    with patch.object(check_errors, "check_service_errors", side_effect=fake):
        check_errors.main()

    out = capsys.readouterr().out
    assert "last 15 minutes" in out
    assert "Failed to process message: 'id' (x2)" in out
    assert "No errors found" in out  # services with no errors
    assert "Total errors found:" in out
    assert "💡 Tip:" in out


def test_main_default_window_and_no_errors(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(check_errors.sys, "argv", ["check_errors.py"])
    with patch.object(check_errors, "check_service_errors", return_value=[]):
        check_errors.main()
    out = capsys.readouterr().out
    assert "last 60 minutes" in out
    assert "Total errors found: 0" in out
    assert "💡 Tip:" not in out  # no tip when nothing to show


def test_main_scans_split_extractor_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md contract: no bare 'extractor' service; both split names present."""
    monkeypatch.setattr(check_errors.sys, "argv", ["check_errors.py"])
    seen: list[str] = []

    def record(service: str, _window: int) -> list[str]:
        seen.append(service)
        return []

    with patch.object(check_errors, "check_service_errors", side_effect=record):
        check_errors.main()

    assert "extractor-discogs" in seen
    assert "extractor-musicbrainz" in seen
    assert "extractor" not in seen
