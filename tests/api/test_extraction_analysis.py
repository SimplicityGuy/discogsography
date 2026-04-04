"""Tests for extraction analysis router — versions and summary endpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch


if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

from tests.api.test_admin_endpoints import _admin_auth_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flagged_dir(base: Path, version: str, entity_type: str, violations: list[dict] | None = None) -> None:
    """Create a flagged directory with a violations.jsonl file."""
    entity_dir = base / "flagged" / version / entity_type
    entity_dir.mkdir(parents=True, exist_ok=True)
    lines = violations or [{"record_id": "123", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850"}]
    (entity_dir / "violations.jsonl").write_text("\n".join(json.dumps(v) for v in lines) + "\n")


def _make_state_marker(base: Path, version: str, source: str) -> None:
    """Create a state marker file for the given source."""
    marker = {
        "download_phase": {"status": "completed"},
        "processing_phase": {"status": "completed"},
        "publishing_phase": {"status": "completed"},
        "summary": {"total_records": 100},
    }
    if source == "discogs":
        (base / f".extraction_status_{version}.json").write_text(json.dumps(marker))
    else:
        mb_dir = base / version
        mb_dir.mkdir(parents=True, exist_ok=True)
        (mb_dir / f".mb_extraction_status_{version}.json").write_text(json.dumps(marker))


# ---------------------------------------------------------------------------
# Task 2: Versions endpoint
# ---------------------------------------------------------------------------


class TestVersionsEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.get("/api/admin/extraction-analysis/versions")
        assert resp.status_code == 401

    def test_empty_when_no_data_roots(self, test_client: TestClient) -> None:
        """Returns empty versions list when data roots are not configured."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", None), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/versions", headers=_admin_auth_headers())
        assert resp.status_code == 200
        assert resp.json() == {"versions": []}

    def test_empty_when_flagged_dir_missing(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns empty versions list when flagged directory does not exist."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/versions", headers=_admin_auth_headers())
        assert resp.status_code == 200
        assert resp.json() == {"versions": []}

    def test_discogs_versions(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns discogs versions from the flagged directory."""
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260101", "artists")
        _make_flagged_dir(tmp_path, "20260101", "releases")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/versions", headers=_admin_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 1
        v = data["versions"][0]
        assert v["version"] == "20260101"
        assert v["source"] == "discogs"
        assert set(v["entity_types"]) == {"artists", "releases"}

    def test_both_sources(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns versions from both discogs and musicbrainz roots."""
        import api.routers.extraction_analysis as ea

        discogs_root = tmp_path / "discogs"
        mb_root = tmp_path / "musicbrainz"
        _make_flagged_dir(discogs_root, "20260101", "artists")
        _make_flagged_dir(mb_root, "20260201", "labels")

        with patch.object(ea, "_discogs_data_root", discogs_root), patch.object(ea, "_musicbrainz_data_root", mb_root):
            resp = test_client.get("/api/admin/extraction-analysis/versions", headers=_admin_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        versions = {v["version"]: v for v in data["versions"]}
        assert "20260101" in versions
        assert versions["20260101"]["source"] == "discogs"
        assert "20260201" in versions
        assert versions["20260201"]["source"] == "musicbrainz"

    def test_skips_dirs_without_violations(self, test_client: TestClient, tmp_path: Path) -> None:
        """Skips entity directories that have no violations.jsonl file."""
        import api.routers.extraction_analysis as ea

        # Create entity dir but no violations.jsonl
        entity_dir = tmp_path / "flagged" / "20260101" / "artists"
        entity_dir.mkdir(parents=True)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/versions", headers=_admin_auth_headers())

        assert resp.status_code == 200
        # Version should not appear because it has no entity with violations
        assert resp.json() == {"versions": []}


# ---------------------------------------------------------------------------
# Task 3: Summary endpoint
# ---------------------------------------------------------------------------


class TestSummaryEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.get("/api/admin/extraction-analysis/20260101/summary")
        assert resp.status_code == 401

    def test_rejects_path_traversal(self, test_client: TestClient) -> None:
        """Returns 400 for version strings with path traversal characters."""
        resp = test_client.get(
            "/api/admin/extraction-analysis/../../../etc/passwd/summary",
            headers=_admin_auth_headers(),
        )
        # FastAPI will 404 for double dots in path, but if it reaches the handler it must 400
        assert resp.status_code in (400, 404, 422)

    def test_rejects_invalid_version(self, test_client: TestClient) -> None:
        """Returns 400 for version strings with invalid characters."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", None), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/bad version!/summary",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code in (400, 422)

    def test_not_found_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when the version is not found in either data root."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/99990101/summary",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_summary_with_violations(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns violation summary for a known discogs version."""
        import api.routers.extraction_analysis as ea

        violations = [
            {"record_id": "1", "rule": "year-out-of-range", "severity": "warning", "field": "year"},
            {"record_id": "2", "rule": "year-out-of-range", "severity": "warning", "field": "year"},
            {"record_id": "3", "rule": "missing-field", "severity": "error", "field": "title"},
        ]
        _make_flagged_dir(tmp_path, "20260101", "artists", violations=violations)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "20260101"
        assert data["source"] == "discogs"
        assert data["pipeline_status"] is None  # no state marker

        vs = data["violation_summary"]
        assert vs["total"] == 3
        assert vs["by_severity"]["warning"] == 2
        assert vs["by_severity"]["error"] == 1
        assert vs["by_entity_type"]["artists"] == 3
        assert vs["by_rule"]["year-out-of-range"] == 2
        assert vs["by_rule"]["missing-field"] == 1

    def test_summary_with_pipeline_status(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns pipeline_status when a state marker file exists."""
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260101", "artists")
        _make_state_marker(tmp_path, "20260101", "discogs")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_status"] is not None
        assert data["pipeline_status"]["download_phase"]["status"] == "completed"

    def test_summary_musicbrainz_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns summary for a musicbrainz version."""
        import api.routers.extraction_analysis as ea

        mb_root = tmp_path / "musicbrainz"
        _make_flagged_dir(mb_root, "20260201", "labels")
        _make_state_marker(mb_root, "20260201", "musicbrainz")

        with patch.object(ea, "_discogs_data_root", None), patch.object(ea, "_musicbrainz_data_root", mb_root):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260201/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "20260201"
        assert data["source"] == "musicbrainz"
        assert data["pipeline_status"] is not None

    def test_summary_handles_corrupt_jsonl(self, test_client: TestClient, tmp_path: Path) -> None:
        """Skips corrupt JSONL lines without failing."""
        import api.routers.extraction_analysis as ea

        entity_dir = tmp_path / "flagged" / "20260101" / "artists"
        entity_dir.mkdir(parents=True)
        (entity_dir / "violations.jsonl").write_text(
            '{"record_id": "1", "rule": "missing-field", "severity": "error"}\n'
            "THIS IS NOT JSON\n"
            '{"record_id": "3", "rule": "missing-field", "severity": "error"}\n'
        )

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        # Only 2 valid lines should be counted
        assert data["violation_summary"]["total"] == 2

    def test_summary_entity_type_injected(self, test_client: TestClient, tmp_path: Path) -> None:
        """Each violation has entity_type added from directory name."""
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(
            tmp_path,
            "20260101",
            "releases",
            violations=[
                {"record_id": "10", "rule": "bad-year", "severity": "warning"},
            ],
        )

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["violation_summary"]["by_entity_type"]["releases"] == 1
