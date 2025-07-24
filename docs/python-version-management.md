# 🐍 Python Version Management

> Centralized Python version control across the entire Discogsography project

## Overview

This project uses a centralized approach to Python version management, ensuring consistency across all services, Docker builds, and CI/CD pipelines. The current Python version (3.13) can be updated from a single location.

## 🔧 Configuration Points

The Python version is configured in these locations:

| Location | Purpose | Auto-Updated |
|----------|---------|--------------|
| `.env` / `.env.example` | `PYTHON_VERSION` variable | ✅ Yes |
| `pyproject.toml` (root) | `requires-python` constraint | ✅ Yes |
| `*/pyproject.toml` | Service-specific constraints | ✅ Yes |
| `Dockerfile` files | Base image and build args | ✅ Yes |
| `.github/workflows/*.yml` | CI/CD environment | Via env var |
| `pyrightconfig.json` | Type checker version | ✅ Yes |

## 📝 How to Update Python Version

### Method 1: Using the Update Script (Recommended)

```bash
# Update to Python 3.14
./scripts/update-python-version.sh 3.14

# Preview changes without applying
./scripts/update-python-version.sh 3.14 --dry-run
```

The script will:

1. Update all `pyproject.toml` files
1. Update all Dockerfiles
1. Update pyrightconfig.json
1. Show a summary of changes
1. Remind you to update `.env` if needed

### Method 2: Environment Variable

Set in your `.env` file:

```bash
PYTHON_VERSION=3.14
```

This affects:

- Docker builds (via `--build-arg`)
- GitHub Actions workflows
- Local development (if using the env var)

### Method 3: Manual Updates

If updating manually, ensure you update:

1. **Root pyproject.toml**:

   ```toml
   [tool.poetry]
   requires-python = ">=3.14"

   [tool.ruff]
   target-version = "py314"

   [tool.mypy]
   python_version = "3.14"
   ```

1. **Service pyproject.toml files**:

   ```toml
   requires-python = ">=3.14"
   ```

1. **Dockerfiles**:

   ```dockerfile
   ARG PYTHON_VERSION=3.14
   FROM python:${PYTHON_VERSION}-slim
   ```

1. **pyrightconfig.json**:

   ```json
   {
     "pythonVersion": "3.14"
   }
   ```

## 🐳 Docker Build Args

All Dockerfiles accept a `PYTHON_VERSION` build argument:

```bash
# Build with specific Python version
docker build --build-arg PYTHON_VERSION=3.14 -f dashboard/Dockerfile .

# Or use docker-compose with .env
docker-compose build  # Uses PYTHON_VERSION from .env
```

## 🔄 GitHub Actions

The workflows use the `PYTHON_VERSION` environment variable:

```yaml
env:
  PYTHON_VERSION: "3.13"  # Set globally in workflow
```

To update CI/CD Python version:

1. Update `PYTHON_VERSION` in `.env`
1. Workflows will use this value automatically

## ✅ Version Compatibility

When updating Python versions, consider:

1. **Dependency Compatibility**: Check all dependencies support the new version
1. **Type Hints**: Newer Python versions may have enhanced type hint features
1. **Performance**: Newer versions often include performance improvements
1. **Security**: Always prefer supported Python versions

### Checking Compatibility

```bash
# Check if dependencies support new version
uv pip compile --python-version 3.14 pyproject.toml

# Test with new version
docker build --build-arg PYTHON_VERSION=3.14 -f dashboard/Dockerfile . --target test
```

## 🚨 Troubleshooting

### Issue: Version mismatch after update

```bash
# Ensure all files are updated
./scripts/update-python-version.sh 3.14

# Rebuild everything
docker-compose down
docker-compose build --no-cache
docker-compose up
```

### Issue: CI/CD using wrong version

1. Check `.env` file has correct `PYTHON_VERSION`
1. Ensure workflows don't override the version
1. Clear GitHub Actions cache if needed

### Issue: Local development version conflicts

```bash
# Reinstall with correct Python version
uv venv --python 3.14
uv sync --all-extras
```

## 📚 Best Practices

1. **Test Before Updating**: Run full test suite with new version
1. **Update Incrementally**: Prefer minor version updates (3.13 → 3.14)
1. **Document Breaking Changes**: Note any compatibility issues
1. **Coordinate Updates**: Ensure team is aware of version changes
1. **Monitor Performance**: Check for regressions after updates

## 🔗 Related Documentation

- [Docker Standards](dockerfile-standards.md) - Dockerfile best practices
- [Task Automation](task-automation.md) - Development workflow commands
- [CI/CD Workflows](../README.md#-github-actions) - GitHub Actions setup
