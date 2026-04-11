"""Extraction Analysis router — versions, summary, violations, and parsing errors for flagged records."""

import json
import math
from pathlib import Path
import re
import time
from typing import Annotated, Any

import defusedxml.ElementTree as ET
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import structlog

from api.dependencies import require_admin


logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level state (set via configure())
_discogs_data_root: Path | None = None
_musicbrainz_data_root: Path | None = None
_anthropic_client: Any = None
_anthropic_model: str = "claude-sonnet-4-20250514"

# Input-validation patterns — only allow safe characters in version / record_id
_SAFE_VERSION = re.compile(r"^[a-zA-Z0-9._-]+$")
_SAFE_RECORD_ID = re.compile(r"^[a-zA-Z0-9._-]+$")

# Parsing-error classification cache: version → (expiry_timestamp, result_dict)
_parsing_error_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_PARSING_ERROR_CACHE_TTL: float = 300.0  # 5 minutes


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class _RuleSelection(BaseModel):
    rule: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    entity_type: str = Field(..., pattern=r"^[a-z-]+$")


class PromptContextRequest(BaseModel):
    rules: list[_RuleSelection] = Field(..., min_length=1, max_length=20)


def configure(
    discogs_root: str | Path | None = None,
    musicbrainz_root: str | Path | None = None,
    anthropic_client: Any = None,
    anthropic_model: str = "claude-sonnet-4-20250514",
) -> None:
    """Initialise module state — called once during app lifespan startup."""
    global _discogs_data_root, _musicbrainz_data_root, _anthropic_client, _anthropic_model
    _discogs_data_root = Path(discogs_root) if discogs_root else None
    _musicbrainz_data_root = Path(musicbrainz_root) if musicbrainz_root else None
    _anthropic_client = anthropic_client
    _anthropic_model = anthropic_model
    logger.info(
        "🔧 Extraction analysis router configured",
        discogs_root=discogs_root,
        musicbrainz_root=musicbrainz_root,
        ai_prompt_available=anthropic_client is not None,
    )


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
    """Aggregate violations by severity, entity type, and rule.

    Returns a dict with:
    - total: int
    - by_severity: {severity: count}
    - by_entity: {entity_type: {total, errors, warnings}}
    - by_rule: [{rule, entity_type, severity, count}]
    """
    by_severity: dict[str, int] = {}
    # entity → {total, errors, warnings}
    by_entity: dict[str, dict[str, int]] = {}
    # (rule, entity_type, severity) → count
    rule_key_counts: dict[tuple[str, str, str], int] = {}

    for v in violations:
        severity: str = v.get("severity", "unknown")
        entity_type: str = v.get("entity_type", "unknown")
        rule: str = v.get("rule", "unknown")

        by_severity[severity] = by_severity.get(severity, 0) + 1

        entity_entry = by_entity.setdefault(entity_type, {"total": 0, "errors": 0, "warnings": 0})
        entity_entry["total"] += 1
        if severity == "error":
            entity_entry["errors"] += 1
        elif severity == "warning":
            entity_entry["warnings"] += 1

        key = (rule, entity_type, severity)
        rule_key_counts[key] = rule_key_counts.get(key, 0) + 1

    by_rule = [{"rule": rule, "entity_type": et, "severity": sev, "count": count} for (rule, et, sev), count in sorted(rule_key_counts.items())]

    return {
        "total": len(violations),
        "by_severity": by_severity,
        "by_entity": by_entity,
        "by_rule": by_rule,
    }


# Maximum size (in bytes) for raw XML / JSON files returned in violation detail responses.
# Files larger than this are truncated to avoid hanging the browser.
_MAX_RECORD_FILE_BYTES = 512 * 1024  # 512 KiB


