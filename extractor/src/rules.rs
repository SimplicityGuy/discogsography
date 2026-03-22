// Rule engine items are wired into the extraction pipeline in a subsequent task.
// The module is fully exercised by rules_tests; suppress dead-code lints until then.
#![allow(dead_code)]

use anyhow::{Context, Result};
use regex::Regex;
use serde::Deserialize;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;
use std::fs;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

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
    Range { min: Option<f64>, max: Option<f64> },
    Required,
    Regex { pattern: String },
    Length { min: Option<usize>, max: Option<usize> },
    Enum { values: Vec<String> },
}

// ── Compiled types (used at evaluation time) ────────────────────────

#[derive(Debug)]
pub struct CompiledRulesConfig {
    rules: HashMap<String, Vec<CompiledRule>>,
}

#[derive(Debug)]
pub struct CompiledRule {
    pub name: String,
    pub description: Option<String>,
    pub field: String,
    pub condition: CompiledCondition,
    pub severity: Severity,
}

#[derive(Debug)]
pub enum CompiledCondition {
    Range { min: Option<f64>, max: Option<f64> },
    Required,
    Regex { regex: Regex },
    Length { min: Option<usize>, max: Option<usize> },
    Enum { values: HashSet<String> },
}

impl RulesConfig {
    pub fn load(path: &Path) -> Result<Self> {
        // Canonicalize resolves symlinks and `..` components, preventing path traversal.
        let canonical = path.canonicalize().with_context(|| format!("Failed to resolve rules file path: {:?}", path))?;

        // Only allow YAML files to be loaded as rules configs.
        let ext = canonical.extension().and_then(|e| e.to_str()).unwrap_or("");
        anyhow::ensure!(ext == "yaml" || ext == "yml", "Rules file must have a .yaml or .yml extension, got: {:?}", canonical);

        // False positive: `canonical` is the result of `Path::canonicalize()` (symlinks and `..`
        // resolved) and the extension has been validated to `.yaml`/`.yml`. This is a CLI tool —
        // the path comes from operator config, not an HTTP request.
        let contents = std::fs::read_to_string(&canonical) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            .with_context(|| format!("Failed to read rules file: {:?}", canonical))?;
        serde_yml::from_str(&contents).with_context(|| format!("Failed to parse rules YAML: {:?}", canonical))
    }
}

impl CompiledRulesConfig {
    pub fn compile(config: RulesConfig) -> Result<Self> {
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
        Ok(Self { rules: compiled })
    }

    pub fn rules_for(&self, data_type: &str) -> &[CompiledRule] {
        self.rules.get(data_type).map(|v| v.as_slice()).unwrap_or(&[])
    }
}

// ── Evaluation ──────────────────────────────────────────────────────

use serde_json::Value;

#[derive(Debug, Clone)]
pub struct Violation {
    pub rule_name: String,
    pub severity: Severity,
    pub field: String,
    pub field_value: String,
}

