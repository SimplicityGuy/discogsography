# Logging Configuration

This document describes the unified logging configuration across all Discogsography services.

## Overview

All services in the Discogsography platform use a consistent logging pattern controlled by the `LOG_LEVEL` environment variable. This ensures uniform behavior across Python and Rust services.

## Log Levels

The following log levels are supported across all services:

| Level | Description | Use Case |
|-------|-------------|----------|
| `DEBUG` | Detailed diagnostic information | Development and troubleshooting |
| `INFO` | General informational messages | Production (default) |
| `WARNING` | Warning messages for potential issues | Production monitoring |
| `ERROR` | Error messages for failures | Production alerts |
| `CRITICAL` | Critical errors requiring immediate attention | Production alerts |

**Default**: If `LOG_LEVEL` is not set, all services default to `INFO`.

## Configuration

### Environment Variable

Set the `LOG_LEVEL` environment variable to control logging verbosity:

```bash
# Development with debug logging
export LOG_LEVEL=DEBUG

# Production with info logging (default)
export LOG_LEVEL=INFO

# Error-only logging
export LOG_LEVEL=ERROR
```

### Docker Compose

```yaml
services:
  my-service:
    environment:
      LOG_LEVEL: INFO
```

### Docker Run

```bash
docker run -e LOG_LEVEL=DEBUG discogsography/service:latest
```

## Service-Specific Details

### Python Services

All Python services (extractor, graphinator, tableinator, dashboard, discovery) use the `setup_logging()` function from `common/config.py`:

```python
from common import setup_logging

# Reads from LOG_LEVEL environment variable, defaults to INFO
setup_logging("service_name", log_file=Path("/logs/service.log"))
```

**Features**:
- Structured JSON logging with emoji indicators
- Correlation IDs from contextvars
- Service-specific context (name, environment)
- File and console output
- Automatic suppression of verbose third-party logs

### Rust Extractor

The Rust extractor uses Rust's `tracing` framework and maps Python log levels to Rust equivalents:

| Python Level | Rust Level | Notes |
|--------------|------------|-------|
| DEBUG | debug | Detailed diagnostic info |
| INFO | info | General messages (default) |
| WARNING | warn | Warning messages |
| ERROR | error | Error messages |
| CRITICAL | error | Mapped to error (Rust has no critical) |

**Configuration**:

```bash
# Debug logging
LOG_LEVEL=DEBUG cargo run

# Production logging
LOG_LEVEL=INFO cargo run
```

**Implementation** (main.rs):

```rust
let log_level = std::env::var("LOG_LEVEL")
    .unwrap_or_else(|_| "INFO".to_string())
    .to_uppercase();

let rust_level = match log_level.as_str() {
    "DEBUG" => "debug",
    "INFO" => "info",
    "WARNING" | "WARN" => "warn",
    "ERROR" => "error",
    "CRITICAL" => "error",
    _ => "info"
};
```

## Log Format

### Python Services (JSON)

```json
{
  "timestamp": "2024-01-15T10:30:45.123456Z",
  "level": "info",
  "logger": "graphinator",
  "event": "🚀 Service starting...",
  "service": "graphinator",
  "environment": "production",
  "lineno": 1210
}
```

### Rust Extractor (JSON)

```json
{
  "timestamp": "2024-01-15T10:30:45.123456Z",
  "level": "INFO",
  "target": "rust_extractor",
  "message": "🚀 Starting Rust-based Discogs data extractor with high performance",
  "line": 59
}
```

## Emoji Indicators

All services use consistent emoji indicators for visual clarity:

- 🚀 Service starting
- ✅ Successful operations
- ❌ Errors and failures
- ⚠️ Warnings
- 📊 Progress updates
- 🔄 In-progress operations
- 🛑 Shutdown events
- 🏥 Health checks
- 📥 Download operations
- 🎉 Completion milestones

## Testing

### Python

```python
import os
import logging
from common import setup_logging

# Test with environment variable
os.environ['LOG_LEVEL'] = 'DEBUG'
setup_logging("test_service")
assert logging.getLogger().level == logging.DEBUG

# Test default behavior
del os.environ['LOG_LEVEL']
setup_logging("test_service")
assert logging.getLogger().level == logging.INFO
```

### Rust

```rust
// Tests in src/config.rs verify environment variable handling
#[test]
fn test_log_level_from_env() {
    std::env::set_var("LOG_LEVEL", "DEBUG");
    // Configuration should use DEBUG level
    std::env::remove_var("LOG_LEVEL");
}
```

## Troubleshooting

### Service not respecting LOG_LEVEL

1. **Check environment variable is set**:
   ```bash
   docker exec <container> printenv LOG_LEVEL
   ```

2. **Verify service startup logs**:
   ```bash
   docker logs <container> | head -20
   ```

3. **Check for explicit level parameter** (Python):
   ```python
   # This overrides LOG_LEVEL
   setup_logging("service", level="WARNING")
   ```

### Too much logging in production

1. Set `LOG_LEVEL=WARNING` or `LOG_LEVEL=ERROR`
2. Check third-party library log levels are suppressed (handled automatically)

### Not enough logging for debugging

1. Set `LOG_LEVEL=DEBUG`
2. Restart the service
3. Monitor logs: `docker logs -f <container>`

## Best Practices

1. **Development**: Use `DEBUG` for detailed diagnostic information
2. **Staging**: Use `INFO` to match production behavior
3. **Production**: Use `INFO` or `WARNING` depending on volume
4. **Incident Response**: Temporarily set to `DEBUG` for affected services
5. **Case Insensitive**: LOG_LEVEL values are case-insensitive (`debug` == `DEBUG`)
6. **Container Logs**: All logs go to stdout/stderr for container orchestration
7. **File Logs**: Python services also write to `/logs/<service>.log` inside containers

## Migration Notes

### From RUST_LOG (Rust Extractor)

**Old**:
```yaml
environment:
  RUST_LOG: rust_extractor=info,lapin=warn
```

**New**:
```yaml
environment:
  LOG_LEVEL: INFO
```

### From Verbose Flag (Rust Extractor)

**Old**:
```bash
cargo run --verbose
```

**New**:
```bash
LOG_LEVEL=DEBUG cargo run
```

## See Also

- [Logging Guide](logging-guide.md) - Detailed logging best practices
- [Emoji Guide](emoji-guide.md) - Complete emoji reference
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