def _load_record_files(flagged_dir: Path, entity_type: str, record_id: str) -> tuple[str | None, dict[str, Any] | None, bool]:
    """Load raw XML and parsed JSON for a record from its flagged entity directory.

    Returns (raw_xml, parsed_json, truncated) where either content value may be None
    if the file is missing or corrupt, and *truncated* is True when at least one file
    exceeded ``_MAX_RECORD_FILE_BYTES`` and was clipped.
    """
    entity_dir = flagged_dir / entity_type
    xml_path = entity_dir / f"{record_id}.xml"
    json_path = entity_dir / f"{record_id}.json"
    truncated = False

    raw_xml: str | None = None
    if xml_path.is_file():
        try:
            size = xml_path.stat().st_size
            if size > _MAX_RECORD_FILE_BYTES:
                raw_xml = xml_path.read_bytes()[:_MAX_RECORD_FILE_BYTES].decode("utf-8", errors="replace")
                raw_xml += f"\n\n... [truncated — file is {size / 1024 / 1024:.1f} MB, showing first {_MAX_RECORD_FILE_BYTES // 1024} KB]"
                truncated = True
            else:
                raw_xml = xml_path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("⚠️ Could not read XML file", path=str(xml_path))

    parsed_json: dict[str, Any] | None = None
    if json_path.is_file():
        try:
            size = json_path.stat().st_size
            if size > _MAX_RECORD_FILE_BYTES:
                raw_json_text = json_path.read_bytes()[:_MAX_RECORD_FILE_BYTES].decode("utf-8", errors="replace")
                parsed_json = {
                    "_truncated": True,
                    "_message": f"File is {size / 1024 / 1024:.1f} MB, too large to display",
                    "_preview": raw_json_text[:4096],
                }
                truncated = True
            else:
                parsed_json = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("⚠️ Could not read JSON file", path=str(json_path))

    return raw_xml, parsed_json, truncated


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
    raw_state = _load_state_marker(data_root, version, source)
    summary = _build_violation_summary(violations)

    # Extract phase statuses from the state marker for the frontend.
    # The raw marker has nested objects for each phase; the dashboard
    # expects {phase_name: status_string}.
    pipeline_status: dict[str, str] = {}
    if raw_state:
        for key, value in raw_state.items():
            if key.endswith("_phase") and isinstance(value, dict):
                pipeline_status[key] = value.get("status", "unknown")

    return JSONResponse(
        content={
            "version": version,
            "source": source,
            "pipeline_status": pipeline_status,
            **summary,
        }
    )


