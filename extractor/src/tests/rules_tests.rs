use crate::rules::{CompiledRulesConfig, QualityReport, RulesConfig, Severity, Violation, apply_filters, evaluate_rules, should_skip_record};
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

// ── sanitize_filename ─────────────────────────────────────────────────

#[test]
fn test_sanitize_filename_normal() {
    use crate::rules::sanitize_filename;
    assert_eq!(sanitize_filename("12345"), "12345");
    assert_eq!(sanitize_filename("artist-name_1"), "artist-name_1");
}

#[test]
fn test_sanitize_filename_path_traversal() {
    use crate::rules::sanitize_filename;
    // Path separators stripped, `..` collapsed to `_`
    assert_eq!(sanitize_filename("../../../etc/passwd"), "___etcpasswd");
    assert_eq!(sanitize_filename("foo/bar\\baz"), "foobarbaz");
}

#[test]
fn test_sanitize_filename_double_dots() {
    use crate::rules::sanitize_filename;
    // Dots are kept but `..` is collapsed to `_`
    assert_eq!(sanitize_filename(".."), "_");
    assert_eq!(sanitize_filename("a..b"), "a_b");
    assert_eq!(sanitize_filename("file.xml"), "file.xml");
}

#[test]
fn test_sanitize_filename_special_chars() {
    use crate::rules::sanitize_filename;
    // Only alphanumeric, hyphens, underscores, and dots survive
    assert_eq!(sanitize_filename("hello world!@#$%"), "helloworld");
    assert_eq!(sanitize_filename(""), "");
}

// ── FlaggedRecordWriter ──────────────────────────────────────────────

#[test]
fn test_flagged_writer_write_violation_and_flush() {
    use crate::rules::{FlaggedRecordWriter, Severity, Violation};
    use tempfile::TempDir;

    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let violation =
        Violation { rule_name: "test-rule".to_string(), severity: Severity::Error, field: "name".to_string(), field_value: "".to_string() };

    let parsed_json = json!({"name": "", "id": "123"});
    let raw_xml = b"<artist id=\"123\"><name></name></artist>";

    writer.write_violation("artists", "123", &violation, Some(raw_xml.as_slice()), &parsed_json, true);
    writer.flush();

    // Check that files were created
    let type_dir = temp_dir.path().join("flagged").join("20260301").join("artists");
    assert!(type_dir.join("123.xml").exists(), "XML file should be created");
    assert!(type_dir.join("123.json").exists(), "JSON file should be created");
    assert!(type_dir.join("violations.jsonl").exists(), "JSONL file should be created");

    // Verify JSONL content
    let jsonl = std::fs::read_to_string(type_dir.join("violations.jsonl")).unwrap();
    assert!(jsonl.contains("test-rule"));
    assert!(jsonl.contains("\"severity\":\"error\""));
}

#[test]
fn test_flagged_writer_deduplicates_files() {
    use crate::rules::{FlaggedRecordWriter, Severity, Violation};
    use tempfile::TempDir;

    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let violation1 =
        Violation { rule_name: "rule-a".to_string(), severity: Severity::Warning, field: "name".to_string(), field_value: "bad".to_string() };
    let violation2 =
        Violation { rule_name: "rule-b".to_string(), severity: Severity::Error, field: "year".to_string(), field_value: "0".to_string() };

    let parsed_json = json!({"name": "bad", "year": "0"});

    // Write two violations for the same record
    writer.write_violation("artists", "42", &violation1, None, &parsed_json, true);
    writer.write_violation("artists", "42", &violation2, None, &parsed_json, true);
    writer.flush();

    // JSON file should exist (written once for first violation)
    let type_dir = temp_dir.path().join("flagged").join("20260301").join("artists");
    assert!(type_dir.join("42.json").exists());

    // JSONL should have two entries
    let jsonl = std::fs::read_to_string(type_dir.join("violations.jsonl")).unwrap();
    let lines: Vec<&str> = jsonl.trim().lines().collect();
    assert_eq!(lines.len(), 2, "Should have two JSONL entries for two violations");
}

