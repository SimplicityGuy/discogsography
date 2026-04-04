# Extraction Analysis Dashboard — Design Spec

**Date:** 2026-04-03
**Status:** Approved

## Overview

Add an "Extraction Analysis" tab to the admin dashboard that analyzes extraction failures from the Discogs and MusicBrainz extractors. The feature combines flagged record violations and state marker pipeline data to provide single-version reports, two-version comparisons, parsing error detection, and a Claude prompt generator for fixable issues.

## Architecture

**Approach:** Balanced API + Frontend (Approach 3)

- API provides pre-aggregated summaries AND raw paginated data
- Parsing error detection (XML vs JSON comparison) happens server-side
- Frontend handles display, filtering within fetched summaries, and prompt assembly
- Prompt template lives in the frontend for easy iteration

### Infrastructure Changes

**Docker Compose volume mounts (API service):**

- `discogs_data:/discogs-data:ro`
- `musicbrainz_data:/musicbrainz-data:ro`

**New environment variables (API):**

- `DISCOGS_DATA_ROOT` — default `/discogs-data`
- `MUSICBRAINZ_DATA_ROOT` — default `/musicbrainz-data`

**New files:**

- `api/routers/extraction_analysis.py` — API router, registered on the admin router with `extraction-analysis` prefix
- Dashboard: new tab in `admin.html` + logic in `admin.js`
- Dashboard: new proxy routes in `admin_proxy.py`

### Data Sources

Two data sources, both on the mounted volumes:

1. **State marker files** — `.extraction_status_{version}.json` (Discogs) and `.mb_extraction_status_{version}.json` (MusicBrainz). Track phase-by-phase pipeline status (download → processing → publishing) with error arrays.

1. **Flagged records** — `flagged/{version}/{entity_type}/` directories containing:

   - `violations.jsonl` — one violation entry per line (record_id, rule, severity, field, field_value, xml_file, json_file, timestamp)
   - `{record_id}.xml` — raw XML snippet of the flagged record
   - `{record_id}.json` — parsed JSON representation
   - `report.txt` — aggregated summary

Rules are dynamic — derived from `extraction-rules.yaml`, not hardcoded. Any new rule automatically appears in the analysis.

## API Endpoints

All endpoints require admin JWT authentication (same dependency as existing `/api/admin/*` routes). All under `/api/admin/extraction-analysis/`.

### `GET /api/admin/extraction-analysis/versions`

List available extraction versions by scanning `flagged/` directories in both data roots.

**Response:**

```json
{
  "versions": [
    {
      "version": "20260101",
      "source": "discogs",
      "entity_types": ["artists", "labels", "masters", "releases"],
      "flagged_dir": "/discogs-data/flagged/20260101"
    }
  ]
}
```

### `GET /api/admin/extraction-analysis/{version}/summary`

Aggregated report for a single version.

**Response:**

```json
{
  "version": "20260101",
  "source": "discogs",
  "pipeline_status": {
    "download_phase": { "status": "completed", "errors": [] },
    "processing_phase": {
      "status": "completed",
      "errors": [],
      "progress_by_file": {
        "discogs_20260101_releases.xml.gz": {
          "status": "completed",
          "records_extracted": 480900,
          "messages_published": 480900
        }
      }
    },
    "publishing_phase": { "status": "completed", "errors": [] }
  },
  "violation_summary": {
    "total_violations": 170,
    "by_severity": { "error": 42, "warning": 120, "info": 8 },
    "by_entity_type": {
      "releases": { "error": 35, "warning": 100, "info": 5 },
      "artists": { "error": 7, "warning": 20, "info": 3 }
    },
    "by_rule": [
      {
        "rule": "year-out-of-range",
        "severity": "error",
        "entity_type": "releases",
        "count": 25
      }
    ]
  }
}
```

If the state marker file is missing, `pipeline_status` is `null` — the endpoint still returns violation data.

