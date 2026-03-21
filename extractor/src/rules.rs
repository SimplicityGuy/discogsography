// Rule engine items are wired into the extraction pipeline in a subsequent task.
// The module is fully exercised by rules_tests; suppress dead-code lints until then.
#![allow(dead_code)]

use anyhow::{Context, Result};
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
        let canonical = path
            .canonicalize()
            .with_context(|| format!("Failed to resolve rules file path: {:?}", path))?;

        // Only allow YAML files to be loaded as rules configs.
        let ext = canonical.extension().and_then(|e| e.to_str()).unwrap_or("");
        anyhow::ensure!(
            ext == "yaml" || ext == "yml",
            "Rules file must have a .yaml or .yml extension, got: {:?}",
            canonical
        );

        // False positive: `canonical` is the result of `Path::canonicalize()` (symlinks and `..`
        // resolved) and the extension has been validated to `.yaml`/`.yml`. This is a CLI tool —
        // the path comes from operator config, not an HTTP request.
        let contents = std::fs::read_to_string(&canonical) // nosemgrep: rust.actix.path-traversal.tainted-path.tainted-path
            .with_context(|| format!("Failed to read rules file: {:?}", canonical))?;
        serde_yml::from_str(&contents)
            .with_context(|| format!("Failed to parse rules YAML: {:?}", canonical))
    }
}

impl CompiledRulesConfig {
    pub fn compile(config: RulesConfig) -> Result<Self> {
        let mut compiled = HashMap::new();
        for (key, rules) in config.rules {
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

#[cfg(test)]
#[path = "tests/rules_tests.rs"]
mod tests;
