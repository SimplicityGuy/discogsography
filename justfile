#!/usr/bin/env just --justfile

# 🎵 Discogsography Justfile
# Task automation for Python/Rust microservices platform
# Run 'just --list' to see all available commands

# Set shell for Windows compatibility
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# Default recipe shows help
default:
    @just --list

# ──────────────────────────────────────────────────────────────────────────────
# Development & Setup
# ──────────────────────────────────────────────────────────────────────────────

# Install all dependencies and setup development environment
[group('setup')]
install:
    uv sync --all-extras

# Install all dependencies including editable packages for all services (used in CI)
[group('setup')]
install-all:
    uv sync --all-extras
    uv pip install -e api
    uv pip install -e brainzgraphinator
    uv pip install -e brainztableinator
    uv pip install -e common
    uv pip install -e dashboard
    uv pip install -e explore
    uv pip install -e graphinator
    uv pip install -e insights
    uv pip install -e mcp-server
    uv pip install -e schema-init
    uv pip install -e tableinator

# Install dependencies for E2E testing (frozen lockfile, subset of packages)
[group('setup')]
install-e2e:
    uv sync --all-extras --frozen
    uv pip install -e common
    uv pip install -e dashboard
    uv pip install -e explore

# Install JavaScript dependencies for Explore frontend tests
[group('setup')]
install-js:
    cd explore && npm ci

# Initialize pre-commit hooks for development
[group('setup')]
init:
    uv run pre-commit install
    @echo '✅ Pre-commit hooks installed!'

# Configure Discogs app credentials (run against the API container)
[group('setup')]
configure-discogs consumer-key consumer-secret container="discogsography-api-1":
    docker exec {{ container }} discogs-setup \
        --consumer-key {{ consumer-key }} \
        --consumer-secret {{ consumer-secret }}

# Update pre-commit hooks to latest versions
[group('setup')]
update-hooks:
    uv run pre-commit autoupdate --freeze

# Check for outdated dependencies (Python, Rust, Docker)
[group('setup')]
check-updates:
    @echo '🐍 Python dependency updates:'
    uv run pip list --outdated
    @echo ''
    @echo '🦀 Rust dependency updates:'
    @if [ -d 'extractor' ]; then \
        cargo install cargo-run-bin --quiet 2>/dev/null || true; \
        cd extractor && cargo bin --install --quiet 2>/dev/null || true && cargo bin cargo-outdated; \
    else \
        echo 'No Rust project found'; \
    fi
    @echo ''
    @echo '🐳 Docker image updates:'
    @docker images --format "table \{\{.Repository\}\}:\{\{.Tag\}\}\t\{\{.CreatedSince\}\}" | head -20 || echo 'Docker not available'

# Update all dependencies to latest versions (Python, Rust, pre-commit, Docker)
[group('setup')]
update-deps:
    @echo '🚀 Running comprehensive dependency update...'
    @./scripts/update-project.sh --no-backup --skip-tests
    @echo ''
    @echo '✅ All dependencies updated!'
    @echo '💡 Run "just test-all" to verify everything still works'

# Update uv itself to the latest version
[group('setup')]
update-uv:
    uv self update

# Lock Python dependencies with upgrades (respects >= constraints)
[group('setup')]
lock-upgrade:
    uv lock --upgrade

# Sync all Python dependencies including dev and optional extras
[group('setup')]
sync:
    uv sync --all-extras --dev

# Sync all Python dependencies with upgrades
[group('setup')]
sync-upgrade:
    uv sync --all-extras --dev --upgrade

# Update npm dependencies in Explore frontend
[group('setup')]
update-npm:
    cd explore && npm update --save

# Update Rust dependencies (lock file only, within Cargo.toml constraints)
[group('setup')]
update-cargo:
    cd extractor && cargo update

# ──────────────────────────────────────────────────────────────────────────────
# Code Quality & Linting
# ──────────────────────────────────────────────────────────────────────────────

# Run all pre-commit hooks on all files
[group('quality')]
lint:
    uv run pre-commit run --all-files

# Run Python-specific linters (ruff & mypy)
[group('quality')]
lint-python:
    uv run ruff check .
    uv run mypy .

# Format all Python code with ruff
[group('quality')]
format:
    uv run ruff format .

# Run security checks with bandit
[group('quality')]
security:
    uv run bandit -r . -c pyproject.toml

