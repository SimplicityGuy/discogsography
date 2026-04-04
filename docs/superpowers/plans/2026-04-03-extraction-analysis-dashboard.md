# Extraction Analysis Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Extraction Analysis" admin tab that analyzes extractor flagged records and state markers, with parsing error detection and Claude prompt generation.

**Architecture:** New API router (`api/routers/extraction_analysis.py`) reads flagged record data and state markers from read-only mounted volumes. Dashboard proxies requests through `admin_proxy.py` and renders a new admin tab with three sub-views: single version report, version comparison, and prompt generator.

**Tech Stack:** Python 3.13+ / FastAPI / Tailwind CSS / vanilla JS. Uses `defusedxml` for safe XML parsing. No new database tables.

**Spec:** `docs/superpowers/specs/2026-04-03-extraction-analysis-dashboard-design.md`

______________________________________________________________________

## File Structure

| Action | File                                                | Responsibility                                              |
| ------ | --------------------------------------------------- | ----------------------------------------------------------- |
| Create | `api/routers/extraction_analysis.py`                | All 7 API endpoints under `/api/admin/extraction-analysis/` |
| Create | `tests/api/test_extraction_analysis.py`             | API endpoint tests with mock filesystem                     |
| Modify | `api/api.py:39,258,399`                             | Import, configure, and register the new router              |
| Modify | `docker-compose.yml:263-264`                        | Add read-only data volume mounts to API service             |
| Modify | `docker-compose.prod.yml:186+`                      | Add read-only data volume mounts to API (prod)              |
| Modify | `dashboard/admin_proxy.py:30,352`                   | Add path regex with dots + 7 new proxy routes               |
| Modify | `dashboard/static/admin.html:282,773`               | Add tab button + tab panel HTML                             |
| Modify | `dashboard/static/admin.js:229,247,1454`            | Add tab switching + all fetch/render methods                |
| Create | `tests/dashboard/test_extraction_analysis_proxy.py` | Dashboard proxy route tests                                 |

______________________________________________________________________

### Task 1: Docker Compose Volume Mounts

**Files:**

- Modify: `docker-compose.yml:263-264`

- Modify: `docker-compose.prod.yml:186+`

- [ ] **Step 1: Add data volumes to API service in docker-compose.yml**

In `docker-compose.yml`, the API service volumes section is at line 263-264. Add the data volume mounts:

```yaml
    volumes:
      - api_logs:/logs
      - discogs_data:/discogs-data:ro
      - musicbrainz_data:/musicbrainz-data:ro
```

- [ ] **Step 2: Add environment variables in docker-compose.yml**

In the API service `environment:` section (after line 247), add:

```yaml
      DISCOGS_DATA_ROOT: /discogs-data
      MUSICBRAINZ_DATA_ROOT: /musicbrainz-data
```

- [ ] **Step 3: Add data volumes to API service in docker-compose.prod.yml**

Find the `api:` service in `docker-compose.prod.yml` (line 186) and add the same volume mounts. Check the prod file for exact syntax — it may not have an explicit `volumes:` key for the API yet, just secrets.

- [ ] **Step 4: Verify compose is valid**

Run: `docker compose config --quiet`
Expected: No output (success)

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.prod.yml
git commit -m "feat: mount discogs/musicbrainz data volumes on API service (read-only)"
```

______________________________________________________________________

### Task 2: API Router — Versions Endpoint

**Files:**

- Create: `api/routers/extraction_analysis.py`

- Create: `tests/api/test_extraction_analysis.py`

- [ ] **Step 1: Write tests for the versions endpoint**

Create `tests/api/test_extraction_analysis.py`:

```python
"""Tests for extraction analysis admin endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

# Re-use admin auth helpers from existing test file
from tests.api.test_admin_endpoints import _admin_auth_headers


class TestListVersions:
    """GET /api/admin/extraction-analysis/versions"""

    def test_returns_401_without_token(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/extraction-analysis/versions")
        assert resp.status_code == 401

    def test_returns_empty_when_no_flagged_dirs(self, test_client: TestClient) -> None:
        with patch("api.routers.extraction_analysis._discogs_data_root", new=Path("/nonexistent")), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/versions",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["versions"] == []

    def test_returns_discogs_versions(self, test_client: TestClient, tmp_path: Path) -> None:
        # Create flagged directory structure
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)
        (flagged / "violations.jsonl").write_text("")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/versions",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 1
        assert data["versions"][0]["version"] == "20260101"
        assert data["versions"][0]["source"] == "discogs"
        assert "releases" in data["versions"][0]["entity_types"]

    def test_returns_both_sources(self, test_client: TestClient, tmp_path: Path) -> None:
        discogs_root = tmp_path / "discogs"
        mb_root = tmp_path / "musicbrainz"

        (discogs_root / "flagged" / "20260101" / "artists").mkdir(parents=True)
        (discogs_root / "flagged" / "20260101" / "artists" / "violations.jsonl").write_text("")

        (mb_root / "flagged" / "20260301" / "artists").mkdir(parents=True)
        (mb_root / "flagged" / "20260301" / "artists" / "violations.jsonl").write_text("")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=discogs_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=mb_root):
            resp = test_client.get(
                "/api/admin/extraction-analysis/versions",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        sources = {v["source"] for v in data["versions"]}
        assert sources == {"discogs", "musicbrainz"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_extraction_analysis.py -v -x`
Expected: ImportError or ModuleNotFoundError for `api.routers.extraction_analysis`

- [ ] **Step 3: Create the extraction_analysis router with versions endpoint**

Create `api/routers/extraction_analysis.py`:

```python
"""Admin endpoints for extraction failure analysis.

Reads flagged record data and state markers from mounted data volumes.
All endpoints require admin authentication.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
import structlog

from api.dependencies import require_admin


logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state — set via configure()
_discogs_data_root: Path = Path(os.environ.get("DISCOGS_DATA_ROOT", "/discogs-data"))
_musicbrainz_data_root: Path = Path(os.environ.get("MUSICBRAINZ_DATA_ROOT", "/musicbrainz-data"))

# Strict version pattern: alphanumeric, hyphens, underscores, dots
_SAFE_VERSION = re.compile(r"^[a-zA-Z0-9._-]+$")
# Strict record ID pattern: alphanumeric, hyphens, underscores, dots
_SAFE_RECORD_ID = re.compile(r"^[a-zA-Z0-9._-]+$")


def configure(discogs_root: str | None = None, musicbrainz_root: str | None = None) -> None:
    """Set data root paths — called once during app lifespan startup."""
    global _discogs_data_root, _musicbrainz_data_root
    if discogs_root:
        _discogs_data_root = Path(discogs_root)
    if musicbrainz_root:
        _musicbrainz_data_root = Path(musicbrainz_root)


def _validate_version(version: str) -> None:
    """Raise 400 if version contains unsafe characters."""
    if not _SAFE_VERSION.match(version):
        raise HTTPException(status_code=400, detail="Invalid version format")


def _validate_record_id(record_id: str) -> None:
    """Raise 400 if record_id contains unsafe characters."""
    if not _SAFE_RECORD_ID.match(record_id):
        raise HTTPException(status_code=400, detail="Invalid record ID format")


def _scan_versions(data_root: Path, source: str) -> list[dict[str, Any]]:
    """Scan a data root for flagged version directories."""
    flagged_dir = data_root / "flagged"
    if not flagged_dir.is_dir():
        return []
    versions = []
    for version_dir in sorted(flagged_dir.iterdir(), reverse=True):
        if not version_dir.is_dir():
            continue
        entity_types = [
            d.name for d in version_dir.iterdir()
            if d.is_dir() and (d / "violations.jsonl").exists()
        ]
        if entity_types:
            versions.append({
                "version": version_dir.name,
                "source": source,
                "entity_types": sorted(entity_types),
            })
    return versions


