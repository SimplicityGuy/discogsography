# Extraction Rules: Skip Records & Filter Transforms

**Date:** 2026-04-10
**Status:** Design
**Builds on:** [2026-03-21 Data Quality Rules](2026-03-21-data-quality-rules-design.md)

## Problem

The extraction quality report surfaces 36 errors and 34 warnings that are all confirmed upstream Discogs data issues — not parser bugs:

| Rule | Entity | Count | Root Cause |
|------|--------|-------|------------|
| `empty-artist-name` | artists | 1 (ID 66827) | `<name>` element absent from XML; profile says "DO NOT USE" |
| `empty-label-name` | labels | 1 (ID 212) | `<name>` element absent from XML; profile says "DO NOT USE" |
| `genre-is-numeric` | releases | 34 (17 releases) | Literal `<genre>1</genre>` in source XML — legacy internal genre ID |
| `genre-not-recognized` | releases | 34 (17 releases) | Same `"1"` values also fail the enum check |

Additionally, the `year-out-of-range` rule on masters generates **170,868 warnings** — all from `<year>0</year>`, which is Discogs's sentinel for "year unknown." The downstream normalizer (`common/data_normalizer.py:_parse_year_int`) already converts `year <= 0` to `None` before writing to Neo4j/PostgreSQL, but this logic is hardcoded in Python rather than configurable. Two more releases have genuinely anomalous years (197 and 338) that are also caught by the rule.

These violations cannot be fixed upstream and will recur every extraction. The current rules engine is observation-only — it flags but cannot skip or transform data. We need a way to:

1. Skip entire records that are known junk (e.g., profile contains "DO NOT USE")
2. Strip bad values from array fields before validation and publishing (e.g., numeric genre IDs)
3. Nullify scalar field values that match a condition (e.g., sentinel years) — replacing hardcoded normalizer logic with configurable extraction rules

## Solution Overview

Extend the existing YAML rules config (`extraction-rules.yaml`) with two new top-level sections: `skip_records` and `filters`. Both are evaluated in the `message_validator` pipeline stage, before existing validation rules and before publishing to RabbitMQ. Skipped records are logged but not forwarded. Filtered fields are mutated in-place so downstream consumers receive clean data.

Filters support two operation types: `remove_matching` (strip array elements by regex) and `nullify_when` (set scalar fields to JSON null based on a range condition). The `nullify_when` filter replaces hardcoded year normalization logic in the Python consumers, making it configurable and applied at the extraction boundary.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Skip condition type | Case-insensitive substring (`contains`) | Covers all markup variants like `[b]DO NOT USE.[/b]`; regex is overkill |
| Array filter type | Regex (`remove_matching`) | Numeric-only detection needs pattern matching; reuses existing regex infrastructure |
| Scalar filter type | Range-based (`nullify_when`) | Year sentinel/implausible detection needs numeric comparison; `below` threshold catches both 0 and implausible years in one rule |
| Normalizer migration | Remove `_parse_year_int` year<=0 logic | Extraction rules now handle sentinel years; eliminates duplicated logic between Rust extractor and Python consumers |
| Skip logging | Separate `skipped.jsonl` per entity type | Distinct from violations — different category, different UI treatment |
| Filter logging | Inline `info`-level log per record | Too many potential matches to accumulate; log line is sufficient |
| Raw XML/JSON capture for skips | Yes, write to flagged directory | Enables inspection of skipped records in the admin panel |
| Pipeline position | Skip check → Filters → Validation → Publish | Skips short-circuit early; filters clean data before rules see it |
| Report integration | Skipped records get their own section | Spike detection across versions; distinct from rule violations |

## YAML Config Schema

Two new optional top-level sections in `extraction-rules.yaml`:

```yaml
# Records matching ANY condition are skipped entirely —
# not validated, not published to consumers.
# Logged in the quality report and skipped.jsonl with reason.
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry marked DO NOT USE"
  labels:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry marked DO NOT USE"

# Field transforms applied before validation and publishing.
# Two types:
#   remove_matching — strip array elements matching a regex
#   nullify_when    — set a scalar field to null if it meets a range condition
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip legacy numeric genre IDs from upstream data"
    - field: year
      nullify_when:
        type: range
        below: 1860
      reason: "Treat sentinel and implausible years as unknown"
  masters:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip legacy numeric genre IDs from upstream data"
    - field: year
      nullify_when:
        type: range
        below: 1860
      reason: "Treat sentinel and implausible years as unknown"

# Existing rules section (unchanged)
rules:
  releases:
    - name: genre-is-numeric
      ...
```