# Run pip-audit (Python dependency vulnerability scan)
[group('quality')]
pip-audit:
    #!/usr/bin/env bash
    set -e
    IGNORE_ARGS=""
    if [[ -f .pip-audit-ignores ]]; then
        while IFS= read -r line; do
            vuln_id=$(echo "$line" | sed 's/#.*//' | tr -d '[:space:]')
            [[ -z "$vuln_id" ]] && continue
            IGNORE_ARGS="$IGNORE_ARGS --ignore-vuln $vuln_id"
        done < .pip-audit-ignores
    fi
    # shellcheck disable=SC2086
    uv run pip-audit --desc $IGNORE_ARGS

# ──────────────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────────────

# Run unit and integration tests (excluding E2E)
[group('test')]
test:
    uv run pytest -m 'not e2e'

# Run JavaScript unit tests for Explore frontend
[group('test')]
test-js:
    cd explore && npx vitest run

# Run JavaScript tests with coverage
[group('test')]
test-js-cov:
    cd explore && npx vitest run --coverage

# Run tests with coverage report
[group('test')]
test-cov:
    uv run pytest --cov --cov-report=xml --cov-report=json --cov-report=term -m 'not e2e'

# Run end-to-end browser tests
[group('test')]
test-e2e:
    uv run pytest tests/dashboard/test_dashboard_ui.py -v

# Run all tests including E2E
[group('test')]
test-all:
    uv run pytest

# Run all service tests in parallel for maximum speed
[group('test')]
test-parallel:
    #!/usr/bin/env bash
    set -e
    echo "🚀 Running all service tests in parallel..."

    # Run each service test in background
    uv run pytest tests/api/ -v > /tmp/test-api.log 2>&1 &
    pid_api=$!

    uv run pytest tests/common/ -v > /tmp/test-common.log 2>&1 &
    pid_common=$!

    uv run pytest tests/dashboard/ -v > /tmp/test-dashboard.log 2>&1 &
    pid_dashboard=$!

    uv run pytest tests/explore/ -m 'not e2e' -v > /tmp/test-explore.log 2>&1 &
    pid_explore=$!

    uv run pytest tests/insights/ -v > /tmp/test-insights.log 2>&1 &
    pid_insights=$!

    uv run pytest tests/brainzgraphinator/ -v > /tmp/test-brainzgraphinator.log 2>&1 &
    pid_brainzgraphinator=$!

    uv run pytest tests/graphinator/ -v > /tmp/test-graphinator.log 2>&1 &
    pid_graphinator=$!

    uv run pytest tests/mcp-server/ -v > /tmp/test-mcp-server.log 2>&1 &
    pid_mcp_server=$!

    uv run pytest tests/schema-init/ -v > /tmp/test-schema-init.log 2>&1 &
    pid_schema_init=$!

    uv run pytest tests/tableinator/ -v > /tmp/test-tableinator.log 2>&1 &
    pid_tableinator=$!

    uv run pytest tests/brainztableinator/ -v > /tmp/test-brainztableinator.log 2>&1 &
    pid_brainztableinator=$!

    (cd explore && npx vitest run) > /tmp/test-js.log 2>&1 &
    pid_js=$!

    if [ -d "extractor" ]; then
        (cd extractor && cargo test) > /tmp/test-extractor.log 2>&1 &
        pid_extractor=$!
    fi

    # Wait for all tests and track results
    failed=0

    wait $pid_api || { echo "❌ API tests failed"; cat /tmp/test-api.log; failed=1; }
    wait $pid_common || { echo "❌ Common tests failed"; cat /tmp/test-common.log; failed=1; }
    wait $pid_dashboard || { echo "❌ Dashboard tests failed"; cat /tmp/test-dashboard.log; failed=1; }
    wait $pid_explore || { echo "❌ Explore tests failed"; cat /tmp/test-explore.log; failed=1; }
    wait $pid_insights || { echo "❌ Insights tests failed"; cat /tmp/test-insights.log; failed=1; }
    wait $pid_brainzgraphinator || { echo "❌ Brainzgraphinator tests failed"; cat /tmp/test-brainzgraphinator.log; failed=1; }
    wait $pid_graphinator || { echo "❌ Graphinator tests failed"; cat /tmp/test-graphinator.log; failed=1; }
    wait $pid_mcp_server || { echo "❌ MCP server tests failed"; cat /tmp/test-mcp-server.log; failed=1; }
    wait $pid_schema_init || { echo "❌ Schema-init tests failed"; cat /tmp/test-schema-init.log; failed=1; }
    wait $pid_tableinator || { echo "❌ Tableinator tests failed"; cat /tmp/test-tableinator.log; failed=1; }
    wait $pid_brainztableinator || { echo "❌ Brainztableinator tests failed"; cat /tmp/test-brainztableinator.log; failed=1; }
    wait $pid_js || { echo "❌ JS tests failed"; cat /tmp/test-js.log; failed=1; }

    if [ -n "$pid_extractor" ]; then
        wait $pid_extractor || { echo "❌ Extractor tests failed"; cat /tmp/test-extractor.log; failed=1; }
    fi

    if [ $failed -eq 0 ]; then
        echo "✅ All service tests passed!"
        # Show summary
        echo ""
        echo "📊 Test Summary:"
        grep -h "passed" /tmp/test-*.log | tail -10
    else
        echo "❌ Some tests failed. Check logs above for details."
        exit 1
    fi