### `GET /api/admin/extraction-analysis/{version}/violations`

Paginated violation entries with filtering.

**Query parameters:**

- `entity_type` — filter by entity type (artists, labels, masters, releases, release-groups)
- `severity` — filter by severity (error, warning, info)
- `rule` — filter by rule name
- `page` — page number (default 1)
- `page_size` — items per page (default 50, max 200)

**Response:**

```json
{
  "violations": [
    {
      "record_id": "123456",
      "rule": "year-out-of-range",
      "severity": "error",
      "field": "released",
      "field_value": "1850",
      "entity_type": "releases",
      "timestamp": "2026-02-03T12:34:56.789Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_items": 170,
    "total_pages": 4
  }
}
```

### `GET /api/admin/extraction-analysis/{version}/violations/{record_id}`

Single record detail with raw XML and parsed JSON.

**Response:**

```json
{
  "record_id": "123456",
  "entity_type": "releases",
  "violations": [
    {
      "rule": "year-out-of-range",
      "severity": "error",
      "field": "released",
      "field_value": "1850",
      "timestamp": "2026-02-03T12:34:56.789Z"
    }
  ],
  "raw_xml": "<release id=\"123456\">...</release>",
  "parsed_json": { "id": "123456", "title": "..." }
}
```

If the XML or JSON file is missing, the respective field is `null`.

### `GET /api/admin/extraction-analysis/{version}/parsing-errors`

Server-side comparison of XML vs JSON for flagged records to classify violations.

**Classification logic:**

1. Load both raw XML and parsed JSON for each flagged record
1. Check if the flagged field's data exists in the XML
1. Classify:
   - **`parsing_error`** — field data present in XML but missing/wrong in JSON (fixable in extractor code)
   - **`source_issue`** — field data missing/invalid in the XML itself (Discogs-side problem)
   - **`indeterminate`** — can't conclusively classify

Results are cached in memory with 5-minute TTL keyed by version (flagged data is immutable after extraction completes).

**Response:**

```json
{
  "parsing_errors": [
    {
      "record_id": "123456",
      "entity_type": "releases",
      "rule": "year-out-of-range",
      "field": "released",
      "xml_value": "2024",
      "json_value": null,
      "classification": "parsing_error"
    }
  ],
  "source_issues": [],
  "indeterminate": [],
  "stats": {
    "total_analyzed": 170,
    "parsing_errors": 42,
    "source_issues": 120,
    "indeterminate": 8
  }
}
```

### `GET /api/admin/extraction-analysis/{version}/compare/{other_version}`

Delta between two versions.

**Response:**

```json
{
  "version_a": "20260101",
  "version_b": "20260201",
  "summary": {
    "improved": 3,
    "worsened": 1,
    "unchanged": 8,
    "new_rules": 0,
    "removed_rules": 0
  },
  "details": [
    {
      "rule": "year-out-of-range",
      "severity": "error",
      "entity_type": "releases",
      "count_a": 25,
      "count_b": 15,
      "direction": "improved"
    }
  ]
}
```

### `POST /api/admin/extraction-analysis/{version}/prompt-context`

Assemble context for Claude prompt generation. Frontend formats the final prompt.

**Request body:**

```json
{
  "record_ids": ["123456", "789012"],
  "rule": "year-out-of-range"
}
```

**Response:**

```json
{
  "rule": "year-out-of-range",
  "rule_definition": {
    "description": "Year is outside valid range",
    "severity": "error",
    "field": "released",
    "source": "extraction-rules.yaml"
  },
  "records": [
    {
      "record_id": "123456",
      "entity_type": "releases",
      "violation": {
        "field": "released",
        "field_value": "1850"
      },
      "raw_xml": "<release id=\"123456\">...</release>",
      "parsed_json": { "id": "123456", "title": "..." }
    }
  ],
  "extractor_context": {
    "parser_file": "extractor/src/xml_parser.rs",
    "rules_file": "extractor/extraction-rules.yaml"
  }
}
```

