# Extraction Rules: Skip Records & Filter Transforms — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Rust extraction rules engine with `skip_records` and `filters` YAML config sections so known-bad upstream records are skipped and numeric genre artifacts are stripped before validation and publishing.

**Architecture:** Two new pipeline stages (`should_skip_record` → `apply_filters`) are inserted into `message_validator` before the existing `evaluate_rules` call. New YAML sections are deserialized alongside existing `rules`, compiled at startup (substring lowercased, regex pre-compiled), and stored in `CompiledRulesConfig`. The quality report gains a skipped-records section. A new API endpoint and admin UI card surface skipped records.

**Tech Stack:** Rust (serde, regex, serde_json, serde_yaml_ng), Python (FastAPI, httpx), vanilla JS (admin dashboard)

---

## Task 1: YAML Schema — Deserialization Types & Compilation

**Files:**
- Modify: `extractor/src/rules.rs:18-21` (RulesConfig) and `extractor/src/rules.rs:62-65` (CompiledRulesConfig)
- Test: `extractor/src/tests/rules_tests.rs`

- [ ] **Step 1: Write failing tests for skip_records and filters YAML parsing**

Add to `extractor/src/tests/rules_tests.rs`:

```rust
#[test]
fn test_yaml_with_skip_records_and_filters() {
    let yaml = r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"
  labels:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"

filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric genre IDs"
  masters:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric genre IDs"

rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#;
    let config = compile_yaml(yaml);
    let rules = config.rules_for("artists");
    assert_eq!(rules.len(), 1);
    let skips = config.skip_conditions_for("artists");
    assert_eq!(skips.len(), 1);
    assert_eq!(skips[0].field, "profile");
    assert_eq!(skips[0].reason, "Upstream junk entry");
    let filters = config.filters_for("releases");
    assert_eq!(filters.len(), 1);
    assert_eq!(filters[0].field, "genres.genre");
    assert_eq!(filters[0].reason, "Strip numeric genre IDs");
}

#[test]
fn test_yaml_without_skip_records_and_filters() {
    // Existing configs without the new sections still work
    let yaml = r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#;
    let config = compile_yaml(yaml);
    assert_eq!(config.skip_conditions_for("artists").len(), 0);
    assert_eq!(config.filters_for("releases").len(), 0);
}

#[test]
fn test_invalid_filter_regex_returns_error() {
    let yaml = r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "[invalid("
      reason: "Bad regex"
rules: {}
"#;
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("invalid("), "Expected regex pattern in error: {msg}");
}

#[test]
fn test_skip_records_validates_data_type() {
    let yaml = r#"
skip_records:
  foobar:
    - field: profile
      contains: "test"
      reason: "test"
rules: {}
"#;
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("foobar"), "Expected unknown type name in error: {msg}");
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_yaml_with_skip_records -- --nocapture 2>&1 | tail -5`
Expected: Compilation errors — `skip_conditions_for` and `filters_for` don't exist yet.

- [ ] **Step 3: Add YAML deserialization types and compiled types**

In `extractor/src/rules.rs`, add new deserialization structs after the existing `RuleCondition` enum (after line 58):

```rust
#[derive(Debug, Deserialize)]
pub struct SkipCondition {
    pub field: String,
    pub contains: String,
    pub reason: String,
}

#[derive(Debug, Deserialize)]
pub struct FilterCondition {
    pub field: String,
    pub remove_matching: String,
    pub reason: String,
}
```

Update `RulesConfig` (line 18-21) to include optional new sections:

```rust
#[derive(Debug, Deserialize)]
pub struct RulesConfig {
    #[serde(default)]
    pub skip_records: HashMap<String, Vec<SkipCondition>>,
    #[serde(default)]
    pub filters: HashMap<String, Vec<FilterCondition>>,
    #[serde(default)]
    pub rules: HashMap<String, Vec<Rule>>,
}
```

Add compiled types after `CompiledCondition` (after line 83):

```rust
#[derive(Debug)]
pub struct CompiledSkipCondition {
    pub field: String,
    pub contains_lower: String,
    pub reason: String,
}

#[derive(Debug)]
pub struct CompiledFilterCondition {
    pub field: String,
    pub remove_matching: Regex,
    pub reason: String,
}
```

Update `CompiledRulesConfig` (line 62-65):

```rust
#[derive(Debug)]
pub struct CompiledRulesConfig {
    rules: HashMap<String, Vec<CompiledRule>>,
    skip_records: HashMap<String, Vec<CompiledSkipCondition>>,
    filters: HashMap<String, Vec<CompiledFilterCondition>>,
}
```

- [ ] **Step 4: Update `compile()` to handle new sections and add accessor methods**

In the `CompiledRulesConfig::compile` method (line 104-131), add compilation of skip_records and filters before the final `Ok(Self { ... })`:

```rust
impl CompiledRulesConfig {
    pub fn compile(config: RulesConfig) -> Result<Self> {
        // Existing rules compilation (unchanged)
        let mut compiled = HashMap::new();
        for (key, rules) in config.rules {
            key.parse::<DataType>().map_err(|_| anyhow::anyhow!("Unknown data type in rules config: '{}'", key))?;
            let mut compiled_rules = Vec::with_capacity(rules.len());
            for rule in rules {
                let condition = match rule.condition {
                    RuleCondition::Range { min, max } => CompiledCondition::Range { min, max },
                    RuleCondition::Required => CompiledCondition::Required,
                    RuleCondition::Regex { pattern } => {
                        let regex = Regex::new(&pattern).with_context(|| format!("Invalid regex in rule '{}': {}", rule.name, pattern))?;
                        CompiledCondition::Regex { regex }
                    }
                    RuleCondition::Length { min, max } => CompiledCondition::Length { min, max },
                    RuleCondition::Enum { values } => CompiledCondition::Enum { values: values.into_iter().collect() },
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

        // Compile skip_records
        let mut compiled_skips = HashMap::new();
        for (key, conditions) in config.skip_records {
            key.parse::<DataType>().map_err(|_| anyhow::anyhow!("Unknown data type in skip_records config: '{}'", key))?;
            let compiled_conditions: Vec<CompiledSkipCondition> = conditions
                .into_iter()
                .map(|c| CompiledSkipCondition {
                    field: c.field,
                    contains_lower: c.contains.to_lowercase(),
                    reason: c.reason,
                })
                .collect();
            compiled_skips.insert(key, compiled_conditions);
        }

        // Compile filters
        let mut compiled_filters = HashMap::new();
        for (key, conditions) in config.filters {
            key.parse::<DataType>().map_err(|_| anyhow::anyhow!("Unknown data type in filters config: '{}'", key))?;
            let mut compiled_conditions = Vec::with_capacity(conditions.len());
            for condition in conditions {
                let regex = Regex::new(&condition.remove_matching)
                    .with_context(|| format!("Invalid regex in filter for field '{}': {}", condition.field, condition.remove_matching))?;
                compiled_conditions.push(CompiledFilterCondition {
                    field: condition.field,
                    remove_matching: regex,
                    reason: condition.reason,
                });
            }
            compiled_filters.insert(key, compiled_conditions);
        }

        Ok(Self {
            rules: compiled,
            skip_records: compiled_skips,
            filters: compiled_filters,
        })
    }

    pub fn rules_for(&self, data_type: &str) -> &[CompiledRule] {
        self.rules.get(data_type).map(|v| v.as_slice()).unwrap_or(&[])
    }

    pub fn skip_conditions_for(&self, data_type: &str) -> &[CompiledSkipCondition] {
        self.skip_records.get(data_type).map(|v| v.as_slice()).unwrap_or(&[])
    }

    pub fn filters_for(&self, data_type: &str) -> &[CompiledFilterCondition] {
        self.filters.get(data_type).map(|v| v.as_slice()).unwrap_or(&[])
    }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_yaml_with_skip_records test_yaml_without_skip_records test_invalid_filter_regex test_skip_records_validates -- --nocapture 2>&1 | tail -10`
Expected: All 4 tests pass.

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test 2>&1 | tail -5`
Expected: All existing tests still pass (the `rules` field is now `#[serde(default)]` so YAML with only `rules:` still works).

- [ ] **Step 7: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat(extractor): add skip_records and filters YAML schema to rules engine"
```

---

## Task 2: Skip Record Evaluation Logic

**Files:**
- Modify: `extractor/src/rules.rs` (add `should_skip_record` function)
- Test: `extractor/src/tests/rules_tests.rs`

- [ ] **Step 1: Write failing tests for should_skip_record**

Add to `extractor/src/tests/rules_tests.rs`:

```rust
use crate::rules::should_skip_record;

#[test]
fn test_skip_record_contains_match() {
    let config = compile_yaml(r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk"
rules: {}
"#);
    let record = json!({"profile": "[b]DO NOT USE.[/b] This is invalid."});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_some());
    let info = result.unwrap();
    assert_eq!(info.reason, "Upstream junk");
    assert_eq!(info.field, "profile");
    assert!(info.field_value.contains("DO NOT USE"));
}

