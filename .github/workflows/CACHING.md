# GitHub Workflows Caching Strategy

This document describes the caching strategy used across all GitHub workflows to optimize build times and reduce redundancy.

## Cache Categories

### 1. Python Dependencies Cache

**Key Pattern**: `${{ runner.os }}-python-${{ inputs.python-version }}-${{ hashFiles('**/uv.lock', '**/pyproject.toml') }}`
**Paths**:

- `~/.cache/uv` - uv package manager cache (also cached by `astral-sh/setup-uv` via `enable-cache: true`)
- `.venv` - Virtual environment

**Used in**: All workflows via `.github/actions/setup-python-uv/action.yml` composite action
**Rationale**: Shared across all workflows since they use the same dependencies

### 2. Test Results Cache

**Key Pattern**:

- Rust tests: `${{ runner.os }}-cargo-test-${{ hashFiles('**/Cargo.lock') }}`
- E2E tests: `${{ runner.os }}-test-e2e-${{ matrix.browser }}-${{ matrix.device || 'desktop' }}-${{ github.sha }}`

**Paths**:

- `.pytest_cache` - Pytest cache
- `.coverage` - Coverage data
- `htmlcov` - Coverage HTML report
- `test-results` - Test results directory (E2E tests only)

**Used in**: test.yml (Rust cache), e2e-test.yml (E2E cache)
**Rationale**: Separate caches for different test types to avoid conflicts

### 3. Pre-commit Cache

**Key Pattern**: `${{ runner.os }}-pre-commit-v3-${{ hashFiles('.pre-commit-config.yaml') }}`
**Paths**: `~/.cache/pre-commit`
**Used in**: code-quality.yml
**Rationale**: Only needed for code quality checks

### 4. Tools Cache

**Key Pattern**: `${{ runner.os }}-tools-arkade-v1`
**Paths**: `~/.arkade` - Arkade tools (hadolint)
**Used in**: code-quality.yml
**Rationale**: Avoids re-downloading hadolint on every run

### 5. Rust Dependencies Cache

**Key Pattern**: `${{ runner.os }}-cargo-{workflow}-${{ hashFiles('**/Cargo.lock') }}`
**Paths**:

- `~/.cargo/bin/`
- `~/.cargo/registry/index/`
- `~/.cargo/registry/cache/`
- `~/.cargo/git/db/`
- `extractor/target/`

**Used in**: code-quality.yml, test.yml, security.yml (each with a workflow-specific key prefix)
**Rationale**: Rust compilation is slow; caching avoids full rebuilds

### 6. Playwright Browsers Cache

**Key Pattern**: `${{ runner.os }}-playwright-browsers-${{ matrix.browser }}-v${{ hashFiles('**/pyproject.toml') }}`
**Paths**:

- `~/.cache/ms-playwright`
- `~/Library/Caches/ms-playwright`

**Used in**: e2e-test.yml
**Rationale**: Browser-specific caching for faster E2E test setup

### 7. Docker Build Cache

**Key Pattern**: `${{ runner.os }}-buildx-${{ inputs.service-name }}-${{ hashFiles(inputs.dockerfile-path) }}-${{ hashFiles('**/uv.lock') }}`
**Paths**: `${{ runner.temp }}/.buildx-cache`
**Used in**: build.yml via `.github/actions/docker-build-cache/action.yml` composite action
**Rationale**: Service-specific Docker layer caching; keys are based on Dockerfile and lockfile content so cache is reused across commits when dependencies haven't changed

## Cache Restoration Strategy

All caches use a hierarchical restore-keys pattern:

1. Most specific key (exact match)
1. Version-specific fallback
1. General fallback

Example:

```yaml
key: ${{ runner.os }}-python-${{ inputs.python-version }}-${{ hashFiles('**/uv.lock', '**/pyproject.toml') }}
restore-keys: |
  ${{ runner.os }}-python-${{ inputs.python-version }}-
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

- Dependencies change (uv.lock, pyproject.toml, Cargo.lock)
- Tool versions change
- Configuration files change (.pre-commit-config.yaml)
- New commits are pushed (for test and build caches)
