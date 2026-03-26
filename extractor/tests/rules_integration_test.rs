//! Integration tests for data quality rules.

use extractor::rules::{CompiledRulesConfig, FlaggedRecordWriter, RulesConfig, Severity, Violation, evaluate_rules};
use extractor::types::DataMessage;
use serde_json::json;
use std::sync::Arc;
use tempfile::TempDir;

fn compile_rules(yaml: &str) -> Arc<CompiledRulesConfig> {
    let config: RulesConfig = serde_yaml_ng::from_str(yaml).unwrap();
    Arc::new(CompiledRulesConfig::compile(config).unwrap())
}

#[test]
fn test_issue_182_bad_data_detected() {
    let rules = compile_rules(
        r#"
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
"#,
    );

    // Genre "1" — should trigger genre-is-numeric and genre-not-recognized
    let record = json!({"@id": "12345", "genres": {"genre": "1"}, "year": "1990"});
    let violations = evaluate_rules(&rules, "releases", &record);
    let rule_names: Vec<&str> = violations.iter().map(|v| v.rule_name.as_str()).collect();
    assert!(rule_names.contains(&"genre-is-numeric"));
    assert!(rule_names.contains(&"genre-not-recognized"));

    // Year 197 — should trigger year-out-of-range
    let record = json!({"@id": "67890", "genres": {"genre": "Jazz"}, "year": "197"});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert!(violations.iter().any(|v| v.rule_name == "year-out-of-range"));

    // Year 338 — should trigger year-out-of-range
    let record = json!({"@id": "11111", "genres": {"genre": "Electronic"}, "year": "338"});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert!(violations.iter().any(|v| v.rule_name == "year-out-of-range"));

    // Clean record — no violations
    let record = json!({"@id": "99999", "genres": {"genre": "Rock"}, "year": "1995"});
    let violations = evaluate_rules(&rules, "releases", &record);
    assert!(violations.is_empty());
}

#[test]
fn test_flagged_record_storage() {
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

    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("releases");
    assert!(flagged_dir.join("12345.xml").exists());
    assert!(flagged_dir.join("12345.json").exists());
    assert!(flagged_dir.join("violations.jsonl").exists());

    let jsonl = std::fs::read_to_string(flagged_dir.join("violations.jsonl")).unwrap();
    assert!(jsonl.contains("genre-is-numeric"));
    assert!(jsonl.contains("12345"));

    // Second violation for same record — should not duplicate files
    let violation2 = Violation {
        rule_name: "genre-not-recognized".to_string(),
        severity: Severity::Warning,
        field: "genres.genre".to_string(),
        field_value: "1".to_string(),
    };
    writer.write_violation("releases", "12345", &violation2, Some(raw_xml), &parsed_json, true);
    writer.flush();

    let jsonl = std::fs::read_to_string(flagged_dir.join("violations.jsonl")).unwrap();
    let lines: Vec<&str> = jsonl.trim().lines().collect();
    assert_eq!(lines.len(), 2, "Should have 2 violation entries");
}

#[test]
fn test_pipeline_without_rules_unchanged() {
    let message = DataMessage { id: "1".to_string(), sha256: "abc".to_string(), data: json!({"name": "test"}), raw_xml: None };
    let serialized = serde_json::to_string(&message).unwrap();
    assert!(!serialized.contains("raw_xml"));
}

// ── FlaggedRecordWriter edge cases ───────────────────────────────────

