# Data Quality Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable data quality rule engine to the Rust extractor that evaluates parsed records against YAML rules, captures raw XML + parsed JSON for flagged records, and produces a summary report.

**Architecture:** A new `rules.rs` module handles YAML config loading, rule compilation, field resolution, and condition evaluation. A new `message_validator` async pipeline stage sits between the parser and batcher. The parser is extended to optionally reconstruct raw XML via `quick-xml::Writer`. Flagged records are stored as separate `.xml`, `.json`, and `.jsonl` files organized by version and data type.

**Tech Stack:** Rust, serde_yml (maintained fork of serde_yaml), quick-xml (Writer), regex (already dep), serde_json, tokio mpsc channels

**Spec:** `docs/superpowers/specs/2026-03-21-data-quality-rules-design.md`
**Issue:** #182

______________________________________________________________________

## File Structure

### New Files

| File                                        | Responsibility                                                                                                                                                      |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extractor/src/rules.rs`                    | Rule engine: config loading, YAML deserialization, rule compilation, field resolution, condition evaluation, violation types, quality report, flagged record writer |
| `extractor/src/tests/rules_tests.rs`        | Unit tests for rule engine (condition evaluation, field resolution, YAML loading, quality report)                                                                   |
| `extractor/tests/rules_integration_test.rs` | Integration test: full pipeline with rules active, flagged record storage verification                                                                              |
| `extractor/extraction-rules.yaml`           | Default rules config file from issue #182                                                                                                                           |

### Modified Files

| File                                      | Changes                                                                                            |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `extractor/Cargo.toml`                    | Add `serde_yml` dependency                                                                         |
| `extractor/src/types.rs:101-107`          | Add `raw_xml: Option<Vec<u8>>` with `#[serde(skip)]` to `DataMessage`                              |
| `extractor/src/parser.rs:101-109,190-227` | Add `capture_raw_xml` flag, reconstruct XML via `quick-xml::Writer`                                |
| `extractor/src/config.rs:5-16,53-74`      | Add `data_quality_rules: Option<PathBuf>` field                                                    |
| `extractor/src/main.rs:20-27,29-58,75-79` | Add `--data-quality-rules` CLI arg, load rules, pass to pipeline                                   |
| `extractor/src/extractor.rs:277-367`      | Wire validator stage in `process_single_file`, aggregate reports                                   |
| `extractor/tests/extractor_di_test.rs`    | Add `compiled_rules: None` parameter to all `process_single_file` and `process_discogs_data` calls |
| 8 test files (36 occurrences)             | Add `raw_xml: None` to all `DataMessage` struct literals                                           |

______________________________________________________________________

### Task 1: Add `serde_yaml` dependency to Cargo.toml

**Files:**

- Modify: `extractor/Cargo.toml:31-33`

- [ ] **Step 1: Add serde_yaml dependency**

In the `[dependencies]` section, after the existing `serde_json` line, add:

```toml
serde_yml = "0.0.12"
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo check 2>&1 | tail -5`
Expected: compiles successfully

- [ ] **Step 3: Commit**

```bash
git add extractor/Cargo.toml
git commit -m "chore: add serde_yaml dependency for data quality rules"
```

______________________________________________________________________

### Task 2: Add `raw_xml` field to `DataMessage`

**Files:**

- Modify: `extractor/src/types.rs:101-107`

- Modify: `extractor/src/parser.rs:167,214` (the two sites that construct `DataMessage`)

- Modify: All 8 test files with `DataMessage` struct literals (36 occurrences)

- [ ] **Step 1: Add `raw_xml` field to `DataMessage`**

In `extractor/src/types.rs`, modify the `DataMessage` struct at line 101-107 to:

```rust
/// Data message containing a parsed record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataMessage {
    pub id: String,
    pub sha256: String,
    #[serde(flatten)]
    pub data: serde_json::Value,
    /// Raw XML fragment for data quality inspection; never serialized to AMQP
    #[serde(skip)]
    pub raw_xml: Option<Vec<u8>>,
}
```

- [ ] **Step 2: Add `raw_xml: None` to parser's DataMessage construction**

In `extractor/src/parser.rs`, update the two `DataMessage { ... }` constructions:

At line 167 (self-closing element):

```rust
let message = DataMessage { id, sha256, data: record.clone(), raw_xml: None };
```

At line 214 (normal record end):

```rust
let message = DataMessage { id: id.clone(), sha256, data: final_value, raw_xml: None };
```

- [ ] **Step 3: Add `raw_xml: None` to all test `DataMessage` struct literals**

Update all 36 occurrences of `DataMessage {` across these 6 test files to include `raw_xml: None`:

- `extractor/src/tests/types_tests.rs` (2 occurrences)
- `extractor/src/tests/message_queue_tests.rs` (2 occurrences)
- `extractor/src/tests/message_queue_unit_tests.rs` (5 occurrences)
- `extractor/src/tests/extractor_tests.rs` (5 occurrences)
- `extractor/tests/message_queue_test.rs` (13 occurrences)
- `extractor/tests/extractor_batcher_test.rs` (6 occurrences)

Each occurrence follows this pattern — add `raw_xml: None` as the last field:

```rust
DataMessage {
    id: "...".to_string(),
    sha256: "...".to_string(),
    data: serde_json::json!({...}),
    raw_xml: None,
}
```

- [ ] **Step 4: Verify compilation and tests pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test 2>&1 | tail -20`
Expected: all existing tests pass

- [ ] **Step 5: Verify `raw_xml` does not leak into AMQP serialization**

Run this quick check — the serialized JSON of a DataMessage should NOT contain `raw_xml`:

```bash
cd /Users/Robert/Code/public/discogsography/extractor && cargo test test_data_message_serialization -- --nocapture 2>&1 | tail -10
```

If no such test exists, verify by inspecting the serde output in the types_tests.rs tests. The `#[serde(skip)]` annotation ensures the field is excluded.

- [ ] **Step 6: Commit**

```bash
git add extractor/src/types.rs extractor/src/parser.rs extractor/src/tests/ extractor/tests/
git commit -m "feat: add raw_xml field to DataMessage for data quality inspection"
```

______________________________________________________________________

### Task 3: Create rule engine module — types, loading, and compilation

**Files:**

- Create: `extractor/src/rules.rs`

- Create: `extractor/src/tests/rules_tests.rs`

- Modify: `extractor/src/main.rs:8-15` (add `mod rules;`)

- [ ] **Step 1: Write failing tests for YAML deserialization and rule compilation**

Create `extractor/src/tests/rules_tests.rs`:

