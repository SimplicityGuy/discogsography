"""Extraction Analysis router — versions, summary, violations, and parsing errors for flagged records."""

import json
from pathlib import Path
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import structlog

from api.dependencies import require_admin


logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state (set via configure())
_discogs_data_root: Path | None = None
_musicbrainz_data_root: Path | None = None

# Input-validation patterns — only allow safe characters in version / record_id
_SAFE_VERSION = re.compile(r"^[a-zA-Z0-9._-]+$")
_SAFE_RECORD_ID = re.compile(r"^[a-zA-Z0-9._-]+$")


def configure(discogs_root: str | Path | None = None, musicbrainz_root: str | Path | None = None) -> None:
    """Initialise module state — called once during app lifespan startup."""
    global _discogs_data_root, _musicbrainz_data_root
    _discogs_data_root = Path(discogs_root) if discogs_root else None
    _musicbrainz_data_root = Path(musicbrainz_root) if musicbrainz_root else None
    logger.info("🔧 Extraction analysis router configured", discogs_root=discogs_root, musicbrainz_root=musicbrainz_root)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_version(version: str) -> str:
    """Validate that *version* contains only safe characters. Raises HTTP 400 on failure."""
    if not _SAFE_VERSION.match(version):
        raise HTTPException(status_code=400, detail=f"Invalid version identifier: {version!r}")
    return version


def _validate_record_id(record_id: str) -> str:
    """Validate that *record_id* contains only safe characters. Raises HTTP 400 on failure."""
    if not _SAFE_RECORD_ID.match(record_id):
        raise HTTPException(status_code=400, detail=f"Invalid record_id: {record_id!r}")
    return record_id


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def _scan_versions(data_root: Path, source: str) -> list[dict[str, Any]]:
    """Scan *data_root*/flagged/ for version directories that contain at least one entity with violations.jsonl.

    Returns a list of dicts with keys: version, source, entity_types.
    """
    flagged = data_root / "flagged"
    if not flagged.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for version_dir in sorted(flagged.iterdir()):
        if not version_dir.is_dir():
            continue
        entity_types = [
            entity_dir.name for entity_dir in sorted(version_dir.iterdir()) if entity_dir.is_dir() and (entity_dir / "violations.jsonl").is_file()
        ]
        if entity_types:
            results.append({"version": version_dir.name, "source": source, "entity_types": entity_types})
    return results


def _find_version_root(version: str) -> tuple[Path, str] | None:
    """Return (data_root, source) for the given *version*, or None if not found in either root."""
    for data_root, source in [(_discogs_data_root, "discogs"), (_musicbrainz_data_root, "musicbrainz")]:
        if data_root is None:
            continue
        flagged_version = data_root / "flagged" / version
        if flagged_version.is_dir():
            return data_root, source
    return None


def _read_violations(flagged_version_dir: Path) -> list[dict[str, Any]]:
    """Read all violations.jsonl files under *flagged_version_dir*, injecting entity_type from the directory name.

    Corrupt lines are logged and skipped.
    """
    violations: list[dict[str, Any]] = []
    for entity_dir in sorted(flagged_version_dir.iterdir()):
        if not entity_dir.is_dir():
            continue
        jsonl_file = entity_dir / "violations.jsonl"
        if not jsonl_file.is_file():
            continue
        entity_type = entity_dir.name
        for lineno, raw_line in enumerate(jsonl_file.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("⚠️ Skipping corrupt JSONL line", file=str(jsonl_file), lineno=lineno)
                continue
            record["entity_type"] = entity_type
            violations.append(record)
    return violations


def _load_state_marker(data_root: Path, version: str, source: str) -> dict[str, Any] | None:
    """Load the extraction state marker for *version* from *data_root*, or None if absent/corrupt."""
    if source == "discogs":
        marker_path = data_root / f".extraction_status_{version}.json"
    else:
        marker_path = data_root / version / f".mb_extraction_status_{version}.json"

    if not marker_path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(marker_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        logger.warning("⚠️ Could not read state marker", path=str(marker_path))
        return None


def _build_violation_summary(violations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate violations by severity, entity type, and rule."""
    by_severity: dict[str, int] = {}
    by_entity_type: dict[str, int] = {}
    by_rule: dict[str, int] = {}

    for v in violations:
        severity: str = v.get("severity", "unknown")
        entity_type: str = v.get("entity_type", "unknown")
        rule: str = v.get("rule", "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_entity_type[entity_type] = by_entity_type.get(entity_type, 0) + 1
        by_rule[rule] = by_rule.get(rule, 0) + 1

    return {
        "total": len(violations),
        "by_severity": by_severity,
        "by_entity_type": by_entity_type,
        "by_rule": by_rule,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/admin/extraction-analysis/versions")
async def list_versions(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """List all extraction versions that have flagged records.

    Scans both the Discogs and MusicBrainz flagged directories and returns
    a unified list of versions with the entity types that contain violations.
    """
    all_versions: list[dict[str, Any]] = []
    for data_root, source in [(_discogs_data_root, "discogs"), (_musicbrainz_data_root, "musicbrainz")]:
        if data_root is None:
            continue
        all_versions.extend(_scan_versions(data_root, source))

    return JSONResponse(content={"versions": all_versions})


@router.get("/api/admin/extraction-analysis/{version}/summary")
async def get_summary(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Return a violation summary and pipeline status for the given extraction version.

    Path variables are validated against a strict allowlist to prevent path traversal.
    """
    _validate_version(version)

    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    data_root, source = location
    flagged_version_dir = data_root / "flagged" / version

    violations = _read_violations(flagged_version_dir)
    pipeline_status = _load_state_marker(data_root, version, source)
    summary = _build_violation_summary(violations)

    return JSONResponse(
        content={
            "version": version,
            "source": source,
            "pipeline_status": pipeline_status,
            "violation_summary": summary,
        }
    )
