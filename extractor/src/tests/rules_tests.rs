use crate::rules::{CompiledRulesConfig, QualityReport, RulesConfig, Severity, Violation, evaluate_rules};
use serde_json::json;

// ── Helper ───────────────────────────────────────────────────────────

fn compile_yaml(yaml: &str) -> CompiledRulesConfig {
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    CompiledRulesConfig::compile(config).unwrap()
}

// ── YAML loading ─────────────────────────────────────────────────────

#[test]
fn test_load_valid_config_all_condition_types() {
    let yaml = r#"
rules:
  artists:
    - name: name_required
      field: name
      condition:
        type: required
      severity: error
    - name: name_length
      field: name
      condition:
        type: length
        min: 1
        max: 500
      severity: warning
    - name: year_range
      field: year
      condition:
        type: range
        min: 1900
        max: 2100
      severity: warning
    - name: name_regex
      field: name
      condition:
        type: regex
        pattern: "^[A-Za-z]"
      severity: info
    - name: status_enum
      field: status
      condition:
        type: enum
        values: [Active, Inactive]
      severity: warning
"#;
    let config = compile_yaml(yaml);
    let rules = config.rules_for("artists");
    assert_eq!(rules.len(), 5);
    assert_eq!(rules[0].name, "name_required");
    assert_eq!(rules[1].name, "name_length");
    assert_eq!(rules[2].name, "year_range");
    assert_eq!(rules[3].name, "name_regex");
    assert_eq!(rules[4].name, "status_enum");
}

#[test]
fn test_severity_levels_deserialize() {
    let yaml = r#"
rules:
  artists:
    - name: r_error
      field: f
      condition: {type: required}
      severity: error
    - name: r_warning
      field: f
      condition: {type: required}
      severity: warning
    - name: r_info
      field: f
      condition: {type: required}
      severity: info
"#;
    let config = compile_yaml(yaml);
    let rules = config.rules_for("artists");
    assert_eq!(rules.len(), 3);
    assert!(matches!(rules[0].severity, Severity::Error));
    assert!(matches!(rules[1].severity, Severity::Warning));
    assert!(matches!(rules[2].severity, Severity::Info));
}

#[test]
fn test_invalid_regex_returns_error() {
    let yaml = r#"
rules:
  artists:
    - name: bad_regex
      field: name
      condition:
        type: regex
        pattern: "[invalid("
      severity: error
"#;
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("bad_regex"), "Expected rule name in error: {msg}");
}

#[test]
fn test_invalid_data_type_returns_error() {
    let yaml = r#"
rules:
  foobar:
    - name: some_rule
      field: name
      condition: {type: required}
      severity: error
"#;
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("foobar"), "Expected unknown type name in error: {msg}");
}

#[test]
fn test_optional_description_field() {
    let yaml = r#"
rules:
  labels:
    - name: with_desc
      description: "Has a description"
      field: name
      condition: {type: required}
      severity: error
    - name: without_desc
      field: name
      condition: {type: required}
      severity: warning
"#;
    let config = compile_yaml(yaml);
    let rules = config.rules_for("labels");
    assert_eq!(rules[0].description, Some("Has a description".to_string()));
    assert_eq!(rules[1].description, None);
}

#[test]
fn test_no_rules_for_unknown_data_type() {
    let yaml = r#"
rules:
  artists:
    - name: r
      field: f
      condition: {type: required}
      severity: error
"#;
    let config = compile_yaml(yaml);
    assert_eq!(config.rules_for("labels").len(), 0);
    assert_eq!(config.rules_for("masters").len(), 0);
    assert_eq!(config.rules_for("releases").len(), 0);
    assert_eq!(config.rules_for("unknown").len(), 0);
}

// ── Range evaluation ──────────────────────────────────────────────────