#[test]
fn test_flagged_writer_no_capture_files() {
    use crate::rules::{FlaggedRecordWriter, Severity, Violation};
    use tempfile::TempDir;

    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let violation = Violation { rule_name: "info-rule".to_string(), severity: Severity::Info, field: "x".to_string(), field_value: "y".to_string() };

    let parsed_json = json!({"x": "y"});

    // capture_files = false — should not write XML/JSON files
    writer.write_violation("labels", "99", &violation, None, &parsed_json, false);
    writer.flush();

    let type_dir = temp_dir.path().join("flagged").join("20260301").join("labels");
    assert!(!type_dir.join("99.xml").exists(), "XML should not be created when capture_files is false");
    assert!(!type_dir.join("99.json").exists(), "JSON should not be created when capture_files is false");
    // JSONL should still be written
    assert!(type_dir.join("violations.jsonl").exists());
}

#[test]
fn test_flagged_writer_write_report() {
    use crate::rules::{FlaggedRecordWriter, QualityReport, Severity};
    use tempfile::TempDir;

    let temp_dir = TempDir::new().unwrap();
    let writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let mut report = QualityReport::new();
    report.record_violation("releases", "test-rule", &Severity::Error);
    report.increment_total("releases");

    writer.write_report(&report, "20260301");

    let report_path = temp_dir.path().join("flagged").join("20260301").join("report.txt");
    assert!(report_path.exists(), "Report file should be created");
    let content = std::fs::read_to_string(report_path).unwrap();
    assert!(content.contains("test-rule"));
    assert!(content.contains("1 errors"));
}

// ── QualityReport edge cases ─────────────────────────────────────────

#[test]
fn test_quality_report_has_violations_false_when_empty() {
    let report = QualityReport::new();
    assert!(!report.has_violations());
}

#[test]
fn test_quality_report_has_violations_true_with_info() {
    let mut report = QualityReport::new();
    report.record_violation("artists", "test", &Severity::Info);
    assert!(report.has_violations());
}

#[test]
fn test_quality_report_format_summary_data_type_with_total_but_no_violations() {
    let mut report = QualityReport::new();
    // Add violation to releases so has_violations() returns true
    report.record_violation("releases", "some-rule", &Severity::Warning);
    report.increment_total("releases");
    // masters has total records but no violations — tests the `else if total > 0` branch
    report.increment_total("masters");
    report.increment_total("masters");
    report.increment_total("masters");

    let summary = report.format_summary("20260301");
    assert!(summary.contains("masters: 0 errors, 0 warnings (of 3 records)"));
}

#[test]
fn test_quality_report_format_summary_info_counts() {
    let mut report = QualityReport::new();
    report.record_violation("artists", "info-rule", &Severity::Info);
    report.record_violation("artists", "info-rule", &Severity::Info);
    report.increment_total("artists");

    let summary = report.format_summary("20260301");
    assert!(summary.contains("2 info"));
}

#[test]
fn test_quality_report_merge_overlapping_rules() {
    let mut report1 = QualityReport::new();
    report1.record_violation("releases", "shared-rule", &Severity::Error);
    report1.record_violation("releases", "shared-rule", &Severity::Warning);
    report1.increment_total("releases");

    let mut report2 = QualityReport::new();
    report2.record_violation("releases", "shared-rule", &Severity::Error);
    report2.record_violation("releases", "shared-rule", &Severity::Info);
    report2.increment_total("releases");

    report1.merge(report2);

    let counts = &report1.counts["releases"]["shared-rule"];
    assert_eq!(counts.errors, 2);
    assert_eq!(counts.warnings, 1);
    assert_eq!(counts.info, 1);
    assert_eq!(report1.total_records["releases"], 2);
}

// ── RulesConfig::load edge cases ─────────────────────────────────────