# ──────────────────────────────────────────────────────────────────────────────
# Service-Specific Tests
# ──────────────────────────────────────────────────────────────────────────────

# Run api service tests with coverage
[group('test')]
test-api:
    uv run pytest tests/api/ -v \
        --cov --cov-config=.coveragerc.api --cov-report=xml --cov-report=json --cov-report=term

# Run common/shared library tests with coverage
[group('test')]
test-common:
    uv run pytest tests/common/ -v \
        --cov --cov-config=.coveragerc.common --cov-report=xml --cov-report=json --cov-report=term

# Run dashboard service tests with coverage
[group('test')]
test-dashboard:
    uv run pytest tests/dashboard/ -v \
        --cov --cov-config=.coveragerc.dashboard --cov-report=xml --cov-report=json --cov-report=term

# Run explore service tests with coverage
[group('test')]
test-explore:
    uv run pytest tests/explore/ -m 'not e2e' -v \
        --cov --cov-config=.coveragerc.explore --cov-report=xml --cov-report=json --cov-report=term

# Run Rust extractor tests (same as extractor-test)
[group('test')]
test-extractor:
    cd extractor && cargo test

# Run Rust extractor tests with coverage (requires cargo-llvm-cov)
[group('test')]
test-extractor-cov:
    cd extractor && \
    cargo llvm-cov test --verbose --lcov --output-path lcov.info

# Run insights service tests with coverage
[group('test')]
test-insights:
    uv run pytest tests/insights/ -v \
        --cov --cov-config=.coveragerc.insights --cov-report=xml --cov-report=json --cov-report=term

# Run brainzgraphinator service tests with coverage
[group('test')]
test-brainzgraphinator:
    uv run pytest tests/brainzgraphinator/ -v \
        --cov --cov-config=.coveragerc.brainzgraphinator --cov-report=xml --cov-report=json --cov-report=term

# Run graphinator service tests with coverage
[group('test')]
test-graphinator:
    uv run pytest tests/graphinator/ -v \
        --cov --cov-config=.coveragerc.graphinator --cov-report=xml --cov-report=json --cov-report=term

# Run mcp-server tests with coverage
[group('test')]
test-mcp-server:
    uv run pytest tests/mcp-server/ -v \
        --cov --cov-config=.coveragerc.mcp-server --cov-report=xml --cov-report=json --cov-report=term

# Run schema-init service tests with coverage
[group('test')]
test-schema-init:
    uv run pytest tests/schema-init/ -v \
        --cov --cov-config=.coveragerc.schema-init --cov-report=xml --cov-report=json --cov-report=term

# Run tableinator service tests with coverage
[group('test')]
test-tableinator:
    uv run pytest tests/tableinator/ -v \
        --cov --cov-config=.coveragerc.tableinator --cov-report=xml --cov-report=json --cov-report=term

# Run brainztableinator service tests with coverage
[group('test')]
test-brainztableinator:
    uv run pytest tests/brainztableinator/ -v \
        --cov --cov-config=.coveragerc.brainztableinator --cov-report=xml --cov-report=json --cov-report=term