#[test]
fn test_write_violation_info_severity_no_files() {
    // Info severity with capture_files=false: JSONL should be written but no XML/JSON files
    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let violation = Violation {
        rule_name: "info-rule".to_string(),
        severity: extractor::rules::Severity::Info,
        field: "some.field".to_string(),
        field_value: "some-value".to_string(),
    };

    let parsed_json = json!({"@id": "99", "some": {"field": "some-value"}});
    let raw_xml = b"<artist id=\"99\"><some><field>some-value</field></some></artist>";

    // capture_files=false — XML/JSON files should NOT be written
    writer.write_violation("artists", "99", &violation, Some(raw_xml), &parsed_json, false);
    writer.flush();

    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("artists");

    // JSONL must exist (always written)
    assert!(flagged_dir.join("violations.jsonl").exists(), "violations.jsonl should always be written");

    // XML and JSON files must NOT exist when capture_files=false
    assert!(!flagged_dir.join("99.xml").exists(), "XML file should NOT be written when capture_files=false");
    assert!(!flagged_dir.join("99.json").exists(), "JSON file should NOT be written when capture_files=false");

    // JSONL must contain the violation
    let jsonl = std::fs::read_to_string(flagged_dir.join("violations.jsonl")).unwrap();
    assert!(jsonl.contains("info-rule"), "JSONL should contain rule name");
    assert!(jsonl.contains("99"), "JSONL should contain record id");
    assert!(jsonl.contains("info"), "JSONL should contain severity");
}

#[test]
fn test_write_violation_capture_files_true_writes_xml_and_json() {
    // Confirm that capture_files=true writes both XML and JSON files (positive case for
    // the capture_files branch, complementing the false-case above)
    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");

    let violation = Violation {
        rule_name: "error-rule".to_string(),
        severity: extractor::rules::Severity::Error,
        field: "name".to_string(),
        field_value: "".to_string(),
    };

    let parsed_json = json!({"@id": "55", "name": ""});
    let raw_xml = b"<label id=\"55\"><name></name></label>";

    writer.write_violation("labels", "55", &violation, Some(raw_xml), &parsed_json, true);
    writer.flush();

    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("labels");
    assert!(flagged_dir.join("55.xml").exists(), "XML file should be written when capture_files=true");
    assert!(flagged_dir.join("55.json").exists(), "JSON file should be written when capture_files=true");
    assert!(flagged_dir.join("violations.jsonl").exists(), "violations.jsonl should be written");
}

// ── QualityReport edge cases ─────────────────────────────────────────

#[test]
fn test_has_violations_returns_false_when_empty() {
    let report = extractor::rules::QualityReport::new();
    assert!(!report.has_violations(), "empty report should have no violations");
}

#[test]
fn test_has_violations_returns_false_after_only_totals() {
    // Incrementing total records without recording any violations must not flip has_violations
    let mut report = extractor::rules::QualityReport::new();
    report.increment_total("releases");
    report.increment_total("releases");
    report.increment_total("artists");
    assert!(!report.has_violations(), "report with totals but no violations should return false");
}

#[test]
fn test_format_summary_data_type_with_totals_but_no_violations() {
    // A data type that has total records but zero rule violations should appear in the
    // summary with "0 errors, 0 warnings (of N records)"
    let mut report = extractor::rules::QualityReport::new();
    // releases has violations, but masters only has totals
    report.record_violation("releases", "genre-is-numeric", &extractor::rules::Severity::Error);
    report.increment_total("releases");
    report.increment_total("masters");
    report.increment_total("masters");

    let summary = report.format_summary("20260301");

    // releases should show the violation
    assert!(summary.contains("releases:"), "summary should mention releases");
    assert!(summary.contains("1 errors"), "summary should show 1 error for releases");

    // masters has totals but no rule violations — should show 0 errors/warnings
    assert!(summary.contains("masters:"), "summary should mention masters with totals");
    assert!(summary.contains("0 errors, 0 warnings (of 2 records)"), "masters should show 0 violations of 2 records");
}

#[test]
fn test_format_summary_no_violations_message() {
    let report = extractor::rules::QualityReport::new();
    let summary = report.format_summary("20260301");
    assert!(summary.contains("No data quality violations"), "empty report summary should say no violations");
    assert!(summary.contains("20260301"), "summary should include the version string");
}

#[test]
fn test_quality_report_info_severity_counted() {
    // Verify that info severity violations are counted and appear in format_summary
    let mut report = extractor::rules::QualityReport::new();
    report.record_violation("artists", "long-name", &extractor::rules::Severity::Info);
    report.increment_total("artists");

    assert!(report.has_violations(), "info violation should count as a violation");

    let summary = report.format_summary("20260301");
    assert!(summary.contains("long-name"), "summary should include the rule name");
    assert!(summary.contains("1 info"), "summary should show 1 info count");
}