#[test]
fn test_range_within_bounds_no_violation() {
    let config = compile_yaml(
        r#"
rules:
  masters:
    - name: year_range
      field: year
      condition: {type: range, min: 1900, max: 2100}
      severity: warning
"#,
    );
    let record = json!({"year": "2000"});
    let violations = evaluate_rules(&config, "masters", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_range_below_min_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  masters:
    - name: year_range
      field: year
      condition: {type: range, min: 1900, max: 2100}
      severity: warning
"#,
    );
    let record = json!({"year": "1800"});
    let violations = evaluate_rules(&config, "masters", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].rule_name, "year_range");
    assert_eq!(violations[0].field_value, "1800");
}

#[test]
fn test_range_above_max_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  masters:
    - name: year_range
      field: year
      condition: {type: range, min: 1900, max: 2100}
      severity: warning
"#,
    );
    let record = json!({"year": "2200"});
    let violations = evaluate_rules(&config, "masters", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "2200");
}

#[test]
fn test_range_non_numeric_field_no_violation() {
    let config = compile_yaml(
        r#"
rules:
  masters:
    - name: year_range
      field: year
      condition: {type: range, min: 1900, max: 2100}
      severity: warning
"#,
    );
    // Non-numeric value: range check skips (returns false), no violation
    let record = json!({"year": "unknown"});
    let violations = evaluate_rules(&config, "masters", &record);
    assert!(violations.is_empty());
}

// ── Required evaluation ───────────────────────────────────────────────

#[test]
fn test_required_field_present_no_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );
    let record = json!({"name": "Aphex Twin"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_required_field_missing_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );
    let record = json!({"other": "value"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].rule_name, "name_required");
    assert!(matches!(violations[0].severity, Severity::Error));
}

#[test]
fn test_required_field_empty_string_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );
    let record = json!({"name": ""});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "");
}

#[test]
fn test_required_field_null_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );
    let record = json!({"name": null});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
}

// ── Regex evaluation ──────────────────────────────────────────────────

#[test]
fn test_regex_match_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  labels:
    - name: no_digits_in_name
      field: name
      condition:
        type: regex
        pattern: "\\d"
      severity: warning
"#,
    );
    // Name contains digits — regex matches → violation
    let record = json!({"name": "Label123"});
    let violations = evaluate_rules(&config, "labels", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "Label123");
}

#[test]
fn test_regex_no_match_no_violation() {
    let config = compile_yaml(
        r#"
rules:
  labels:
    - name: no_digits_in_name
      field: name
      condition:
        type: regex
        pattern: "\\d"
      severity: warning
"#,
    );
    let record = json!({"name": "Clean Label"});
    let violations = evaluate_rules(&config, "labels", &record);
    assert!(violations.is_empty());
}

// ── Enum evaluation ───────────────────────────────────────────────────