# E2E workflow: dashboard unit tests establishing coverage baseline
[group('test')]
test-e2e-unit-dashboard:
    uv run pytest tests/dashboard/ -v -m 'not e2e' \
        --cov=dashboard --cov=explore --cov=common \
        --cov-report=xml --cov-report=json --cov-report=term

# E2E workflow: explore unit tests appending to coverage baseline
[group('test')]
test-e2e-unit-explore:
    uv run pytest tests/explore/ -v -m 'not e2e' \
        --cov=dashboard --cov=explore --cov=common \
        --cov-append --cov-report=xml --cov-report=json --cov-report=term

# E2E workflow: dashboard E2E tests for a given browser (desktop)
[group('test')]
test-e2e-dashboard browser:
    uv run pytest tests/dashboard/test_dashboard_ui.py -v -m e2e \
        --browser {{ browser }} \
        --cov=dashboard --cov=explore --cov=common --cov-append \
        --cov-report=xml --cov-report=json --cov-report=term

# E2E workflow: dashboard E2E tests with mobile device emulation
[group('test')]
test-e2e-dashboard-mobile browser device:
    uv run pytest tests/dashboard/test_dashboard_ui.py -v -m e2e \
        --browser {{ browser }} \
        --device "{{ device }}" \
        --cov=dashboard --cov=explore --cov=common --cov-append \
        --cov-report=xml --cov-report=json --cov-report=term

# E2E workflow: explore E2E tests for a given browser (desktop)
[group('test')]
test-e2e-explore browser:
    uv run pytest tests/explore/test_explore_ui.py -v -m e2e \
        --browser {{ browser }} \
        --cov=dashboard --cov=explore --cov=common --cov-append \
        --cov-report=xml --cov-report=json --cov-report=term

# E2E workflow: explore E2E tests with mobile device emulation
[group('test')]
test-e2e-explore-mobile browser device:
    uv run pytest tests/explore/test_explore_ui.py -v -m e2e \
        --browser {{ browser }} \
        --device "{{ device }}" \
        --cov=dashboard --cov=explore --cov=common --cov-append \
        --cov-report=xml --cov-report=json --cov-report=term

# ──────────────────────────────────────────────────────────────────────────────
# Python Services
# ──────────────────────────────────────────────────────────────────────────────

# Run the API service (user accounts & JWT authentication)
[group('services')]
api:
    uv run python api/api.py

# Run the dashboard service (monitoring UI)
[group('services')]
dashboard:
    uv run python dashboard/dashboard.py

# Run the explore service (graph exploration and trends)
[group('services')]
explore:
    uv run python -m explore.explore

# Run insights service locally
[group('services')]
insights:
    uv run python insights/insights.py

# Run the graphinator service (Neo4j graph builder)
[group('services')]
graphinator:
    uv run python graphinator/graphinator.py

# Run the schema-init service (one-time Neo4j and PostgreSQL schema initialization)
[group('services')]
schema-init:
    uv run python schema-init/schema_init.py

# Run the brainzgraphinator service (MusicBrainz → Neo4j enrichment)
[group('services')]
brainzgraphinator:
    uv run python brainzgraphinator/brainzgraphinator.py

# Run the brainztableinator service (MusicBrainz → PostgreSQL)
[group('services')]
brainztableinator:
    uv run python brainztableinator/brainztableinator.py

# Run the Rust extractor (high-performance Discogs data ingestion)
[group('services')]
extractor: extractor-run

# Run the MCP server (AI assistant knowledge graph interface)
[group('services')]
mcp-server:
    uv run python -m mcp_server.server

# Run the tableinator service (PostgreSQL table builder)
[group('services')]
tableinator:
    uv run python tableinator/tableinator.py

# ──────────────────────────────────────────────────────────────────────────────
# Rust Development
# ──────────────────────────────────────────────────────────────────────────────

# Build Rust extractor in release mode
[group('rust')]
extractor-build:
    cd extractor && \
    cargo build --release

# Run Rust extractor tests
[group('rust')]
extractor-test:
    cd extractor && \
    cargo test

# Run Rust extractor benchmarks
[group('rust')]
extractor-bench:
    cd extractor && \
    cargo bench

# Run Rust extractor in release mode
[group('rust')]
extractor-run:
    cd extractor && \
    cargo run --release