```rust
use crate::rules::{CompiledRulesConfig, RulesConfig, Severity};

#[test]
fn test_load_valid_yaml() {
    let yaml = r#"
rules:
  releases:
    - name: year-out-of-range
      description: "Release year out of range"
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
    - name: missing-title
      field: title
      condition:
        type: required
      severity: error
"#;
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    assert_eq!(config.rules.len(), 1);
    assert_eq!(config.rules["releases"].len(), 2);

    let compiled = CompiledRulesConfig::compile(config).unwrap();
    assert_eq!(compiled.rules_for("releases").len(), 2);
    assert_eq!(compiled.rules_for("nonexistent").len(), 0);
}

#[test]
fn test_load_all_condition_types() {
    let yaml = r#"
rules:
  releases:
    - name: range-rule
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
    - name: required-rule
      field: title
      condition:
        type: required
      severity: error
    - name: regex-rule
      field: name
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: warning
    - name: length-rule
      field: name
      condition:
        type: length
        min: 1
        max: 500
      severity: info
    - name: enum-rule
      field: genre
      condition:
        type: enum
        values:
          - Rock
          - Jazz
          - Electronic
      severity: warning
"#;
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    let compiled = CompiledRulesConfig::compile(config).unwrap();
    assert_eq!(compiled.rules_for("releases").len(), 5);
}

#[test]
fn test_invalid_regex_fails_compilation() {
    let yaml = r#"
rules:
  releases:
    - name: bad-regex
      field: name
      condition:
        type: regex
        pattern: "[invalid"
      severity: error
"#;
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
}

#[test]
fn test_invalid_data_type_fails_compilation() {
    let yaml = r#"
rules:
  invalid_type:
    - name: test
      field: name
      condition:
        type: required
      severity: error
"#;
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
}

#[test]
fn test_severity_deserialization() {
    let yaml = r#"
rules:
  artists:
    - name: err
      field: name
      condition:
        type: required
      severity: error
    - name: warn
      field: name
      condition:
        type: required
      severity: warning
    - name: inf
      field: name
      condition:
        type: required
      severity: info
"#;
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    let compiled = CompiledRulesConfig::compile(config).unwrap();
    let rules = compiled.rules_for("artists");
    assert!(matches!(rules[0].severity, Severity::Error));
    assert!(matches!(rules[1].severity, Severity::Warning));
    assert!(matches!(rules[2].severity, Severity::Info));
}
```

- [ ] **Step 2: Write the rule engine types and loading logic**

Create `extractor/src/rules.rs`:

```rust
use anyhow::{Context, Result, bail};
use regex::Regex;
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::path::Path;

use crate::types::DataType;

// ── YAML deserialization types ──────────────────────────────────────

#[derive(Debug, Deserialize)]
pub struct RulesConfig {
    pub rules: HashMap<String, Vec<Rule>>,
}

#[derive(Debug, Deserialize)]
pub struct Rule {
    pub name: String,
    pub description: Option<String>,
    pub field: String,
    pub condition: RuleCondition,
    pub severity: Severity,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Error,
    Warning,
    Info,
}

impl fmt::Display for Severity {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Severity::Error => write!(f, "error"),
            Severity::Warning => write!(f, "warning"),
            Severity::Info => write!(f, "info"),
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum RuleCondition {
    Range {
        min: Option<f64>,
        max: Option<f64>,
    },
    Required,
    Regex {
        pattern: String,
    },
    Length {
        min: Option<usize>,
        max: Option<usize>,
    },
    Enum {
        values: Vec<String>,
    },
}

// ── Compiled types (used at evaluation time) ────────────────────────

pub struct CompiledRulesConfig {
    rules: HashMap<String, Vec<CompiledRule>>,
}

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
    Regex { regex: Regex },
    Length { min: Option<usize>, max: Option<usize> },
    Enum { values: HashSet<String> },
}

impl RulesConfig {
    /// Load rules from a YAML file.
    pub fn load(path: &Path) -> Result<Self> {
        let contents = std::fs::read_to_string(path)
            .with_context(|| format!("Failed to read rules file: {:?}", path))?;
        serde_yml::from_str(&contents)
            .with_context(|| format!("Failed to parse rules YAML: {:?}", path))
    }
}

impl CompiledRulesConfig {
    /// Compile a deserialized config: validate data type keys and pre-compile regexes.
    pub fn compile(config: RulesConfig) -> Result<Self> {
        let mut compiled = HashMap::new();

        for (key, rules) in config.rules {
            // Validate the data type key
            key.parse::<DataType>()
                .map_err(|_| anyhow::anyhow!("Unknown data type in rules config: '{}'", key))?;

            let mut compiled_rules = Vec::with_capacity(rules.len());
            for rule in rules {
                let condition = match rule.condition {
                    RuleCondition::Range { min, max } => CompiledCondition::Range { min, max },
                    RuleCondition::Required => CompiledCondition::Required,
                    RuleCondition::Regex { pattern } => {
                        let regex = Regex::new(&pattern).with_context(|| {
                            format!("Invalid regex in rule '{}': {}", rule.name, pattern)
                        })?;
                        CompiledCondition::Regex { regex }
                    }
                    RuleCondition::Length { min, max } => CompiledCondition::Length { min, max },
                    RuleCondition::Enum { values } => {
                        CompiledCondition::Enum { values: values.into_iter().collect() }
                    }
                };

                compiled_rules.push(CompiledRule {
                    name: rule.name,
                    description: rule.description,
                    field: rule.field,
                    condition,
                    severity: rule.severity,
                });
            }
            compiled.insert(key, compiled_rules);
        }

        Ok(Self { rules: compiled })
    }

    /// Get compiled rules for a data type. Returns empty slice if none configured.
    pub fn rules_for(&self, data_type: &str) -> &[CompiledRule] {
        self.rules.get(data_type).map(|v| v.as_slice()).unwrap_or(&[])
    }
}

#[cfg(test)]
#[path = "tests/rules_tests.rs"]
mod tests;
```

- [ ] **Step 3: Register the module in main.rs**

In `extractor/src/main.rs`, add after line 13 (`mod parser;`):

```rust
mod rules;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test rules_tests -- --nocapture 2>&1 | tail -20`
Expected: all 5 tests pass

- [ ] **Step 5: Commit**

```bash
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs extractor/src/main.rs
git commit -m "feat: add rule engine types, YAML loading, and compilation"
```

______________________________________________________________________

### Task 4: Implement condition evaluation and field resolution

**Files:**

- Modify: `extractor/src/rules.rs` (add evaluation functions)

- Modify: `extractor/src/tests/rules_tests.rs` (add evaluation tests)

- [ ] **Step 1: Write failing tests for condition evaluation**

Append to `extractor/src/tests/rules_tests.rs`:

```rust
use crate::rules::{evaluate_rules, Violation};
use serde_json::json;

// ── Range condition tests ───────────────────────────────────────────

#[test]
fn test_range_within_bounds() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: year-check
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
"#);
    let record = json!({"year": "1990"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_range_below_min() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: year-check
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: error
"#);
    let record = json!({"year": "338"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].rule_name, "year-check");
    assert_eq!(violations[0].field_value, "338");
}

#[test]
fn test_range_min_only_catches_below() {
    // year-out-of-range with min=1860 catches years like 197 and 338
    // because they are below the minimum. No need for a separate "suspicious year" rule.
    let config = compile_yaml(r#"
rules:
  releases:
    - name: year-out-of-range
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
"#);
    let record = json!({"year": "197"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1, "Year 197 should be flagged as below min 1860");
    assert_eq!(violations[0].rule_name, "year-out-of-range");
}

#[test]
fn test_range_above_max() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: year-out-of-range
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
"#);
    let record = json!({"year": "2030"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1, "Year 2030 should be flagged as above max 2027");
}

// ── Required condition tests ────────────────────────────────────────

#[test]
fn test_required_present() {
    let config = compile_yaml(r#"
rules:
  labels:
    - name: empty-name
      field: name
      condition:
        type: required
      severity: error
"#);
    let record = json!({"name": "Test Label"});
    let violations = evaluate_rules(&config, "labels", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_required_missing() {
    let config = compile_yaml(r#"
rules:
  labels:
    - name: empty-name
      field: name
      condition:
        type: required
      severity: error
"#);
    let record = json!({"other_field": "value"});
    let violations = evaluate_rules(&config, "labels", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].rule_name, "empty-name");
}

#[test]
fn test_required_empty_string() {
    let config = compile_yaml(r#"
rules:
  labels:
    - name: empty-name
      field: name
      condition:
        type: required
      severity: error
"#);
    let record = json!({"name": ""});
    let violations = evaluate_rules(&config, "labels", &record);
    assert_eq!(violations.len(), 1);
}

#[test]
fn test_required_null() {
    let config = compile_yaml(r#"
rules:
  labels:
    - name: empty-name
      field: name
      condition:
        type: required
      severity: error
"#);
    let record = json!({"name": null});
    let violations = evaluate_rules(&config, "labels", &record);
    assert_eq!(violations.len(), 1);
}

// ── Regex condition tests ───────────────────────────────────────────

#[test]
fn test_regex_match_flags() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: numeric-genre
      field: genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
"#);
    let record = json!({"genre": "1"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "1");
}

#[test]
fn test_regex_no_match_ok() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: numeric-genre
      field: genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
"#);
    let record = json!({"genre": "Rock"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

// ── Enum condition tests ────────────────────────────────────────────

#[test]
fn test_enum_valid_value() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: genre-check
      field: genre
      condition:
        type: enum
        values: [Rock, Jazz, Electronic]
      severity: warning
"#);
    let record = json!({"genre": "Rock"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_enum_invalid_value() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: genre-check
      field: genre
      condition:
        type: enum
        values: [Rock, Jazz, Electronic]
      severity: warning
"#);
    let record = json!({"genre": "1"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].rule_name, "genre-check");
}

// ── Length condition tests ───────────────────────────────────────────

#[test]
fn test_length_within_bounds() {
    let config = compile_yaml(r#"
rules:
  artists:
    - name: name-length
      field: name
      condition:
        type: length
        min: 1
        max: 500
      severity: warning
"#);
    let record = json!({"name": "Test Artist"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_length_too_short() {
    let config = compile_yaml(r#"
rules:
  artists:
    - name: name-length
      field: name
      condition:
        type: length
        min: 2
      severity: warning
"#);
    let record = json!({"name": "A"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
}

// ── Dot notation / nested field tests ───────────────────────────────

#[test]
fn test_dot_notation_nested_object() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: numeric-genre
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
"#);
    let record = json!({"genres": {"genre": "1"}});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
}

#[test]
fn test_dot_notation_array() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: numeric-genre
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
"#);
    let record = json!({"genres": {"genre": ["Rock", "1", "Jazz"]}});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "1");
}

#[test]
fn test_dot_notation_all_clean() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: numeric-genre
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
"#);
    let record = json!({"genres": {"genre": ["Rock", "Jazz"]}});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_dot_notation_missing_intermediate() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: numeric-genre
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
"#);
    let record = json!({"title": "Test"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty(), "Missing intermediate field should not flag");
}

// ── No rules for data type ──────────────────────────────────────────

#[test]
fn test_no_rules_for_data_type() {
    let config = compile_yaml(r#"
rules:
  releases:
    - name: test
      field: year
      condition:
        type: required
      severity: error
"#);
    let record = json!({"name": "Test"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert!(violations.is_empty());
}

// ── Helper ──────────────────────────────────────────────────────────

fn compile_yaml(yaml: &str) -> CompiledRulesConfig {
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    CompiledRulesConfig::compile(config).unwrap()
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test rules_tests -- 2>&1 | tail -20`
Expected: FAIL — `evaluate_rules` function not found

- [ ] **Step 3: Implement field resolution and condition evaluation**

Add to `extractor/src/rules.rs`, before the `#[cfg(test)]` block:

```rust
use serde_json::Value;

/// A single rule violation found during evaluation.
#[derive(Debug, Clone)]
pub struct Violation {
    pub rule_name: String,
    pub severity: Severity,
    pub field: String,
    pub field_value: String,
}

/// Evaluate all rules for a data type against a parsed record.
/// Returns a list of violations (may be empty).
pub fn evaluate_rules(
    config: &CompiledRulesConfig,
    data_type: &str,
    record: &Value,
) -> Vec<Violation> {
    let rules = config.rules_for(data_type);
    let mut violations = Vec::new();

    for rule in rules {
        let field_values = resolve_field(record, &rule.field);

        // Required is special: flag if no values resolved
        if matches!(rule.condition, CompiledCondition::Required) {
            if field_values.is_empty() {
                violations.push(Violation {
                    rule_name: rule.name.clone(),
                    severity: rule.severity.clone(),
                    field: rule.field.clone(),
                    field_value: String::new(),
                });
            } else {
                for val in &field_values {
                    if val.is_empty() {
                        violations.push(Violation {
                            rule_name: rule.name.clone(),
                            severity: rule.severity.clone(),
                            field: rule.field.clone(),
                            field_value: val.clone(),
                        });
                    }
                }
            }
            continue;
        }

        for val in &field_values {
            if check_condition(&rule.condition, val) {
                violations.push(Violation {
                    rule_name: rule.name.clone(),
                    severity: rule.severity.clone(),
                    field: rule.field.clone(),
                    field_value: val.clone(),
                });
            }
        }
    }

    violations
}

/// Resolve a potentially dotted field path to a list of string values.
/// Returns empty vec if the field path doesn't exist in the record.
fn resolve_field(value: &Value, field: &str) -> Vec<String> {
    let segments: Vec<&str> = field.split('.').collect();
    let mut current_values = vec![value.clone()];

    for segment in &segments {
        let mut next_values = Vec::new();
        for val in &current_values {
            match val {
                Value::Object(map) => {
                    if let Some(child) = map.get(*segment) {
                        match child {
                            Value::Array(arr) => next_values.extend(arr.iter().cloned()),
                            other => next_values.push(other.clone()),
                        }
                    }
                }
                _ => {}
            }
        }
        current_values = next_values;
    }

    current_values
        .into_iter()
        .filter_map(|v| match v {
            Value::String(s) => Some(s),
            Value::Number(n) => Some(n.to_string()),
            Value::Null => Some(String::new()),
            _ => None,
        })
        .collect()
}

/// Check if a value triggers a condition. Returns true if the value is FLAGGED.
fn check_condition(condition: &CompiledCondition, value: &str) -> bool {
    match condition {
        CompiledCondition::Range { min, max } => {
            if let Ok(num) = value.parse::<f64>() {
                if let Some(min_val) = min {
                    if num < *min_val {
                        return true;
                    }
                }
                if let Some(max_val) = max {
                    if num > *max_val {
                        return true;
                    }
                }
                false
            } else {
                false // Non-numeric value, can't check range
            }
        }
        CompiledCondition::Required => {
            // Handled separately in evaluate_rules
            unreachable!()
        }
        CompiledCondition::Regex { regex } => regex.is_match(value),
        CompiledCondition::Length { min, max } => {
            let len = value.len();
            if let Some(min_val) = min {
                if len < *min_val {
                    return true;
                }
            }
            if let Some(max_val) = max {
                if len > *max_val {
                    return true;
                }
            }
            false
        }
        CompiledCondition::Enum { values } => !values.contains(value),
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test rules_tests -- --nocapture 2>&1 | tail -30`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat: implement condition evaluation and dot-notation field resolution"
```

______________________________________________________________________

### Task 5: Add quality report accumulator and flagged record writer

**Files:**

- Modify: `extractor/src/rules.rs` (add QualityReport, FlaggedRecordWriter)

- Modify: `extractor/src/tests/rules_tests.rs` (add report tests)

- [ ] **Step 1: Write failing tests for QualityReport**

Append to `extractor/src/tests/rules_tests.rs`:

```rust
use crate::rules::QualityReport;