#[test]
fn test_evaluate_rules_with_combined_writer_and_report() {
    // Exercise evaluate_rules + FlaggedRecordWriter + QualityReport together
    // (simulates what the message_validator pipeline does per-record)
    let rules = compile_rules(
        r#"
rules:
  artists:
    - name: name-required
      field: name
      condition:
        type: required
      severity: error
    - name: profile-length
      field: profile
      condition:
        type: length
        min: 1
        max: 200
      severity: info
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let mut writer = FlaggedRecordWriter::new(temp_dir.path(), "20260301");
    let mut report = extractor::rules::QualityReport::new();

    // Record 1: missing name (error), no profile (no violation on profile since field absent)
    let record1 = json!({"@id": "1"});
    let raw_xml1 = b"<artist id=\"1\"></artist>";
    let violations1 = evaluate_rules(&rules, "artists", &record1);
    report.increment_total("artists");
    for v in &violations1 {
        report.record_violation("artists", &v.rule_name, &v.severity);
        let capture = matches!(v.severity, extractor::rules::Severity::Error | extractor::rules::Severity::Warning);
        writer.write_violation("artists", "1", v, Some(raw_xml1), &record1, capture);
    }

    // Record 2: has name, profile too long → info violation, capture_files=false
    let long_profile = "x".repeat(250);
    let record2 = json!({"@id": "2", "name": "Test Artist", "profile": long_profile});
    let raw_xml2 = b"<artist id=\"2\"><name>Test Artist</name></artist>";
    let violations2 = evaluate_rules(&rules, "artists", &record2);
    report.increment_total("artists");
    for v in &violations2 {
        report.record_violation("artists", &v.rule_name, &v.severity);
        let capture = matches!(v.severity, extractor::rules::Severity::Error | extractor::rules::Severity::Warning);
        writer.write_violation("artists", "2", v, Some(raw_xml2), &record2, capture);
    }

    writer.flush();

    // Record 1 had a name-required error → capture_files=true → XML/JSON written
    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("artists");
    assert!(flagged_dir.join("1.xml").exists(), "error-severity record 1 should have XML file");
    assert!(flagged_dir.join("1.json").exists(), "error-severity record 1 should have JSON file");

    // Record 2 had a profile-length info → capture_files=false → no XML/JSON
    assert!(!flagged_dir.join("2.xml").exists(), "info-severity record 2 should NOT have XML file");
    assert!(!flagged_dir.join("2.json").exists(), "info-severity record 2 should NOT have JSON file");

    assert!(report.has_violations(), "report should have violations");
    let summary = report.format_summary("20260301");
    assert!(summary.contains("name-required"), "summary should mention name-required");
    assert!(summary.contains("profile-length"), "summary should mention profile-length");
    assert!(summary.contains("(of 2 records)"), "summary should show 2 total records");
}

// ── message_validator async pipeline test ────────────────────────────

#[tokio::test]
async fn test_message_validator_forwards_all_messages() {
    use extractor::extractor::message_validator;
    use tokio::sync::mpsc;

    let rules = compile_rules(
        r#"
rules:
  artists:
    - name: name-required
      field: name
      condition:
        type: required
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (in_tx, in_rx) = mpsc::channel::<DataMessage>(10);
    let (out_tx, mut out_rx) = mpsc::channel::<DataMessage>(10);

    // Spawn the validator
    let handle = tokio::spawn({
        let rules = rules.clone();
        let root = temp_dir.path().to_path_buf();
        async move { message_validator(in_rx, out_tx, rules, "artists", &root, "20260301").await }
    });

    // Send 3 messages: 1 bad (missing name), 2 clean
    let bad = DataMessage {
        id: "1".to_string(),
        sha256: "aaa".to_string(),
        data: json!({"@id": "1", "profile": "no name"}),
        raw_xml: Some(b"<artist id=\"1\"><profile>no name</profile></artist>".to_vec()),
    };
    let good1 = DataMessage {
        id: "2".to_string(),
        sha256: "bbb".to_string(),
        data: json!({"@id": "2", "name": "Artist Two"}),
        raw_xml: Some(b"<artist id=\"2\"><name>Artist Two</name></artist>".to_vec()),
    };
    let good2 = DataMessage { id: "3".to_string(), sha256: "ccc".to_string(), data: json!({"@id": "3", "name": "Artist Three"}), raw_xml: None };

    in_tx.send(bad).await.unwrap();
    in_tx.send(good1).await.unwrap();
    in_tx.send(good2).await.unwrap();
    drop(in_tx); // Close channel so validator exits

    // All 3 messages should pass through
    let mut received = Vec::new();
    while let Some(msg) = out_rx.recv().await {
        received.push(msg);
    }
    assert_eq!(received.len(), 3, "All messages should be forwarded regardless of violations");
    assert_eq!(received[0].id, "1");
    assert_eq!(received[1].id, "2");
    assert_eq!(received[2].id, "3");

    // Check the report
    let report = handle.await.unwrap().unwrap();
    assert!(report.has_violations());
    let summary = report.format_summary("20260301");
    assert!(summary.contains("name-required"));
    assert!(summary.contains("1 errors"));
    assert!(summary.contains("(of 3 records)"));

    // Check flagged files were written for the bad record
    let flagged_dir = temp_dir.path().join("flagged").join("20260301").join("artists");
    assert!(flagged_dir.join("1.xml").exists(), "Bad record should have XML file");
    assert!(flagged_dir.join("1.json").exists(), "Bad record should have JSON file");
    assert!(!flagged_dir.join("2.xml").exists(), "Clean record should NOT have XML file");
    assert!(!flagged_dir.join("3.xml").exists(), "Clean record should NOT have XML file");
}

#[tokio::test]
async fn test_message_validator_no_violations_clean_report() {
    use extractor::extractor::message_validator;
    use tokio::sync::mpsc;

    let rules = compile_rules(
        r#"
rules:
  releases:
    - name: year-check
      field: year
      condition:
        type: range
        min: 1860
        max: 2027
      severity: warning
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (in_tx, in_rx) = mpsc::channel::<DataMessage>(10);
    let (out_tx, mut out_rx) = mpsc::channel::<DataMessage>(10);

    let handle = tokio::spawn({
        let rules = rules.clone();
        let root = temp_dir.path().to_path_buf();
        async move { message_validator(in_rx, out_tx, rules, "releases", &root, "20260301").await }
    });

    let msg = DataMessage { id: "1".to_string(), sha256: "aaa".to_string(), data: json!({"@id": "1", "year": "1990"}), raw_xml: None };
    in_tx.send(msg).await.unwrap();
    drop(in_tx);

    let mut received = Vec::new();
    while let Some(msg) = out_rx.recv().await {
        received.push(msg);
    }
    assert_eq!(received.len(), 1);

    let report = handle.await.unwrap().unwrap();
    assert!(!report.has_violations());
}

#[tokio::test]
async fn test_message_validator_downstream_dropped() {
    use extractor::extractor::message_validator;
    use tokio::sync::mpsc;

    let rules = compile_rules(
        r#"
rules:
  artists:
    - name: test
      field: name
      condition:
        type: required
      severity: error
"#,
    );

    let temp_dir = TempDir::new().unwrap();
    let (in_tx, in_rx) = mpsc::channel::<DataMessage>(10);
    let (out_tx, out_rx) = mpsc::channel::<DataMessage>(1);

    // Drop the receiver immediately so validator hits the "downstream dropped" path
    drop(out_rx);

    let handle = tokio::spawn({
        let rules = rules.clone();
        let root = temp_dir.path().to_path_buf();
        async move { message_validator(in_rx, out_tx, rules, "artists", &root, "20260301").await }
    });

    let msg = DataMessage { id: "1".to_string(), sha256: "aaa".to_string(), data: json!({"@id": "1", "name": "Test"}), raw_xml: None };
    in_tx.send(msg).await.unwrap();
    drop(in_tx);

    // Validator should still complete without error
    let report = handle.await.unwrap().unwrap();
    assert!(!report.has_violations());
}