All three sections (`skip_records`, `filters`, `rules`) are optional. Existing configs without the new sections continue to work unchanged.

## Rust Implementation

### New Types in `rules.rs`

```rust
// Deserialized from YAML
struct SkipCondition {
    field: String,
    contains: String,
    reason: String,
}

// Filter is an enum — each variant carries its own condition data
enum FilterCondition {
    RemoveMatching {
        field: String,
        remove_matching: String,  // regex pattern string
        reason: String,
    },
    NullifyWhen {
        field: String,
        nullify_when: NullifyCondition,
        reason: String,
    },
}

struct NullifyCondition {
    type: String,  // currently only "range"
    below: Option<f64>,
    above: Option<f64>,
}

// Compiled at startup (pre-lowercased / pre-compiled regex)
struct CompiledSkipCondition {
    field: String,
    contains_lower: String,
    reason: String,
}

// Compiled filter — enum matching the deserialization variants
enum CompiledFilterCondition {
    RemoveMatching {
        field: String,
        remove_matching: Regex,
        reason: String,
    },
    NullifyWhen {
        field: String,
        below: Option<f64>,
        above: Option<f64>,
        reason: String,
    },
}
```

Added to `CompiledRulesConfig`:

```rust
skip_records: HashMap<String, Vec<CompiledSkipCondition>>,
filters: HashMap<String, Vec<CompiledFilterCondition>>,
```

### New Functions

**`should_skip_record(config, data_type, record) -> Option<SkipInfo>`**

- Resolves each skip condition's `field` using existing `resolve_field()` logic
- Performs case-insensitive substring match (`field_value.to_lowercase().contains(&contains_lower)`)
- Returns `Some(SkipInfo { reason, field, field_value })` on first match, `None` if no match
- Short-circuits on first matching condition

**`apply_filters(config, data_type, record) -> Vec<FilterAction>`**

- For each filter condition:
  - **`RemoveMatching`**: resolves the parent path (e.g., `genres`) and array key (e.g., `genre`), removes matching elements from the array in-place
  - **`NullifyWhen`**: resolves the scalar field, parses as f64, sets to JSON `null` if value is below the `below` threshold or above the `above` threshold
- Mutates the record in-place
- Returns a `Vec<FilterAction>` describing what was changed (for logging)

### Pipeline Flow in `message_validator`

```
for each message:
    1. should_skip_record() → if Some: log skip, write to skipped.jsonl,
       write raw XML/JSON to flagged dir, increment skip count, continue
    2. apply_filters() → if any removals: log at info level
    3. evaluate_rules() → existing violation logic (unchanged)
    4. forward message to batcher
```

## Quality Report Changes

### New Fields in `QualityReport`

```rust
skipped_records: HashMap<String, Vec<SkippedRecord>>,

struct SkippedRecord {
    record_id: String,
    reason: String,
}
```

### Report Output

New section prepended to the existing report:

```
📊 Data Quality Report for discogs_20260401:
  ⏭️ Skipped records:
    artists: 1 (Upstream junk entry marked DO NOT USE: 66827)
    labels: 1 (Upstream junk entry marked DO NOT USE: 212)
  releases: 0 errors, 0 warnings (of 1000000 records)
  artists: 0 errors, 0 warnings (of 500000 records)
  ...
```

### JSONL Storage

Skipped records are written to `{data_type}/skipped.jsonl` in the flagged directory:

```json
{"record_id":"66827","reason":"Upstream junk entry marked DO NOT USE","field":"profile","field_value":"[b]DO NOT USE.[/b] ...","timestamp":"2026-04-03T22:07:13Z"}
```

Raw XML and parsed JSON files are still written to the flagged directory for skipped records, enabling inspection in the admin panel.

## API Changes

### New Endpoint

**`GET /api/admin/extraction-analysis/{version}/skipped`**

Query params: `entity_type` (optional filter), `page`, `page_size`

Response:

```json
{
  "skipped": [
    {
      "record_id": "66827",
      "entity_type": "artists",
      "reason": "Upstream junk entry marked DO NOT USE",
      "field": "profile",
      "field_value": "[b]DO NOT USE.[/b] ...",
      "timestamp": "2026-04-03T22:07:13Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 50
}
```

### Summary Endpoint Extension

The existing `GET /api/admin/extraction-analysis/{version}/summary` response gains a `skipped` field:

```json
{
  "skipped": {
    "artists": {"count": 1, "reasons": ["Upstream junk entry marked DO NOT USE"]},
    "labels": {"count": 1, "reasons": ["Upstream junk entry marked DO NOT USE"]}
  },
  "violations": { ... }
}
```