#[test]
fn test_skip_record_case_insensitive() {
    let config = compile_yaml(r#"
skip_records:
  labels:
    - field: profile
      contains: "DO NOT USE"
      reason: "Junk"
rules: {}
"#);
    let record = json!({"profile": "please do not use this label"});
    let result = should_skip_record(&config, "labels", &record);
    assert!(result.is_some());
}

#[test]
fn test_skip_record_no_match() {
    let config = compile_yaml(r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Junk"
rules: {}
"#);
    let record = json!({"profile": "Legendary electronic artist from Detroit."});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_none());
}

#[test]
fn test_skip_record_missing_field() {
    let config = compile_yaml(r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Junk"
rules: {}
"#);
    let record = json!({"name": "Aphex Twin"});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_none());
}

#[test]
fn test_skip_record_no_conditions_for_data_type() {
    let config = compile_yaml(r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Junk"
rules: {}
"#);
    let record = json!({"profile": "DO NOT USE"});
    let result = should_skip_record(&config, "releases", &record);
    assert!(result.is_none());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_skip_record 2>&1 | tail -5`
Expected: Compilation error — `should_skip_record` doesn't exist yet.

- [ ] **Step 3: Implement should_skip_record**

Add to `extractor/src/rules.rs` in the Evaluation section (after `evaluate_rules`, around line 189):

```rust
#[derive(Debug, Clone)]
pub struct SkipInfo {
    pub reason: String,
    pub field: String,
    pub field_value: String,
}

/// Check if a record should be skipped based on skip_records conditions.
/// Returns Some(SkipInfo) on first matching condition, None if no match.
pub fn should_skip_record(config: &CompiledRulesConfig, data_type: &str, record: &Value) -> Option<SkipInfo> {
    let conditions = config.skip_conditions_for(data_type);
    for condition in conditions {
        let field_values = resolve_field(record, &condition.field);
        for val in &field_values {
            if val.to_lowercase().contains(&condition.contains_lower) {
                return Some(SkipInfo {
                    reason: condition.reason.clone(),
                    field: condition.field.clone(),
                    field_value: val.clone(),
                });
            }
        }
    }
    None
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_skip_record -- --nocapture 2>&1 | tail -10`
Expected: All 5 skip record tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat(extractor): add should_skip_record evaluation logic"
```

---

## Task 3: Filter Evaluation Logic

**Files:**
- Modify: `extractor/src/rules.rs` (add `apply_filters` function)
- Test: `extractor/src/tests/rules_tests.rs`

- [ ] **Step 1: Write failing tests for apply_filters**

Add to `extractor/src/tests/rules_tests.rs`:

```rust
use crate::rules::apply_filters;

#[test]
fn test_filter_removes_numeric_genres() {
    let config = compile_yaml(r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric genre IDs"
rules: {}
"#);
    let mut record = json!({"genres": {"genre": ["1", "1", "Electronic"]}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert_eq!(record["genres"]["genre"], json!(["Electronic"]));
    assert_eq!(actions.len(), 1);
    assert_eq!(actions[0].removed_count, 2);
    assert_eq!(actions[0].reason, "Strip numeric genre IDs");
}

#[test]
fn test_filter_preserves_non_matching() {
    let config = compile_yaml(r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric genre IDs"
rules: {}
"#);
    let mut record = json!({"genres": {"genre": ["Rock", "Pop"]}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert_eq!(record["genres"]["genre"], json!(["Rock", "Pop"]));
    assert!(actions.is_empty());
}

#[test]
fn test_filter_empty_after_removal() {
    let config = compile_yaml(r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric"
rules: {}
"#);
    let mut record = json!({"genres": {"genre": ["1", "2"]}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert_eq!(record["genres"]["genre"], json!([]));
    assert_eq!(actions.len(), 1);
    assert_eq!(actions[0].removed_count, 2);
}

#[test]
fn test_filter_no_match_field_missing() {
    let config = compile_yaml(r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric"
rules: {}
"#);
    let mut record = json!({"title": "Some Release"});
    let actions = apply_filters(&config, "releases", &mut record);
    assert!(actions.is_empty());
    // Record unchanged
    assert_eq!(record, json!({"title": "Some Release"}));
}

#[test]
fn test_filter_no_conditions_for_data_type() {
    let config = compile_yaml(r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric"
rules: {}
"#);
    let mut record = json!({"genres": {"genre": ["1", "Electronic"]}});
    let actions = apply_filters(&config, "masters", &mut record);
    assert!(actions.is_empty());
    // Record unchanged — filter was for releases, not masters
    assert_eq!(record["genres"]["genre"], json!(["1", "Electronic"]));
}

#[test]
fn test_filter_single_string_genre_not_array() {
    let config = compile_yaml(r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip numeric"
rules: {}
"#);
    // Single genre as string, not array — filter should handle gracefully
    let mut record = json!({"genres": {"genre": "Electronic"}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert!(actions.is_empty());
    // Non-array values are left untouched
    assert_eq!(record["genres"]["genre"], json!("Electronic"));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_filter_ 2>&1 | tail -5`
Expected: Compilation error — `apply_filters` doesn't exist yet.

- [ ] **Step 3: Implement apply_filters**

Add to `extractor/src/rules.rs` after `should_skip_record`:

```rust
#[derive(Debug, Clone)]
pub struct FilterAction {
    pub field: String,
    pub removed_count: usize,
    pub removed_values: Vec<String>,
    pub reason: String,
}

/// Apply filter transforms to a record, removing matching array elements in-place.
/// Returns a list of actions describing what was removed.
pub fn apply_filters(config: &CompiledRulesConfig, data_type: &str, record: &mut Value) -> Vec<FilterAction> {
    let conditions = config.filters_for(data_type);
    let mut actions = Vec::new();

    for condition in conditions {
        // Split field into parent path and leaf key
        // e.g., "genres.genre" -> parent segments ["genres"], leaf "genre"
        let segments: Vec<&str> = condition.field.split('.').collect();
        if segments.is_empty() {
            continue;
        }
        let leaf = segments[segments.len() - 1];
        let parent_segments = &segments[..segments.len() - 1];

        // Navigate to the parent object
        let mut current = &mut *record;
        let mut found = true;
        for segment in parent_segments {
            if let Value::Object(map) = current {
                if let Some(child) = map.get_mut(*segment) {
                    current = child;
                } else {
                    found = false;
                    break;
                }
            } else {
                found = false;
                break;
            }
        }
        if !found {
            continue;
        }

        // Get the array at the leaf key
        if let Value::Object(map) = current {
            if let Some(Value::Array(arr)) = map.get_mut(leaf) {
                let original_len = arr.len();
                let mut removed_values = Vec::new();

                arr.retain(|v| {
                    if let Value::String(s) = v {
                        if condition.remove_matching.is_match(s) {
                            removed_values.push(s.clone());
                            return false;
                        }
                    }
                    true
                });

                let removed_count = original_len - arr.len();
                if removed_count > 0 {
                    actions.push(FilterAction {
                        field: condition.field.clone(),
                        removed_count,
                        removed_values,
                        reason: condition.reason.clone(),
                    });
                }
            }
        }
    }

    actions
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_filter_ -- --nocapture 2>&1 | tail -15`
Expected: All 6 filter tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat(extractor): add apply_filters evaluation logic"
```

---

## Task 4: Quality Report — Skipped Records Tracking

**Files:**
- Modify: `extractor/src/rules.rs` (QualityReport, FlaggedRecordWriter)
- Test: `extractor/src/tests/rules_tests.rs`

- [ ] **Step 1: Write failing tests for skipped records in QualityReport**

Add to `extractor/src/tests/rules_tests.rs`:

```rust
#[test]
fn test_quality_report_skipped_records() {
    let mut report = QualityReport::new();
    report.record_skip("artists", "66827", "Upstream junk entry marked DO NOT USE");
    report.record_skip("labels", "212", "Upstream junk entry marked DO NOT USE");
    report.increment_total("artists");
    report.increment_total("labels");

    let skips = report.skipped_records();
    assert_eq!(skips.len(), 2);
    assert!(skips.contains_key("artists"));
    assert_eq!(skips["artists"].len(), 1);
    assert_eq!(skips["artists"][0].record_id, "66827");

    let summary = report.format_summary("20260401");
    assert!(summary.contains("Skipped records"));
    assert!(summary.contains("artists: 1"));
    assert!(summary.contains("66827"));
}

#[test]
fn test_quality_report_merge_with_skips() {
    let mut report1 = QualityReport::new();
    report1.record_skip("artists", "66827", "Junk");
    let mut report2 = QualityReport::new();
    report2.record_skip("labels", "212", "Junk");
    report1.merge(report2);

    let skips = report1.skipped_records();
    assert_eq!(skips.len(), 2);
}

#[test]
fn test_quality_report_no_skips_no_section() {
    let mut report = QualityReport::new();
    report.record_violation("releases", "test", &Severity::Warning);
    report.increment_total("releases");
    let summary = report.format_summary("20260401");
    assert!(!summary.contains("Skipped"));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_quality_report_skipped 2>&1 | tail -5`
Expected: Compilation error — `record_skip` doesn't exist yet.

- [ ] **Step 3: Add SkippedRecord struct and update QualityReport**

In `extractor/src/rules.rs`, add a struct and update `QualityReport`:

```rust
#[derive(Debug, Clone)]
pub struct SkippedRecord {
    pub record_id: String,
    pub reason: String,
}

#[derive(Debug, Default)]
pub struct QualityReport {
    /// data_type -> rule_name -> counts (BTreeMap for deterministic output ordering)
    pub counts: HashMap<String, BTreeMap<String, RuleCounts>>,
    /// data_type -> total records evaluated
    pub total_records: HashMap<String, u64>,
    /// data_type -> list of skipped records
    skipped: HashMap<String, Vec<SkippedRecord>>,
}
```

Add methods to `QualityReport`:

```rust
pub fn record_skip(&mut self, data_type: &str, record_id: &str, reason: &str) {
    self.skipped
        .entry(data_type.to_string())
        .or_default()
        .push(SkippedRecord {
            record_id: record_id.to_string(),
            reason: reason.to_string(),
        });
}

pub fn skipped_records(&self) -> &HashMap<String, Vec<SkippedRecord>> {
    &self.skipped
}

pub fn has_skipped_records(&self) -> bool {
    self.skipped.values().any(|v| !v.is_empty())
}
```

Update `merge` to include skips:

```rust
pub fn merge(&mut self, other: QualityReport) {
    // ... existing counts/total merge logic ...
    for (dt, skips) in other.skipped {
        self.skipped.entry(dt).or_default().extend(skips);
    }
}
```

Update `format_summary` to include the skipped section when present — insert it right after the header line, before the per-data-type violation lines:

```rust
pub fn format_summary(&self, version: &str) -> String {
    if !self.has_violations() && !self.has_skipped_records() {
        return format!("📊 Data Quality Report for discogs_{}: No data quality violations found.\n", version);
    }
    let mut output = format!("📊 Data Quality Report for discogs_{}:\n", version);

    // Skipped records section
    if self.has_skipped_records() {
        output.push_str("  ⏭️ Skipped records:\n");
        for dt in &["releases", "artists", "labels", "masters"] {
            if let Some(skips) = self.skipped.get(*dt) {
                if !skips.is_empty() {
                    let ids: Vec<&str> = skips.iter().map(|s| s.record_id.as_str()).collect();
                    let reason = &skips[0].reason;
                    output.push_str(&format!("    {}: {} ({}: {})\n", dt, skips.len(), reason, ids.join(", ")));
                }
            }
        }
    }

    // Existing violation section (unchanged)
    for dt in &["releases", "artists", "labels", "masters"] {
        let total = self.total_records.get(*dt).copied().unwrap_or(0);
        if let Some(rules) = self.counts.get(*dt) {
            let total_errors: u64 = rules.values().map(|c| c.errors).sum();
            let total_warnings: u64 = rules.values().map(|c| c.warnings).sum();
            output.push_str(&format!("  {}: {} errors, {} warnings (of {} records)\n", dt, total_errors, total_warnings, total));
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_quality_report -- --nocapture 2>&1 | tail -15`
Expected: All quality report tests pass (new and existing).

- [ ] **Step 5: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat(extractor): add skipped records tracking to QualityReport"
```

---

## Task 5: FlaggedRecordWriter — write_skip Method & Skipped JSONL

**Files:**
- Modify: `extractor/src/rules.rs` (FlaggedRecordWriter)
- Test: `extractor/src/tests/rules_tests.rs`

- [ ] **Step 1: Write failing test for write_skip**

Add to `extractor/src/tests/rules_tests.rs`:

```rust
#[test]
fn test_flagged_writer_write_skip() {
    use crate::rules::{FlaggedRecordWriter, SkipInfo};
    use tempfile::TempDir;

    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260401");

    let skip_info = SkipInfo {
        reason: "Upstream junk entry".to_string(),
        field: "profile".to_string(),
        field_value: "[b]DO NOT USE.[/b]".to_string(),
    };
    let parsed_json = json!({"id": "66827", "profile": "[b]DO NOT USE.[/b]"});
    let raw_xml = b"<artist><id>66827</id><profile>[b]DO NOT USE.[/b]</profile></artist>";

    writer.write_skip("artists", "66827", &skip_info, Some(raw_xml.as_slice()), &parsed_json);
    writer.flush();

    let type_dir = temp_dir.path().join("flagged").join("20260401").join("artists");

    // XML and JSON captured
    assert!(type_dir.join("66827.xml").exists(), "XML file should be created for skipped record");
    assert!(type_dir.join("66827.json").exists(), "JSON file should be created for skipped record");

    // skipped.jsonl written (separate from violations.jsonl)
    let skipped_jsonl = type_dir.join("skipped.jsonl");
    assert!(skipped_jsonl.exists(), "skipped.jsonl should be created");
    let content = std::fs::read_to_string(&skipped_jsonl).unwrap();
    assert!(content.contains("66827"));
    assert!(content.contains("Upstream junk entry"));
    assert!(content.contains("DO NOT USE"));

    // violations.jsonl should NOT exist
    assert!(!type_dir.join("violations.jsonl").exists(), "violations.jsonl should NOT be created for skipped records");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_flagged_writer_write_skip 2>&1 | tail -5`
Expected: Compilation error — `write_skip` doesn't exist yet.

- [ ] **Step 3: Implement write_skip on FlaggedRecordWriter**

Add a new `HashMap` for skip JSONL writers and the `write_skip` method to `FlaggedRecordWriter`:

Update the struct (line 346-349):

```rust
pub struct FlaggedRecordWriter {
    base_dir: PathBuf,
    written_records: HashSet<String>,
    jsonl_writers: HashMap<String, BufWriter<std::fs::File>>,
    skip_jsonl_writers: HashMap<String, BufWriter<std::fs::File>>,
}
```

Update `new` (line 364-370):

```rust
pub fn new(discogs_root: &Path, version: &str) -> Self {
    Self {
        base_dir: discogs_root.join("flagged").join(version),
        written_records: HashSet::new(),
        jsonl_writers: HashMap::new(),
        skip_jsonl_writers: HashMap::new(),
    }
}
```

Add the `write_skip` method after `write_violation`:

```rust
/// Write a skipped record to skipped.jsonl and capture XML/JSON files.
pub fn write_skip(
    &mut self,
    data_type: &str,
    record_id: &str,
    skip_info: &SkipInfo,
    raw_xml: Option<&[u8]>,
    parsed_json: &Value,
) {
    let type_dir = self.base_dir.join(data_type);

    if let Err(e) = fs::create_dir_all(&type_dir) {
        tracing::warn!("⚠️ Failed to create flagged directory {:?}: {}", type_dir, e);
        return;
    }

    let safe_id = sanitize_filename(record_id);

    // Write XML and JSON files (same dedup logic as violations)
    let record_key = format!("{}:{}", data_type, safe_id);
    if !self.written_records.contains(&record_key) {
        if let Some(xml_bytes) = raw_xml {
            let xml_path = type_dir.join(format!("{}.xml", safe_id));
            if let Err(e) = fs::write(&xml_path, xml_bytes) {
                tracing::warn!("⚠️ Failed to write skipped XML {:?}: {}", xml_path, e);
            }
        }
        let json_path = type_dir.join(format!("{}.json", safe_id));
        if let Err(e) = fs::write(&json_path, serde_json::to_string_pretty(parsed_json).unwrap_or_default()) {
            tracing::warn!("⚠️ Failed to write skipped JSON {:?}: {}", json_path, e);
        }
        self.written_records.insert(record_key);
    }

    // Append to skipped.jsonl
    if !self.skip_jsonl_writers.contains_key(data_type) {
        let jsonl_path = type_dir.join("skipped.jsonl");
        match fs::OpenOptions::new().create(true).append(true).open(&jsonl_path) {
            Ok(file) => {
                self.skip_jsonl_writers.insert(data_type.to_string(), BufWriter::new(file));
            }
            Err(e) => {
                tracing::warn!("⚠️ Failed to open skipped.jsonl {:?}: {}", jsonl_path, e);
                return;
            }
        }
    }
    let writer = self.skip_jsonl_writers.get_mut(data_type).unwrap();

    let entry = serde_json::json!({
        "record_id": record_id,
        "reason": skip_info.reason,
        "field": skip_info.field,
        "field_value": skip_info.field_value,
        "xml_file": format!("{}.xml", safe_id),
        "json_file": format!("{}.json", safe_id),
        "timestamp": chrono::Utc::now().to_rfc3339(),
    });
    if let Err(e) = writeln!(writer, "{}", serde_json::to_string(&entry).unwrap_or_default()) {
        tracing::warn!("⚠️ Failed to write skip entry: {}", e);
    }
}
```

Update `flush` to also flush skip writers:

```rust
pub fn flush(&mut self) {
    for writer in self.jsonl_writers.values_mut() {
        let _ = writer.flush();
    }
    for writer in self.skip_jsonl_writers.values_mut() {
        let _ = writer.flush();
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_flagged_writer -- --nocapture 2>&1 | tail -15`
Expected: All flagged writer tests pass (new and existing).

- [ ] **Step 5: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/src/rules.rs extractor/src/tests/rules_tests.rs
git commit -m "feat(extractor): add write_skip method to FlaggedRecordWriter"
```

---

## Task 6: Pipeline Integration — message_validator

**Files:**
- Modify: `extractor/src/extractor.rs:578-606` (message_validator function)
- Test: existing Rust integration tests (manual verification via `cargo test`)

- [ ] **Step 1: Update message_validator to call skip and filter before evaluate_rules**

In `extractor/src/extractor.rs`, update the `message_validator` function. The current loop body (lines 589-600) becomes:

```rust
pub async fn message_validator(
    mut receiver: mpsc::Receiver<DataMessage>,
    sender: mpsc::Sender<DataMessage>,
    rules: Arc<CompiledRulesConfig>,
    data_type: &str,
    discogs_root: &Path,
    version: &str,
) -> Result<QualityReport> {
    let mut report = QualityReport::new();
    let mut writer = FlaggedRecordWriter::new(discogs_root, version);

    while let Some(mut message) = receiver.recv().await {
        report.increment_total(data_type);

        // 1. Skip check — if record matches, log and do NOT forward
        if let Some(skip_info) = should_skip_record(&rules, data_type, &message.data) {
            info!(
                "⏭️ Skipping record {} ({}): {}",
                message.id, data_type, skip_info.reason
            );
            report.record_skip(data_type, &message.id, &skip_info.reason);
            writer.write_skip(data_type, &message.id, &skip_info, message.raw_xml.as_deref(), &message.data);
            continue;
        }

        // 2. Apply filters — mutate data in-place
        let filter_actions = apply_filters(&rules, data_type, &mut message.data);
        for action in &filter_actions {
            info!(
                "🔧 Filtered {} value(s) from {} in {} {}: removed {:?}, reason: {}",
                action.removed_count, action.field, data_type, message.id, action.removed_values, action.reason
            );
        }

        // 3. Validate (existing logic, unchanged)
        let violations = evaluate_rules(&rules, data_type, &message.data);
        for violation in &violations {
            report.record_violation(data_type, &violation.rule_name, &violation.severity);
            let capture_files = matches!(violation.severity, Severity::Error | Severity::Warning);
            writer.write_violation(data_type, &message.id, violation, message.raw_xml.as_deref(), &message.data, capture_files);
        }

        // 4. Forward (always, regardless of violations)
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

Also add the necessary imports at the top of `extractor.rs` — update the existing `use crate::rules::` import to include the new functions:

```rust
use crate::rules::{
    apply_filters, evaluate_rules, should_skip_record,
    CompiledRulesConfig, FlaggedRecordWriter, QualityReport, Severity,
};
```

- [ ] **Step 2: Verify it compiles and existing tests pass**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test 2>&1 | tail -5`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/src/extractor.rs
git commit -m "feat(extractor): integrate skip_records and filters into message_validator pipeline"
```

---

## Task 7: Update extraction-rules.yaml

**Files:**
- Modify: `extractor/extraction-rules.yaml`
- Test: `extractor/src/tests/rules_tests.rs` (existing `test_default_rules_file`)

- [ ] **Step 1: Add skip_records and filters sections to the YAML config**

Prepend the following to `extractor/extraction-rules.yaml` before the existing `rules:` section:

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

# Array field transforms applied before validation and publishing.
# Matching values are removed from the array in-place.
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip legacy numeric genre IDs from upstream data"
  masters:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Strip legacy numeric genre IDs from upstream data"

```

- [ ] **Step 2: Verify the default rules file test still passes**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test test_default_rules_file -- --nocapture 2>&1 | tail -5`
Expected: PASS — the test loads and compiles the default rules file.

- [ ] **Step 3: Commit**

```bash
cd /home/datum/Code/discogsography
git add extractor/extraction-rules.yaml
git commit -m "feat(extractor): add skip_records and filters to extraction-rules.yaml"
```

---

## Task 8: API — Skipped Records Endpoint & Summary Extension

**Files:**
- Modify: `api/routers/extraction_analysis.py`
- Test: `tests/api/test_extraction_analysis.py`

- [ ] **Step 1: Write failing tests for the new /skipped endpoint and summary extension**

Add to `tests/api/test_extraction_analysis.py`:

```python
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
            resp = test_client.get(
                "/api/admin/extraction-analysis/20260401/skipped?entity_type=labels", headers=_admin_auth_headers()
            )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/api/test_extraction_analysis.py::TestSkippedEndpoint -v 2>&1 | tail -10`
Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Implement _read_skipped and the /skipped endpoint**

Add to `api/routers/extraction_analysis.py` after `_read_violations` (after line 135):

```python
def _read_skipped(flagged_version_dir: Path) -> list[dict[str, Any]]:
    """Read all skipped.jsonl files under *flagged_version_dir*, injecting entity_type from the directory name."""
    skipped: list[dict[str, Any]] = []
    for entity_dir in sorted(flagged_version_dir.iterdir()):
        if not entity_dir.is_dir():
            continue
        jsonl_file = entity_dir / "skipped.jsonl"
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
                logger.warning("⚠️ Skipping corrupt skipped JSONL line", file=str(jsonl_file), lineno=lineno)
                continue
            record["entity_type"] = entity_type
            skipped.append(record)
    return skipped
```

Add a helper to build the skipped summary for the summary endpoint, after `_build_violation_summary`:

```python
def _build_skipped_summary(skipped: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate skipped records by entity type."""
    by_entity: dict[str, dict[str, Any]] = {}
    for s in skipped:
        entity_type = s.get("entity_type", "unknown")
        entry = by_entity.setdefault(entity_type, {"count": 0, "reasons": []})
        entry["count"] += 1
        reason = s.get("reason", "Unknown reason")
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)
    return by_entity
```

Add the new endpoint after the existing violations endpoint:

```python
@router.get("/api/admin/extraction-analysis/{version}/skipped")
async def list_skipped(
    version: str,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    entity_type: Annotated[str | None, Query(pattern=r"^[a-z-]+$")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    """Return a paginated list of skipped records for the given extraction version."""
    _validate_version(version)

    location = _find_version_root(version)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version!r}")

    data_root, _source = location
    flagged_version_dir = data_root / "flagged" / version

    skipped = _read_skipped(flagged_version_dir)

    if entity_type:
        skipped = [s for s in skipped if s.get("entity_type") == entity_type]

    total = len(skipped)
    start = (page - 1) * page_size
    page_items = skipped[start : start + page_size]

    return JSONResponse(
        content={
            "skipped": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
```

- [ ] **Step 4: Update the summary endpoint to include skipped data**

In the `get_summary` function (around line 268-306), add the skipped summary to the response. After `summary = _build_violation_summary(violations)`, add:

```python
    skipped = _read_skipped(flagged_version_dir)
    skipped_summary = _build_skipped_summary(skipped)
```

And update the return to include it:

```python
    return JSONResponse(
        content={
            "version": version,
            "source": source,
            "pipeline_status": pipeline_status,
            "skipped": skipped_summary,
            **summary,
        }
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/api/test_extraction_analysis.py::TestSkippedEndpoint tests/api/test_extraction_analysis.py::TestSummarySkippedField -v 2>&1 | tail -15`
Expected: All tests pass.

- [ ] **Step 6: Run full API test suite to check for regressions**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/api/test_extraction_analysis.py -v 2>&1 | tail -10`
Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
cd /home/datum/Code/discogsography
git add api/routers/extraction_analysis.py tests/api/test_extraction_analysis.py
git commit -m "feat(api): add /skipped endpoint and skipped summary to extraction analysis"
```

---

## Task 9: Dashboard Proxy — Forward /skipped Endpoint

**Files:**
- Modify: `dashboard/admin_proxy.py`
- Test: `tests/dashboard/test_extraction_analysis_proxy.py`

- [ ] **Step 1: Write failing test for the proxy route**

Add to `tests/dashboard/test_extraction_analysis_proxy.py`:

```python
class TestEaSkippedProxy:
    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_forwards_correctly(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"skipped":[],"total":0,"page":1,"page_size":50}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20260401/skipped", headers={"Authorization": "Bearer tok"}
        )
        assert resp.status_code == 200
        assert "skipped" in resp.json()
        mock_instance.get.assert_called_once()
        call_url = mock_instance.get.call_args[0][0]
        assert "/api/admin/extraction-analysis/20260401/skipped" in call_url

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_passes_query_params(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx("get", 200, b'{"skipped":[],"total":0,"page":1,"page_size":50}')
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get(
            "/admin/api/extraction-analysis/20260401/skipped?entity_type=artists&page=2",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_instance.get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params.get("entity_type") == "artists"
        assert params.get("page") == "2"

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_rejects_invalid_version(self, _mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/admin/api/extraction-analysis/../etc/skipped")
        assert resp.status_code == 400

    @patch("dashboard.admin_proxy.httpx.AsyncClient")
    def test_returns_502_on_error(self, mock_cls_patch: AsyncMock, proxy_client: TestClient) -> None:
        _, mock_instance = _mock_httpx_error("get")
        mock_cls_patch.return_value = mock_instance

        resp = proxy_client.get("/admin/api/extraction-analysis/20260401/skipped")
        assert resp.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/dashboard/test_extraction_analysis_proxy.py::TestEaSkippedProxy -v 2>&1 | tail -10`
Expected: FAIL — route doesn't exist (404).

- [ ] **Step 3: Add proxy route to admin_proxy.py**

Add after the existing `proxy_ea_violation_detail` route (after line 405) and before `proxy_ea_violations` (the `/skipped` path must be registered before the bare `/violations` to avoid path conflicts):

```python
@router.get("/admin/api/extraction-analysis/{version}/skipped")
async def proxy_ea_skipped(
    version: str,
    request: Request,
    entity_type: str | None = Query(default=None, pattern=r"^[a-z-]+$"),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
) -> Response:
    """Proxy extraction analysis skipped records list with optional query param filtering."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/skipped")
    params: dict[str, str] = {}
    if entity_type is not None:
        params["entity_type"] = entity_type
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/dashboard/test_extraction_analysis_proxy.py::TestEaSkippedProxy -v 2>&1 | tail -10`
Expected: All 4 proxy tests pass.

- [ ] **Step 5: Run full proxy test suite**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/dashboard/test_extraction_analysis_proxy.py -v 2>&1 | tail -10`
Expected: All existing proxy tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /home/datum/Code/discogsography
git add dashboard/admin_proxy.py tests/dashboard/test_extraction_analysis_proxy.py
git commit -m "feat(dashboard): add proxy route for extraction analysis skipped records"
```

---

## Task 10: Admin UI — Skipped Records Section in Report View

**Files:**
- Modify: `dashboard/static/admin.html` (add skipped cards container)
- Modify: `dashboard/static/admin.js` (fetch and render skipped data)

- [ ] **Step 1: Add skipped records HTML section between pipeline status and violations**

In `dashboard/static/admin.html`, insert after the pipeline status `</section>` (line 829) and before the violations section (line 831):

```html
                <!-- Skipped records cards (per entity type) -->
                <section id="ea-skipped-section" class="dashboard-card p-6 space-y-4" style="display:none">
                    <h3 class="text-sm font-semibold flex items-center gap-2 border-b b-theme pb-3">
                        <span class="material-symbols-outlined text-sm t-dim">block</span> Skipped Records
                    </h3>
                    <div id="ea-skipped-cards" class="flex flex-wrap gap-3"></div>
                    <div id="ea-skipped-detail" class="space-y-2" style="display:none"></div>
                </section>
```

- [ ] **Step 2: Add JS rendering logic for skipped records**

In `dashboard/static/admin.js`, add a new method after `_eaRenderEntityCards` (after line 1756):

```javascript
    _eaRenderSkippedCards(skippedSummary) {
        const section = document.getElementById('ea-skipped-section');
        const container = document.getElementById('ea-skipped-cards');
        const detail = document.getElementById('ea-skipped-detail');
        if (!section || !container) return;

        const entries = Object.entries(skippedSummary || {});
        if (entries.length === 0) {
            section.style.display = 'none';
            return;
        }

        section.style.display = '';
        const cards = entries.map(([entityType, info]) => {
            const card = document.createElement('div');
            card.className = 'stat-card flex flex-col gap-1 cursor-pointer hover:ring-1 ring-current rounded';
            card.title = 'Click to view skipped records';
            const label = document.createElement('p');
            label.className = 'text-[10px] font-bold uppercase tracking-wider t-muted';
            label.textContent = entityType;
            const count = document.createElement('p');
            count.className = 'text-xl font-bold t-high';
            count.textContent = (info.count ?? 0).toLocaleString();
            const reason = document.createElement('p');
            reason.className = 'text-[10px] t-muted truncate';
            reason.style.maxWidth = '200px';
            reason.textContent = (info.reasons || []).join(', ') || 'Unknown reason';
            card.append(label, count, reason);

            card.addEventListener('click', () => this._eaLoadSkippedDetail(entityType));
            return card;
        });
        container.replaceChildren(...cards);
        if (detail) detail.style.display = 'none';
    }

    async _eaLoadSkippedDetail(entityType) {
        const sel = document.getElementById('ea-version-select');
        const version = sel ? sel.value : '';
        if (!version) return;
        const detail = document.getElementById('ea-skipped-detail');
        if (!detail) return;

        try {
            const resp = await this.authFetch(
                `/admin/api/extraction-analysis/${encodeURIComponent(version)}/skipped?entity_type=${encodeURIComponent(entityType)}`
            );
            if (!resp.ok) return;
            const data = await resp.json();
            const items = data.skipped || [];

            if (items.length === 0) {
                detail.style.display = 'none';
                return;
            }

            const heading = document.createElement('p');
            heading.className = 'text-xs font-bold t-dim uppercase tracking-wider';
            heading.textContent = `Skipped ${entityType} (${items.length})`;

            const list = document.createElement('div');
            list.className = 'flex flex-wrap gap-2';

            for (const item of items) {
                const chip = document.createElement('button');
                chip.className = 'text-xs px-2 py-1 rounded border b-theme t-mid hover:t-high mono';
                chip.textContent = item.record_id;
                chip.title = item.reason || '';
                chip.addEventListener('click', () => this._eaShowRecordDetail(version, item.record_id));
                list.appendChild(chip);
            }

            detail.replaceChildren(heading, list);
            detail.style.display = '';
        } catch {
            // Silently fail
        }
    }
```

- [ ] **Step 3: Wire the skipped rendering into _eaLoadReport**

In `dashboard/static/admin.js`, in the `_eaLoadReport` method (around line 1686), after `this._eaRenderEntityCards(summary);`, add:

```javascript
                this._eaRenderSkippedCards(summary.skipped || {});
```

- [ ] **Step 4: Verify in browser**

Start the dev server and open the admin panel. Navigate to Extraction Analysis, select a version that has skipped records. The "Skipped Records" card section should appear between pipeline status and violations. Clicking a card should expand the list of record IDs. Clicking a record ID should open the record detail modal.

- [ ] **Step 5: Commit**

```bash
cd /home/datum/Code/discogsography
git add dashboard/static/admin.html dashboard/static/admin.js
git commit -m "feat(dashboard): add skipped records section to extraction analysis report view"
```

---

## Task 11: Compare View — Skipped Delta Row

**Files:**
- Modify: `api/routers/extraction_analysis.py` (compare endpoint)
- Modify: `dashboard/static/admin.js` (_eaCompare method)

- [ ] **Step 1: Update compare endpoint to include skipped counts**

In `api/routers/extraction_analysis.py`, in the `compare_versions` function (line 546-629), add skipped counting after the violation counting:

```python
    skipped_a = _read_skipped(loc_a[0] / "flagged" / version)
    skipped_b = _read_skipped(loc_b[0] / "flagged" / other_version)

    def _count_by_entity(skipped: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in skipped:
            et = s.get("entity_type", "unknown")
            counts[et] = counts.get(et, 0) + 1
        return counts

    skipped_counts_a = _count_by_entity(skipped_a)
    skipped_counts_b = _count_by_entity(skipped_b)
```

Add skipped comparison data to the response content dict, after `"details": details`:

```python
            "skipped": {
                "version_a": skipped_counts_a,
                "version_b": skipped_counts_b,
            },
```

- [ ] **Step 2: Update the JS compare renderer to show skipped delta**

In `dashboard/static/admin.js`, in the `_eaCompare` method, after the delta table rows are built and inserted into tbody (around line 1985), add a skipped summary line before `tableWrap.style.display = '';`:

```javascript
            // Add skipped records delta below the table
            const skippedData = data.skipped || {};
            const skA = skippedData.version_a || {};
            const skB = skippedData.version_b || {};
            const allSkipEntities = new Set([...Object.keys(skA), ...Object.keys(skB)]);
            if (allSkipEntities.size > 0) {
                const skipRow = document.createElement('tr');
                skipRow.className = 'border-b b-row bg-inner';
                const tdLabel = document.createElement('td');
                tdLabel.className = 'py-2 px-2 t-dim italic';
                tdLabel.colSpan = 2;
                tdLabel.textContent = '⏭️ Skipped records';
                const totalSkA = Object.values(skA).reduce((a, b) => a + b, 0);
                const totalSkB = Object.values(skB).reduce((a, b) => a + b, 0);
                const tdA = document.createElement('td');
                tdA.className = 'py-2 px-2 text-right mono t-mid';
                tdA.textContent = totalSkA.toLocaleString();
                const tdB = document.createElement('td');
                tdB.className = 'py-2 px-2 text-right mono t-mid';
                tdB.textContent = totalSkB.toLocaleString();
                const tdD = document.createElement('td');
                tdD.className = 'py-2 px-2 text-right mono font-bold';
                const skipDiff = totalSkB - totalSkA;
                tdD.textContent = (skipDiff > 0 ? '+' : '') + skipDiff.toLocaleString();
                tdD.style.color = skipDiff > 0 ? 'var(--text-high)' : skipDiff < 0 ? '#10B981' : 'var(--text-dim)';
                skipRow.append(tdLabel, tdA, tdB, tdD);
                tbody.appendChild(skipRow);
            }
```

- [ ] **Step 3: Run API test suite**

Run: `cd /home/datum/Code/discogsography && uv run pytest tests/api/test_extraction_analysis.py -v 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/datum/Code/discogsography
git add api/routers/extraction_analysis.py dashboard/static/admin.js
git commit -m "feat(dashboard): add skipped records delta to extraction analysis compare view"
```

---

## Task 12: Full Test Suite & Lint

**Files:** (no new files)

- [ ] **Step 1: Run full Rust test suite**

Run: `cd /home/datum/Code/discogsography/extractor && cargo test 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 2: Run Rust lints**

Run: `cd /home/datum/Code/discogsography && just extractor-lint 2>&1 | tail -10`
Expected: No warnings or errors.

- [ ] **Step 3: Run Rust formatting check**

Run: `cd /home/datum/Code/discogsography && just extractor-fmt-check 2>&1 | tail -5`
Expected: No formatting issues.

- [ ] **Step 4: Run full Python test suite**

Run: `cd /home/datum/Code/discogsography && just test 2>&1 | tail -10`
Expected: All Python tests pass.

- [ ] **Step 5: Run Python lints**

Run: `cd /home/datum/Code/discogsography && just lint-python 2>&1 | tail -10`
Expected: No lint errors.

- [ ] **Step 6: Commit any formatting fixes**

If any formatting or lint issues were found and fixed:

```bash
cd /home/datum/Code/discogsography
git add -u
git commit -m "style: fix formatting and lint issues"
```