# Lint Rust code with clippy (treats warnings as errors)
[group('rust')]
extractor-lint:
    cd extractor && \
    cargo clippy --all-targets -- -D warnings

# Format Rust code
[group('rust')]
extractor-fmt:
    cargo fmt --manifest-path extractor/Cargo.toml

# Check Rust code formatting (for CI/pre-commit)
[group('rust')]
extractor-fmt-check:
    cd extractor && \
    cargo fmt --check

# Run cargo-audit (Rust advisory database scan)
[group('rust')]
extractor-audit:
    cargo audit --file Cargo.lock

# Run cargo-deny (Rust license and policy check)
[group('rust')]
extractor-deny:
    cargo deny --manifest-path extractor/Cargo.toml check

# Clean Rust build artifacts
[group('rust')]
extractor-clean:
    cd extractor && \
    cargo clean

# ──────────────────────────────────────────────────────────────────────────────
# Docker Operations
# ──────────────────────────────────────────────────────────────────────────────

# Start all Docker services in background
[group('docker')]
up:
    docker compose up -d

# Stop all Docker services
[group('docker')]
down:
    docker compose down

# Show logs from all services (follow mode)
[group('docker')]
logs:
    docker compose logs -f

# Rebuild all Docker images and restart services
[group('docker')]
rebuild:
    docker compose down
    docker compose build
    docker compose up -d

# Build specific service Docker images
[group('docker')]
build:
    docker compose build \
        api \
        brainzgraphinator \
        brainztableinator \
        dashboard \
        explore \
        extractor-discogs \
        extractor-musicbrainz \
        graphinator \
        insights \
        schema-init \
        tableinator

# Build production Docker images
[group('docker')]
build-prod:
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        build

# Deploy services in production mode
[group('docker')]
deploy-prod:
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        up -d

# ──────────────────────────────────────────────────────────────────────────────
# Monitoring & Utilities
# ──────────────────────────────────────────────────────────────────────────────

# Monitor RabbitMQ queues in real-time
[group('monitor')]
monitor:
    uv run python utilities/monitor_queues.py

# Check for errors in service logs
[group('monitor')]
check-errors:
    uv run python utilities/check_errors.py

# Monitor system resources and performance
[group('monitor')]
system-monitor:
    uv run python utilities/system_monitor.py

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

# Clean project directory of temporary files and caches
[group('clean')]
clean:
    @echo '🧹 Cleaning project directory...'
    @find . -type d -name '__pycache__' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name '.pytest_cache' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name '.ruff_cache' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name '.mypy_cache' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name '.coverage' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name 'htmlcov' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name 'dist' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name 'build' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name '*.egg-info' ! -path './.claude/*' -exec rm -rf {} + 2>/dev/null || true
    @find . -type f -name '*.pyc' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.pyo' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.pyd' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '.DS_Store' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.orig' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.rej' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.bak' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.swp' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*.swo' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name '*~' ! -path './.claude/*' -delete 2>/dev/null || true
    @if [ -d 'extractor/target' ]; then \
        rm -rf extractor/target; \
    fi
    @if [ -d 'extractor/.bin' ]; then \
        rm -rf extractor/.bin; \
    fi
    @if [ -d '.hypothesis' ]; then \
        rm -rf .hypothesis; \
    fi
    @if [ -d '.benchmarks' ]; then \
        rm -rf .benchmarks; \
    fi
    @if [ -d '.venv' ]; then \
        rm -rf .venv; \
    fi
    @if [ -d 'target' ]; then \
        rm -rf target; \
    fi
    @if [ -d 'rust-version/target' ]; then \
        rm -rf rust-version/target; \
    fi
    @if [ -d 'data' ]; then \
        rm -rf data; \
    fi
    @find . -type f -name '.coverage' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name 'coverage.xml' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name 'coverage.json' ! -path './.claude/*' -delete 2>/dev/null || true
    @find . -type f -name 'lcov.info' ! -path './.claude/*' -delete 2>/dev/null || true
    @echo '✅ Project cleaned!'
    @echo '📁 Preserved: .claude, .git, uv.lock'

# Deep clean including Docker volumes (use with caution!)
[group('clean')]
deep-clean: clean
    @echo '🐳 Cleaning Docker...'
    @docker compose down -v --remove-orphans 2>/dev/null || true
    @docker system prune -f 2>/dev/null || true
    @echo '✅ Deep clean done!'
