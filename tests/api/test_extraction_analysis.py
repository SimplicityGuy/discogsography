"""Tests for extraction analysis router — versions and summary endpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch


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
        assert data["pipeline_status"] == {}  # no state marker

        assert data["total"] == 3
        assert data["by_severity"]["warning"] == 2
        assert data["by_severity"]["error"] == 1
        assert data["by_entity"]["artists"]["total"] == 3
        assert data["by_entity"]["artists"]["errors"] == 1
        assert data["by_entity"]["artists"]["warnings"] == 2
        # by_rule is now an array of {rule, entity_type, severity, count}
        rules = {(r["rule"], r["severity"]): r["count"] for r in data["by_rule"]}
        assert rules[("year-out-of-range", "warning")] == 2
        assert rules[("missing-field", "error")] == 1

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
        assert data["pipeline_status"]["download_phase"] == "completed"

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
        assert data["total"] == 2

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
        assert resp.json()["by_entity"]["releases"]["total"] == 1


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
            json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
        )
        assert resp.status_code == 401

    def test_not_found_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when version is not found."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/99990101/prompt-context",
                json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_validation_rejects_empty_rules(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 422 when rules list is empty."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"rules": []},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 422

    def test_prompt_context_with_records(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns contexts grouped by rule with sample records."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) == 1
        ctx = data["contexts"][0]
        assert ctx["rule"] == "year-out-of-range"
        assert ctx["entity_type"] == "artists"
        assert ctx["severity"] == "warning"
        assert ctx["total_violations"] == 2
        record_ids = {r["record_id"] for r in ctx["sample_records"]}
        assert "1" in record_ids
        assert "2" in record_ids

    def test_prompt_context_multiple_rules(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns separate contexts when multiple rules are selected."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={
                    "rules": [
                        {"rule": "year-out-of-range", "entity_type": "artists"},
                        {"rule": "missing-field", "entity_type": "artists"},
                    ]
                },
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) == 2
        rules = {ctx["rule"] for ctx in data["contexts"]}
        assert rules == {"year-out-of-range", "missing-field"}

    def test_prompt_context_no_matching_violations(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns empty sample_records when no violations match the rule+entity_type."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                json={"rules": [{"rule": "nonexistent-rule", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) == 1
        assert data["contexts"][0]["total_violations"] == 0
        assert data["contexts"][0]["sample_records"] == []


class TestGenerateAiPromptEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        """Returns 401 without a valid token."""
        resp = test_client.post(
            "/api/admin/extraction-analysis/20260101/generate-ai-prompt",
            json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
        )
        assert resp.status_code == 401

    def test_returns_503_when_no_anthropic_client(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 503 when NLQ_API_KEY is not configured."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with (
            patch.object(ea, "_discogs_data_root", tmp_path),
            patch.object(ea, "_musicbrainz_data_root", None),
            patch.object(ea, "_anthropic_client", None),
        ):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/generate-ai-prompt",
                json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 503
        assert "NLQ_API_KEY" in resp.json()["detail"]

    def test_not_found_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 404 when version is not found."""
        import api.routers.extraction_analysis as ea

        mock_client = MagicMock()
        with (
            patch.object(ea, "_discogs_data_root", tmp_path),
            patch.object(ea, "_musicbrainz_data_root", None),
            patch.object(ea, "_anthropic_client", mock_client),
        ):
            resp = test_client.post(
                "/api/admin/extraction-analysis/99990101/generate-ai-prompt",
                json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_validation_rejects_empty_rules(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 422 when rules list is empty."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)
        mock_client = MagicMock()

        with (
            patch.object(ea, "_discogs_data_root", tmp_path),
            patch.object(ea, "_musicbrainz_data_root", None),
            patch.object(ea, "_anthropic_client", mock_client),
        ):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/generate-ai-prompt",
                json={"rules": []},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 422

    def test_successful_ai_prompt_generation(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns AI-generated prompt when Anthropic client is available."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        # Mock the Anthropic client response
        mock_text_block = MagicMock()
        mock_text_block.text = "## Root Cause Analysis\nThe year field is missing."
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(ea, "_discogs_data_root", tmp_path),
            patch.object(ea, "_musicbrainz_data_root", None),
            patch.object(ea, "_anthropic_client", mock_client),
            patch.object(ea, "_anthropic_model", "claude-sonnet-4-20250514"),
        ):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/generate-ai-prompt",
                json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_generated"] is True
        assert "Root Cause Analysis" in data["prompt"]
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert "year-out-of-range" in call_kwargs["messages"][0]["content"]

    def test_returns_502_on_anthropic_error(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns 502 when the Anthropic API call fails."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API unavailable"))

        with (
            patch.object(ea, "_discogs_data_root", tmp_path),
            patch.object(ea, "_musicbrainz_data_root", None),
            patch.object(ea, "_anthropic_client", mock_client),
        ):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/generate-ai-prompt",
                json={"rules": [{"rule": "year-out-of-range", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 502

    def test_no_matching_violations_still_succeeds(self, test_client: TestClient, tmp_path: Path) -> None:
        """Returns successfully even when no violations match — empty context sent to AI."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        mock_text_block = MagicMock()
        mock_text_block.text = "No violations found for the selected rules."
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(ea, "_discogs_data_root", tmp_path),
            patch.object(ea, "_musicbrainz_data_root", None),
            patch.object(ea, "_anthropic_client", mock_client),
        ):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/generate-ai-prompt",
                json={"rules": [{"rule": "nonexistent-rule", "entity_type": "artists"}]},
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_generated"] is True


# ---------------------------------------------------------------------------
# Additional edge-case coverage tests
# ---------------------------------------------------------------------------


class TestValidateRecordId:
    def test_rejects_invalid_record_id_in_detail_endpoint(self, test_client: TestClient, tmp_path: Path) -> None:
        """_validate_record_id raises HTTP 400 when record_id contains unsafe characters (line 70)."""
        import api.routers.extraction_analysis as ea

        _make_flagged_version(tmp_path)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/bad%2Frecord",
                headers=_admin_auth_headers(),
            )
        # FastAPI may 404 before reaching the handler for encoded slashes, but
        # if it does reach the handler the validation must reject with 400.
        assert resp.status_code in (400, 404, 422)

    def test_rejects_dotdot_record_id(self) -> None:
        """Direct call to _validate_record_id raises HTTPException for ../etc style strings (line 70)."""
        from fastapi import HTTPException

        import api.routers.extraction_analysis as ea

        try:
            ea._validate_record_id("../etc/passwd")
            raised = False
        except HTTPException as exc:
            raised = True
            assert exc.status_code == 400
        assert raised, "Expected HTTPException to be raised"


class TestScanVersionsNonDir:
    def test_skips_non_directory_entries_in_flagged(self, test_client: TestClient, tmp_path: Path) -> None:
        """_scan_versions skips regular files inside flagged/ — only version dirs are scanned (line 91)."""
        import api.routers.extraction_analysis as ea

        # Create a valid version dir
        _make_flagged_dir(tmp_path, "20260101", "artists")
        # Place a regular file alongside it in flagged/
        (tmp_path / "flagged" / "stale_file.txt").write_text("not a dir")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/versions", headers=_admin_auth_headers())

        assert resp.status_code == 200
        versions = resp.json()["versions"]
        # Only the real version dir should appear; the regular file must be skipped
        assert len(versions) == 1
        assert versions[0]["version"] == "20260101"


class TestReadViolationsEdgeCases:
    def test_skips_non_directory_entity_entries(self, test_client: TestClient, tmp_path: Path) -> None:
        """_read_violations skips non-directory entries inside the version dir (line 119)."""
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260101", "artists")
        # Place a regular file alongside the entity dir
        (tmp_path / "flagged" / "20260101" / "junk.txt").write_text("not a dir")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        # The junk file must not inflate the violation count
        assert resp.json()["total"] == 1

    def test_skips_entity_dirs_without_violations_jsonl(self, test_client: TestClient, tmp_path: Path) -> None:
        """_read_violations skips entity dirs that have no violations.jsonl (line 122)."""
        import api.routers.extraction_analysis as ea

        # Create a version dir with one entity that has violations and one that doesn't
        _make_flagged_dir(tmp_path, "20260101", "artists")
        empty_entity = tmp_path / "flagged" / "20260101" / "labels"
        empty_entity.mkdir(parents=True)
        # No violations.jsonl in labels dir

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        # Only the artists violation should be counted
        assert resp.json()["total"] == 1

    def test_skips_empty_lines_in_jsonl(self, test_client: TestClient, tmp_path: Path) -> None:
        """_read_violations skips blank lines in violations.jsonl (line 127)."""
        import api.routers.extraction_analysis as ea

        entity_dir = tmp_path / "flagged" / "20260101" / "artists"
        entity_dir.mkdir(parents=True)
        (entity_dir / "violations.jsonl").write_text(
            '{"record_id": "1", "rule": "missing-field", "severity": "error"}\n'
            "\n"
            "   \n"
            '{"record_id": "2", "rule": "missing-field", "severity": "error"}\n'
        )

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        # Empty lines must be skipped; only 2 real records
        assert resp.json()["total"] == 2


class TestLoadStateMarkerCorrupt:
    def test_corrupt_state_marker_returns_none(self, test_client: TestClient, tmp_path: Path) -> None:
        """_load_state_marker returns None (and logs warning) for corrupt JSON state marker (lines 150-152)."""
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260101", "artists")
        # Write corrupt JSON to the state marker file
        (tmp_path / ".extraction_status_20260101.json").write_text("{ NOT VALID JSON }")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        # pipeline_status must be empty when state marker is corrupt
        assert resp.json()["pipeline_status"] == {}


class TestLoadRecordFilesErrors:
    def test_unreadable_xml_file_returns_null(self, test_client: TestClient, tmp_path: Path) -> None:
        """OSError reading XML file yields null raw_xml in violation detail (lines 190-191)."""
        import api.routers.extraction_analysis as ea

        violations = [{"record_id": "42", "rule": "missing-field", "severity": "error", "field": "title"}]
        entity_dir = tmp_path / "flagged" / "20260101" / "artists"
        entity_dir.mkdir(parents=True)
        (entity_dir / "violations.jsonl").write_text(json.dumps(violations[0]) + "\n")
        xml_path = entity_dir / "42.xml"
        xml_path.write_text("<artist><title>Test</title></artist>")
        xml_path.chmod(0o000)

        try:
            with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
                resp = test_client.get(
                    "/api/admin/extraction-analysis/20260101/violations/42",
                    headers=_admin_auth_headers(),
                )
        finally:
            xml_path.chmod(0o644)

        assert resp.status_code == 200
        assert resp.json()["raw_xml"] is None

    def test_corrupt_json_file_returns_null(self, test_client: TestClient, tmp_path: Path) -> None:
        """Corrupt JSON file yields null parsed_json in violation detail (lines 197-198)."""
        import api.routers.extraction_analysis as ea

        violations = [{"record_id": "55", "rule": "missing-field", "severity": "error", "field": "title"}]
        entity_dir = tmp_path / "flagged" / "20260101" / "artists"
        entity_dir.mkdir(parents=True)
        (entity_dir / "violations.jsonl").write_text(json.dumps(violations[0]) + "\n")
        (entity_dir / "55.xml").write_text("<artist><title>Test</title></artist>")
        (entity_dir / "55.json").write_text("{ NOT VALID JSON }")

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/55",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["parsed_json"] is None


class TestLoadRecordFilesTruncation:
    def test_oversized_json_returns_truncation_marker(self, test_client: TestClient, tmp_path: Path) -> None:
        """Oversized JSON file returns _truncated dict instead of parsed content."""
        import api.routers.extraction_analysis as ea

        violations = [{"record_id": "77", "rule": "missing-field", "severity": "error", "field": "title"}]
        entity_dir = tmp_path / "flagged" / "20260101" / "artists"
        entity_dir.mkdir(parents=True)
        (entity_dir / "violations.jsonl").write_text(json.dumps(violations[0]) + "\n")

        # Create a JSON file larger than _MAX_RECORD_FILE_BYTES (512 KiB)
        large_json = json.dumps({"data": "x" * (600 * 1024)})
        (entity_dir / "77.json").write_text(large_json)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/77",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed_json"]["_truncated"] is True
        assert "too large" in data["parsed_json"]["_message"]
        assert "_preview" in data["parsed_json"]
        assert data["truncated"] is True


class TestViolationDetailNotFound:
    def test_version_not_found_returns_404(self, test_client: TestClient, tmp_path: Path) -> None:
        """violation_detail returns 404 when version directory does not exist (line 319)."""
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/99990101/violations/abc123",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404


class TestExtractXmlFieldValue:
    def test_invalid_xml_returns_none(self) -> None:
        """_extract_xml_field_value returns None for malformed XML (lines 359-361)."""
        import api.routers.extraction_analysis as ea

        result = ea._extract_xml_field_value("<<< not xml >>>", "year")
        assert result is None

    def test_nested_element_found_via_iter(self) -> None:
        """_extract_xml_field_value finds element using iter() when find() misses nested path (lines 367-368)."""
        import api.routers.extraction_analysis as ea

        # <root><data><year>1995</year></data></root> — find('year') fails on root, iter finds it
        xml = "<root><data><year>1995</year></data></root>"
        result = ea._extract_xml_field_value(xml, "year")
        assert result == "1995"


class TestClassifyViolationBothPresent:
    def test_both_xml_and_json_have_value_returns_source_issue(self, tmp_path: Path) -> None:
        """_classify_violation returns source_issue when both XML and JSON have the field (line 413)."""
        import api.routers.extraction_analysis as ea

        entity_dir = tmp_path / "artists"
        entity_dir.mkdir(parents=True)
        (entity_dir / "99.xml").write_text("<artist><year>1990</year></artist>")
        (entity_dir / "99.json").write_text(json.dumps({"year": "1990"}))

        violation = {"record_id": "99", "rule": "year-out-of-range", "severity": "warning", "field": "year"}
        result = ea._classify_violation(violation, tmp_path, "artists")
        # Both present — should be classified as source_issue (not parsing_error)
        assert result["classification"] == "source_issue"
        assert result["xml_value"] == "1990"
        assert result["json_value"] == "1990"


class TestCompareVersionsEdgeCases:
    def test_removed_rule_in_version_b(self, test_client: TestClient, tmp_path: Path) -> None:
        """Rule present in A but absent in B is counted as improved/removed_rules (lines 540-542)."""
        import api.routers.extraction_analysis as ea

        violations_a = [{"record_id": "1", "rule": "old-rule", "severity": "warning", "field": "x"}]
        violations_b = [{"record_id": "2", "rule": "new-rule", "severity": "warning", "field": "y"}]
        _make_flagged_dir(tmp_path, "20260101", "artists", violations=violations_a)
        _make_flagged_dir(tmp_path, "20260201", "artists", violations=violations_b)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/compare/20260201",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        summary = data["summary"]
        # old-rule is in A but not B → improved + removed_rules
        assert summary["removed_rules"] >= 1
        assert summary["improved"] >= 1
        by_rule = {d["rule"]: d for d in data["details"]}
        assert by_rule["old-rule"]["direction"] == "improved"

    def test_worsened_non_new_rule(self, test_client: TestClient, tmp_path: Path) -> None:
        """Rule in both versions with more violations in B is worsened (not new_rule) (lines 547-548)."""
        import api.routers.extraction_analysis as ea

        violations_a = [{"record_id": "1", "rule": "missing-field", "severity": "error", "field": "title"}]
        violations_b = [
            {"record_id": "2", "rule": "missing-field", "severity": "error", "field": "title"},
            {"record_id": "3", "rule": "missing-field", "severity": "error", "field": "title"},
        ]
        _make_flagged_dir(tmp_path, "20260101", "artists", violations=violations_a)
        _make_flagged_dir(tmp_path, "20260201", "artists", violations=violations_b)

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/compare/20260201",
                headers=_admin_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        by_rule = {d["rule"]: d for d in data["details"]}
        assert by_rule["missing-field"]["direction"] == "worsened"
        # Must NOT be counted as a new rule
        assert data["summary"]["new_rules"] == 0
        assert data["summary"]["worsened"] == 1


# ---------------------------------------------------------------------------
# Task 8: Skipped records helpers & endpoints
# ---------------------------------------------------------------------------


def _make_skipped_file(base: Path, version: str, entity_type: str, skipped: list[dict] | None = None) -> None:
    """Create a flagged directory with a skipped.jsonl file."""
    entity_dir = base / "flagged" / version / entity_type
    entity_dir.mkdir(parents=True, exist_ok=True)
    entries = skipped or [
        {"record_id": "66827", "reason": "Upstream junk entry marked DO NOT USE", "field": "profile", "field_value": "[b]DO NOT USE.[/b]"}
    ]
    (entity_dir / "skipped.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


class TestSkippedEndpoint:
    def test_requires_auth(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/extraction-analysis/20260401/skipped")
        assert resp.status_code == 401

    def test_returns_skipped_records(self, test_client: TestClient, tmp_path: Path) -> None:
        import api.routers.extraction_analysis as ea

        _make_skipped_file(tmp_path, "20260401", "artists")
        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/20260401/skipped", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["skipped"][0]["record_id"] == "66827"
        assert data["skipped"][0]["entity_type"] == "artists"

    def test_filters_by_entity_type(self, test_client: TestClient, tmp_path: Path) -> None:
        import api.routers.extraction_analysis as ea

        _make_skipped_file(tmp_path, "20260401", "artists")
        _make_skipped_file(tmp_path, "20260401", "labels", [{"record_id": "212", "reason": "Junk", "field": "profile", "field_value": "DO NOT USE"}])
        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/20260401/skipped?entity_type=labels", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["skipped"][0]["record_id"] == "212"

    def test_empty_when_no_skipped(self, test_client: TestClient, tmp_path: Path) -> None:
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260401", "artists")
        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/20260401/skipped", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["skipped"] == []

    def test_version_not_found(self, test_client: TestClient, tmp_path: Path) -> None:
        import api.routers.extraction_analysis as ea

        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/99999999/skipped", headers=_admin_auth_headers())
        assert resp.status_code == 404


class TestSummarySkippedField:
    def test_summary_includes_skipped(self, test_client: TestClient, tmp_path: Path) -> None:
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260401", "artists")
        _make_skipped_file(tmp_path, "20260401", "artists")
        _make_state_marker(tmp_path, "20260401", "discogs")
        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/20260401/summary", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "skipped" in data
        assert data["skipped"]["artists"]["count"] == 1
        assert "Upstream junk" in data["skipped"]["artists"]["reasons"][0]

    def test_summary_skipped_empty_when_none(self, test_client: TestClient, tmp_path: Path) -> None:
        import api.routers.extraction_analysis as ea

        _make_flagged_dir(tmp_path, "20260401", "artists")
        _make_state_marker(tmp_path, "20260401", "discogs")
        with patch.object(ea, "_discogs_data_root", tmp_path), patch.object(ea, "_musicbrainz_data_root", None):
            resp = test_client.get("/api/admin/extraction-analysis/20260401/summary", headers=_admin_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] == {}
