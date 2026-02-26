# 🚀 GitHub Actions Guide

<div align="center">

**Comprehensive guide to Discogsography's CI/CD workflows and automation**

[📋 Workflows](#-workflows) | [🔧 Composite Actions](#-composite-actions) | [⚡ Performance](#-performance-optimizations) |
[🛡️ Security](#-security-features) | [🎯 Best Practices](#-best-practices)

</div>

## 📋 Workflows

Discogsography uses GitHub Actions for continuous integration, testing, and deployment automation. All workflows follow
consistent patterns with emojis for visual clarity and optimal performance through parallelization and caching.

### 🏗️ Build Workflow (`build.yml`)

**Trigger**: Push to main, PRs, weekly schedule **Purpose**: Main CI pipeline that orchestrates all quality checks and
Docker builds

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 1 * * 6"  # Weekly on Saturday
```

**Jobs**:

1. **Code Quality** ✅ - Runs linting and formatting checks
1. **Tests** 🧪 - Executes unit and integration tests (parallel with E2E)
1. **E2E Tests** 🎭 - Browser-based testing (parallel with unit tests)
1. **Docker Build** 🐳 - Builds and pushes images to GitHub Container Registry

**Key Features**:

- ⚡ Parallel test execution for faster feedback
- 💾 Advanced Docker layer caching
- 📊 Build metrics and performance tracking
- 📢 Discord notifications with build status

### 🧹 Code Quality Workflow (`code-quality.yml`)

**Trigger**: Push/PR on Python files, configs, or Dockerfiles **Purpose**: Ensures code quality standards are met

**Checks**:

- 🎨 **Ruff** - Fast Python linting and formatting
- 🔍 **mypy** - Static type checking
- 🛡️ **Bandit** - Security vulnerability scanning
- 🐳 **Hadolint** - Dockerfile best practices
- ✅ **Pre-commit hooks** - All configured checks

### 🧪 Test Workflow (`test.yml`)

**Trigger**: Push/PR on Python files **Purpose**: Runs comprehensive test suite

**Features**:

- 🎯 Smart test detection - skips if no relevant changes
- 📊 Coverage reporting with pytest-cov
- 💾 Test result caching
- 🔄 Grouped test execution to avoid async conflicts

### 🎭 E2E Test Workflow (`e2e-test.yml`)

**Trigger**: Dashboard or test changes **Purpose**: Cross-browser end-to-end testing

**Test Matrix**:

- 🌐 **Browsers**: Chromium, Firefox, WebKit
- 📱 **Devices**: iPhone 15, iPad Pro 11
- 🖥️ **Platforms**: Ubuntu, macOS

**Features**:

- 🎥 Video recording on failures
- 📸 Screenshot artifacts
- ⚡ Concurrent test limiting (max 3)
- 💾 Browser caching for faster runs

### 🔄 Update Dependencies (`update-dependencies.yml`)

**Trigger**: Weekly schedule (Monday 9 AM UTC) or manual **Purpose**: Automated dependency updates with PR creation

**Options**:

- 🐍 Python version updates
- 📦 Major version upgrades
- 🔒 Security patch application

**Process**:

1. Runs update script
1. Creates PR with detailed summary
1. Assigns reviewers
1. Sends Discord notification

### 🛡️ Security Workflow (`security.yml`)

**Trigger**: Called by `build.yml`, weekly schedule (Monday 04:00 UTC) **Purpose**: Comprehensive
security scanning across Python, Rust, secrets, and containers

**Jobs**:

1. **Python Security** 🐍 — `pip-audit` (dependency vulnerabilities), `bandit` (SAST), `osv-scanner` (multi-ecosystem)
1. **Semgrep CE Scan** 🔬 — Static analysis with SARIF upload to GitHub Advanced Security; suppressed findings (`# nosemgrep`) are stripped before upload
1. **Rust Security** 🦀 — `cargo-audit` (advisory database), `cargo-deny` (license and policy checks)
1. **Secret Scanning** 🔑 — TruffleHog on full history (`fetch-depth: 0`), verified secrets only
1. **Container Scanning** 🐳 — Trivy filesystem scan for HIGH/CRITICAL CVEs, SARIF uploaded to GitHub Security tab

**Key Features**:

- 🔒 Minimal permissions (`contents: read`, `security-events: write`)
- 📤 SARIF results uploaded to GitHub Advanced Security for all scanners
- 🚫 Semgrep job skipped for Dependabot PRs (`github.actor != 'dependabot[bot]'`)

### 🧹 Cleanup Workflows

#### Cache Cleanup (`cleanup-cache.yml`)

- **Trigger**: PR closure
- **Purpose**: Removes PR-specific caches

#### Docker Image Cleanup (`cleanup-images.yml`)

- **Trigger**: Monthly schedule
- **Purpose**: Removes old Docker images
- **Retention**: Keeps 2 most recent tagged versions

### 🐳 Docker Validation (`docker-validate.yml`)

**Trigger**: Docker-related file changes **Purpose**: Validates Docker configurations

**Checks**:

- 📋 docker-compose syntax validation
- 🔍 Dockerfile linting with Hadolint
- 🔒 Security best practices verification
- 🏗️ Build testing for all services

### 📋 List Sub-Projects (`list-sub-projects.yml`)

**Trigger**: Called by other workflows **Purpose**: Provides service matrix for build jobs

**Output**: JSON matrix of services with cache settings

## 🔧 Composite Actions

Reusable actions that reduce duplication and improve maintainability:

### 📦 `setup-python-uv`

Sets up Python environment with UV package manager and caching.

```yaml
- uses: ./.github/actions/setup-python-uv
  with:
    python-version: "3.13"
    cache-dependency-glob: "**/uv.lock"
```

**Features**:

- 🐍 Python setup with specified version
- 📦 UV package manager installation
- 💾 Intelligent dependency caching
- ⚡ Cache restoration with fallbacks

### 🐳 `docker-build-cache`

Advanced Docker layer caching for faster builds.

```yaml
- uses: ./.github/actions/docker-build-cache
  with:
    service-name: dashboard
    dockerfile-path: dashboard/Dockerfile
    use-cache: true
```

**Features**:

- 💾 BuildKit cache optimization
- 🔄 Cache hit detection
- 📊 Performance metrics
- 🎯 Service-specific caching

### 🔄 `retry-step`

Retry mechanism with exponential backoff for flaky operations.

```yaml
- uses: ./.github/actions/retry-step
  with:
    command: npm install
    max-attempts: 3
    retry-delay: 10
```

**Features**:

- ⏱️ Configurable timeouts
- 📈 Exponential backoff
- 🎯 Detailed attempt logging
- ❌ Graceful failure handling

## ⚡ Performance Optimizations

### 🚀 Parallelization

- Tests and E2E tests run in parallel after code quality
- Independent Docker builds use matrix strategy
- Concurrent browser tests limited to prevent resource exhaustion

### 💾 Caching Strategy

- **Hierarchical cache keys** with multiple fallback levels
- **Docker BuildKit** inline caching and cache namespaces
- **Dependency caching** for Python, UV, and pre-commit
- **Test result caching** for faster subsequent runs

### 🎯 Conditional Execution

- Skip tests when no relevant files changed in PRs
- Smart file change detection for targeted workflows
- Resource-aware execution based on context

### 📊 Monitoring & Metrics

- Build duration tracking
- Cache hit rate reporting
- Performance notices in workflow logs
- Enhanced Discord notifications with metrics

## 🛡️ Security Features

### 🔒 Least Privilege Permissions

All workflows specify minimal required permissions:

```yaml
permissions:
  contents: read        # Most workflows
  packages: write      # For Docker push
  pull-requests: write # For PR creation
```

### 📌 Action Pinning

- Non-GitHub/Docker actions pinned to specific SHA
- Regular updates through dependabot
- Version comments for clarity

### 🐳 Container Security

- Non-root user execution (1000:1000)
- No-new-privileges security option
- Anchore security scanning for images
- Hadolint validation for Dockerfiles

## 🎯 Best Practices

### 📝 Naming Conventions

- **Steps**: Start with emoji for visual scanning
- **Jobs**: Descriptive names with purpose
- **Workflows**: Clear, action-oriented names

### 🎨 Quote Standardization

- **Expressions**: Single quotes (`${{ }}`)
- **YAML strings**: Double quotes when needed
- **Simple values**: Unquoted when appropriate

### 📢 Notifications

- Discord webhooks for build status
- Detailed error messages in logs
- PR comments for dependency updates
- Workflow status badges in README

### 🔧 Maintenance

- Weekly dependency updates
- Monthly Docker image cleanup
- Automated cache management
- Regular security scanning

## 📊 Workflow Status

Monitor workflow health through status badges:

- [![Build](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/build.yml)
- [![Code Quality](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/code-quality.yml)
- [![Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/test.yml)
- [![E2E Tests](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml/badge.svg)](https://github.com/SimplicityGuy/discogsography/actions/workflows/e2e-test.yml)

## 🚀 Getting Started

### Running Workflows Locally

Use [act](https://github.com/nektos/act) to test workflows locally:

```bash
# Run specific workflow
act -W .github/workflows/test.yml

# Run with specific event
act pull_request -W .github/workflows/build.yml

# List available workflows
act -l
```

### Debugging Workflows

1. **Enable debug logging**:

   ```yaml
   env:
     ACTIONS_RUNNER_DEBUG: true
     ACTIONS_STEP_DEBUG: true
   ```

1. **Add debugging steps**:

   ```yaml
   - name: 🐛 Debug context
     run: |
       echo "Event: ${{ github.event_name }}"
       echo "Ref: ${{ github.ref }}"
       echo "SHA: ${{ github.sha }}"
   ```

1. **Check workflow runs**: Navigate to Actions tab in GitHub

## 📚 Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow Syntax Reference](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions)
- [Composite Actions Guide](https://docs.github.com/en/actions/creating-actions/creating-a-composite-action)
- [Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