@router.get("/api/admin/extraction-analysis/{version}/violations")
async def list_violations(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    entity_type: Annotated[str | None, Query(pattern=r"^[a-z-]+$")] = None,
    severity: Annotated[str | None, Query(pattern=r"^(error|warning|info)$")] = None,
    rule: Annotated[str | None, Query(pattern=r"^[a-zA-Z0-9_-]+$")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    """Return a paginated list of violations for the given extraction version, with optional filters."""
    _validate_version(version)

    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    data_root, _source = location
    flagged_version_dir = data_root / "flagged" / version

    violations = _read_violations(flagged_version_dir)

    # Apply filters
    if entity_type is not None:
        violations = [v for v in violations if v.get("entity_type") == entity_type]
    if severity is not None:
        violations = [v for v in violations if v.get("severity") == severity]
    if rule is not None:
        violations = [v for v in violations if v.get("rule") == rule]

    total_items = len(violations)
    total_pages = max(1, math.ceil(total_items / page_size))
    start = (page - 1) * page_size
    end = start + page_size
    page_violations = violations[start:end]

    return JSONResponse(
        content={
            "violations": page_violations,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
            },
        }
    )


@router.get("/api/admin/extraction-analysis/{version}/violations/{record_id}")
async def get_violation_detail(
    version: str,
    record_id: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Return all violations for a specific record, plus raw XML and parsed JSON (if available)."""
    _validate_version(version)
    _validate_record_id(record_id)

    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    data_root, _source = location
    flagged_version_dir = data_root / "flagged" / version

    all_violations = _read_violations(flagged_version_dir)
    record_violations = [v for v in all_violations if v.get("record_id") == record_id]

    if not record_violations:
        raise HTTPException(status_code=404, detail=f"No violations found for record_id: {record_id!r}")

    # Determine the entity type (use the first match)
    found_entity_type: str = record_violations[0].get("entity_type", "unknown")
    raw_xml, parsed_json, truncated = _load_record_files(flagged_version_dir, found_entity_type, record_id)

    return JSONResponse(
        content={
            "record_id": record_id,
            "entity_type": found_entity_type,
            "violations": record_violations,
            "raw_xml": raw_xml,
            "parsed_json": parsed_json,
            "truncated": truncated,
        }
    )


# ---------------------------------------------------------------------------
# Task 5 — helpers
# ---------------------------------------------------------------------------


def _extract_xml_field_value(xml_text: str, field: str) -> str | None:
    """Safely parse *xml_text* and return the text of the element named *field*.

    Supports dot-notation by taking only the last segment (e.g. ``"release.year"`` → ``"year"``).
    Returns None if the field is absent, empty, or XML is malformed.
    """
    leaf = field.rsplit(".", maxsplit=1)[-1]
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        logger.warning("⚠️ Could not parse XML for field extraction", field=field)
        return None

    # Search direct children first, then recursively
    element = root.find(leaf)
    if element is None:
        for elem in root.iter(leaf):
            element = elem
            break

    if element is None:
        return None
    text = element.text
    return text.strip() if text and text.strip() else None


def _classify_violation(
    violation: dict[str, Any],
    flagged_dir: Path,
    entity_type: str,
) -> dict[str, Any]:
    """Classify a violation as parsing_error, source_issue, or indeterminate.

    - indeterminate: XML or JSON file is missing
    - parsing_error: XML has the field value but JSON does not
    - source_issue: XML also lacks the field value
    """
    record_id: str = violation.get("record_id", "")
    field: str = violation.get("field", "")
    rule: str = violation.get("rule", "")

    raw_xml, parsed_json, truncated = _load_record_files(flagged_dir, entity_type, record_id)

    xml_value: str | None = None
    json_value: str | None = None
    classification: str

    if raw_xml is None or parsed_json is None or truncated:
        classification = "indeterminate"
    else:
        xml_value = _extract_xml_field_value(raw_xml, field) if field else None

        # Extract JSON value: support dot-notation — use the last segment as the key
        leaf = field.rsplit(".", maxsplit=1)[-1] if field else field
        raw_json_val = parsed_json.get(leaf)
        json_value = str(raw_json_val).strip() if raw_json_val is not None and str(raw_json_val).strip() else None

        if xml_value and not json_value:
            classification = "parsing_error"
        elif not xml_value and not json_value:
            classification = "source_issue"
        else:
            # Both present — field exists in both, flagged for another reason; treat as source_issue
            classification = "source_issue"

    return {
        "record_id": record_id,
        "entity_type": entity_type,
        "rule": rule,
        "field": field,
        "xml_value": xml_value,
        "json_value": json_value,
        "classification": classification,
    }


# ---------------------------------------------------------------------------
# Task 5 — endpoint
# ---------------------------------------------------------------------------


@router.get("/api/admin/extraction-analysis/{version}/parsing-errors")
async def get_parsing_errors(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Classify violations as parsing errors, source issues, or indeterminate.

    Results are cached in memory for 5 minutes to avoid repeated filesystem scans.
    """
    _validate_version(version)

    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    cache_key = version
    now = time.monotonic()
    if cache_key in _parsing_error_cache:
        expiry, cached_result = _parsing_error_cache[cache_key]
        if now < expiry:
            return JSONResponse(content=cached_result)

    data_root, _source = location
    flagged_version_dir = data_root / "flagged" / version

    violations = _read_violations(flagged_version_dir)

    parsing_errors: list[dict[str, Any]] = []
    source_issues: list[dict[str, Any]] = []
    indeterminate: list[dict[str, Any]] = []

    for v in violations:
        entity_type: str = v.get("entity_type", "unknown")
        entry = _classify_violation(v, flagged_version_dir, entity_type)
        cls = entry["classification"]
        if cls == "parsing_error":
            parsing_errors.append(entry)
        elif cls == "source_issue":
            source_issues.append(entry)
        else:
            indeterminate.append(entry)

    result: dict[str, Any] = {
        "parsing_errors": parsing_errors,
        "source_issues": source_issues,
        "indeterminate": indeterminate,
        "stats": {
            "total_analyzed": len(violations),
            "parsing_errors": len(parsing_errors),
            "source_issues": len(source_issues),
            "indeterminate": len(indeterminate),
        },
    }

    _parsing_error_cache[cache_key] = (now + _PARSING_ERROR_CACHE_TTL, result)
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Task 6 — endpoints
# ---------------------------------------------------------------------------


@router.get("/api/admin/extraction-analysis/{version}/compare/{other_version}")
async def compare_versions(
    version: str,
    other_version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Return a delta between two extraction versions, grouped by (rule, severity, entity_type)."""
    _validate_version(version)
    _validate_version(other_version)

    loc_a = _find_version_root(version)
    if loc_a is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")
    loc_b = _find_version_root(other_version)
    if loc_b is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {other_version!r}")

    def _count_violations(data_root: Path, ver: str) -> dict[tuple[str, str, str], int]:
        flagged_version_dir = data_root / "flagged" / ver
        counts: dict[tuple[str, str, str], int] = {}
        for v in _read_violations(flagged_version_dir):
            key = (v.get("rule", "unknown"), v.get("severity", "unknown"), v.get("entity_type", "unknown"))
            counts[key] = counts.get(key, 0) + 1
        return counts

    counts_a = _count_violations(loc_a[0], version)
    counts_b = _count_violations(loc_b[0], other_version)

    all_keys = set(counts_a) | set(counts_b)

    improved = 0
    worsened = 0
    unchanged = 0
    new_rules = 0
    removed_rules = 0
    details: list[dict[str, Any]] = []

    for rule, sev, etype in sorted(all_keys):
        count_a = counts_a.get((rule, sev, etype), 0)
        count_b = counts_b.get((rule, sev, etype), 0)

        if count_a == 0:
            direction = "worsened"
            new_rules += 1
            worsened += 1
        elif count_b == 0:
            direction = "improved"
            removed_rules += 1
            improved += 1
        elif count_b < count_a:
            direction = "improved"
            improved += 1
        elif count_b > count_a:
            direction = "worsened"
            worsened += 1
        else:
            direction = "unchanged"
            unchanged += 1

        details.append(
            {
                "rule": rule,
                "severity": sev,
                "entity_type": etype,
                "count_a": count_a,
                "count_b": count_b,
                "direction": direction,
            }
        )

    return JSONResponse(
        content={
            "version_a": version,
            "version_b": other_version,
            "summary": {
                "improved": improved,
                "worsened": worsened,
                "unchanged": unchanged,
                "new_rules": new_rules,
                "removed_rules": removed_rules,
            },
            "details": details,
        }
    )


@router.post("/api/admin/extraction-analysis/{version}/prompt-context")
async def get_prompt_context(
    version: str,
    body: PromptContextRequest,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Assemble structured context for AI prompts — violations and sample records grouped by rule+entity_type."""
    _validate_version(version)

    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    data_root, _source = location
    flagged_version_dir = data_root / "flagged" / version

    all_violations = _read_violations(flagged_version_dir)

    max_samples = 5
    contexts: list[dict[str, Any]] = []
    for sel in body.rules:
        matching = [v for v in all_violations if v.get("rule") == sel.rule and v.get("entity_type") == sel.entity_type]
        severity = matching[0].get("severity", "unknown") if matching else "unknown"

        sample_records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for v in matching:
            rid = v.get("record_id", "")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            raw_xml, parsed_json, _truncated = _load_record_files(flagged_version_dir, sel.entity_type, rid)
            record_violations = [m for m in matching if m.get("record_id") == rid]
            sample_records.append(
                {
                    "record_id": rid,
                    "violations": [{"rule": m.get("rule", ""), "message": m.get("message", m.get("field", ""))} for m in record_violations],
                    "raw_xml": raw_xml,
                    "parsed_json": parsed_json,
                }
            )
            if len(sample_records) >= max_samples:
                break

        contexts.append(
            {
                "rule": sel.rule,
                "entity_type": sel.entity_type,
                "severity": severity,
                "total_violations": len(matching),
                "sample_records": sample_records,
            }
        )

    return JSONResponse(content={"contexts": contexts})


# ---------------------------------------------------------------------------
# AI-powered prompt generation
# ---------------------------------------------------------------------------

_MAX_XML_CHARS_PER_RECORD = 1500
_MAX_JSON_CHARS_PER_RECORD = 1500
_MAX_SAMPLES_FOR_AI = 3


@router.post("/api/admin/extraction-analysis/{version}/generate-ai-prompt")
async def generate_ai_prompt(
    version: str,
    body: PromptContextRequest,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> JSONResponse:
    """Use Claude to analyze violations and produce a targeted debugging prompt."""
    if _anthropic_client is None:
        raise HTTPException(status_code=503, detail="AI prompt generation unavailable — NLQ_API_KEY not configured")

    _validate_version(version)
    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    data_root, source = location
    flagged_version_dir = data_root / "flagged" / version
    all_violations = _read_violations(flagged_version_dir)

    # Build a compact context payload for Claude
    rule_sections: list[str] = []
    for sel in body.rules:
        matching = [v for v in all_violations if v.get("rule") == sel.rule and v.get("entity_type") == sel.entity_type]
        if not matching:
            continue

        severity = matching[0].get("severity", "unknown")
        total = len(matching)

        # Collect unique field values to show distribution
        field_values: list[str] = []
        for v in matching[:50]:
            val = v.get("value", v.get("field", ""))
            if val and val not in field_values:
                field_values.append(str(val))
            if len(field_values) >= 10:
                break

        section_lines = [
            f"### Rule: `{sel.rule}` (entity: {sel.entity_type})",
            f"- Severity: {severity}",
            f"- Total violations: {total:,}",
        ]
        if field_values:
            section_lines.append(f"- Affected fields/values: {', '.join(f'`{v}`' for v in field_values)}")

        # Sample records with truncated XML/JSON
        seen_ids: set[str] = set()
        sample_count = 0
        for v in matching:
            rid = v.get("record_id", "")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            raw_xml, parsed_json, _truncated = _load_record_files(flagged_version_dir, sel.entity_type, rid)
            record_violations = [m for m in matching if m.get("record_id") == rid]

            section_lines.append(f"\n**Sample record {sample_count + 1} — ID {rid}:**")
            section_lines.append("Violations:")
            for rv in record_violations:
                section_lines.append(
                    f"  - `{rv.get('rule', '')}` on field `{rv.get('field', rv.get('message', ''))}` — value: `{rv.get('value', '(not captured)')}`"
                )

            if parsed_json:
                json_str = json.dumps(parsed_json, indent=2) if isinstance(parsed_json, dict) else str(parsed_json)
                if len(json_str) > _MAX_JSON_CHARS_PER_RECORD:
                    json_str = json_str[:_MAX_JSON_CHARS_PER_RECORD] + "\n... (truncated)"
                section_lines.append(f"```json\n{json_str}\n```")

            if raw_xml:
                xml_trimmed = raw_xml[:_MAX_XML_CHARS_PER_RECORD]
                if len(raw_xml) > _MAX_XML_CHARS_PER_RECORD:
                    xml_trimmed += "\n... (truncated)"
                section_lines.append(f"```xml\n{xml_trimmed}\n```")

            sample_count += 1
            if sample_count >= _MAX_SAMPLES_FOR_AI:
                break

        rule_sections.append("\n".join(section_lines))

    user_content = f"# Extraction Analysis — Version {version} (source: {source})\n\n" + "\n\n---\n\n".join(rule_sections)

    system_prompt = (
        "You are a data pipeline debugging expert for Discogsography, a system that parses "
        "Discogs XML database dumps and MusicBrainz JSONL exports into Neo4j and PostgreSQL.\n\n"
        "The user will show you data quality violations from the extraction pipeline. "
        "Each violation has a rule name, severity, affected field, the actual value, "
        "and sample records with raw XML and parsed JSON.\n\n"
        "Your task is to produce a **debugging prompt** — a self-contained document that someone "
        "(or another AI assistant) can use in a future session to:\n"
        "1. Understand the root cause of each violation\n"
        "2. Determine if it's a data issue (bad upstream data) or a parser/validation bug\n"
        "3. Propose concrete fixes or workarounds — heuristics, parser changes, or validation rule adjustments\n\n"
        "Structure your output as a markdown document with:\n"
        "- A brief summary of all violations and their likely categories\n"
        "- Per-rule sections with: root cause analysis, evidence from the sample data, "
        "and specific recommended actions (code changes, heuristic fixes, rule adjustments)\n"
        "- For high-volume rules (thousands+ violations), focus on whether the rule itself "
        "needs adjustment rather than individual records\n"
        "- Reference specific field values, XML elements, and JSON keys from the samples\n\n"
        "Be concrete and actionable. Include code snippets for proposed fixes when applicable."
    )

    try:
        response = await _anthropic_client.messages.create(
            model=_anthropic_model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=4096,
        )
        prompt_text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return JSONResponse(content={"prompt": prompt_text, "ai_generated": True})
    except Exception:
        logger.exception("❌ AI prompt generation failed")
        raise HTTPException(status_code=502, detail="AI prompt generation failed") from None