## Dashboard UI

New "Extraction Analysis" tab in the admin panel, with three sub-views toggled by buttons.

### Sub-view 1: Single Version Report (default)

- **Version selector** dropdown, most recent first, with source badge (Discogs / MusicBrainz)
- **Pipeline Status card** — phase-by-phase status indicators (download → processing → publishing) with error counts from state marker
- **Violation Summary cards** — one card per entity type showing total violations broken down by severity (error/warning/info)
- **Rule Breakdown table** — columns: rule name, severity, entity type, count, "parsing error" badge (from parsing-errors endpoint). Sortable by count. Clicking a row expands inline showing sample violations with field values.
- **Record Detail modal** — clicking a record ID shows side-by-side raw XML and parsed JSON, with missing/mismatched fields highlighted

### Sub-view 2: Version Comparison

- **Two version dropdowns** — select any two available versions
- **Delta table** — columns: rule name, severity, entity type, count in version A, count in version B, change with green (improved) / red (worsened) direction indicators
- **Summary line** — "X rules improved, Y rules worsened, Z unchanged"

### Sub-view 3: Prompt Generator

- Accessed from the Rule Breakdown table: checkbox per violation row, "Generate Prompt" button
- Shows a **text area** with the assembled prompt containing:
  - Rule definition from extraction-rules.yaml
  - Sample violations with field values
  - Raw XML + parsed JSON for each selected record
  - Relevant extractor source file paths
- **Copy-to-clipboard** button
- Prompt template lives entirely in `admin.js` for easy iteration without backend redeployment

### Dashboard Proxy Routes

New routes in `admin_proxy.py`, all forwarding to the API with JWT auth validation:

- `GET /admin/api/extraction-analysis/versions`
- `GET /admin/api/extraction-analysis/{version}/summary`
- `GET /admin/api/extraction-analysis/{version}/violations`
- `GET /admin/api/extraction-analysis/{version}/violations/{record_id}`
- `GET /admin/api/extraction-analysis/{version}/parsing-errors`
- `GET /admin/api/extraction-analysis/{version}/compare/{other_version}`
- `POST /admin/api/extraction-analysis/{version}/prompt-context`

Path parameters validated with strict regex (`[a-zA-Z0-9._-]+`) consistent with existing proxy validation patterns.

## Testing

### API Tests (`tests/api/test_extraction_analysis.py`)

- Each endpoint tested with mock filesystem data (temp directories mimicking `flagged/{version}/` structure with sample `violations.jsonl`, XML, and JSON files)
- Admin auth enforcement: 401 without token, 403 with non-admin token
- Version not found: 404
- Pagination, filtering, and sorting on violations endpoint
- Parsing error classification with known XML/JSON pairs (one parsing error, one source issue, one indeterminate)
- Comparison between two versions
- Prompt context assembly with valid and invalid record IDs

### Dashboard Tests (`tests/dashboard/`)

- New proxy routes forward correctly with auth headers
- Path parameter validation rejects traversal attempts (e.g., `../`, `%2e%2e`)

## Error Handling

- **Missing flagged directory for a version** → 404 with clear message
- **Corrupt/unreadable JSONL line** → skip and log warning, don't fail the whole response
- **Missing XML or JSON file for a record** → return what's available, mark the missing one as `null`
- **State marker file missing** → summary works, `pipeline_status` is `null`
- **Version path parameter** validated with strict regex (alphanumeric, hyphens, underscores, dots only) to prevent path traversal
- **Large violation sets** → pagination enforced, parsing error results cached with 5-minute TTL

## Security

- All endpoints behind existing admin JWT auth dependency
- Read-only volume mounts — API cannot modify extraction data
- Path traversal prevention via strict version/record_id regex validation
- Request body validation on prompt-context endpoint (record_ids array, rule string)
- Consistent with existing admin proxy security patterns (path sanitization, JWT forwarding)
