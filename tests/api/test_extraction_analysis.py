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


# ---------------------------------------------------------------------------
# Shared helper for Tasks 4-6
# ---------------------------------------------------------------------------


def _make_flagged_version(tmp_path: Path, version: str = "20260101") -> Path:
    """Create a sample flagged directory with violations and record files for the given version.

    Layout:
        {tmp_path}/flagged/{version}/artists/violations.jsonl  (3 violations)
        {tmp_path}/flagged/{version}/artists/{record_id}.xml
        {tmp_path}/flagged/{version}/artists/{record_id}.json
    """
    violations = [
        {"record_id": "1", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850"},
        {"record_id": "2", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1920"},
        {"record_id": "3", "rule": "missing-field", "severity": "error", "field": "title", "field_value": ""},
    ]
    entity_dir = tmp_path / "flagged" / version / "artists"
    entity_dir.mkdir(parents=True, exist_ok=True)
    (entity_dir / "violations.jsonl").write_text("\n".join(json.dumps(v) for v in violations) + "\n")

    # Record 1: XML has year, JSON is missing it → parsing_error
    (entity_dir / "1.xml").write_text("<artist><year>1850</year><name>Test</name></artist>")
    (entity_dir / "1.json").write_text(json.dumps({"name": "Test"}))

    # Record 2: XML also missing year → source_issue
    (entity_dir / "2.xml").write_text("<artist><name>Old Artist</name></artist>")
    (entity_dir / "2.json").write_text(json.dumps({"name": "Old Artist"}))

    # Record 3: no files at all → indeterminate
    # (no .xml or .json written)

    return tmp_path / "flagged" / version


# ---------------------------------------------------------------------------
# Task 4: Violations List endpoint
# ---------------------------------------------------------------------------


class TestViolationsListEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.get("/api/admin/extraction-analysis/20260101/violations")
        assert resp.status_code == 401

    def test_not_found_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 for an unknown version."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/99990101/violations", headers=_admin_auth_headers())
        assert resp.status_code == 404

    def test_paginated_results(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns paginated violations with correct pagination metadata."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?page=1&page_size=2",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["violations"]) == 2
        pagination = data["pagination"]
        assert pagination["page"] == 1
        assert pagination["page_size"] == 2
        assert pagination["total_items"] == 3
        assert pagination["total_pages"] == 2

    def test_filter_by_severity(self, test_client: TestClient, tmp_path: Path) -> None:
        """Filters violations by severity."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?severity=error",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total_items"] == 1
        assert all(v["severity"] == "error" for v in data["violations"])

    def test_filter_by_rule(self, test_client: TestClient, tmp_path: Path) -> None:
        """Filters violations by rule."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?rule=year-out-of-range",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total_items"] == 2
        assert all(v["rule"] == "year-out-of-range" for v in data["violations"])

    def test_filter_by_entity_type(self, test_client: TestClient, tmp_path: Path) -> None:
        """Filters violations by entity_type."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?entity_type=artists",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total_items"] == 3

    def test_empty_page_beyond_results(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns empty violations list for a page beyond available results."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?page=99&page_size=50",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["violations"] == []
        assert data["pagination"]["total_items"] == 3


# ---------------------------------------------------------------------------
# Task 4: Violation Detail endpoint
# ---------------------------------------------------------------------------


class TestViolationDetailEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.get("/api/admin/extraction-analysis/20260101/violations/1")
        assert resp.status_code == 401

    def test_not_found_for_unknown_record(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when record_id has no violations."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/9999",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_record_detail_with_files(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns violation detail with raw XML and parsed JSON when files are present."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/1",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["record_id"] == "1"
        assert data["entity_type"] == "artists"
        assert len(data["violations"]) == 1
        assert data["raw_xml"] is not None
        assert "<year>1850</year>" in data["raw_xml"]
        assert data["parsed_json"] is not None
        assert data["parsed_json"]["name"] == "Test"

    def test_record_detail_null_for_missing_files(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns null raw_xml and parsed_json when record files are missing."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/3",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["record_id"] == "3"
        assert data["raw_xml"] is None
        assert data["parsed_json"] is None


# ---------------------------------------------------------------------------
# Task 5: Parsing Errors endpoint
# ---------------------------------------------------------------------------


class TestParsingErrorsEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.get("/api/admin/extraction-analysis/20260101/parsing-errors")
        assert resp.status_code == 401

    def test_not_found_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 for an unknown version."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/99990101/parsing-errors", headers=_admin_auth_headers())
        assert resp.status_code == 404

    def test_classifies_parsing_error(self, test_client: TestClient, tmp_path: Path) -> None:
        """Record 1 is a parsing_error: XML has year but JSON doesn't."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        parsing_errors = data["parsing_errors"]
        assert any(e["record_id"] == "1" and e["classification"] == "parsing_error" for e in parsing_errors)

    def test_classifies_source_issue(self, test_client: TestClient, tmp_path: Path) -> None:
        """Record 2 is a source_issue: neither XML nor JSON has the year field."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        source_issues = data["source_issues"]
        assert any(e["record_id"] == "2" and e["classification"] == "source_issue" for e in source_issues)

    def test_classifies_indeterminate(self, test_client: TestClient, tmp_path: Path) -> None:
        """Record 3 is indeterminate: XML and JSON files are missing."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        indeterminate = data["indeterminate"]
        assert any(e["record_id"] == "3" and e["classification"] == "indeterminate" for e in indeterminate)

    def test_stats_totals(self, test_client: TestClient, tmp_path: Path) -> None:
        """Stats totals add up to total_analyzed."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        stats = resp.json()["stats"]
        assert stats["total_analyzed"] == stats["parsing_errors"] + stats["source_issues"] + stats["indeterminate"]

    def test_caches_result(self, test_client: TestClient, tmp_path: Path) -> None:
        """A second identical request returns the same result (cached)."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp1 = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )
            resp2 = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()


# ---------------------------------------------------------------------------
# Task 6: Compare endpoint
# ---------------------------------------------------------------------------


class TestCompareEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.get("/api/admin/extraction-analysis/20260101/compare/20260201")
        assert resp.status_code == 401

    def test_not_found_for_unknown_version_a(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when version_a is not found."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path, version="20260201")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/99990101/compare/20260201",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_not_found_for_unknown_version_b(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when version_b is not found."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path, version="20260101")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/compare/99990201",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_compare_two_versions(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns a delta between two versions with correct direction labels."""
        import api.routers.extraction_analysis as ea

        # Version A: 2 year-out-of-range warnings, 1 missing-field error
        _make_flagged_version(tmp_path, version="20260101")

        # Version B: 1 year-out-of-range warning (improved), same missing-field, new extra-field info
        violations_b = [
            {"record_id": "1", "rule": "year-out-of-range", "severity": "warning", "field": "year"},
            {"record_id": "3", "rule": "missing-field", "severity": "error", "field": "title"},
            {"record_id": "4", "rule": "extra-field", "severity": "info", "field": "notes"},
        ]
        _make_flagged_dir(tmp_path, "20260201", "artists", violations=violations_b)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/compare/20260201",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["version_a"] == "20260101"
        assert data["version_b"] == "20260201"

        by_rule = {d["rule"]: d for d in data["details"]}
        assert by_rule["year-out-of-range"]["direction"] == "improved"  # 2 → 1
        assert by_rule["missing-field"]["direction"] == "unchanged"  # 1 → 1
        assert by_rule["extra-field"]["direction"] == "worsened"  # 0 → 1 (new rule)

        summary = data["summary"]
        assert summary["improved"] >= 1
        assert summary["worsened"] >= 1
        assert summary["new_rules"] >= 1


# ---------------------------------------------------------------------------
# Task 6: Prompt Context endpoint
# ---------------------------------------------------------------------------


class TestPromptContextEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.post(
            "/api/admin/extraction-analysis/20260101/prompt-context",
            json={"record_ids": ["1"], "rule": "year-out-of-range"},
        )
        assert resp.status_code == 401

    def test_not_found_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when version is not found."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/99990101/prompt-context",
                json={"record_ids": ["1"], "rule": "year-out-of-range"},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_validation_rejects_empty_record_ids(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 422 when record_ids is empty."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"record_ids": [], "rule": "year-out-of-range"},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 422

    def test_prompt_context_with_records(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns records with violation, raw_xml, and parsed_json."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"record_ids": ["1", "2"], "rule": "year-out-of-range"},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rule"] == "year-out-of-range"
        assert data["extractor_context"]["parser_file"] == "extractor/src/xml_parser.rs"
        assert data["extractor_context"]["rules_file"] == "extractor/extraction-rules.yaml"
        assert len(data["records"]) == 2
        record_ids = {r["record_id"] for r in data["records"]}
        assert "1" in record_ids
        assert "2" in record_ids

    def test_prompt_context_rule_definition_loaded(self, test_client: TestClient, tmp_path: Path) -> None:
        """Loads rule definition from extraction-rules.yaml when present."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)
        (tmp_path / "extraction-rules.yaml").write_text(
            "rules:\n  - id: year-out-of-range\n    description: Year is out of valid range\n    severity: warning\n"
        )

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"record_ids": ["1"], "rule": "year-out-of-range"},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rule_definition"] is not None
        assert data["rule_definition"]["id"] == "year-out-of-range"
        assert data["rule_definition"]["description"] == "Year is out of valid range"

    def test_prompt_context_rule_definition_null_when_missing(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns null rule_definition when extraction-rules.yaml is absent."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"record_ids": ["1"], "rule": "year-out-of-range"},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rule_definition"] is None

    def test_prompt_context_skips_unmatched_records(self, test_client: TestClient, tmp_path: Path) -> None:
        """Skips record_ids that have no violations for the given rule."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"record_ids": ["3", "9999"], "rule": "year-out-of-range"},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        # Record 3 has missing-field rule, not year-out-of-range; 9999 doesn't exist
        assert data["records"] == []
