# Data Quality Rules for Extraction Validation

**Issue:** #182
**Date:** 2026-03-21
**Status:** Design

## Problem

Querying genre first-year data from the knowledge graph reveals records with clearly incorrect values (e.g., Jazz year 197, genre "1"). There is currently no mechanism to detect or flag suspicious data during extraction. Bad data flows silently through the pipeline into Neo4j/PostgreSQL.

## Solution Overview

Add an optional, configurable data quality rule engine to the Rust extractor. Rules are defined in a YAML config file, evaluated after XML parsing but before RabbitMQ publishing. Flagged records have their raw XML and parsed JSON captured to disk for later analysis. Records are always published regardless of violations — flagging is observation-only.

## Design Decisions

| Decision                 | Choice                                  | Rationale                                                                   |
| ------------------------ | --------------------------------------- | --------------------------------------------------------------------------- |
| Raw XML capture          | Buffer raw bytes in parser              | Needed to distinguish parsing errors from upstream data errors              |
| Config format            | YAML                                    | Naturally represents nested rule structures; matches issue examples         |
| Pipeline insertion       | Dedicated validation stage              | Clean separation, independently testable, easy to disable                   |
| Flagged storage writes   | Buffered inline in validator            | Only ~0.001% of records flag; dedicated async writer is over-engineering    |
| Flagged storage format   | Separate XML, JSON, and JSONL log files | Each artifact independently inspectable (xmllint, jq, grep)                 |
| Rule engine architecture | Static enum-based dispatch              | Compile-time safety, exhaustive match, idiomatic Rust for 5 condition types |
| Version in storage path  | Discogs dump version (e.g., 20260301)   | Aligns with existing versioning throughout extractor                        |

## Architecture

### Modified Pipeline

When rules are configured:

```
Parser (with raw XML buffering) → channel → Validator → channel → Batcher → channel → Publisher
```

When no rules are configured (current behavior, zero overhead):

```
Parser → channel → Batcher → channel → Publisher
```

### New Module: `src/rules.rs`

Contains all rule engine types, YAML deserialization, field resolution, condition evaluation, violation storage, and quality report accumulation.

## Detailed Design

### 1. Parser Changes — Raw XML Capture

Add a `raw_xml_buffer: Vec<u8>` to `XmlParser` that accumulates raw bytes between record start/end tags (depth 2 elements). When parsing completes for a record, the buffer is attached to the `DataMessage` and cleared for the next record.

**Changes to `DataMessage` (in `types.rs`):**

```rust
pub struct DataMessage {
    pub id: String,
    pub sha256: String,
    pub data: serde_json::Value,
    #[serde(skip)]
    pub raw_xml: Option<Vec<u8>>,  // Only populated when rules are active; never serialized to AMQP
}
```

- `raw_xml` is `Option` so that when no rule config is provided, the parser skips buffering entirely (zero overhead)
- `#[serde(skip)]` ensures the raw XML is never included in AMQP message serialization — it is pipeline-internal only, consumed by the validator stage and discarded before publishing
- The parser takes a `capture_raw_xml: bool` flag set at construction
- Existing tests that construct `DataMessage` will need `raw_xml: None` added to their struct literals

**Raw XML capture mechanism:**

The SAX parser (`quick-xml::Reader`) does not expose byte offsets that map back to per-record boundaries in the decompressed stream. Instead of attempting byte-level capture, we **reconstruct the XML fragment** from the parsed `ElementContext` tree using `quick-xml::Writer`.

After the parser accumulates a record's `ElementContext` (the same tree used to build the `serde_json::Value`), it writes it back to a `Vec<u8>` via `quick-xml::Writer::new(Cursor::new(Vec::new()))`. This produces semantically equivalent XML — same elements, attributes, text content, and structure — though not byte-identical to the original (e.g., attribute ordering or whitespace may differ). This is sufficient for the diagnostic purpose: comparing the reconstructed XML to the parsed JSON reveals parsing errors, while matching content indicates upstream data errors.

The reconstruction happens inside the parser's record-completion path (when `Event::End` fires at depth 2), immediately before sending the `DataMessage` through the channel. The cost is a `quick-xml::Writer` serialization per record, which is cheap relative to the AMQP round-trips downstream. When `capture_raw_xml` is false, this step is skipped entirely.

### 2. Rule Engine — Config, Types, and Evaluation