#[test]
fn test_load_rejects_non_yaml_extension() {
    use crate::rules::RulesConfig;
    use tempfile::NamedTempFile;

    let temp_file = NamedTempFile::with_suffix(".json").unwrap();
    std::fs::write(temp_file.path(), "{}").unwrap();

    let result = RulesConfig::load(temp_file.path());
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains(".yaml") || msg.contains(".yml"), "Error should mention required extension: {msg}");
}

#[test]
fn test_load_rejects_nonexistent_file() {
    use crate::rules::RulesConfig;
    use std::path::Path;

    let result = RulesConfig::load(Path::new("/nonexistent/path/rules.yaml"));
    assert!(result.is_err());
}

#[test]
fn test_load_accepts_yml_extension() {
    use crate::rules::RulesConfig;
    use tempfile::NamedTempFile;

    let temp_file = NamedTempFile::with_suffix(".yml").unwrap();
    std::fs::write(
        temp_file.path(),
        r#"rules:
  artists:
    - name: test
      field: name
      condition: {type: required}
      severity: error
"#,
    )
    .unwrap();

    let result = RulesConfig::load(temp_file.path());
    assert!(result.is_ok(), "Should accept .yml extension: {:?}", result.err());
}

#[test]
fn test_load_rejects_invalid_yaml() {
    use crate::rules::RulesConfig;
    use tempfile::NamedTempFile;

    let temp_file = NamedTempFile::with_suffix(".yaml").unwrap();
    std::fs::write(temp_file.path(), "not: [valid: yaml: {{{{").unwrap();

    let result = RulesConfig::load(temp_file.path());
    assert!(result.is_err());
}

// ── resolve_field_values coverage: Value::Number branch ─────────────

#[test]
fn test_range_rule_with_numeric_json_value() {
    // When a field has a JSON number (not a string), the resolve_field_values
    // function should convert it via Value::Number(n) => Some(n.to_string()).
    let rules = compile_yaml(
        r#"
rules:
  releases:
    - name: year_range
      field: year
      condition:
        type: range
        min: 1900
        max: 2100
      severity: warning
"#,
    );

    // Year as an actual JSON number (not string) — tests the Number branch
    let record = json!({"year": 1850});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert_eq!(violations.len(), 1, "Numeric year 1850 should violate range 1900-2100");
    assert_eq!(violations[0].rule_name, "year_range");

    // Year within range — no violation
    let record2 = json!({"year": 2000});
    let violations2 = evaluate_rules(&rules, "releases", &record2);
    assert!(violations2.is_empty(), "Numeric year 2000 should be within range");
}

#[test]
fn test_resolve_field_values_with_non_object_value() {
    // Exercise the `_ => None` branch: field resolves to something that isn't
    // String, Number, or Null (e.g., a bool or nested object).
    let rules = compile_yaml(
        r#"
rules:
  artists:
    - name: name_length
      field: name
      condition:
        type: length
        min: 1
      severity: warning
"#,
    );

    // name is a boolean — can't be converted to a string, so no violation
    let record = json!({"name": true});
    let violations = evaluate_rules(&rules, "artists", &record);
    // The field resolves to a boolean, which is `_ => None` — skipped entirely
    assert!(violations.is_empty(), "Boolean field value should be skipped");
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

// ── Task 1: YAML Schema — skip_records & filters ────────────────────

#[test]
fn test_yaml_with_skip_records_and_filters() {
    let yaml = r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry marked DO NOT USE"

filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres are parsing artifacts"

rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#;
    let config = compile_yaml(yaml);
    assert_eq!(config.rules_for("artists").len(), 1);
    assert_eq!(config.skip_conditions_for("artists").len(), 1);
    assert_eq!(config.filters_for("releases").len(), 1);
    // Check compiled values
    let skip = &config.skip_conditions_for("artists")[0];
    assert_eq!(skip.field, "profile");
    assert_eq!(skip.contains_lower, "do not use");
    let filter = &config.filters_for("releases")[0];
    assert_eq!(filter.field, "genres.genre");
    assert!(filter.remove_matching.is_match("123"));
    assert!(!filter.remove_matching.is_match("Rock"));
}

#[test]
fn test_yaml_without_skip_records_and_filters() {
    // Backward compat: existing configs with only `rules` still work
    let yaml = r#"
rules:
  artists:
    - name: name_required
      field: name
      condition: {type: required}
      severity: error
"#;
    let config = compile_yaml(yaml);
    assert_eq!(config.rules_for("artists").len(), 1);
    assert_eq!(config.skip_conditions_for("artists").len(), 0);
    assert_eq!(config.filters_for("artists").len(), 0);
}

#[test]
fn test_invalid_filter_regex_returns_error() {
    let yaml = r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "[invalid("
      reason: "bad regex"
"#;
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("genres.genre"), "Expected field name in error: {msg}");
}