#[test]
fn test_quality_report_accumulation() {
    let mut report = QualityReport::new();
    report.record_violation("releases", "genre-is-numeric", &Severity::Error);
    report.record_violation("releases", "genre-is-numeric", &Severity::Error);
    report.record_violation("releases", "year-out-of-range", &Severity::Warning);
    report.record_violation("artists", "suspicious-name", &Severity::Warning);
    report.increment_total("releases");
    report.increment_total("releases");
    report.increment_total("artists");

    let summary = report.format_summary("20260301");
    assert!(summary.contains("releases:"));
    assert!(summary.contains("genre-is-numeric"));
    assert!(summary.contains("2 errors"));
    assert!(summary.contains("artists:"));
}

#[test]
fn test_quality_report_merge() {
    let mut report1 = QualityReport::new();
    report1.record_violation("releases", "test-rule", &Severity::Error);
    report1.increment_total("releases");

    let mut report2 = QualityReport::new();
    report2.record_violation("artists", "test-rule", &Severity::Warning);
    report2.increment_total("artists");

    report1.merge(report2);

    let summary = report1.format_summary("20260301");
    assert!(summary.contains("releases:"));
    assert!(summary.contains("artists:"));
}

#[test]
fn test_quality_report_empty() {
    let report = QualityReport::new();
    let summary = report.format_summary("20260301");
    assert!(summary.contains("No data quality violations"));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test test_quality_report -- 2>&1 | tail -10`
Expected: FAIL — `QualityReport` not found

- [ ] **Step 3: Implement QualityReport and FlaggedRecordWriter**

Add to `extractor/src/rules.rs`, before the `#[cfg(test)]` block:

```rust
use std::io::Write;

// ── Quality Report ──────────────────────────────────────────────────

#[derive(Debug, Default)]
pub struct RuleCounts {
    pub errors: u64,
    pub warnings: u64,
    pub info: u64,
}

#[derive(Debug, Default)]
use std::collections::BTreeMap;

pub struct QualityReport {
    /// data_type -> rule_name -> counts (BTreeMap for deterministic output)
    pub counts: HashMap<String, BTreeMap<String, RuleCounts>>,
    /// data_type -> total records evaluated
    pub total_records: HashMap<String, u64>,
}

impl QualityReport {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn record_violation(&mut self, data_type: &str, rule_name: &str, severity: &Severity) {
        let rule_counts = self
            .counts
            .entry(data_type.to_string())
            .or_default()
            .entry(rule_name.to_string())
            .or_default();
        match severity {
            Severity::Error => rule_counts.errors += 1,
            Severity::Warning => rule_counts.warnings += 1,
            Severity::Info => rule_counts.info += 1,
        }
    }

    pub fn increment_total(&mut self, data_type: &str) {
        *self.total_records.entry(data_type.to_string()).or_default() += 1;
    }

    pub fn merge(&mut self, other: QualityReport) {
        for (dt, rules) in other.counts {
            let entry = self.counts.entry(dt).or_default();
            for (rule, counts) in rules {
                let rc = entry.entry(rule).or_default();
                rc.errors += counts.errors;
                rc.warnings += counts.warnings;
                rc.info += counts.info;
            }
        }
        for (dt, count) in other.total_records {
            *self.total_records.entry(dt).or_default() += count;
        }
    }

    pub fn has_violations(&self) -> bool {
        self.counts.values().any(|rules| {
            rules.values().any(|c| c.errors > 0 || c.warnings > 0 || c.info > 0)
        })
    }

    pub fn format_summary(&self, version: &str) -> String {
        if !self.has_violations() {
            return format!("📊 Data Quality Report for discogs_{}: No data quality violations found.\n", version);
        }

        let mut output = format!("📊 Data Quality Report for discogs_{}:\n", version);

        for dt in &["releases", "artists", "labels", "masters"] {
            let total = self.total_records.get(*dt).copied().unwrap_or(0);
            if let Some(rules) = self.counts.get(*dt) {
                let total_errors: u64 = rules.values().map(|c| c.errors).sum();
                let total_warnings: u64 = rules.values().map(|c| c.warnings).sum();
                output.push_str(&format!(
                    "  {}: {} errors, {} warnings (of {} records)\n",
                    dt, total_errors, total_warnings, total
                ));
                for (rule_name, counts) in rules {
                    let mut parts = Vec::new();
                    if counts.errors > 0 {
                        parts.push(format!("{} errors", counts.errors));
                    }
                    if counts.warnings > 0 {
                        parts.push(format!("{} warnings", counts.warnings));
                    }
                    if counts.info > 0 {
                        parts.push(format!("{} info", counts.info));
                    }
                    output.push_str(&format!("    {}: {}\n", rule_name, parts.join(", ")));
                }
            } else if total > 0 {
                output.push_str(&format!("  {}: 0 errors, 0 warnings (of {} records)\n", dt, total));
            }
        }

        output
    }
}

// ── Flagged Record Writer ───────────────────────────────────────────

use std::collections::HashSet as FlaggedSet;
use std::fs;
use std::io::BufWriter;
use std::path::PathBuf;

pub struct FlaggedRecordWriter {
    base_dir: PathBuf,
    written_records: FlaggedSet<String>,  // track record IDs already written
    jsonl_writers: HashMap<String, BufWriter<std::fs::File>>,
}

impl FlaggedRecordWriter {
    pub fn new(discogs_root: &Path, version: &str) -> Self {
        Self {
            base_dir: discogs_root.join("flagged").join(version),
            written_records: FlaggedSet::new(),
            jsonl_writers: HashMap::new(),
        }
    }

    /// Write a flagged record's XML and JSON files (once per record),
    /// and append violation to the JSONL log.
    /// For info severity, only the JSONL entry is written (no XML/JSON files).
    pub fn write_violation(
        &mut self,
        data_type: &str,
        record_id: &str,
        violation: &Violation,
        raw_xml: Option<&[u8]>,
        parsed_json: &Value,
        capture_files: bool,
    ) {
        let type_dir = self.base_dir.join(data_type);

        // Create directory lazily
        if let Err(e) = fs::create_dir_all(&type_dir) {
            tracing::warn!("⚠️ Failed to create flagged directory {:?}: {}", type_dir, e);
            return;
        }

        // Write XML and JSON files (once per record, only for error/warning severity)
        if capture_files {
            let record_key = format!("{}:{}", data_type, record_id);
            if !self.written_records.contains(&record_key) {
                if let Some(xml_bytes) = raw_xml {
                    let xml_path = type_dir.join(format!("{}.xml", record_id));
                    if let Err(e) = fs::write(&xml_path, xml_bytes) {
                        tracing::warn!("⚠️ Failed to write flagged XML {:?}: {}", xml_path, e);
                    }
                }

                let json_path = type_dir.join(format!("{}.json", record_id));
                if let Err(e) = fs::write(&json_path, serde_json::to_string_pretty(parsed_json).unwrap_or_default()) {
                    tracing::warn!("⚠️ Failed to write flagged JSON {:?}: {}", json_path, e);
                }

                self.written_records.insert(record_key);
            }
        }

        // Append to violations.jsonl
        let writer = self.jsonl_writers.entry(data_type.to_string()).or_insert_with(|| {
            let jsonl_path = type_dir.join("violations.jsonl");
            let file = fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&jsonl_path)
                .unwrap_or_else(|e| {
                    tracing::warn!("⚠️ Failed to open violations.jsonl {:?}: {}", jsonl_path, e);
                    // Fall back to a temp file to avoid crashing (cross-platform)
                    tempfile::tempfile().expect("Failed to create fallback temp file")
                });
            BufWriter::new(file)
        });

        let xml_file = format!("{}.xml", record_id);
        let json_file = format!("{}.json", record_id);
        let entry = serde_json::json!({
            "record_id": record_id,
            "rule": violation.rule_name,
            "severity": violation.severity.to_string(),
            "field": violation.field,
            "field_value": violation.field_value,
            "xml_file": xml_file,
            "json_file": json_file,
            "timestamp": chrono::Utc::now().to_rfc3339(),
        });

        if let Err(e) = writeln!(writer, "{}", serde_json::to_string(&entry).unwrap_or_default()) {
            tracing::warn!("⚠️ Failed to write violation entry: {}", e);
        }
    }

    /// Flush all JSONL writers.
    pub fn flush(&mut self) {
        for writer in self.jsonl_writers.values_mut() {
            let _ = writer.flush();
        }
    }

    /// Write the summary report to disk.
    pub fn write_report(&self, report: &QualityReport, version: &str) {
        if let Err(e) = fs::create_dir_all(&self.base_dir) {
            tracing::warn!("⚠️ Failed to create flagged directory: {}", e);
            return;
        }
        let report_path = self.base_dir.join("report.txt");
        if let Err(e) = fs::write(&report_path, report.format_summary(version)) {
            tracing::warn!("⚠️ Failed to write quality report: {}", e);
        }
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test rules_tests -- --nocapture 2>&1 | tail -30`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat: add quality report accumulator and flagged record writer"
```

______________________________________________________________________

### Task 6: Add raw XML reconstruction to the parser

**Files:**

- Modify: `extractor/src/parser.rs:101-109` (add `capture_raw_xml` flag)

- Modify: `extractor/src/parser.rs:190-227` (reconstruct XML on record completion)

- [ ] **Step 1: Write a test for raw XML capture**

Append to `extractor/src/tests/parser_tests.rs` (find the existing test module):

```rust
#[tokio::test]
async fn test_raw_xml_capture() {
    let xml = create_gzipped_xml(
        "artists",
        r#"<artist><name>Test Artist</name></artist>"#,
    );
    let (sender, mut receiver) = mpsc::channel(100);
    let parser = XmlParser::with_options(DataType::Artists, sender, true);

    let temp_file = write_temp_gz(&xml);
    let count = parser.parse_file(temp_file.path()).await.unwrap();

    assert_eq!(count, 1);
    let msg = receiver.recv().await.unwrap();
    assert!(msg.raw_xml.is_some(), "raw_xml should be populated when capture is enabled");
    let xml_str = String::from_utf8_lossy(msg.raw_xml.as_ref().unwrap());
    assert!(xml_str.contains("Test Artist"), "reconstructed XML should contain the artist name");
    assert!(xml_str.contains("artist"), "reconstructed XML should contain the element name");
}

#[tokio::test]
async fn test_raw_xml_not_captured_by_default() {
    let xml = create_gzipped_xml(
        "artists",
        r#"<artist><name>Test Artist</name></artist>"#,
    );
    let (sender, mut receiver) = mpsc::channel(100);
    let parser = XmlParser::new(DataType::Artists, sender);

    let temp_file = write_temp_gz(&xml);
    let count = parser.parse_file(temp_file.path()).await.unwrap();

    assert_eq!(count, 1);
    let msg = receiver.recv().await.unwrap();
    assert!(msg.raw_xml.is_none(), "raw_xml should be None when capture is disabled");
}
```

Note: The test helpers `create_gzipped_xml` and `write_temp_gz` should already exist in the parser tests — check and reuse them. If not, create minimal helpers.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test test_raw_xml -- 2>&1 | tail -10`
Expected: FAIL — `with_options` method not found

- [ ] **Step 3: Implement raw XML capture in the parser**

In `extractor/src/parser.rs`, modify the `XmlParser` struct and `impl` block:

```rust
pub struct XmlParser {
    data_type: DataType,
    sender: mpsc::Sender<DataMessage>,
    capture_raw_xml: bool,
}

impl XmlParser {
    pub fn new(data_type: DataType, sender: mpsc::Sender<DataMessage>) -> Self {
        Self { data_type, sender, capture_raw_xml: false }
    }

    pub fn with_options(data_type: DataType, sender: mpsc::Sender<DataMessage>, capture_raw_xml: bool) -> Self {
        Self { data_type, sender, capture_raw_xml }
    }
    // ... rest of impl
```

Then in `parse_file`, add XML reconstruction at the two points where `DataMessage` is constructed.

For the normal record completion (inside `Event::End` when `name == target_element && depth == 2`), before constructing the `DataMessage`, add:

```rust
let raw_xml = if self.capture_raw_xml {
    Some(reconstruct_xml(target_element, &final_value))
} else {
    None
};
let message = DataMessage { id: id.clone(), sha256, data: final_value, raw_xml };
```

For the self-closing element case (inside `Event::Empty`), similarly:

```rust
let raw_xml = if self.capture_raw_xml {
    Some(reconstruct_xml(target_element, &record))
} else {
    None
};
let message = DataMessage { id, sha256, data: record.clone(), raw_xml };
```

Add the `reconstruct_xml` helper function at the bottom of the file:

```rust
/// Reconstruct an XML fragment from a parsed JSON Value using quick-xml::Writer.
fn reconstruct_xml(element_name: &str, value: &Value) -> Vec<u8> {
    use quick_xml::Writer;
    use quick_xml::events::{BytesEnd, BytesStart, BytesText};
    use std::io::Cursor;

    let mut writer = Writer::new(Cursor::new(Vec::new()));
    write_element(&mut writer, element_name, value);
    writer.into_inner().into_inner()
}

fn write_element<W: std::io::Write>(writer: &mut quick_xml::Writer<W>, name: &str, value: &Value) {
    use quick_xml::events::{BytesEnd, BytesStart, BytesText};

    match value {
        Value::Object(map) => {
            let mut start = BytesStart::new(name);
            // Add attributes (keys starting with @)
            for (key, val) in map {
                if let Some(attr_name) = key.strip_prefix('@') {
                    if let Value::String(s) = val {
                        start.push_attribute((attr_name, s.as_str()));
                    }
                }
            }
            writer.write_event(quick_xml::events::Event::Start(start)).unwrap();

            // Write #text if present
            if let Some(Value::String(text)) = map.get("#text") {
                writer
                    .write_event(quick_xml::events::Event::Text(BytesText::new(text)))
                    .unwrap();
            }

            // Write child elements (non-@ keys, non-#text)
            // Skip synthetic "id" only when it duplicates the @id attribute
            let has_at_id = map.contains_key("@id");
            for (key, val) in map {
                if key.starts_with('@') || key == "#text" {
                    continue;
                }
                if key == "id" && has_at_id {
                    // Skip synthetic id that duplicates @id (added by parser for releases/masters)
                    continue;
                }
                match val {
                    Value::Array(arr) => {
                        for item in arr {
                            write_element(writer, key, item);
                        }
                    }
                    _ => write_element(writer, key, val),
                }
            }

            writer
                .write_event(quick_xml::events::Event::End(BytesEnd::new(name)))
                .unwrap();
        }
        Value::String(s) => {
            writer
                .write_event(quick_xml::events::Event::Start(BytesStart::new(name)))
                .unwrap();
            writer
                .write_event(quick_xml::events::Event::Text(BytesText::new(s)))
                .unwrap();
            writer
                .write_event(quick_xml::events::Event::End(BytesEnd::new(name)))
                .unwrap();
        }
        Value::Number(n) => {
            let s = n.to_string();
            writer
                .write_event(quick_xml::events::Event::Start(BytesStart::new(name)))
                .unwrap();
            writer
                .write_event(quick_xml::events::Event::Text(BytesText::new(&s)))
                .unwrap();
            writer
                .write_event(quick_xml::events::Event::End(BytesEnd::new(name)))
                .unwrap();
        }
        Value::Null => {
            writer
                .write_event(quick_xml::events::Event::Empty(BytesStart::new(name)))
                .unwrap();
        }
        _ => {}
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test test_raw_xml -- --nocapture 2>&1 | tail -20`
Expected: both raw XML tests pass

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test parser_tests -- 2>&1 | tail -10`
Expected: all parser tests still pass

- [ ] **Step 5: Commit**

```bash
git add extractor/src/parser.rs extractor/src/tests/parser_tests.rs
git commit -m "feat: add raw XML reconstruction to parser for data quality inspection"
```

______________________________________________________________________

### Task 7: Add configuration and CLI arg for rules file

**Files:**

- Modify: `extractor/src/config.rs:5-16,53-74`

- Modify: `extractor/src/main.rs:20-27,29-58`

- [ ] **Step 1: Add `data_quality_rules` field to `ExtractorConfig`**

In `extractor/src/config.rs`, add the field to the struct:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractorConfig {
    pub amqp_connection: String,
    pub discogs_root: PathBuf,
    pub periodic_check_days: u64,
    pub health_port: u16,
    pub max_workers: usize,
    pub batch_size: usize,
    pub queue_size: usize,
    pub progress_log_interval: usize,
    pub state_save_interval: usize,
    pub data_quality_rules: Option<PathBuf>,
}
```

Update `Default`:

```rust
impl Default for ExtractorConfig {
    fn default() -> Self {
        Self {
            // ... existing fields ...
            data_quality_rules: None,
        }
    }
}
```

Update `from_env()`:

```rust
let data_quality_rules = std::env::var("DATA_QUALITY_RULES").ok().map(PathBuf::from);

Ok(Self { amqp_connection, discogs_root, periodic_check_days, max_workers, batch_size, data_quality_rules, ..Default::default() })
```

- [ ] **Step 2: Add CLI arg to Args struct in main.rs**

In `extractor/src/main.rs`, add to the `Args` struct:

```rust
struct Args {
    #[clap(short, long, env = "FORCE_REPROCESS", value_parser = clap::builder::BoolishValueParser::new(), default_value_t = false)]
    force_reprocess: bool,

    /// Path to data quality rules YAML file
    #[clap(long, env = "DATA_QUALITY_RULES")]
    data_quality_rules: Option<std::path::PathBuf>,
}
```

- [ ] **Step 3: Load and compile rules in main.rs startup**

In `main()`, after loading the config and before initializing shared state, add:

```rust
// Override config with CLI arg if provided
let mut config = match ExtractorConfig::from_env() {
    Ok(c) => c,
    Err(e) => {
        error!("❌ Configuration error: {}", e);
        std::process::exit(1);
    }
};

// CLI arg takes precedence over env var
if args.data_quality_rules.is_some() {
    config.data_quality_rules = args.data_quality_rules;
}

// Load and compile data quality rules if configured
let compiled_rules = if let Some(ref rules_path) = config.data_quality_rules {
    info!("📋 Loading data quality rules from {:?}", rules_path);
    match rules::RulesConfig::load(rules_path) {
        Ok(rules_config) => match rules::CompiledRulesConfig::compile(rules_config) {
            Ok(compiled) => {
                info!("✅ Data quality rules loaded and compiled successfully");
                Some(Arc::new(compiled))
            }
            Err(e) => {
                error!("❌ Failed to compile data quality rules: {}", e);
                std::process::exit(1);
            }
        },
        Err(e) => {
            error!("❌ Failed to load data quality rules: {}", e);
            std::process::exit(1);
        }
    }
} else {
    None
};

let config = Arc::new(config);
```

Then pass `compiled_rules` to the extraction loop (this will be wired in Task 8).

- [ ] **Step 4: Verify compilation**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo check 2>&1 | tail -5`
Expected: compiles (with possible unused variable warnings for `compiled_rules`)

- [ ] **Step 5: Commit**

```bash
git add extractor/src/config.rs extractor/src/main.rs
git commit -m "feat: add data_quality_rules config field and CLI arg"
```

______________________________________________________________________

### Task 8: Wire the validator pipeline stage

**Files:**

- Modify: `extractor/src/extractor.rs:277-367` (add validator stage to `process_single_file`)

- Modify: `extractor/src/extractor.rs:548-604` (pass rules through `run_extraction_loop`)

- Modify: `extractor/src/main.rs:75-79` (pass compiled_rules to extraction loop)

- [ ] **Step 1: Add `compiled_rules` parameter through the call chain**

Update function signatures in `extractor/src/extractor.rs`:

`run_extraction_loop` — add `compiled_rules: Option<Arc<CompiledRulesConfig>>` parameter:

```rust
pub async fn run_extraction_loop(
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    shutdown: Arc<tokio::sync::Notify>,
    force_reprocess: bool,
    mq_factory: Arc<dyn MessageQueueFactory>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<()> {
```

`process_discogs_data` — add the same parameter and pass it through to `process_single_file`.

`process_single_file` — add the parameter:

```rust
pub async fn process_single_file(
    file_name: &str,
    config: Arc<ExtractorConfig>,
    state: Arc<RwLock<ExtractorState>>,
    state_marker: Arc<tokio::sync::Mutex<StateMarker>>,
    marker_path: PathBuf,
    mq: Arc<dyn MessagePublisher>,
    compiled_rules: Option<Arc<CompiledRulesConfig>>,
) -> Result<()> {
```

Update `main.rs` to pass `compiled_rules` to `run_extraction_loop`.

- [ ] **Step 2: Wire the validator stage in `process_single_file`**

Replace the channel setup and task spawning (lines 307-337) with:

```rust
    let has_rules = compiled_rules.is_some();

    // Create channels for processing pipeline
    let (parse_sender, parse_receiver) = mpsc::channel::<DataMessage>(config.queue_size);
    let (batch_sender, batch_receiver) = mpsc::channel::<Vec<DataMessage>>(100);

    // Start parser (with raw XML capture if rules are active)
    let parser_handle = tokio::spawn({
        let file_path = config.discogs_root.join(file_name);
        async move {
            let parser = if has_rules {
                XmlParser::with_options(data_type, parse_sender, true)
            } else {
                XmlParser::new(data_type, parse_sender)
            };
            parser.parse_file(&file_path).await
        }
    });

    // If rules are configured, insert validator stage between parser and batcher
    let (validated_receiver, validator_handle) = if let Some(ref rules) = compiled_rules {
        let (validated_sender, validated_receiver) = mpsc::channel::<DataMessage>(config.queue_size);
        let rules = rules.clone();
        let discogs_root = config.discogs_root.clone();
        let version = extract_version_from_filename(
            Path::new(file_name).file_name().and_then(|n| n.to_str()).unwrap_or("")
        ).unwrap_or_default();
        let dt_str = data_type.as_str().to_string();

        let handle = tokio::spawn(async move {
            message_validator(
                parse_receiver,
                validated_sender,
                rules,
                &dt_str,
                &discogs_root,
                &version,
            ).await
        });
        (validated_receiver, Some(handle))
    } else {
        (parse_receiver, None)
    };

    let batcher_handle = tokio::spawn({
        let batcher_config = BatcherConfig {
            batch_size: config.batch_size,
            data_type,
            state: state.clone(),
            state_marker: state_marker.clone(),
            marker_path: marker_path.clone(),
            file_name: file_name.to_string(),
            state_save_interval: config.state_save_interval,
        };
        async move { message_batcher(validated_receiver, batch_sender, batcher_config).await }
    });

    let publisher_handle = tokio::spawn({
        let mq = mq.clone();
        let state = state.clone();
        async move { message_publisher(batch_receiver, mq, data_type, state).await }
    });

    // Wait for all workers to complete
    let total_count = parser_handle.await??;
    if let Some(handle) = validator_handle {
        let report = handle.await??;
        // Log quality report if there were violations
        if report.has_violations() {
            info!("{}", report.format_summary(
                &extract_version_from_filename(
                    Path::new(file_name).file_name().and_then(|n| n.to_str()).unwrap_or("")
                ).unwrap_or_default()
            ));
        }
    }
    batcher_handle.await??;
    publisher_handle.await??;
```

- [ ] **Step 3: Implement the `message_validator` function**

Add to `extractor/src/extractor.rs`:

```rust
use crate::rules::{CompiledRulesConfig, FlaggedRecordWriter, QualityReport, Severity, evaluate_rules};

/// Validate messages against data quality rules.
/// All messages are forwarded downstream regardless of violations.
async fn message_validator(
    mut receiver: mpsc::Receiver<DataMessage>,
    sender: mpsc::Sender<DataMessage>,
    rules: Arc<CompiledRulesConfig>,
    data_type: &str,
    discogs_root: &Path,
    version: &str,
) -> Result<QualityReport> {
    let mut report = QualityReport::new();
    let mut writer = FlaggedRecordWriter::new(discogs_root, version);

    while let Some(message) = receiver.recv().await {
        report.increment_total(data_type);

        let violations = evaluate_rules(&rules, data_type, &message.data);

        for violation in &violations {
            report.record_violation(data_type, &violation.rule_name, &violation.severity);

            let capture_files = matches!(violation.severity, Severity::Error | Severity::Warning);
            writer.write_violation(
                data_type,
                &message.id,
                violation,
                message.raw_xml.as_deref(),
                &message.data,
                capture_files,
            );
        }

        // Always forward the message downstream
        if sender.send(message).await.is_err() {
            warn!("⚠️ Validator: downstream receiver dropped");
            break;
        }
    }

    writer.flush();
    writer.write_report(&report, version);

    Ok(report)
}
```

- [ ] **Step 4: Update all call sites that invoke `process_single_file` and `process_discogs_data`**

The spawned tasks in `process_discogs_data` that call `process_single_file` need the `compiled_rules` parameter cloned into each task.

Also update `extractor/tests/extractor_di_test.rs` — all calls to `process_single_file` and `process_discogs_data` need the new `compiled_rules` parameter. Pass `None` for all existing test calls since they don't use rules:

```rust
// In each test that calls process_single_file, add None as the last arg:
process_single_file(&file, config, state, state_marker, marker_path, mq, None).await?;

// In each test that calls process_discogs_data, add None as the last arg:
process_discogs_data(config, state, shutdown, false, &mut downloader, mq_factory, None).await?;

// In each test that calls run_extraction_loop, add None as the last arg:
run_extraction_loop(config, state, shutdown, false, mq_factory, None).await?;
```

- [ ] **Step 5: Verify compilation and all existing tests pass**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test 2>&1 | tail -20`
Expected: all tests pass (existing tests pass `None` for `compiled_rules`)

- [ ] **Step 6: Commit**

```bash
git add extractor/src/extractor.rs extractor/src/main.rs
git commit -m "feat: wire validator pipeline stage between parser and batcher"
```

______________________________________________________________________

### Task 9: Create default extraction-rules.yaml

**Files:**

- Create: `extractor/extraction-rules.yaml`

- [ ] **Step 1: Create the default rules file**

Create `extractor/extraction-rules.yaml` with the rules from issue #182:

```yaml
# Data Quality Rules for Discogs Extraction
# Configure via: DATA_QUALITY_RULES env var or --data-quality-rules CLI arg
#
# NOTE: The 'max' value in year-range rules is static and should be updated
# periodically (e.g., bump to current_year + 1 at the start of each year).

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

    - name: missing-title
      description: "Release has no title"
      field: title
      condition:
        type: required
      severity: error

    - name: genre-not-recognized
      description: "Genre value is not in the known Discogs genre list"
      field: genres.genre
      condition:
        type: enum
        values:
          - Blues
          - Brass & Military
          - "Children's"
          - Classical
          - Electronic
          - "Folk, World, & Country"
          - Funk / Soul
          - Hip Hop
          - Jazz
          - Latin
          - Non-Music
          - Pop
          - Reggae
          - Rock
          - Stage & Screen
      severity: warning

    - name: genre-is-numeric
      description: "Genre value is purely numeric — likely a parsing error"
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error

    # Note: years like 197 and 338 are already caught by year-out-of-range (< min 1860).
    # No separate "suspicious year" rule is needed.

  artists:
    - name: suspicious-name
      description: "Artist name is purely numeric or single character"
      field: name
      condition:
        type: regex
        pattern: "^\\d+$|^.$"
      severity: warning

  labels:
    - name: empty-label-name
      description: "Label has no name"
      field: name
      condition:
        type: required
      severity: error

  masters:
    - name: year-out-of-range
      description: "Master year is before 1860 or after current year + 1"
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
```

- [ ] **Step 2: Test that the YAML loads and compiles**

```bash
cd /Users/Robert/Code/public/discogsography/extractor && cargo test -- --ignored test_default_rules_file 2>&1 | tail -10
```

If no such test exists, add a quick one to `rules_tests.rs`:

```rust
#[test]
fn test_default_rules_file() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("extraction-rules.yaml");
    if path.exists() {
        let config = RulesConfig::load(&path).unwrap();
        let compiled = CompiledRulesConfig::compile(config).unwrap();
        assert!(!compiled.rules_for("releases").is_empty());
        assert!(!compiled.rules_for("artists").is_empty());
        assert!(!compiled.rules_for("labels").is_empty());
        assert!(!compiled.rules_for("masters").is_empty());
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add extractor/extraction-rules.yaml extractor/src/tests/rules_tests.rs
git commit -m "feat: add default extraction-rules.yaml with rules from issue #182"
```

______________________________________________________________________

### Task 10: Integration test — full pipeline with rules active

**Files:**

- Create: `extractor/tests/rules_integration_test.rs`

- [ ] **Step 1: Write integration test**

Create `extractor/tests/rules_integration_test.rs`:

```rust
//! Integration tests for data quality rules in the extraction pipeline.
//!
//! Tests the full flow: XML parsing → validation → flagged record storage.

use extractor::rules::{CompiledRulesConfig, RulesConfig, evaluate_rules};
use extractor::parser::XmlParser;
use extractor::types::{DataMessage, DataType};
use serde_json::json;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::mpsc;

/// Helper: compile rules from inline YAML
fn compile_rules(yaml: &str) -> Arc<CompiledRulesConfig> {
    let config: RulesConfig = serde_yml::from_str(yaml).unwrap();
    Arc::new(CompiledRulesConfig::compile(config).unwrap())
}

#[test]
fn test_issue_182_bad_data_detected() {
    // These are the exact bad data examples from issue #182
    let rules = compile_rules(r#"
rules:
  releases:
    - name: genre-is-numeric
      field: genres.genre
      condition:
        type: regex
        pattern: "^\\d+$"
      severity: error
    - name: genre-not-recognized
      field: genres.genre
      condition:
        type: enum
        values: [Blues, "Brass & Military", "Children's", Classical, Electronic, "Folk, World, & Country", "Funk / Soul", "Hip Hop", Jazz, Latin, Non-Music, Pop, Reggae, Rock, "Stage & Screen"]
      severity: warning
    - name: year-out-of-range
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
"#);

    // Genre "1" — should trigger genre-is-numeric and genre-not-recognized
    let record = json!({"@id": "12345", "genres": {"genre": "1"}, "year": "1990"});
    let violations = evaluate_rules(&rules, "releases", &record);
    let rule_names: Vec<&str> = violations.iter().map(|v| v.rule_name.as_str()).collect();
    assert!(rule_names.contains(&"genre-is-numeric"), "Should catch numeric genre");
    assert!(rule_names.contains(&"genre-not-recognized"), "Should catch unrecognized genre");

    // Year 197 — should trigger year-out-of-range
    let record = json!({"@id": "67890", "genres": {"genre": "Jazz"}, "year": "197"});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert!(violations.iter().any(|v| v.rule_name == "year-out-of-range"),
        "Should catch year 197 as out of range (< 1860)");

    // Year 338 — should trigger year-out-of-range
    let record = json!({"@id": "11111", "genres": {"genre": "Electronic"}, "year": "338"});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert!(violations.iter().any(|v| v.rule_name == "year-out-of-range"),
        "Should catch year 338 as out of range (< 1860)");

    // Clean record — no violations
    let record = json!({"@id": "99999", "genres": {"genre": "Rock"}, "year": "1995"});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert!(violations.is_empty(), "Clean record should have no violations");
}

#[test]
fn test_flagged_record_storage() {
    use extractor::rules::{FlaggedRecordWriter, Severity, Violation};

    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let violation = Violation {
        rule_name: "genre-is-numeric".to_string(),
        severity: Severity::Error,
        field: "genres.genre".to_string(),
        field_value: "1".to_string(),
    };

    let parsed_json = json!({"@id": "12345", "genres": {"genre": "1"}});
    let raw_xml = b"<release id=\"12345\"><genres><genre>1</genre></genres></release>";

    writer.write_violation("releases", "12345", &violation, Some(raw_xml), &parsed_json, true);
    writer.flush();

    // Verify files were created
    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("releases");
    assert!(flagged_dir.join("12345.xml").exists(), "XML file should exist");
    assert!(flagged_dir.join("12345.json").exists(), "JSON file should exist");
    assert!(flagged_dir.join("violations.jsonl").exists(), "JSONL file should exist");

    // Verify JSONL content
    let jsonl = std::fs::read_to_string(flagged_dir.join("violations.jsonl")).unwrap();
    assert!(jsonl.contains("genre-is-numeric"));
    assert!(jsonl.contains("12345"));

    // Verify duplicate writes don't create duplicate files
    let violation2 = Violation {
        rule_name: "genre-not-recognized".to_string(),
        severity: Severity::Warning,
        field: "genres.genre".to_string(),
        field_value: "1".to_string(),
    };
    writer.write_violation("releases", "12345", &violation2, Some(raw_xml), &parsed_json, true);
    writer.flush();

    // Should have 2 lines in JSONL but still only 1 XML/JSON file pair
    let jsonl = std::fs::read_to_string(flagged_dir.join("violations.jsonl")).unwrap();
    let lines: Vec<&str> = jsonl.trim().lines().collect();
    assert_eq!(lines.len(), 2, "Should have 2 violation entries");
}

#[test]
fn test_pipeline_without_rules_unchanged() {
    // Verify that when no rules are configured, DataMessage has raw_xml: None
    let message = DataMessage {
        id: "1".to_string(),
        sha256: "abc".to_string(),
        data: json!({"name": "test"}),
        raw_xml: None,
    };

    // Serialize to verify raw_xml is not included
    let serialized = serde_json::to_string(&message).unwrap();
    assert!(!serialized.contains("raw_xml"), "raw_xml should not appear in serialized output");
}
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test --test rules_integration_test -- --nocapture 2>&1 | tail -20`
Expected: all tests pass

- [ ] **Step 3: Run the full test suite**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test 2>&1 | tail -20`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add extractor/tests/rules_integration_test.rs
git commit -m "test: add integration tests for data quality rules pipeline"
```

______________________________________________________________________

### Task 11: Final verification and cleanup

**Files:**

- All modified files

- [ ] **Step 1: Run clippy**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo clippy -- -D warnings 2>&1 | tail -20`
Expected: no warnings or errors

- [ ] **Step 2: Run cargo fmt**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo fmt --check 2>&1 | tail -10`
Expected: no formatting issues (or run `cargo fmt` to fix)

- [ ] **Step 3: Run full test suite one more time**

Run: `cd /Users/Robert/Code/public/discogsography/extractor && cargo test 2>&1 | tail -20`
Expected: all tests pass

- [ ] **Step 4: Verify zero-overhead when rules not configured**

Check that the parser's `capture_raw_xml` defaults to `false` and the validator stage is skipped:

```bash
cd /Users/Robert/Code/public/discogsography/extractor && grep -n "capture_raw_xml: false" src/parser.rs
cd /Users/Robert/Code/public/discogsography/extractor && grep -n "compiled_rules.is_some\|has_rules" src/extractor.rs
```

Expected: confirm the default path avoids any overhead

- [ ] **Step 5: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final cleanup for data quality rules feature"
```