## Admin Panel UI Changes

### Report View

New "Skipped Records" card row between pipeline status and violations sections:

- One card per entity type that had skips, showing count and reason
- Clicking a card expands an inline list of skipped record IDs
- Each record ID is clickable and opens the existing record detail modal (raw XML + parsed JSON)

### Compare View

The delta table gains a "Skipped" row showing changes in skip counts between versions.

### Dashboard Proxy

New route in `admin_proxy.py` to forward the `/skipped` endpoint with the same validation and timeout patterns as existing routes.

## Testing

### Rust Tests (in `rules.rs` test module)

- `test_skip_record_contains_match` — record with "DO NOT USE" in profile triggers skip
- `test_skip_record_case_insensitive` — "do not use" matches "DO NOT USE"
- `test_skip_record_no_match` — normal record passes through
- `test_skip_record_missing_field` — record without the field does not skip
- `test_filter_removes_numeric_genres` — `["1", "1", "Electronic"]` becomes `["Electronic"]`
- `test_filter_preserves_non_matching` — `["Rock", "Pop"]` unchanged
- `test_filter_empty_after_removal` — all-numeric genres results in empty array
- `test_filter_no_match` — record without genres field unchanged
- `test_nullify_when_below_threshold` — year=0 becomes null, year=197 becomes null
- `test_nullify_when_above_threshold` — year=9999 becomes null
- `test_nullify_when_normal_year_preserved` — year=1995 unchanged
- `test_nullify_when_non_numeric_unchanged` — non-numeric string unchanged
- `test_nullify_when_missing_field` — record without field unchanged
- `test_skip_then_filter_order` — skipped records don't get filtered (short-circuit)
- `test_yaml_parsing_with_skip_and_filters` — full YAML round-trip including nullify_when

### Python Tests

- API endpoint tests for `/skipped` with pagination and filtering
- Summary endpoint tests verifying `skipped` field in response
- Dashboard proxy forwarding tests

### Integration

- End-to-end test with a small XML fixture containing artist 66827 pattern and genre `"1"` pattern
- Verify: skipped record appears in `skipped.jsonl`, not in `violations.jsonl`, not published to RabbitMQ
- Verify: filtered genre record has clean genres in published message and no `genre-is-numeric` violation
- Verify: year=0 in master record becomes JSON null after filtering, `year-out-of-range` rule does not fire

## Normalizer Migration

The `_parse_year_int` function in `common/data_normalizer.py` (lines 340-358) currently converts `year <= 0` to `None`. With the `nullify_when` filter handling this at the extraction boundary, the normalizer's year-zero logic becomes redundant.

**Migration approach:**
- Remove the `year <= 0 → None` conversion from `_parse_year_int` — the function should only handle string-to-int parsing (e.g., extracting year from date strings like `"1969-09-26"`)
- The extractor's `nullify_when` filter sets `year` to JSON `null` before the message reaches RabbitMQ, so consumers already receive clean data
- The normalizer still parses `released` date strings (e.g., `"1969-09-26"` → `1969`) — this is unrelated to the sentinel issue and stays

**Risk:** If an extraction is run without the updated `extraction-rules.yaml` (e.g., using an older config), year=0 would pass through unfiltered. The normalizer's existing logic provides a safety net. Consider keeping a defensive check in the normalizer until the extraction rules are confirmed deployed, then removing it in a follow-up.

## Files Changed

| File | Change |
|------|--------|
| `extractor/extraction-rules.yaml` | Add `skip_records` and `filters` sections (including `nullify_when` for years) |
| `extractor/src/rules.rs` | New types, parsing, `should_skip_record()`, `apply_filters()` with `nullify_when` support, report changes |
| `extractor/src/extractor.rs` | Call skip/filter in `message_validator` before `evaluate_rules` |
| `api/routers/extraction_analysis.py` | New `/skipped` endpoint, extend summary response |
| `dashboard/admin_proxy.py` | New proxy route for `/skipped` |
| `dashboard/static/admin.html` | Skipped records card section in report view |
| `dashboard/static/admin.js` | Fetch/render skipped data, compare view delta row |
| `common/data_normalizer.py` | Remove year<=0 sentinel conversion (moved to extraction rules) |
| `docs/extraction-rules-guide.md` | Standalone usage guide for all rule types |
| `tests/extractor/` | Rust unit tests for skip/filter/nullify logic |
| `tests/api/` | Python tests for new/modified endpoints |
| `tests/dashboard/` | Proxy forwarding tests |
| `tests/common/` | Update normalizer tests to reflect removed year sentinel logic |