#[test]
fn test_skip_records_validates_data_type() {
    let yaml = r#"
skip_records:
  foobar:
    - field: profile
      contains: "DO NOT USE"
      reason: "test"
"#;
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    let result = CompiledRulesConfig::compile(config);
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("foobar"), "Expected unknown type name in error: {msg}");
}

// ── Task 2: Skip Record Evaluation Logic ────────────────────────────

fn compile_skip_yaml(yaml: &str) -> CompiledRulesConfig {
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    CompiledRulesConfig::compile(config).unwrap()
}

#[test]
fn test_skip_record_contains_match() {
    let config = compile_skip_yaml(
        r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"
"#,
    );
    let record = json!({"profile": "[b]DO NOT USE.[/b] This is a junk entry."});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_some());
    let info = result.unwrap();
    assert_eq!(info.reason, "Upstream junk entry");
    assert_eq!(info.field, "profile");
    assert!(info.field_value.contains("DO NOT USE"));
}

#[test]
fn test_skip_record_case_insensitive() {
    let config = compile_skip_yaml(
        r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"
"#,
    );
    let record = json!({"profile": "do not use this entry"});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_some());
}

#[test]
fn test_skip_record_no_match() {
    let config = compile_skip_yaml(
        r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"
"#,
    );
    let record = json!({"profile": "This is a real artist with a valid profile."});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_none());
}

#[test]
fn test_skip_record_missing_field() {
    let config = compile_skip_yaml(
        r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"
"#,
    );
    let record = json!({"name": "Some Artist"});
    let result = should_skip_record(&config, "artists", &record);
    assert!(result.is_none());
}

#[test]
fn test_skip_record_no_conditions_for_data_type() {
    let config = compile_skip_yaml(
        r#"
skip_records:
  artists:
    - field: profile
      contains: "DO NOT USE"
      reason: "Upstream junk entry"
"#,
    );
    let record = json!({"profile": "DO NOT USE"});
    let result = should_skip_record(&config, "releases", &record);
    assert!(result.is_none());
}

// ── Task 3: Filter Evaluation Logic ─────────────────────────────────

fn compile_filter_yaml(yaml: &str) -> CompiledRulesConfig {
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    CompiledRulesConfig::compile(config).unwrap()
}