#[test]
fn test_enum_valid_value_no_violation() {
    let config = compile_yaml(
        r#"
rules:
  releases:
    - name: valid_format
      field: format
      condition:
        type: enum
        values: [Vinyl, CD, Digital, Cassette]
      severity: warning
"#,
    );
    let record = json!({"format": "Vinyl"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_enum_invalid_value_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  releases:
    - name: valid_format
      field: format
      condition:
        type: enum
        values: [Vinyl, CD, Digital, Cassette]
      severity: warning
"#,
    );
    let record = json!({"format": "Wax Cylinder"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "Wax Cylinder");
}

// ── Length evaluation ─────────────────────────────────────────────────

#[test]
fn test_length_within_bounds_no_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_length
      field: name
      condition: {type: length, min: 1, max: 100}
      severity: warning
"#,
    );
    let record = json!({"name": "The Beatles"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_length_too_short_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_length
      field: name
      condition: {type: length, min: 2, max: 100}
      severity: warning
"#,
    );
    let record = json!({"name": "X"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "X");
}

#[test]
fn test_length_too_long_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_length
      field: name
      condition: {type: length, min: 1, max: 5}
      severity: info
"#,
    );
    let record = json!({"name": "This name is way too long"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
}

// ── Dot-notation field resolution ────────────────────────────────────

#[test]
fn test_dot_notation_nested_object() {
    let config = compile_yaml(
        r#"
rules:
  releases:
    - name: label_name_required
      field: label.name
      condition: {type: required}
      severity: error
"#,
    );
    let record = json!({"label": {"name": "Sub Pop"}});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_dot_notation_missing_intermediate_produces_violation() {
    let config = compile_yaml(
        r#"
rules:
  releases:
    - name: label_name_required
      field: label.name
      condition: {type: required}
      severity: error
"#,
    );
    // `label` key is absent entirely
    let record = json!({"title": "Some Album"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].rule_name, "label_name_required");
}

#[test]
fn test_dot_notation_array_expands_to_multiple_values() {
    let config = compile_yaml(
        r#"
rules:
  releases:
    - name: genre_length
      field: genres.name
      condition: {type: length, min: 1, max: 50}
      severity: warning
"#,
    );
    // All genre names are within bounds — no violations
    let record = json!({"genres": [{"name": "Rock"}, {"name": "Jazz"}]});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_dot_notation_array_one_violating_element() {
    let config = compile_yaml(
        r#"
rules:
  releases:
    - name: genre_length
      field: genres.name
      condition: {type: length, min: 1, max: 5}
      severity: warning
"#,
    );
    // "Electronic" is 10 chars, exceeds max of 5
    let record = json!({"genres": [{"name": "Rock"}, {"name": "Electronic"}]});
    let violations = evaluate_rules(&config, "releases", &record);
    assert_eq!(violations.len(), 1);
    assert_eq!(violations[0].field_value, "Electronic");
}

#[test]
fn test_no_rules_for_data_type_returns_empty_violations() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );
    // Record is for "releases" — no rules defined for it
    let record = json!({"title": "Some Album"});
    let violations = evaluate_rules(&config, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_violation_carries_correct_severity() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#,
    );
    let record = json!({});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 1);
    assert!(matches!(violations[0].severity, Severity::Error));
    assert_eq!(violations[0].severity.to_string(), "error");
}

#[test]
fn test_multiple_rules_multiple_violations() {
    let config = compile_yaml(
        r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
    - name: year_range
      field: year
      condition: {type: range, min: 1900, max: 2100}
      severity: warning
"#,
    );
    // Both rules violate: name missing, year out of range
    let record = json!({"year": "1800"});
    let violations = evaluate_rules(&config, "artists", &record);
    assert_eq!(violations.len(), 2);
    let names: Vec<&str> = violations.iter().map(|v| v.rule_name.as_str()).collect();
    assert!(names.contains(&"name_required"));
    assert!(names.contains(&"year_range"));
}

#[test]
fn test_severity_display() {
    assert_eq!(Severity::Error.to_string(), "error");
    assert_eq!(Severity::Warning.to_string(), "warning");
    assert_eq!(Severity::Info.to_string(), "info");
}

#[test]
fn test_violation_fields_populated_correctly() {
    let config = compile_yaml(
        r#"
rules:
  labels:
    - name: name_required
      field: name
      condition: {type: required}
      severity: warning
"#,
    );
    let record = json!({});
    let violations = evaluate_rules(&config, "labels", &record);
    assert_eq!(violations.len(), 1);
    let v: &Violation = &violations[0];
    assert_eq!(v.rule_name, "name_required");
    assert_eq!(v.field, "name");
    assert_eq!(v.field_value, "");
    assert!(matches!(v.severity, Severity::Warning));
}

#[test]
fn test_all_valid_data_type_keys_accepted() {
    for data_type in ["artists", "labels", "masters", "releases"] {
        let yaml = format!(
            r#"
rules:
  {data_type}:
    - name: r
      field: f
      condition: {{type: required}}
      severity: error
"#
        );
        let result = serde_yaml_ng::from_str::<RulesConfig>(&yaml).map(|_| ()).is_ok();
        assert!(result, "Failed to parse config for data type: {data_type}");

        let config: RulesConfig = serde_yaml_ng::from_str(&yaml).unwrap();
        let compiled = CompiledRulesConfig::compile(config);
        assert!(compiled.is_ok(), "Failed to compile config for data type: {data_type}");
    }
}

// ── QualityReport ─────────────────────────────────────────────────────

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