**YAML config structure:**

```yaml
rules:
  releases:
    - name: year-out-of-range
      description: "Release year is before 1860 or after current year + 1"
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
    - name: genre-is-numeric
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
  artists:
    - name: suspicious-name
      field: name
      condition:
        type: regex
        pattern: "^\\d+$|^.$"
      severity: warning
```

**Rust types:**

```rust
pub struct RulesConfig {
    pub rules: HashMap<String, Vec<Rule>>,  // keyed by data type
}

pub struct Rule {
    pub name: String,
    pub description: Option<String>,
    pub field: String,              // supports dot notation: "genres.genre"
    pub condition: RuleCondition,
    pub severity: Severity,
}

pub enum Severity { Error, Warning, Info }

pub enum RuleCondition {
    Range { min: Option<f64>, max: Option<f64> },
    Required,
    Regex { pattern: String },
    Length { min: Option<usize>, max: Option<usize> },
    Enum { values: Vec<String> },    // value must be IN set; anything else is flagged
}

pub struct Violation {
    pub rule_name: String,
    pub severity: Severity,
    pub field: String,
    pub field_value: String,
}
```

**Compiled rules:** After YAML deserialization, rules are compiled into a separate `CompiledRule` struct that holds pre-compiled `regex::Regex` instances:

```rust
pub struct CompiledRule {
    pub name: String,
    pub description: Option<String>,
    pub field: String,
    pub condition: CompiledCondition,
    pub severity: Severity,
}

pub enum CompiledCondition {
    Range { min: Option<f64>, max: Option<f64> },
    Required,
    Regex { regex: regex::Regex },   // pre-compiled at load time
    Length { min: Option<usize>, max: Option<usize> },
    Enum { values: HashSet<String> },  // HashSet for O(1) lookups
}
```

**Loading:** `RulesConfig::load(path: &Path)` deserializes YAML, validates data type keys against `DataType` variants (unknown keys cause a startup error), and compiles rules into `CompiledRule` instances. Invalid regex causes a startup error (fail fast). Called once; the resulting compiled config is shared as `Arc<CompiledRulesConfig>`.

**Dot notation field resolution:** `resolve_field(data: &Value, field: "genres.genre")` walks the JSON tree. At each segment, if the value is an array, it collects all child values and evaluates the rule against each. If any element triggers, the record is flagged.

**Evaluation logic per condition:**

- **Range** — Parse value as `f64`. Flag if outside `[min, max]` (either bound optional).
- **Required** — Flag if field is missing, null, or empty string.
- **Regex** — Flag if value matches the pattern (matching = suspicious).
- **Length** — Flag if string length outside `[min, max]`.
- **Enum** — Flag if value is NOT in the allowed set.

### 3. Validation Pipeline Stage

**New async task: `message_validator`**

Wired between parser and batcher in `process_single_file()`.

**Per-message behavior:**

1. Look up rules for the current `data_type` in `Arc<CompiledRulesConfig>`
1. Evaluate all matching rules against `message.data`
1. If violations exist at `error` or `warning` severity:
   - Write `{record_id}.xml` and `{record_id}.json` if not already written for this record
   - Append violation lines to `violations.jsonl`
   - Increment per-rule counters in `QualityReport`
1. Forward the message downstream (always — flagging is non-blocking)

**`QualityReport` accumulator:**

Each validator task owns its own `QualityReport` (one per file/data type — no shared state, no locks). After a file completes, its report is returned to the orchestrator which merges them into an aggregate report for the final summary.

```rust
pub struct QualityReport {
    pub counts: HashMap<String, HashMap<String, RuleCounts>>,  // data_type -> rule_name -> counts
    pub total_records: HashMap<String, u64>,                    // data_type -> total count
}

pub struct RuleCounts {
    pub errors: u64,
    pub warnings: u64,
    pub info: u64,
}
```

### 4. Flagged Record Storage

**Directory layout:**

```
{discogs_root}/flagged/{version}/
├── releases/
│   ├── 12345.xml          # raw XML fragment
│   ├── 12345.json         # parsed JSON (what would go to RabbitMQ)
│   └── violations.jsonl   # per-data-type violation log
├── artists/
│   └── violations.jsonl
├── labels/
│   └── violations.jsonl
├── masters/
│   └── violations.jsonl
└── report.txt             # summary report
```