#[test]
fn test_filter_removes_numeric_genres() {
    let config = compile_filter_yaml(
        r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres are parsing artifacts"
"#,
    );
    let mut record = json!({"genres": {"genre": ["1", "1", "Electronic"]}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert_eq!(actions.len(), 1);
    assert_eq!(actions[0].removed_count, 2);
    assert_eq!(actions[0].removed_values, vec!["1", "1"]);
    assert_eq!(record["genres"]["genre"], json!(["Electronic"]));
}

#[test]
fn test_filter_preserves_non_matching() {
    let config = compile_filter_yaml(
        r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres"
"#,
    );
    let mut record = json!({"genres": {"genre": ["Rock", "Pop"]}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert!(actions.is_empty());
    assert_eq!(record["genres"]["genre"], json!(["Rock", "Pop"]));
}

#[test]
fn test_filter_empty_after_removal() {
    let config = compile_filter_yaml(
        r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres"
"#,
    );
    let mut record = json!({"genres": {"genre": ["1", "2", "3"]}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert_eq!(actions.len(), 1);
    assert_eq!(actions[0].removed_count, 3);
    assert_eq!(record["genres"]["genre"], json!([]));
}

#[test]
fn test_filter_no_match_field_missing() {
    let config = compile_filter_yaml(
        r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres"
"#,
    );
    let mut record = json!({"title": "Some Album"});
    let actions = apply_filters(&config, "releases", &mut record);
    assert!(actions.is_empty());
}

#[test]
fn test_filter_no_conditions_for_data_type() {
    let config = compile_filter_yaml(
        r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres"
"#,
    );
    let mut record = json!({"genres": {"genre": ["1", "2"]}});
    let actions = apply_filters(&config, "artists", &mut record);
    assert!(actions.is_empty());
    // Record should be unchanged
    assert_eq!(record["genres"]["genre"], json!(["1", "2"]));
}

#[test]
fn test_filter_single_string_genre_not_array() {
    let config = compile_filter_yaml(
        r#"
filters:
  releases:
    - field: genres.genre
      remove_matching: "^\\d+$"
      reason: "Numeric genres"
"#,
    );
    // genre is a single string, not an array — should be left untouched
    let mut record = json!({"genres": {"genre": "123"}});
    let actions = apply_filters(&config, "releases", &mut record);
    assert!(actions.is_empty());
    assert_eq!(record["genres"]["genre"], json!("123"));
}

// ── Task 4: QualityReport — Skipped Records Tracking ────────────────

#[test]
fn test_quality_report_skipped_records() {
    let mut report = QualityReport::new();
    report.record_skip("artists", "66827", "Upstream junk entry marked DO NOT USE");
    report.increment_total("artists");

    assert!(report.has_skipped_records());
    let skipped = report.skipped_records();
    assert_eq!(skipped["artists"].len(), 1);
    assert_eq!(skipped["artists"][0].record_id, "66827");

    let summary = report.format_summary("20260401");
    assert!(summary.contains("Skipped records:"));
    assert!(summary.contains("artists: 1"));
    assert!(summary.contains("66827"));
    assert!(summary.contains("Upstream junk entry marked DO NOT USE"));
}

#[test]
fn test_quality_report_merge_with_skips() {
    let mut report1 = QualityReport::new();
    report1.record_skip("artists", "100", "junk");

    let mut report2 = QualityReport::new();
    report2.record_skip("artists", "200", "junk");
    report2.record_skip("releases", "300", "bad release");

    report1.merge(report2);

    assert_eq!(report1.skipped["artists"].len(), 2);
    assert_eq!(report1.skipped["releases"].len(), 1);
}

#[test]
fn test_quality_report_no_skips_no_section() {
    let mut report = QualityReport::new();
    report.record_violation("releases", "test-rule", &Severity::Error);
    report.increment_total("releases");

    assert!(!report.has_skipped_records());
    let summary = report.format_summary("20260401");
    assert!(!summary.contains("Skipped records:"));
    assert!(summary.contains("releases:"));
}

// ── Task 5: FlaggedRecordWriter — write_skip Method ─────────────────

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
    let raw_xml = b"<artist id=\"66827\"><profile>[b]DO NOT USE.[/b]</profile></artist>";

    writer.write_skip("artists", "66827", &skip_info, Some(raw_xml.as_slice()), &parsed_json);
    writer.flush();

    let type_dir = temp_dir.path().join("flagged").join("20260401").join("artists");
    assert!(type_dir.join("66827.xml").exists(), "XML file should be created");
    assert!(type_dir.join("66827.json").exists(), "JSON file should be created");
    assert!(type_dir.join("skipped.jsonl").exists(), "skipped.jsonl should be created");
    assert!(!type_dir.join("violations.jsonl").exists(), "violations.jsonl should NOT be created");

    // Verify skipped.jsonl content
    let jsonl = std::fs::read_to_string(type_dir.join("skipped.jsonl")).unwrap();
    assert!(jsonl.contains("Upstream junk entry"));
    assert!(jsonl.contains("66827"));
    assert!(jsonl.contains("profile"));
}
