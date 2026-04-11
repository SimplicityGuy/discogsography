# Design: Move data_normalizer.py Logic to Rust Extractor

**Date:** 2026-04-11
**Issue:** #290
**Status:** Approved

## Problem

The `common/data_normalizer.py` module runs in every Python consumer (graphinator, tableinator) to normalize raw extractor JSON into a consistent format. This is redundant work — the same transformations run identically in every consumer. The Rust extractor is the single producer; it should produce clean, consumer-ready JSON so normalization happens once at the extraction boundary.

## Approach

Clean cut: update extractor + all consumers in the same PR. The next extraction re-processes all records (different JSON shape = different sha256 hash), which is safe since all writes are idempotent upserts.

## Design

### 1. Rust Extractor — New `normalize.rs` Module

A new module in the extractor that transforms XML-shaped JSON into flat, consumer-ready JSON. Called in the validator stage after `apply_filters()` and before `calculate_content_hash()`.

**Pipeline ordering:**
```
parse XML → apply_filters() → normalize() → calculate_content_hash() → evaluate_rules() → publish
```

Rules operate on the pre-normalization (XML) shape and require no config changes.

**Generic transforms (all entity types):**
- Strip `@` prefix from attribute keys (`@id` → `id`)
- Extract `#text` values into plain strings
- Unwrap single-item containers into proper lists

**Artist transforms:**
- `members.name[]` → `members[]` as `[{id, name}, ...]`
- `groups.name[]` → `groups[]` as `[{id, name}, ...]`
- `aliases.name[]` → `aliases[]` as `[{id, name}, ...]`

**Label transforms:**
- `parentLabel` → `{id, name}` (strip `@`, extract `#text`)
- `sublabels.label[]` → `sublabels[]` as `[{id, name}, ...]`

**Master transforms:**
- `artists.artist[]` → `artists[]` as `[{id, name, ...}, ...]`
- `genres.genre[]` → `genres[]` as `["Rock", "Pop"]`
- `styles.style[]` → `styles[]` as `["Punk", "Hardcore"]`

**Release transforms:**
- Same artist/genre/style flattening as masters
- `labels.label[]` → `labels[]` as `[{id, name, catno}, ...]`
- `master_id` dict → plain string value
- `extraartists.artist[]` → `extraartists[]` as `[{id, name, role}, ...]`
- `formats.format[]` → `formats[]` as `[{name, qty, descriptions}, ...]` (strip `@name` → `name`, `@qty` → `qty`)

### 2. Python Consumer Changes

**`common/data_normalizer.py` — simplify:**
- Remove helper functions: `normalize_id()`, `normalize_text()`, `normalize_item_with_id()`, `normalize_nested_list()`, `ensure_list()`
- Remove entity normalizers: `normalize_artist()`, `normalize_label()`, `normalize_master()`, `normalize_release()`
- Remove `extract_format_names()` — formats arrive flat, consumers use `[f["name"] for f in record.get("formats", [])]`
- Keep `_parse_year_int()` — date string → year integer conversion (consumer-specific: masters use `year` field, releases use `released` field)
- Keep `normalize_record()` as a thin wrapper doing only year parsing and field passthrough

**Graphinator:**
- Remove `extract_format_names` import and usage from `graphinator.py` and `batch_processor.py`
- Replace with direct list comprehension on flat `formats` list

**Tableinator:**
- `normalize_record` calls continue to work; function internals are simpler

**No changes to consumer business logic** — Neo4j queries and PostgreSQL upserts already work with the normalized shape.

### 3. What Stays in Python

- `_parse_year_int()` — date string parsing (`"1969-09-26" → 1969`) is consumer-specific
- Field selection/projection — each consumer picks the fields it needs
- `normalize_record()` call sites — function signature unchanged

### 4. Testing Strategy

**Rust tests (`normalize.rs`):**
- Unit tests per entity type: XML-shaped JSON in, flat JSON out
- Edge cases: missing fields, single vs multi-item containers, empty containers, `#text` extraction
- `@` prefix stripping on nested dicts (formats with `@name`/`@qty`)
- Integration test: full pipeline parse → filter → normalize → verify output

**Python test updates:**
- `tests/common/test_data_normalizer.py` — rewrite for simplified normalizer (mostly `_parse_year_int` and thin `normalize_record`)
- Remove tests for deleted helpers
- `tests/graphinator/` and `tests/tableinator/` — update mock data fixtures to flat shape

**Existing tests unchanged:**
- Parser tests validate XML → JSON (pre-normalization)
- Rules tests validate filter/skip/nullify on XML shape
