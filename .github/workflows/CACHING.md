# GitHub Workflows Caching Strategy

This document describes the caching strategy used across all GitHub workflows to optimize build times and reduce redundancy.

## Cache Categories

### 1. Python Dependencies Cache

**Key Pattern**: `${{ runner.os }}-python-${{ env.PYTHON_VERSION }}-${{ hashFiles('**/uv.lock', '**/pyproject.toml') }}`
**Paths**:

- `~/.cache/uv` - uv package manager cache
- `.venv` - Virtual environment

**Used in**: All workflows that install Python dependencies
**Rationale**: Shared across all workflows since they use the same dependencies

### 2. Test Results Cache

**Key Pattern**:

- Unit tests: `${{ runner.os }}-test-unit-${{ github.sha }}`
- E2E tests: `${{ runner.os }}-test-e2e-${{ matrix.browser }}-${{ matrix.device || 'desktop' }}-${{ github.sha }}`

**Paths**:

- `.pytest_cache` - Pytest cache
- `.coverage` - Coverage data (unit tests only)
- `htmlcov` - Coverage HTML report (unit tests only)
- `test-results` - Test results directory (E2E tests only)

**Used in**: test.yml, e2e-test.yml
**Rationale**: Separate caches for different test types to avoid conflicts

### 3. Pre-commit Cache

**Key Pattern**: `${{ runner.os }}-pre-commit-${{ hashFiles('.pre-commit-config.yaml') }}`
**Paths**: `~/.cache/pre-commit`
**Used in**: code-quality.yml
**Rationale**: Only needed for code quality checks

### 4. Tools Cache

**Key Pattern**:

- Arkade: `${{ runner.os }}-tools-arkade-v1`
- Docker Compose: `${{ runner.os }}-tools-docker-compose-${{ env.COMPOSE_VERSION }}`

**Paths**:

- `~/.arkade` - Arkade tools
- `/usr/local/bin/docker-compose` - Docker Compose binary

**Used in**: code-quality.yml, docker-validate.yml
**Rationale**: Version-specific tool caching

### 5. Playwright Browsers Cache

**Key Pattern**: `${{ runner.os }}-playwright-browsers-${{ matrix.browser }}-v${{ hashFiles('**/pyproject.toml') }}`
**Paths**:

- `~/.cache/ms-playwright`
- `~/Library/Caches/ms-playwright`

**Used in**: e2e-test.yml
**Rationale**: Browser-specific caching for faster E2E test setup

### 6. Docker Build Cache

**Key Pattern**: `${{ runner.os }}-docker-buildx-${{ matrix.sub-project }}-${{ github.sha }}`
**Paths**: `/tmp/.buildx-cache`
**Used in**: build.yml
**Rationale**: Service-specific Docker layer caching

## Cache Restoration Strategy

All caches use a hierarchical restore-keys pattern:

1. Most specific key (exact match)
1. Version-specific fallback
1. General fallback

Example:

```yaml
key: ${{ runner.os }}-python-${{ env.PYTHON_VERSION }}-${{ hashFiles('**/uv.lock', '**/pyproject.toml') }}
restore-keys: |
  ${{ runner.os }}-python-${{ env.PYTHON_VERSION }}-
  ${{ runner.os }}-python-
```

## Best Practices

1. **Consistent Naming**: All cache names follow the pattern `{os}-{category}-{specifics}`
1. **Version Pinning**: Include version numbers in cache keys for tools and dependencies
1. **Hierarchical Restoration**: Always provide fallback keys for partial cache hits
1. **Descriptive Comments**: Each cache block has a comment explaining its purpose
1. **Shared Dependencies**: Python dependencies use the same cache key across workflows

## Cache Invalidation

Caches are automatically invalidated when:

- Dependencies change (uv.lock, pyproject.toml)
- Tool versions change
- Configuration files change (.pre-commit-config.yaml)
- New commits are pushed (for test and build caches)