pub fn evaluate_rules(config: &CompiledRulesConfig, data_type: &str, record: &Value) -> Vec<Violation> {
    let rules = config.rules_for(data_type);
    let mut violations = Vec::new();
    for rule in rules {
        let field_values = resolve_field(record, &rule.field);
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

fn resolve_field(value: &Value, field: &str) -> Vec<String> {
    let segments: Vec<&str> = field.split('.').collect();
    let mut current_values = vec![value.clone()];
    for segment in &segments {
        let mut next_values = Vec::new();
        for val in &current_values {
            if let Value::Object(map) = val
                && let Some(child) = map.get(*segment)
            {
                match child {
                    Value::Array(arr) => next_values.extend(arr.iter().cloned()),
                    other => next_values.push(other.clone()),
                }
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

fn check_condition(condition: &CompiledCondition, value: &str) -> bool {
    match condition {
        CompiledCondition::Range { min, max } => {
            if let Ok(num) = value.parse::<f64>() {
                if let Some(min_val) = min
                    && num < *min_val
                {
                    return true;
                }
                if let Some(max_val) = max
                    && num > *max_val
                {
                    return true;
                }
                false
            } else {
                false
            }
        }
        CompiledCondition::Required => unreachable!(),
        CompiledCondition::Regex { regex } => regex.is_match(value),
        CompiledCondition::Length { min, max } => {
            let len = value.len();
            if let Some(min_val) = min
                && len < *min_val
            {
                return true;
            }
            if let Some(max_val) = max
                && len > *max_val
            {
                return true;
            }
            false
        }
        CompiledCondition::Enum { values } => !values.contains(value),
    }
}

// ── Quality Report ──────────────────────────────────────────────────

#[derive(Debug, Default)]
pub struct RuleCounts {
    pub errors: u64,
    pub warnings: u64,
    pub info: u64,
}

#[derive(Debug, Default)]
pub struct QualityReport {
    /// data_type -> rule_name -> counts (BTreeMap for deterministic output ordering)
    pub counts: HashMap<String, BTreeMap<String, RuleCounts>>,
    /// data_type -> total records evaluated
    pub total_records: HashMap<String, u64>,
}

impl QualityReport {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn record_violation(&mut self, data_type: &str, rule_name: &str, severity: &Severity) {
        let rule_counts = self.counts.entry(data_type.to_string()).or_default().entry(rule_name.to_string()).or_default();
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
        self.counts.values().any(|rules| rules.values().any(|c| c.errors > 0 || c.warnings > 0 || c.info > 0))
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
}

// ── Flagged Record Writer ───────────────────────────────────────────

pub struct FlaggedRecordWriter {
    base_dir: PathBuf,
    written_records: HashSet<String>,
    jsonl_writers: HashMap<String, BufWriter<std::fs::File>>,
}

/// Sanitize a value from parsed data for use as a filename component.
/// Retains only alphanumeric characters, hyphens, underscores, and dots;
/// removes path separators and `..` traversal sequences entirely.
fn sanitize_filename(raw: &str) -> String {
    raw.chars()
        .filter(|c| c.is_alphanumeric() || matches!(c, '-' | '_' | '.'))
        .collect::<String>()
        // Collapse any remaining `..` that could still traverse after filtering
        .replace("..", "_")
}

impl FlaggedRecordWriter {
    pub fn new(discogs_root: &Path, version: &str) -> Self {
        Self {
            // `discogs_root` and `version` come from operator-controlled config, not user input.
            base_dir: discogs_root.join("flagged").join(version), // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            written_records: HashSet::new(),
            jsonl_writers: HashMap::new(),
        }
    }

    /// Write violation to JSONL log. If capture_files is true, also write XML/JSON files.
    pub fn write_violation(
        &mut self,
        data_type: &str,
        record_id: &str,
        violation: &Violation,
        raw_xml: Option<&[u8]>,
        parsed_json: &Value,
        capture_files: bool,
    ) {
        // `data_type` is always one of the four enum variants ("artists", "labels",
        // "masters", "releases") — validated upstream via DataType::as_str().
        let type_dir = self.base_dir.join(data_type); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path

        if let Err(e) = fs::create_dir_all(&type_dir) {
            tracing::warn!("⚠️ Failed to create flagged directory {:?}: {}", type_dir, e);
            return;
        }

        // Sanitize record_id before using it in any file path — it originates from
        // parsed XML data and must not be allowed to traverse directories.
        let safe_id = sanitize_filename(record_id);

        // Write XML and JSON files once per record (only for error/warning)
        if capture_files {
            let record_key = format!("{}:{}", data_type, safe_id);
            if !self.written_records.contains(&record_key) {
                if let Some(xml_bytes) = raw_xml {
                    let xml_path = type_dir.join(format!("{}.xml", safe_id));
                    if let Err(e) = fs::write(&xml_path, xml_bytes) {
                        tracing::warn!("⚠️ Failed to write flagged XML {:?}: {}", xml_path, e);
                    }
                }
                let json_path = type_dir.join(format!("{}.json", safe_id));
                if let Err(e) = fs::write(&json_path, serde_json::to_string_pretty(parsed_json).unwrap_or_default()) {
                    tracing::warn!("⚠️ Failed to write flagged JSON {:?}: {}", json_path, e);
                }
                self.written_records.insert(record_key);
            }
        }

        // Append to violations.jsonl — path is fully under base_dir/data_type (both operator-
        // controlled); the filename "violations.jsonl" is a literal constant.
        if !self.jsonl_writers.contains_key(data_type) {
            let jsonl_path = type_dir.join("violations.jsonl");
            match fs::OpenOptions::new().create(true).append(true).open(&jsonl_path) {
                // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
                Ok(file) => {
                    self.jsonl_writers.insert(data_type.to_string(), BufWriter::new(file));
                }
                Err(e) => {
                    tracing::warn!("⚠️ Failed to open violations.jsonl {:?}: {}", jsonl_path, e);
                    return;
                }
            }
        }
        let writer = self.jsonl_writers.get_mut(data_type).unwrap();

        let entry = serde_json::json!({
            "record_id": record_id,
            "rule": violation.rule_name,
            "severity": violation.severity.to_string(),
            "field": violation.field,
            "field_value": violation.field_value,
            "xml_file": format!("{}.xml", safe_id),
            "json_file": format!("{}.json", safe_id),
            "timestamp": chrono::Utc::now().to_rfc3339(),
        });
        if let Err(e) = writeln!(writer, "{}", serde_json::to_string(&entry).unwrap_or_default()) {
            tracing::warn!("⚠️ Failed to write violation entry: {}", e);
        }
    }

    pub fn flush(&mut self) {
        for writer in self.jsonl_writers.values_mut() {
            let _ = writer.flush();
        }
    }

    pub fn write_report(&self, report: &QualityReport, version: &str) {
        if let Err(e) = fs::create_dir_all(&self.base_dir) {
            tracing::warn!("⚠️ Failed to create flagged directory: {}", e);
            return;
        }
        // `self.base_dir` is built from operator config in `new()` — not user input.
        let report_path = self.base_dir.join("report.txt"); // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
        if let Err(e) = fs::write(&report_path, report.format_summary(version)) {
            tracing::warn!("⚠️ Failed to write quality report: {}", e);
        }
    }
}

#[cfg(test)]
#[path = "tests/rules_tests.rs"]
mod tests;