**Key behaviors:**

- One XML/JSON pair per record (not per violation) — if a record triggers 3 rules, it gets one `.xml` + one `.json` file, but 3 lines in `violations.jsonl`
- Directories created lazily on first violation (no empty dirs for clean data types)
- `BufWriter<File>` for the JSONL writer, one per data type
- `info` severity violations are logged to `violations.jsonl` (for traceability) but do not trigger XML/JSON file capture
- Storage I/O failures (e.g., unwritable directory, full disk) are logged as warnings and do not halt the pipeline — the "always publish" guarantee takes precedence over flagged record persistence

**violations.jsonl line format:**

```json
{"record_id": "12345", "rule": "genre-is-numeric", "severity": "error", "field": "genres.genre", "field_value": "1", "xml_file": "12345.xml", "json_file": "12345.json", "timestamp": "2026-03-21T10:30:00Z"}
```

### 5. Summary Report

Logged at extraction completion and written to `{discogs_root}/flagged/{version}/report.txt`:

```
Data Quality Report for discogs_20260301:
  releases: 2 errors, 15 warnings (of 16,234,502 records)
    genre-is-numeric:              2 errors
    genre-not-recognized:          5 warnings
    release-with-suspicious-year:  8 warnings
    year-out-of-range:             2 warnings
  artists:  0 errors, 3 warnings (of 8,912,344 records)
  labels:   1 error, 0 warnings (of 2,123,456 records)
  masters:  0 errors, 8 warnings (of 2,345,678 records)
```

## Configuration

- **Env var:** `DATA_QUALITY_RULES` — path to YAML rules file
- **CLI arg:** `--data-quality-rules` (consistent with existing `--force-reprocess`)
- If unset, extraction runs exactly as today — no overhead
- Invalid YAML or bad regex patterns cause a startup error with a clear message

## New Dependencies

- `serde_yaml` — YAML deserialization

Note: `regex` is already in `Cargo.toml` (`regex = "1.12"`).

## Default Rules File

Ship `extraction-rules.yaml` in the `extractor/` directory as a ready-to-use starting point containing the rules from issue #182. Not loaded automatically — must be explicitly configured.

Note: The `max` value in year-range rules (e.g., `max: 2027`) is static and must be updated periodically. A comment in the default rules file will flag this. Dynamic expressions (e.g., `current_year + 1`) are out of scope for the initial implementation.

## Testing Strategy

### Unit Tests (`src/tests/rules_test.rs`)

- Each condition type: range (both bounds, single bound, edge cases), required (missing/null/empty), regex (match/no-match), length, enum (in-set/not-in-set)
- Dot notation field resolution: simple field, nested field, array iteration, missing intermediate field
- YAML deserialization: valid config, invalid regex (expect error), unknown condition type
- `QualityReport` accumulation

### Integration Test (`extractor/tests/rules_integration_test.rs`)

- Sample XML with known-bad records (genre "1", year 197, year 338) parsed through full pipeline with rules active
- Assert correct violations are captured
- Assert flagged files are written (XML, JSON, violations.jsonl)
- Assert clean records pass through unmodified
- Assert pipeline without rules config behaves identically to current behavior

### Existing Tests

Existing tests that construct `DataMessage` will need `raw_xml: None` added to struct literals (mechanical update). No behavioral changes — validator stage is only wired when rules are configured.

## Out of Scope

- Cross-record rules (e.g., "genre X should not appear before year Y")
- Auto-correction or filtering of flagged records
- Dashboard/UI for reviewing flagged records
- Downstream consumer awareness of flagged records

## Files to Create/Modify

### New Files

- `extractor/src/rules.rs` — rule engine module
- `extractor/src/tests/rules_test.rs` — unit tests
- `extractor/tests/rules_integration_test.rs` — integration tests
- `extractor/extraction-rules.yaml` — default rules config file

### Modified Files

- `extractor/src/types.rs` — add `raw_xml: Option<Vec<u8>>` to `DataMessage` with `#[serde(skip)]`
- `extractor/src/parser.rs` — raw XML byte buffering
- `extractor/src/extractor.rs` — wire validator stage, aggregate quality report
- `extractor/src/config.rs` — add `data_quality_rules` config field
- `extractor/src/main.rs` — load rules config, pass to pipeline
- `extractor/Cargo.toml` — add `serde_yaml` dependency