@router.get("/api/admin/extraction-analysis/versions")
async def list_versions(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """List available extraction versions with flagged data."""
    versions = _scan_versions(_discogs_data_root, "discogs")
    versions.extend(_scan_versions(_musicbrainz_data_root, "musicbrainz"))
    # Sort by version descending (most recent first)
    versions.sort(key=lambda v: v["version"], reverse=True)
    return JSONResponse(content={"versions": versions})
```

- [ ] **Step 4: Register the router in api/api.py**

Add import at line 39 (with the other router imports):

```python
import api.routers.extraction_analysis as _extraction_analysis_router
```

Add configure call around line 258 (with the other configure calls):

```python
_extraction_analysis_router.configure(
    discogs_root=os.environ.get("DISCOGS_DATA_ROOT"),
    musicbrainz_root=os.environ.get("MUSICBRAINZ_DATA_ROOT"),
)
```

Add router inclusion around line 403 (with the other include_router calls):

```python
app.include_router(_extraction_analysis_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_extraction_analysis.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/extraction_analysis.py tests/api/test_extraction_analysis.py api/api.py
git commit -m "feat: add extraction analysis versions endpoint"
```

______________________________________________________________________

### Task 3: API Router — Summary Endpoint

**Files:**

- Modify: `api/routers/extraction_analysis.py`

- Modify: `tests/api/test_extraction_analysis.py`

- [ ] **Step 1: Write tests for the summary endpoint**

Append to `tests/api/test_extraction_analysis.py`:

```python
class TestVersionSummary:
    """GET /api/admin/extraction-analysis/{version}/summary"""

    def test_returns_401_without_token(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/admin/extraction-analysis/20260101/summary")
        assert resp.status_code == 401

    def test_rejects_path_traversal(self, test_client: TestClient) -> None:
        resp = test_client.get(
            "/api/admin/extraction-analysis/../etc/passwd/summary",
            headers=_admin_auth_headers(),
        )
        # FastAPI may return 404 or 400 depending on route matching
        assert resp.status_code in (400, 404, 422)

    def test_returns_404_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=tmp_path):
            resp = test_client.get(
                "/api/admin/extraction-analysis/99999999/summary",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404

    def test_returns_summary_with_violations(self, test_client: TestClient, tmp_path: Path) -> None:
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)

        violations = [
            {"record_id": "1", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850", "xml_file": "1.xml", "json_file": "1.json", "timestamp": "2026-01-31T12:00:00Z"},
            {"record_id": "2", "rule": "missing-title", "severity": "error", "field": "title", "field_value": "", "xml_file": "2.xml", "json_file": "2.json", "timestamp": "2026-01-31T12:00:01Z"},
        ]
        (flagged / "violations.jsonl").write_text("\n".join(json.dumps(v) for v in violations) + "\n")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "20260101"
        assert data["source"] == "discogs"
        assert data["violation_summary"]["total_violations"] == 2
        assert data["violation_summary"]["by_severity"]["warning"] == 1
        assert data["violation_summary"]["by_severity"]["error"] == 1

    def test_includes_pipeline_status_when_state_marker_exists(
        self, test_client: TestClient, tmp_path: Path
    ) -> None:
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)
        (flagged / "violations.jsonl").write_text("")

        state_marker = {
            "metadata_version": "1.0",
            "last_updated": "2026-01-31T12:00:00Z",
            "current_version": "20260101",
            "download_phase": {"status": "completed", "errors": []},
            "processing_phase": {"status": "completed", "errors": [], "records_extracted": 500000},
            "publishing_phase": {"status": "completed", "errors": [], "messages_published": 500000},
            "summary": {"overall_status": "completed", "files_by_type": {"releases": "completed"}},
        }
        (tmp_path / ".extraction_status_20260101.json").write_text(json.dumps(state_marker))

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_status"] is not None
        assert data["pipeline_status"]["download_phase"]["status"] == "completed"

    def test_pipeline_status_null_when_no_state_marker(
        self, test_client: TestClient, tmp_path: Path
    ) -> None:
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)
        (flagged / "violations.jsonl").write_text("")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/summary",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["pipeline_status"] is None
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest tests/api/test_extraction_analysis.py::TestVersionSummary -v -x`
Expected: FAIL — endpoint not implemented yet

- [ ] **Step 3: Implement the summary endpoint**

Add to `api/routers/extraction_analysis.py`:

```python
def _find_version_root(version: str) -> tuple[Path, str] | None:
    """Find which data root contains a flagged directory for this version.

    Returns (data_root, source) or None.
    """
    discogs_flagged = _discogs_data_root / "flagged" / version
    if discogs_flagged.is_dir():
        return _discogs_data_root, "discogs"
    mb_flagged = _musicbrainz_data_root / "flagged" / version
    if mb_flagged.is_dir():
        return _musicbrainz_data_root, "musicbrainz"
    return None


def _read_violations(flagged_version_dir: Path) -> list[dict[str, Any]]:
    """Read all violations from JSONL files across entity type subdirectories."""
    violations: list[dict[str, Any]] = []
    for entity_dir in sorted(flagged_version_dir.iterdir()):
        if not entity_dir.is_dir():
            continue
        jsonl_path = entity_dir / "violations.jsonl"
        if not jsonl_path.exists():
            continue
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry["entity_type"] = entity_dir.name
                    violations.append(entry)
                except json.JSONDecodeError:
                    logger.warning("⚠️ Skipping corrupt JSONL line", path=str(jsonl_path))
    return violations


def _load_state_marker(data_root: Path, version: str, source: str) -> dict[str, Any] | None:
    """Load the extraction state marker JSON file if it exists."""
    if source == "discogs":
        marker_path = data_root / f".extraction_status_{version}.json"
    else:
        marker_path = data_root / version / f".mb_extraction_status_{version}.json"
    if not marker_path.exists():
        return None
    try:
        return json.loads(marker_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("⚠️ Could not read state marker", path=str(marker_path), error=str(exc))
        return None


def _build_violation_summary(violations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate violation counts by severity, entity type, and rule."""
    by_severity: dict[str, int] = {}
    by_entity: dict[str, dict[str, int]] = {}
    by_rule: list[dict[str, Any]] = []
    rule_counts: dict[tuple[str, str, str], int] = {}

    for v in violations:
        severity = v.get("severity", "unknown")
        entity = v.get("entity_type", "unknown")
        rule = v.get("rule", "unknown")

        by_severity[severity] = by_severity.get(severity, 0) + 1

        if entity not in by_entity:
            by_entity[entity] = {}
        by_entity[entity][severity] = by_entity[entity].get(severity, 0) + 1

        key = (rule, severity, entity)
        rule_counts[key] = rule_counts.get(key, 0) + 1

    for (rule, severity, entity), count in sorted(rule_counts.items(), key=lambda x: -x[1]):
        by_rule.append({
            "rule": rule,
            "severity": severity,
            "entity_type": entity,
            "count": count,
        })

    return {
        "total_violations": len(violations),
        "by_severity": by_severity,
        "by_entity_type": by_entity,
        "by_rule": by_rule,
    }


@router.get("/api/admin/extraction-analysis/{version}/summary")
async def version_summary(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Aggregated report for a single extraction version."""
    _validate_version(version)

    result = _find_version_root(version)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {version}")
    data_root, source = result

    flagged_dir = data_root / "flagged" / version
    violations = _read_violations(flagged_dir)
    state_marker = _load_state_marker(data_root, version, source)

    # Extract pipeline status from state marker if available
    pipeline_status = None
    if state_marker:
        pipeline_status = {
            "download_phase": state_marker.get("download_phase"),
            "processing_phase": state_marker.get("processing_phase"),
            "publishing_phase": state_marker.get("publishing_phase"),
            "summary": state_marker.get("summary"),
        }

    return JSONResponse(content={
        "version": version,
        "source": source,
        "pipeline_status": pipeline_status,
        "violation_summary": _build_violation_summary(violations),
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_extraction_analysis.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/extraction_analysis.py tests/api/test_extraction_analysis.py
git commit -m "feat: add extraction analysis summary endpoint"
```

______________________________________________________________________

### Task 4: API Router — Violations Endpoints (List + Detail)

**Files:**

- Modify: `api/routers/extraction_analysis.py`

- Modify: `tests/api/test_extraction_analysis.py`

- [ ] **Step 1: Write tests for violations list and detail**

Append to `tests/api/test_extraction_analysis.py`:

```python
def _make_flagged_version(tmp_path: Path, version: str = "20260101") -> Path:
    """Helper: create a flagged version directory with sample violations and record files."""
    flagged = tmp_path / "flagged" / version / "releases"
    flagged.mkdir(parents=True)

    violations = [
        {"record_id": "100", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850", "xml_file": "100.xml", "json_file": "100.json", "timestamp": "2026-01-31T12:00:00Z"},
        {"record_id": "200", "rule": "missing-title", "severity": "error", "field": "title", "field_value": "", "xml_file": "200.xml", "json_file": "200.json", "timestamp": "2026-01-31T12:00:01Z"},
        {"record_id": "300", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1800", "xml_file": "300.xml", "json_file": "300.json", "timestamp": "2026-01-31T12:00:02Z"},
    ]
    (flagged / "violations.jsonl").write_text("\n".join(json.dumps(v) for v in violations) + "\n")

    (flagged / "100.xml").write_text('<release id="100"><year>1850</year><title>Old Record</title></release>')
    (flagged / "100.json").write_text(json.dumps({"id": "100", "year": 1850, "title": "Old Record"}))
    (flagged / "200.xml").write_text('<release id="200"><title></title></release>')
    (flagged / "200.json").write_text(json.dumps({"id": "200", "title": ""}))

    return tmp_path


class TestViolationsList:
    """GET /api/admin/extraction-analysis/{version}/violations"""

    def test_returns_paginated_violations(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?page=1&page_size=2",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["violations"]) == 2
        assert data["pagination"]["total_items"] == 3
        assert data["pagination"]["total_pages"] == 2

    def test_filters_by_severity(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?severity=error",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total_items"] == 1
        assert data["violations"][0]["rule"] == "missing-title"

    def test_filters_by_rule(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations?rule=year-out-of-range",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total_items"] == 2


class TestViolationDetail:
    """GET /api/admin/extraction-analysis/{version}/violations/{record_id}"""

    def test_returns_record_with_xml_and_json(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/100",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["record_id"] == "100"
        assert data["entity_type"] == "releases"
        assert '<release id="100">' in data["raw_xml"]
        assert data["parsed_json"]["id"] == "100"

    def test_returns_null_for_missing_xml(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            # record 300 has violations but no XML/JSON files
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/300",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["record_id"] == "300"
        assert data["raw_xml"] is None
        assert data["parsed_json"] is None

    def test_returns_404_for_unknown_record(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/violations/99999",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest tests/api/test_extraction_analysis.py::TestViolationsList -v -x`
Expected: FAIL — endpoints not implemented

- [ ] **Step 3: Implement violations list and detail endpoints**

Add to `api/routers/extraction_analysis.py`:

```python
@router.get("/api/admin/extraction-analysis/{version}/violations")
async def list_violations(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    entity_type: str | None = Query(default=None, pattern=r"^[a-z-]+$"),
    severity: str | None = Query(default=None, pattern=r"^(error|warning|info)$"),
    rule: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9_-]+$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """Paginated violations with optional filters."""
    _validate_version(version)

    result = _find_version_root(version)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {version}")
    data_root, _source = result

    violations = _read_violations(data_root / "flagged" / version)

    # Apply filters
    if entity_type:
        violations = [v for v in violations if v.get("entity_type") == entity_type]
    if severity:
        violations = [v for v in violations if v.get("severity") == severity]
    if rule:
        violations = [v for v in violations if v.get("rule") == rule]

    total = len(violations)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_violations = violations[start : start + page_size]

    return JSONResponse(content={
        "violations": page_violations,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": total_pages,
        },
    })


@router.get("/api/admin/extraction-analysis/{version}/violations/{record_id}")
async def violation_detail(
    version: str,
    record_id: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Single record detail with raw XML and parsed JSON."""
    _validate_version(version)
    _validate_record_id(record_id)

    result = _find_version_root(version)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {version}")
    data_root, _source = result

    flagged_dir = data_root / "flagged" / version

    # Find which entity type directory contains this record
    record_violations: list[dict[str, Any]] = []
    entity_type: str | None = None
    for entity_dir in flagged_dir.iterdir():
        if not entity_dir.is_dir():
            continue
        jsonl_path = entity_dir / "violations.jsonl"
        if not jsonl_path.exists():
            continue
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("record_id") == record_id:
                        record_violations.append(entry)
                        entity_type = entity_dir.name
                except json.JSONDecodeError:
                    continue

    if not record_violations:
        raise HTTPException(status_code=404, detail=f"No violations found for record {record_id}")

    # Load raw files
    entity_dir = flagged_dir / entity_type
    xml_path = entity_dir / f"{record_id}.xml"
    json_path = entity_dir / f"{record_id}.json"

    raw_xml: str | None = None
    parsed_json: dict[str, Any] | None = None

    if xml_path.exists():
        try:
            raw_xml = xml_path.read_text()
        except OSError:
            pass
    if json_path.exists():
        try:
            parsed_json = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    return JSONResponse(content={
        "record_id": record_id,
        "entity_type": entity_type,
        "violations": [
            {k: v for k, v in rv.items() if k != "entity_type"}
            for rv in record_violations
        ],
        "raw_xml": raw_xml,
        "parsed_json": parsed_json,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_extraction_analysis.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/extraction_analysis.py tests/api/test_extraction_analysis.py
git commit -m "feat: add violations list and detail endpoints"
```

______________________________________________________________________

### Task 5: API Router — Parsing Errors Endpoint

**Files:**

- Modify: `api/routers/extraction_analysis.py`

- Modify: `tests/api/test_extraction_analysis.py`

- [ ] **Step 1: Write tests for parsing error detection**

Append to `tests/api/test_extraction_analysis.py`:

```python
class TestParsingErrors:
    """GET /api/admin/extraction-analysis/{version}/parsing-errors"""

    def test_classifies_parsing_error(self, test_client: TestClient, tmp_path: Path) -> None:
        """XML has year data but JSON doesn't — parsing error."""
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)

        violations = [
            {"record_id": "100", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "", "xml_file": "100.xml", "json_file": "100.json", "timestamp": "2026-01-31T12:00:00Z"},
        ]
        (flagged / "violations.jsonl").write_text(json.dumps(violations[0]) + "\n")

        # XML has year, JSON doesn't
        (flagged / "100.xml").write_text('<release id="100"><year>2024</year><title>Test</title></release>')
        (flagged / "100.json").write_text(json.dumps({"id": "100", "title": "Test"}))

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["parsing_errors"] >= 1
        assert any(r["record_id"] == "100" and r["classification"] == "parsing_error" for r in data["parsing_errors"])

    def test_classifies_source_issue(self, test_client: TestClient, tmp_path: Path) -> None:
        """XML also has empty title — source data issue."""
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)

        violations = [
            {"record_id": "200", "rule": "missing-title", "severity": "error", "field": "title", "field_value": "", "xml_file": "200.xml", "json_file": "200.json", "timestamp": "2026-01-31T12:00:00Z"},
        ]
        (flagged / "violations.jsonl").write_text(json.dumps(violations[0]) + "\n")

        # Both XML and JSON have empty title
        (flagged / "200.xml").write_text('<release id="200"><title></title></release>')
        (flagged / "200.json").write_text(json.dumps({"id": "200", "title": ""}))

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["source_issues"] >= 1

    def test_indeterminate_when_files_missing(self, test_client: TestClient, tmp_path: Path) -> None:
        """No XML/JSON files — indeterminate."""
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)

        violations = [
            {"record_id": "300", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850", "xml_file": "300.xml", "json_file": "300.json", "timestamp": "2026-01-31T12:00:00Z"},
        ]
        (flagged / "violations.jsonl").write_text(json.dumps(violations[0]) + "\n")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/parsing-errors",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["indeterminate"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_extraction_analysis.py::TestParsingErrors -v -x`
Expected: FAIL

- [ ] **Step 3: Implement the parsing errors endpoint**

Add to `api/routers/extraction_analysis.py`:

```python
import time

import defusedxml.ElementTree as _safe_xml


# In-memory cache for parsing error results: {version: (timestamp, result)}
_parsing_error_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _extract_xml_field_value(xml_text: str, field: str) -> str | None:
    """Extract a field value from raw XML text using safe parsing.

    Supports simple element names (e.g., 'year', 'title') and dot-notation
    paths (e.g., 'genres.genre') by searching for the leaf element name.
    Returns the text content or None if not found / empty.
    """
    try:
        root = _safe_xml.fromstring(xml_text)
    except Exception:
        return None

    # Use the leaf name (after last dot)
    leaf = field.rsplit(".", 1)[-1]

    # Search recursively for the element
    elem = root.find(f".//{leaf}")
    if elem is not None and elem.text and elem.text.strip():
        return elem.text.strip()
    return None


def _classify_violation(
    violation: dict[str, Any],
    flagged_dir: Path,
    entity_type: str,
) -> dict[str, Any]:
    """Classify a single violation as parsing_error, source_issue, or indeterminate."""
    record_id = violation["record_id"]
    field = violation.get("field", "")

    entity_dir = flagged_dir / entity_type
    xml_path = entity_dir / f"{record_id}.xml"
    json_path = entity_dir / f"{record_id}.json"

    if not xml_path.exists() or not json_path.exists():
        return {
            "record_id": record_id,
            "entity_type": entity_type,
            "rule": violation.get("rule", ""),
            "field": field,
            "xml_value": None,
            "json_value": None,
            "classification": "indeterminate",
        }

    # Read XML field value
    try:
        xml_text = xml_path.read_text()
    except OSError:
        xml_text = ""
    xml_value = _extract_xml_field_value(xml_text, field) if xml_text else None

    # Read JSON field value
    json_value: Any = None
    try:
        parsed = json.loads(json_path.read_text())
        # Support dot-notation fields
        parts = field.split(".")
        obj = parsed
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            elif isinstance(obj, list) and obj:
                # For array fields, check first element
                obj = obj[0] if isinstance(obj[0], str) else obj[0].get(part) if isinstance(obj[0], dict) else None
            else:
                obj = None
                break
        if obj is not None and str(obj).strip():
            json_value = str(obj).strip()
    except (json.JSONDecodeError, OSError):
        pass

    # Classify
    if xml_value and not json_value:
        classification = "parsing_error"
    elif not xml_value:
        classification = "source_issue"
    else:
        classification = "source_issue"

    return {
        "record_id": record_id,
        "entity_type": entity_type,
        "rule": violation.get("rule", ""),
        "field": field,
        "xml_value": xml_value,
        "json_value": json_value,
        "classification": classification,
    }


@router.get("/api/admin/extraction-analysis/{version}/parsing-errors")
async def parsing_errors(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Classify flagged violations as parsing errors vs source data issues."""
    _validate_version(version)

    # Check cache
    now = time.monotonic()
    cached = _parsing_error_cache.get(version)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return JSONResponse(content=cached[1])

    result = _find_version_root(version)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {version}")
    data_root, _source = result

    flagged_dir = data_root / "flagged" / version
    violations = _read_violations(flagged_dir)

    parsing_errors_list: list[dict[str, Any]] = []
    source_issues: list[dict[str, Any]] = []
    indeterminate: list[dict[str, Any]] = []

    for v in violations:
        classified = _classify_violation(v, flagged_dir, v.get("entity_type", ""))
        if classified["classification"] == "parsing_error":
            parsing_errors_list.append(classified)
        elif classified["classification"] == "source_issue":
            source_issues.append(classified)
        else:
            indeterminate.append(classified)

    response = {
        "parsing_errors": parsing_errors_list,
        "source_issues": source_issues,
        "indeterminate": indeterminate,
        "stats": {
            "total_analyzed": len(violations),
            "parsing_errors": len(parsing_errors_list),
            "source_issues": len(source_issues),
            "indeterminate": len(indeterminate),
        },
    }

    _parsing_error_cache[version] = (now, response)
    return JSONResponse(content=response)
```

- [ ] **Step 4: Add defusedxml dependency**

Run: `uv add defusedxml`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_extraction_analysis.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run linting**

Run: `uv run ruff check api/routers/extraction_analysis.py`
Expected: No errors (fix any that appear)

- [ ] **Step 7: Commit**

```bash
git add api/routers/extraction_analysis.py tests/api/test_extraction_analysis.py pyproject.toml uv.lock
git commit -m "feat: add parsing error detection endpoint with XML vs JSON comparison"
```

______________________________________________________________________

### Task 6: API Router — Compare and Prompt Context Endpoints

**Files:**

- Modify: `api/routers/extraction_analysis.py`

- Modify: `tests/api/test_extraction_analysis.py`

- [ ] **Step 1: Write tests for compare endpoint**

Append to `tests/api/test_extraction_analysis.py`:

```python
class TestCompareVersions:
    """GET /api/admin/extraction-analysis/{version}/compare/{other_version}"""

    def test_compares_two_versions(self, test_client: TestClient, tmp_path: Path) -> None:
        # Version A: 2 year-out-of-range warnings, 1 missing-title error
        flagged_a = tmp_path / "flagged" / "20260101" / "releases"
        flagged_a.mkdir(parents=True)
        violations_a = [
            {"record_id": "1", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850", "xml_file": "1.xml", "json_file": "1.json", "timestamp": "2026-01-31T12:00:00Z"},
            {"record_id": "2", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1800", "xml_file": "2.xml", "json_file": "2.json", "timestamp": "2026-01-31T12:00:01Z"},
            {"record_id": "3", "rule": "missing-title", "severity": "error", "field": "title", "field_value": "", "xml_file": "3.xml", "json_file": "3.json", "timestamp": "2026-01-31T12:00:02Z"},
        ]
        (flagged_a / "violations.jsonl").write_text("\n".join(json.dumps(v) for v in violations_a) + "\n")

        # Version B: 1 year-out-of-range warning (improved), 1 missing-title error (same)
        flagged_b = tmp_path / "flagged" / "20260201" / "releases"
        flagged_b.mkdir(parents=True)
        violations_b = [
            {"record_id": "1", "rule": "year-out-of-range", "severity": "warning", "field": "year", "field_value": "1850", "xml_file": "1.xml", "json_file": "1.json", "timestamp": "2026-02-28T12:00:00Z"},
            {"record_id": "3", "rule": "missing-title", "severity": "error", "field": "title", "field_value": "", "xml_file": "3.xml", "json_file": "3.json", "timestamp": "2026-02-28T12:00:01Z"},
        ]
        (flagged_b / "violations.jsonl").write_text("\n".join(json.dumps(v) for v in violations_b) + "\n")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/compare/20260201",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_a"] == "20260101"
        assert data["version_b"] == "20260201"
        assert data["summary"]["improved"] >= 1
        # Find the year-out-of-range detail
        year_detail = next(d for d in data["details"] if d["rule"] == "year-out-of-range")
        assert year_detail["count_a"] == 2
        assert year_detail["count_b"] == 1
        assert year_detail["direction"] == "improved"

    def test_returns_404_for_unknown_version(self, test_client: TestClient, tmp_path: Path) -> None:
        flagged = tmp_path / "flagged" / "20260101" / "releases"
        flagged.mkdir(parents=True)
        (flagged / "violations.jsonl").write_text("")

        with patch("api.routers.extraction_analysis._discogs_data_root", new=tmp_path), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260101/compare/99999999",
                headers=_admin_auth_headers(),
            )
        assert resp.status_code == 404


class TestPromptContext:
    """POST /api/admin/extraction-analysis/{version}/prompt-context"""

    def test_returns_prompt_context(self, test_client: TestClient, tmp_path: Path) -> None:
        data_root = _make_flagged_version(tmp_path)

        with patch("api.routers.extraction_analysis._discogs_data_root", new=data_root), \
             patch("api.routers.extraction_analysis._musicbrainz_data_root", new=Path("/nonexistent")):
            resp = test_client.post(
                "/api/admin/extraction-analysis/20260101/prompt-context",
                headers=_admin_auth_headers(),
                json={"record_ids": ["100"], "rule": "year-out-of-range"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule"] == "year-out-of-range"
        assert len(data["records"]) == 1
        assert data["records"][0]["record_id"] == "100"
        assert data["records"][0]["raw_xml"] is not None
        assert data["records"][0]["parsed_json"] is not None

    def test_returns_422_for_empty_record_ids(self, test_client: TestClient) -> None:
        resp = test_client.post(
            "/api/admin/extraction-analysis/20260101/prompt-context",
            headers=_admin_auth_headers(),
            json={"record_ids": [], "rule": "test"},
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_extraction_analysis.py::TestCompareVersions -v -x`
Expected: FAIL

- [ ] **Step 3: Implement compare and prompt-context endpoints**

Add to `api/routers/extraction_analysis.py`:

```python
from pydantic import BaseModel, Field


class PromptContextRequest(BaseModel):
    record_ids: list[str] = Field(..., min_length=1, max_length=20)
    rule: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")


def _load_rules_yaml(data_root: Path) -> dict[str, Any]:
    """Load extraction-rules.yaml if available. Returns empty dict on failure."""
    rules_path = data_root / "extraction-rules.yaml"
    if not rules_path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(rules_path.read_text()) or {}
    except Exception:
        return {}


def _get_rule_definition(data_root: Path, rule_name: str) -> dict[str, Any] | None:
    """Look up a rule definition by name from extraction-rules.yaml."""
    rules_config = _load_rules_yaml(data_root)
    rules = rules_config.get("rules", {})
    for _entity_type, entity_rules in rules.items():
        if not isinstance(entity_rules, list):
            continue
        for rule in entity_rules:
            if rule.get("name") == rule_name:
                return rule
    return None


@router.get("/api/admin/extraction-analysis/{version}/compare/{other_version}")
async def compare_versions(
    version: str,
    other_version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Compare violation counts between two versions."""
    _validate_version(version)
    _validate_version(other_version)

    result_a = _find_version_root(version)
    if result_a is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {version}")

    result_b = _find_version_root(other_version)
    if result_b is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {other_version}")

    violations_a = _read_violations(result_a[0] / "flagged" / version)
    violations_b = _read_violations(result_b[0] / "flagged" / other_version)

    # Count by (rule, severity, entity_type)
    def count_by_key(violations: list[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
        counts: dict[tuple[str, str, str], int] = {}
        for v in violations:
            key = (v.get("rule", ""), v.get("severity", ""), v.get("entity_type", ""))
            counts[key] = counts.get(key, 0) + 1
        return counts

    counts_a = count_by_key(violations_a)
    counts_b = count_by_key(violations_b)

    all_keys = set(counts_a.keys()) | set(counts_b.keys())
    details: list[dict[str, Any]] = []
    improved = 0
    worsened = 0
    unchanged = 0

    for key in sorted(all_keys):
        ca = counts_a.get(key, 0)
        cb = counts_b.get(key, 0)
        if cb < ca:
            direction = "improved"
            improved += 1
        elif cb > ca:
            direction = "worsened"
            worsened += 1
        else:
            direction = "unchanged"
            unchanged += 1

        details.append({
            "rule": key[0],
            "severity": key[1],
            "entity_type": key[2],
            "count_a": ca,
            "count_b": cb,
            "direction": direction,
        })

    return JSONResponse(content={
        "version_a": version,
        "version_b": other_version,
        "summary": {
            "improved": improved,
            "worsened": worsened,
            "unchanged": unchanged,
            "new_rules": sum(1 for k in counts_b if k not in counts_a),
            "removed_rules": sum(1 for k in counts_a if k not in counts_b),
        },
        "details": details,
    })


@router.post("/api/admin/extraction-analysis/{version}/prompt-context")
async def prompt_context(
    version: str,
    body: PromptContextRequest,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Assemble context for Claude prompt generation."""
    _validate_version(version)

    result = _find_version_root(version)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No flagged data found for version {version}")
    data_root, _source = result

    flagged_dir = data_root / "flagged" / version

    # Load rule definition
    rule_def = _get_rule_definition(data_root, body.rule)

    # Gather records
    records: list[dict[str, Any]] = []
    for rid in body.record_ids:
        _validate_record_id(rid)

        # Find violations and entity type for this record
        record_violations: list[dict[str, Any]] = []
        entity_type: str | None = None
        for entity_dir_path in flagged_dir.iterdir():
            if not entity_dir_path.is_dir():
                continue
            jsonl_path = entity_dir_path / "violations.jsonl"
            if not jsonl_path.exists():
                continue
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("record_id") == rid and entry.get("rule") == body.rule:
                            record_violations.append(entry)
                            entity_type = entity_dir_path.name
                    except json.JSONDecodeError:
                        continue

        if not record_violations or not entity_type:
            continue

        # Load raw files
        entity_dir_path = flagged_dir / entity_type
        xml_path = entity_dir_path / f"{rid}.xml"
        json_path = entity_dir_path / f"{rid}.json"

        raw_xml = xml_path.read_text() if xml_path.exists() else None
        parsed_json = None
        if json_path.exists():
            try:
                parsed_json = json.loads(json_path.read_text())
            except json.JSONDecodeError:
                pass

        records.append({
            "record_id": rid,
            "entity_type": entity_type,
            "violation": {
                "field": record_violations[0].get("field", ""),
                "field_value": record_violations[0].get("field_value", ""),
            },
            "raw_xml": raw_xml,
            "parsed_json": parsed_json,
        })

    return JSONResponse(content={
        "rule": body.rule,
        "rule_definition": rule_def,
        "records": records,
        "extractor_context": {
            "parser_file": "extractor/src/xml_parser.rs",
            "rules_file": "extractor/extraction-rules.yaml",
        },
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_extraction_analysis.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run type checking**

Run: `uv run mypy api/routers/extraction_analysis.py`
Expected: No errors (fix any that appear)

- [ ] **Step 6: Commit**

```bash
git add api/routers/extraction_analysis.py tests/api/test_extraction_analysis.py
git commit -m "feat: add version comparison and prompt context endpoints"
```

______________________________________________________________________

### Task 7: Dashboard Proxy Routes

**Files:**

- Modify: `dashboard/admin_proxy.py`

- Create: `tests/dashboard/test_extraction_analysis_proxy.py`

- [ ] **Step 1: Write tests for proxy routes**

Create `tests/dashboard/test_extraction_analysis_proxy.py`:

```python
"""Tests for extraction analysis proxy routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx as httpx_mod
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from dashboard.admin_proxy import configure, router


@pytest.fixture
def proxy_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    configure("localhost", 8004)
    return app


@pytest.fixture
def proxy_client(proxy_app: FastAPI) -> TestClient:
    return TestClient(proxy_app)


def _mock_httpx(method: str = "get", status: int = 200, content: bytes = b"{}") -> tuple[AsyncMock, AsyncMock]:
    mock_resp = AsyncMock()
    mock_resp.status_code = status
    mock_resp.content = content

    mock_instance = AsyncMock()
    setattr(mock_instance, method, AsyncMock(return_value=mock_resp))
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cls = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


def _mock_httpx_error(method: str = "get") -> tuple[AsyncMock, AsyncMock]:
    mock_instance = AsyncMock()
    setattr(mock_instance, method, AsyncMock(side_effect=httpx_mod.ConnectError("refused")))
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cls = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


class TestExtractionAnalysisProxyVersions:
    def test_forwards_versions(self, proxy_client: TestClient) -> None:
        from unittest.mock import patch

        _, mock_instance = _mock_httpx("get", 200, b'{"versions":[]}')

        with patch("dashboard.admin_proxy.httpx.AsyncClient", return_value=mock_instance):
            resp = proxy_client.get(
                "/admin/api/extraction-analysis/versions",
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 200

    def test_returns_502_on_error(self, proxy_client: TestClient) -> None:
        from unittest.mock import patch

        _, mock_instance = _mock_httpx_error("get")

        with patch("dashboard.admin_proxy.httpx.AsyncClient", return_value=mock_instance):
            resp = proxy_client.get(
                "/admin/api/extraction-analysis/versions",
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 502


class TestExtractionAnalysisProxyPathValidation:
    def test_rejects_invalid_version(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get(
            "/admin/api/extraction-analysis/../passwd/summary",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code in (400, 404, 422)

    def test_rejects_invalid_record_id(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20260101/violations/../etc",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code in (400, 404, 422)


class TestExtractionAnalysisProxyPromptContext:
    def test_forwards_post_with_body(self, proxy_client: TestClient) -> None:
        from unittest.mock import patch

        _, mock_instance = _mock_httpx("post", 200, b'{"rule":"test","records":[]}')

        with patch("dashboard.admin_proxy.httpx.AsyncClient", return_value=mock_instance):
            resp = proxy_client.post(
                "/admin/api/extraction-analysis/20260101/prompt-context",
                headers={"Authorization": "Bearer test-token"},
                json={"record_ids": ["100"], "rule": "year-out-of-range"},
            )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_extraction_analysis_proxy.py -v -x`
Expected: FAIL — proxy routes not defined yet

- [ ] **Step 3: Update path validation regex to allow dots**

In `dashboard/admin_proxy.py`, line 30, the current regex is `r"^[a-zA-Z0-9_-]+$"`. Version strings may contain dots, so update it:

```python
_SAFE_PATH_SEGMENT = re.compile(r"^[a-zA-Z0-9._-]+$")
```

- [ ] **Step 4: Add proxy routes to admin_proxy.py**

Append before the end of `dashboard/admin_proxy.py` (after the audit-log route, around line 352):

```python
# ---------------------------------------------------------------------------
# Phase 5 — Extraction Analysis proxy routes
# ---------------------------------------------------------------------------


@router.get("/admin/api/extraction-analysis/versions")
async def proxy_extraction_analysis_versions(request: Request) -> Response:
    """Proxy extraction analysis versions requests to the API service."""
    url = _build_url("/api/admin/extraction-analysis/versions")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/summary")
async def proxy_extraction_analysis_summary(version: str, request: Request) -> Response:
    """Proxy extraction analysis summary requests to the API service."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/summary")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/violations/{record_id}")
async def proxy_extraction_analysis_violation_detail(
    version: str, record_id: str, request: Request,
) -> Response:
    """Proxy extraction analysis violation detail requests to the API service."""
    if not _validate_path_segment(version) or not _validate_path_segment(record_id):
        return Response(content=b'{"detail":"Invalid parameter"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/violations/{record_id}")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/violations")
async def proxy_extraction_analysis_violations(
    version: str,
    request: Request,
    entity_type: str | None = Query(default=None, pattern=r"^[a-z-]+$"),
    severity: str | None = Query(default=None, pattern=r"^(error|warning|info)$"),
    rule: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9_-]+$"),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
) -> Response:
    """Proxy extraction analysis violations requests to the API service."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/violations")
    params: dict[str, str] = {}
    if entity_type is not None:
        params["entity_type"] = entity_type
    if severity is not None:
        params["severity"] = severity
    if rule is not None:
        params["rule"] = rule
    if page is not None:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/parsing-errors")
async def proxy_extraction_analysis_parsing_errors(version: str, request: Request) -> Response:
    """Proxy extraction analysis parsing errors requests to the API service."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/parsing-errors")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/compare/{other_version}")
async def proxy_extraction_analysis_compare(
    version: str, other_version: str, request: Request,
) -> Response:
    """Proxy extraction analysis compare requests to the API service."""
    if not _validate_path_segment(version) or not _validate_path_segment(other_version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/compare/{other_version}")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.post("/admin/api/extraction-analysis/{version}/prompt-context")
async def proxy_extraction_analysis_prompt_context(version: str, request: Request) -> Response:
    """Proxy extraction analysis prompt context requests to the API service."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/prompt-context")
    headers = _auth_headers(request)
    try:
        sanitised_body = await _validated_json_body(request)
    except json.JSONDecodeError:
        return JSONResponse(content={"detail": "Malformed JSON in request body"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if sanitised_body:
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, headers=headers, content=sanitised_body)
            else:
                resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)
```

**Important:** The `violations/{record_id}` route MUST be registered BEFORE the bare `violations` route so FastAPI doesn't match `{record_id}` as a query parameter path. Check that the route with `{record_id}` appears first in the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_extraction_analysis_proxy.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/admin_proxy.py tests/dashboard/test_extraction_analysis_proxy.py
git commit -m "feat: add extraction analysis proxy routes to dashboard"
```

______________________________________________________________________

### Task 8: Dashboard UI — Tab Button and Panel HTML

**Files:**

- Modify: `dashboard/static/admin.html`

- [ ] **Step 1: Add the tab button**

In `admin.html`, after the "Audit Log" tab button (line 282), add:

```html
            <button class="tab-btn" data-tab="extraction-analysis" id="tab-btn-extraction-analysis">
                <span class="material-symbols-outlined text-sm">analytics</span> Extraction Analysis
            </button>
```

- [ ] **Step 2: Add the tab panel HTML**

After the audit-log tab closing `</div>` (line 773), before the `</div><!-- /admin-view -->` (line 775), add the extraction analysis panel. This is a large HTML block — the full content is:

```html
        <!-- ============================================================
             TAB: EXTRACTION ANALYSIS
             ============================================================ -->
        <div id="tab-extraction-analysis" class="space-y-6" style="display:none">
            <section class="dashboard-card p-6">
                <div class="flex items-center justify-between mb-4 border-b b-theme pb-4">
                    <h3 class="text-sm font-semibold flex items-center gap-2">
                        <span class="material-symbols-outlined text-sm t-dim">analytics</span> Extraction Analysis
                    </h3>
                    <div class="flex items-center gap-3">
                        <span id="ea-loading" class="text-xs t-muted" style="display:none">Loading...</span>
                        <span id="ea-error" class="text-xs text-amber-500 flex items-center gap-1" style="display:none">
                            <span class="material-symbols-outlined text-xs">warning</span> <span id="ea-error-msg"></span>
                        </span>
                    </div>
                </div>

                <!-- Sub-view toggle buttons -->
                <div class="flex items-center gap-2 mb-6">
                    <button class="ea-view-btn active text-[10px] px-2.5 py-1 rounded font-bold uppercase tracking-wider transition-colors" data-view="report">Single Version Report</button>
                    <button class="ea-view-btn text-[10px] px-2.5 py-1 rounded font-bold uppercase tracking-wider transition-colors" data-view="compare">Version Comparison</button>
                    <button class="ea-view-btn text-[10px] px-2.5 py-1 rounded font-bold uppercase tracking-wider transition-colors" data-view="prompt">Prompt Generator</button>
                </div>

                <!-- Sub-view: Single Version Report -->
                <div id="ea-view-report">
                    <div class="flex items-center gap-3 mb-4">
                        <label class="text-xs t-dim font-semibold">Version:</label>
                        <select id="ea-version-select" class="text-xs px-3 py-1.5 rounded border b-theme bg-transparent t-mid"></select>
                        <span id="ea-source-badge" class="text-[10px] px-2 py-0.5 rounded uppercase font-bold badge-running"></span>
                        <button id="ea-refresh-btn" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-high transition-colors flex items-center gap-1">
                            <span class="material-symbols-outlined text-sm">refresh</span> Refresh
                        </button>
                    </div>

                    <!-- Pipeline Status -->
                    <div id="ea-pipeline-status" class="mb-6" style="display:none">
                        <h4 class="text-xs font-semibold t-dim mb-3 uppercase tracking-wider">Pipeline Status</h4>
                        <div class="grid grid-cols-3 gap-4" id="ea-pipeline-cards"></div>
                    </div>

                    <!-- Violation Summary Cards -->
                    <div id="ea-violation-summary" class="mb-6">
                        <h4 class="text-xs font-semibold t-dim mb-3 uppercase tracking-wider">Violations by Entity</h4>
                        <div class="grid grid-cols-2 md:grid-cols-4 gap-4" id="ea-entity-cards"></div>
                    </div>

                    <!-- Rule Breakdown Table -->
                    <div id="ea-rule-breakdown" class="mb-6">
                        <h4 class="text-xs font-semibold t-dim mb-3 uppercase tracking-wider">Rule Breakdown</h4>
                        <table class="w-full text-xs">
                            <thead>
                                <tr class="border-b b-theme t-dim text-left">
                                    <th class="py-2 pr-4"><input type="checkbox" id="ea-select-all" class="mr-2">Rule</th>
                                    <th class="py-2 pr-4">Severity</th>
                                    <th class="py-2 pr-4">Entity</th>
                                    <th class="py-2 pr-4 text-right">Count</th>
                                    <th class="py-2 pr-4">Type</th>
                                </tr>
                            </thead>
                            <tbody id="ea-rules-body"></tbody>
                        </table>
                    </div>
                </div>

                <!-- Sub-view: Version Comparison -->
                <div id="ea-view-compare" style="display:none">
                    <div class="flex items-center gap-3 mb-4">
                        <label class="text-xs t-dim font-semibold">Version A:</label>
                        <select id="ea-compare-a" class="text-xs px-3 py-1.5 rounded border b-theme bg-transparent t-mid"></select>
                        <label class="text-xs t-dim font-semibold">Version B:</label>
                        <select id="ea-compare-b" class="text-xs px-3 py-1.5 rounded border b-theme bg-transparent t-mid"></select>
                        <button id="ea-compare-btn" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-high transition-colors flex items-center gap-1">
                            <span class="material-symbols-outlined text-sm">compare_arrows</span> Compare
                        </button>
                    </div>
                    <div id="ea-compare-summary" class="mb-4" style="display:none"></div>
                    <table class="w-full text-xs" id="ea-compare-table" style="display:none">
                        <thead>
                            <tr class="border-b b-theme t-dim text-left">
                                <th class="py-2 pr-4">Rule</th>
                                <th class="py-2 pr-4">Severity</th>
                                <th class="py-2 pr-4">Entity</th>
                                <th class="py-2 pr-4 text-right">Version A</th>
                                <th class="py-2 pr-4 text-right">Version B</th>
                                <th class="py-2 pr-4">Change</th>
                            </tr>
                        </thead>
                        <tbody id="ea-compare-body"></tbody>
                    </table>
                </div>

                <!-- Sub-view: Prompt Generator -->
                <div id="ea-view-prompt" style="display:none">
                    <p class="text-xs t-muted mb-3">Select violations from the Rule Breakdown table, then switch here to generate a Claude prompt.</p>
                    <div class="flex items-center gap-3 mb-4">
                        <span id="ea-prompt-count" class="text-xs t-mid">0 records selected</span>
                        <button id="ea-generate-prompt-btn" class="text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded bg-purple-600 text-white hover:bg-purple-500 transition-colors">
                            Generate Prompt
                        </button>
                        <button id="ea-copy-prompt-btn" class="text-xs font-bold uppercase tracking-wider t-dim hover:t-high transition-colors flex items-center gap-1" style="display:none">
                            <span class="material-symbols-outlined text-sm">content_copy</span> Copy
                        </button>
                    </div>
                    <textarea id="ea-prompt-output" class="w-full h-96 text-xs mono p-4 rounded border b-theme bg-transparent t-mid" readonly style="display:none"></textarea>
                </div>
            </section>

            <!-- Record Detail Modal -->
            <div id="ea-record-modal" class="fixed inset-0 bg-black/50 flex items-center justify-center" style="display:none; z-index:9998">
                <div class="dashboard-card p-6 max-w-4xl w-full mx-4 max-h-[80vh] overflow-y-auto">
                    <div class="flex items-center justify-between mb-4 border-b b-theme pb-4">
                        <h3 class="text-sm font-semibold">Record Detail — <span id="ea-modal-record-id" class="mono"></span></h3>
                        <button id="ea-modal-close" class="t-dim hover:t-high">
                            <span class="material-symbols-outlined">close</span>
                        </button>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <h4 class="text-xs font-semibold t-dim mb-2 uppercase tracking-wider">Raw XML</h4>
                            <pre id="ea-modal-xml" class="text-xs mono p-3 rounded border b-theme overflow-x-auto max-h-96 overflow-y-auto"></pre>
                        </div>
                        <div>
                            <h4 class="text-xs font-semibold t-dim mb-2 uppercase tracking-wider">Parsed JSON</h4>
                            <pre id="ea-modal-json" class="text-xs mono p-3 rounded border b-theme overflow-x-auto max-h-96 overflow-y-auto"></pre>
                        </div>
                    </div>
                    <div id="ea-modal-violations" class="mt-4"></div>
                </div>
            </div>
        </div><!-- /tab-extraction-analysis -->
```

- [ ] **Step 3: Add CSS for sub-view buttons**

In the `<style>` section (around line 100-119), add after the `.tab-btn.active` rule:

```css
.ea-view-btn { color: var(--text-dim); background: transparent; border: 1px solid var(--border-color); cursor: pointer; }
.ea-view-btn:hover { color: var(--text-high); }
.ea-view-btn.active { background: var(--purple-accent); color: #fff; border-color: var(--purple-accent); }
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/admin.html
git commit -m "feat: add extraction analysis tab HTML to admin dashboard"
```

______________________________________________________________________

### Task 9: Dashboard UI — JavaScript Logic

**Files:**

- Modify: `dashboard/static/admin.js`

This task adds all the JavaScript methods for the extraction analysis tab. **Security note:** All dynamic content from API responses that is inserted into the DOM must be HTML-escaped to prevent XSS. Use `textContent` for plain text and an escape helper for any HTML templates.

- [ ] **Step 1: Add HTML escape utility**

At the top of `admin.js`, after the `_emptyRow` helper function (around line 28), add:

```javascript
function _esc(str) {
    /** Escape a string for safe insertion into innerHTML. */
    const div = document.createElement('div');
    div.textContent = String(str ?? '');
    return div.innerHTML;
}
```

- [ ] **Step 2: Update switchTab panels array and add tab data fetch**

In `admin.js`, update the `switchTab()` method (line 229):

Change:

```javascript
const panels = ['extractions', 'dlq', 'users', 'storage', 'queue-trends', 'system-health', 'audit-log'];
```

To:

```javascript
const panels = ['extractions', 'dlq', 'users', 'storage', 'queue-trends', 'system-health', 'audit-log', 'extraction-analysis'];
```

Add after the `audit-log` fetch block (line 246):

```javascript
        } else if (tabName === 'extraction-analysis') {
            this.fetchExtractionAnalysisVersions();
        }
```

- [ ] **Step 3: Add constructor state and event bindings**

In the constructor (around line 32-47), add state properties:

```javascript
    this._eaVersions = [];
    this._eaSelectedRecords = new Map();
    this._eaParsingErrors = null;
```

In the `bindEvents()` method, add event bindings for the extraction analysis tab:

```javascript
    // Extraction Analysis sub-view switching
    document.querySelectorAll('.ea-view-btn').forEach(btn => {
        btn.addEventListener('click', () => this._eaSwitchView(btn.dataset.view));
    });
    const eaRefreshBtn = document.getElementById('ea-refresh-btn');
    if (eaRefreshBtn) eaRefreshBtn.addEventListener('click', () => this._eaLoadReport());
    const eaCompareBtn = document.getElementById('ea-compare-btn');
    if (eaCompareBtn) eaCompareBtn.addEventListener('click', () => this._eaCompare());
    const eaGenerateBtn = document.getElementById('ea-generate-prompt-btn');
    if (eaGenerateBtn) eaGenerateBtn.addEventListener('click', () => this._eaGeneratePrompt());
    const eaCopyBtn = document.getElementById('ea-copy-prompt-btn');
    if (eaCopyBtn) eaCopyBtn.addEventListener('click', () => this._eaCopyPrompt());
    const eaModalClose = document.getElementById('ea-modal-close');
    if (eaModalClose) eaModalClose.addEventListener('click', () => {
        document.getElementById('ea-record-modal').style.display = 'none';
    });
    const eaSelectAll = document.getElementById('ea-select-all');
    if (eaSelectAll) eaSelectAll.addEventListener('change', (e) => this._eaToggleSelectAll(e.target.checked));
    const eaVersionSelect = document.getElementById('ea-version-select');
    if (eaVersionSelect) eaVersionSelect.addEventListener('change', () => this._eaLoadReport());
```

- [ ] **Step 4: Add extraction analysis methods**

Before the closing `}` of the `AdminDashboard` class (line 1454), add all methods. Use `_esc()` for all values inserted via innerHTML, and `textContent` for plain text values:

````javascript
    // ─── Extraction Analysis ─────────────────────────────────────────────

    _eaSwitchView(viewName) {
        document.querySelectorAll('.ea-view-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewName);
        });
        ['report', 'compare', 'prompt'].forEach(name => {
            const el = document.getElementById(`ea-view-${name}`);
            if (el) el.style.display = name === viewName ? 'block' : 'none';
        });
    }

    async fetchExtractionAnalysisVersions() {
        const loadingEl = document.getElementById('ea-loading');
        const errorEl = document.getElementById('ea-error');
        const errorMsgEl = document.getElementById('ea-error-msg');
        if (loadingEl) loadingEl.style.display = 'inline';
        if (errorEl) errorEl.style.display = 'none';

        try {
            const resp = await this.authFetch('/admin/api/extraction-analysis/versions');
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                this._showInlineError(errorEl, errorMsgEl, err.detail || `Error ${resp.status}`);
                return;
            }
            const data = await resp.json();
            this._eaVersions = data.versions || [];
            this._eaPopulateVersionSelects();
            if (this._eaVersions.length > 0) this._eaLoadReport();
        } catch {
            this._showInlineError(errorEl, errorMsgEl, 'Failed to load versions');
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    _eaPopulateVersionSelects() {
        const selects = ['ea-version-select', 'ea-compare-a', 'ea-compare-b'];
        selects.forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            sel.replaceChildren();
            this._eaVersions.forEach(v => {
                const opt = document.createElement('option');
                opt.value = `${v.source}:${v.version}`;
                opt.textContent = `${v.version} (${v.source})`;
                sel.appendChild(opt);
            });
        });
        const compB = document.getElementById('ea-compare-b');
        if (compB && compB.options.length > 1) compB.selectedIndex = 1;
    }

    async _eaLoadReport() {
        const sel = document.getElementById('ea-version-select');
        if (!sel || !sel.value) return;
        const [source, version] = sel.value.split(':');
        const badge = document.getElementById('ea-source-badge');
        if (badge) {
            badge.textContent = source;
            badge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${source === 'discogs' ? 'badge-completed' : 'badge-running'}`;
        }

        const loadingEl = document.getElementById('ea-loading');
        if (loadingEl) loadingEl.style.display = 'inline';

        try {
            const [summaryResp, parsingResp] = await Promise.all([
                this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/summary`),
                this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/parsing-errors`),
            ]);

            if (summaryResp.ok) {
                const summary = await summaryResp.json();
                this._eaRenderPipelineStatus(summary.pipeline_status);
                this._eaRenderEntityCards(summary.violation_summary);
                this._eaParsingErrors = parsingResp.ok ? await parsingResp.json() : null;
                this._eaRenderRuleBreakdown(summary.violation_summary.by_rule);
            }
        } catch { /* handled by auth */ } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    _eaRenderPipelineStatus(pipelineStatus) {
        const container = document.getElementById('ea-pipeline-status');
        const cardsEl = document.getElementById('ea-pipeline-cards');
        if (!container || !cardsEl) return;
        if (!pipelineStatus) { container.style.display = 'none'; return; }
        container.style.display = '';

        const phases = [
            { key: 'download_phase', label: 'Download', icon: 'download' },
            { key: 'processing_phase', label: 'Processing', icon: 'settings' },
            { key: 'publishing_phase', label: 'Publishing', icon: 'publish' },
        ];

        cardsEl.replaceChildren(...phases.map(p => {
            const phase = pipelineStatus[p.key] || {};
            const div = document.createElement('div');
            div.className = 'dashboard-card p-4';

            const header = document.createElement('div');
            header.className = 'flex items-center gap-2 mb-2';

            const icon = document.createElement('span');
            icon.className = 'material-symbols-outlined text-sm t-dim';
            icon.textContent = p.icon;

            const label = document.createElement('span');
            label.className = 'text-xs font-semibold';
            label.textContent = p.label;

            const statusBadge = document.createElement('span');
            statusBadge.className = `text-[10px] px-2 py-0.5 rounded uppercase font-bold ${this._statusBadgeClass(phase.status || 'unknown')}`;
            statusBadge.textContent = phase.status || '\u2014';

            header.append(icon, label, statusBadge);
            div.appendChild(header);

            const errors = (phase.errors || []).length;
            if (errors > 0) {
                const errSpan = document.createElement('span');
                errSpan.className = 'text-[10px] text-amber-500';
                errSpan.textContent = `${errors} error(s)`;
                div.appendChild(errSpan);
            }

            return div;
        }));
    }

    _eaRenderEntityCards(summary) {
        const container = document.getElementById('ea-entity-cards');
        if (!container) return;
        const byEntity = summary.by_entity_type || {};

        if (Object.keys(byEntity).length === 0) {
            const div = document.createElement('div');
            div.className = 'text-xs t-muted py-3';
            div.textContent = 'No violations found';
            container.replaceChildren(div);
            return;
        }

        container.replaceChildren(...Object.entries(byEntity).map(([entity, counts]) => {
            const div = document.createElement('div');
            div.className = 'dashboard-card p-4';

            const title = document.createElement('div');
            title.className = 'text-xs font-semibold mb-2 uppercase tracking-wider';
            title.textContent = entity;
            div.appendChild(title);

            const statsRow = document.createElement('div');
            statsRow.className = 'flex gap-3';
            for (const [sev, cls] of [['error', 'text-red-400'], ['warning', 'text-amber-400'], ['info', 't-muted']]) {
                if (counts[sev]) {
                    const span = document.createElement('span');
                    span.className = 'text-[10px]';
                    const num = document.createElement('span');
                    num.className = `${cls} font-bold`;
                    num.textContent = counts[sev];
                    span.append(num, ` ${sev}s`);
                    statsRow.appendChild(span);
                }
            }
            div.appendChild(statsRow);
            return div;
        }));
    }

    _eaRenderRuleBreakdown(byRule) {
        const tbody = document.getElementById('ea-rules-body');
        if (!tbody) return;
        this._eaSelectedRecords.clear();

        const parsingErrorRules = new Set();
        if (this._eaParsingErrors) {
            (this._eaParsingErrors.parsing_errors || []).forEach(pe => parsingErrorRules.add(pe.rule));
        }

        const rows = (byRule || []).map(r => {
            const tr = document.createElement('tr');
            tr.className = 'border-b b-row cursor-pointer hover:bg-white/5';

            // Checkbox + rule name cell
            const tdRule = document.createElement('td');
            tdRule.className = 'py-2.5 pr-4';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'ea-rule-cb mr-2';
            cb.dataset.rule = r.rule;
            cb.dataset.entity = r.entity_type;
            cb.addEventListener('change', () => this._eaUpdatePromptCount());
            tdRule.appendChild(cb);
            tdRule.appendChild(document.createTextNode(r.rule));

            // Severity cell
            const tdSev = document.createElement('td');
            tdSev.className = `py-2.5 pr-4 text-[10px] uppercase font-bold ${r.severity === 'error' ? 'text-red-400' : r.severity === 'warning' ? 'text-amber-400' : 't-muted'}`;
            tdSev.textContent = r.severity;

            // Entity type cell
            const tdEntity = document.createElement('td');
            tdEntity.className = 'py-2.5 pr-4 t-mid';
            tdEntity.textContent = r.entity_type;

            // Count cell
            const tdCount = document.createElement('td');
            tdCount.className = 'py-2.5 pr-4 text-right mono t-mid';
            tdCount.textContent = r.count.toLocaleString();

            // Type badge cell
            const tdType = document.createElement('td');
            tdType.className = 'py-2.5 pr-4';
            const badge = document.createElement('span');
            if (parsingErrorRules.has(r.rule)) {
                badge.className = 'text-[10px] px-2 py-0.5 rounded font-bold bg-purple-600/20 text-purple-400';
                badge.textContent = 'Parsing Error';
            } else {
                badge.className = 'text-[10px] t-muted';
                badge.textContent = 'Source';
            }
            tdType.appendChild(badge);

            tr.append(tdRule, tdSev, tdEntity, tdCount, tdType);

            tr.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') return;
                this._eaShowViolationsForRule(r.rule, r.entity_type);
            });

            return tr;
        });

        if (rows.length === 0) {
            tbody.replaceChildren(_emptyRow(5, 'No violations'));
        } else {
            tbody.replaceChildren(...rows);
        }

        this._eaUpdatePromptCount();
    }

    async _eaShowViolationsForRule(rule, entityType) {
        const sel = document.getElementById('ea-version-select');
        if (!sel) return;
        const version = sel.value.split(':')[1];
        try {
            const resp = await this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/violations?rule=${encodeURIComponent(rule)}&entity_type=${encodeURIComponent(entityType)}&page_size=10`);
            if (!resp.ok) return;
            const data = await resp.json();
            if (data.violations.length > 0) {
                this._eaShowRecordDetail(version, data.violations[0].record_id);
            }
        } catch { /* ignore */ }
    }

    async _eaShowRecordDetail(version, recordId) {
        try {
            const resp = await this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/violations/${encodeURIComponent(recordId)}`);
            if (!resp.ok) return;
            const data = await resp.json();

            const modalRecordId = document.getElementById('ea-modal-record-id');
            if (modalRecordId) modalRecordId.textContent = `${data.record_id} (${data.entity_type})`;

            const modalXml = document.getElementById('ea-modal-xml');
            if (modalXml) modalXml.textContent = data.raw_xml || '(not available)';

            const modalJson = document.getElementById('ea-modal-json');
            if (modalJson) modalJson.textContent = data.parsed_json ? JSON.stringify(data.parsed_json, null, 2) : '(not available)';

            const violationsDiv = document.getElementById('ea-modal-violations');
            if (violationsDiv && data.violations) {
                violationsDiv.replaceChildren();
                const h4 = document.createElement('h4');
                h4.className = 'text-xs font-semibold t-dim mb-2 uppercase tracking-wider';
                h4.textContent = 'Violations';
                violationsDiv.appendChild(h4);

                const list = document.createElement('div');
                list.className = 'space-y-1';
                for (const v of data.violations) {
                    const row = document.createElement('div');
                    row.className = 'text-xs';
                    const sevSpan = document.createElement('span');
                    sevSpan.className = `font-bold ${v.severity === 'error' ? 'text-red-400' : 'text-amber-400'}`;
                    sevSpan.textContent = v.severity;
                    row.append(sevSpan, ` ${v.rule}: ${v.field} = "${v.field_value}"`);
                    list.appendChild(row);
                }
                violationsDiv.appendChild(list);
            }

            document.getElementById('ea-record-modal').style.display = 'flex';
        } catch { /* ignore */ }
    }

    async _eaCompare() {
        const selA = document.getElementById('ea-compare-a');
        const selB = document.getElementById('ea-compare-b');
        if (!selA || !selB) return;
        const versionA = selA.value.split(':')[1];
        const versionB = selB.value.split(':')[1];

        try {
            const resp = await this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(versionA)}/compare/${encodeURIComponent(versionB)}`);
            if (!resp.ok) return;
            const data = await resp.json();

            const summaryEl = document.getElementById('ea-compare-summary');
            if (summaryEl) {
                summaryEl.style.display = '';
                summaryEl.textContent = '';
                const div = document.createElement('div');
                div.className = 'text-xs t-mid';
                div.textContent = `${data.summary.improved} improved, ${data.summary.worsened} worsened, ${data.summary.unchanged} unchanged`;
                summaryEl.appendChild(div);
            }

            const table = document.getElementById('ea-compare-table');
            const tbody = document.getElementById('ea-compare-body');
            if (table && tbody) {
                table.style.display = '';
                tbody.replaceChildren(...data.details.map(d => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b b-row';

                    const tdRule = document.createElement('td');
                    tdRule.className = 'py-2.5 pr-4 t-mid';
                    tdRule.textContent = d.rule;

                    const tdSev = document.createElement('td');
                    tdSev.className = 'py-2.5 pr-4 text-[10px] uppercase font-bold';
                    tdSev.textContent = d.severity;

                    const tdEntity = document.createElement('td');
                    tdEntity.className = 'py-2.5 pr-4 t-mid';
                    tdEntity.textContent = d.entity_type;

                    const tdCountA = document.createElement('td');
                    tdCountA.className = 'py-2.5 pr-4 text-right mono t-mid';
                    tdCountA.textContent = d.count_a.toLocaleString();

                    const tdCountB = document.createElement('td');
                    tdCountB.className = 'py-2.5 pr-4 text-right mono t-mid';
                    tdCountB.textContent = d.count_b.toLocaleString();

                    const dirClass = d.direction === 'improved' ? 'text-green-400' : d.direction === 'worsened' ? 'text-red-400' : 't-muted';
                    const dirIcon = d.direction === 'improved' ? 'arrow_downward' : d.direction === 'worsened' ? 'arrow_upward' : 'remove';
                    const tdDir = document.createElement('td');
                    tdDir.className = `py-2.5 pr-4 ${dirClass} font-bold flex items-center gap-1`;
                    const icon = document.createElement('span');
                    icon.className = 'material-symbols-outlined text-sm';
                    icon.textContent = dirIcon;
                    tdDir.append(icon, ` ${d.direction}`);

                    tr.append(tdRule, tdSev, tdEntity, tdCountA, tdCountB, tdDir);
                    return tr;
                }));
            }
        } catch { /* ignore */ }
    }

    _eaToggleSelectAll(checked) {
        document.querySelectorAll('.ea-rule-cb').forEach(cb => { cb.checked = checked; });
        this._eaUpdatePromptCount();
    }

    _eaUpdatePromptCount() {
        const count = document.querySelectorAll('.ea-rule-cb:checked').length;
        const el = document.getElementById('ea-prompt-count');
        if (el) el.textContent = `${count} rule(s) selected`;
    }

    async _eaGeneratePrompt() {
        const sel = document.getElementById('ea-version-select');
        if (!sel) return;
        const version = sel.value.split(':')[1];

        const selectedCbs = document.querySelectorAll('.ea-rule-cb:checked');
        if (selectedCbs.length === 0) return;

        const loadingEl = document.getElementById('ea-loading');
        if (loadingEl) loadingEl.style.display = 'inline';

        try {
            const promptParts = [];
            promptParts.push('# Extraction Failure Analysis \u2014 Fix Request\n');
            promptParts.push(`Version: ${version}\n`);
            promptParts.push('The following violations were detected during extraction. Each represents a case where the Rust extractor produced incorrect output. Please investigate and fix the parser.\n');

            for (const cb of selectedCbs) {
                const rule = cb.dataset.rule;
                const entityType = cb.dataset.entity;

                const violResp = await this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/violations?rule=${encodeURIComponent(rule)}&entity_type=${encodeURIComponent(entityType)}&page_size=3`);
                if (!violResp.ok) continue;
                const violData = await violResp.json();
                if (violData.violations.length === 0) continue;

                const recordIds = violData.violations.map(v => v.record_id);
                const ctxResp = await this.authFetch(`/admin/api/extraction-analysis/${encodeURIComponent(version)}/prompt-context`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ record_ids: recordIds, rule }),
                });
                if (!ctxResp.ok) continue;
                const ctx = await ctxResp.json();

                promptParts.push(`\n## Rule: ${rule} (${entityType})\n`);
                if (ctx.rule_definition) {
                    promptParts.push(`Description: ${ctx.rule_definition.description || 'N/A'}`);
                    promptParts.push(`Field: ${ctx.rule_definition.field || 'N/A'}`);
                    promptParts.push(`Severity: ${ctx.rule_definition.severity || 'N/A'}\n`);
                }
                promptParts.push(`Total violations: ${violData.pagination.total_items}\n`);
                promptParts.push(`Parser file: ${ctx.extractor_context.parser_file}`);
                promptParts.push(`Rules file: ${ctx.extractor_context.rules_file}\n`);

                for (const rec of ctx.records) {
                    promptParts.push(`### Record ${rec.record_id} (${rec.entity_type})`);
                    promptParts.push(`Flagged field: ${rec.violation.field} = "${rec.violation.field_value}"\n`);
                    if (rec.raw_xml) {
                        promptParts.push('**Raw XML:**');
                        promptParts.push('```xml');
                        promptParts.push(rec.raw_xml);
                        promptParts.push('```\n');
                    }
                    if (rec.parsed_json) {
                        promptParts.push('**Parsed JSON:**');
                        promptParts.push('```json');
                        promptParts.push(JSON.stringify(rec.parsed_json, null, 2));
                        promptParts.push('```\n');
                    }
                }
            }

            const textarea = document.getElementById('ea-prompt-output');
            if (textarea) {
                textarea.value = promptParts.join('\n');
                textarea.style.display = '';
            }
            const copyBtn = document.getElementById('ea-copy-prompt-btn');
            if (copyBtn) copyBtn.style.display = '';
        } catch { /* ignore */ } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    async _eaCopyPrompt() {
        const textarea = document.getElementById('ea-prompt-output');
        if (!textarea) return;
        try {
            await navigator.clipboard.writeText(textarea.value);
            this.showToast('Prompt copied to clipboard', 'success');
        } catch {
            textarea.select();
        }
    }
````

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/admin.js dashboard/static/admin.html
git commit -m "feat: add extraction analysis JavaScript logic to admin dashboard"
```

______________________________________________________________________

### Task 10: Integration Verification

**Files:**

- All modified files

- [ ] **Step 1: Run full API test suite**

Run: `uv run pytest tests/api/ -v --timeout=60`
Expected: All tests PASS (including new extraction analysis tests)

- [ ] **Step 2: Run dashboard test suite**

Run: `uv run pytest tests/dashboard/ -v --timeout=60`
Expected: All tests PASS

- [ ] **Step 3: Run type checking**

Run: `uv run mypy api/routers/extraction_analysis.py`
Expected: No errors

- [ ] **Step 4: Run full lint**

Run: `just lint-python`
Expected: No errors

- [ ] **Step 5: Verify Docker compose config is valid**

Run: `docker compose config --quiet`
Expected: No output (success)

- [ ] **Step 6: Commit any fixes**

If any fixes were needed, commit them:

```bash
git add -A
git commit -m "fix: resolve integration issues from extraction analysis feature"
```
