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
