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

# Initialize pre-commit hooks for development
[group('setup')]
init:
    uv run pre-commit install
    @echo '✅ Pre-commit hooks installed!'

# Update pre-commit hooks to latest versions
[group('setup')]
update-hooks:
    uv run pre-commit autoupdate --freeze

# Check for outdated dependencies
[group('setup')]
check-updates:
    uv pip list --outdated

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
    uv run bandit -r . -x './.venv/*,./tests/*'

# ──────────────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────────────

# Run unit and integration tests (excluding E2E)
[group('test')]
test:
    uv run pytest -m 'not e2e'

# Run tests with coverage report
[group('test')]
test-cov:
    uv run pytest --cov -m 'not e2e'

# Run end-to-end browser tests
[group('test')]
test-e2e:
    uv run pytest tests/dashboard/test_dashboard_ui.py -v

# Run all tests including E2E
[group('test')]
test-all:
    uv run pytest

# ──────────────────────────────────────────────────────────────────────────────
# Python Services
# ──────────────────────────────────────────────────────────────────────────────

# Run the dashboard service (monitoring UI)
[group('services')]
dashboard:
    uv run python dashboard/dashboard.py

# Run the discovery service (AI-powered music intelligence)
[group('services')]
discovery:
    uv run python discovery/discovery.py

# Run the Python extractor service
[group('services')]
pyextractor:
    uv run python extractor/pyextractor/extractor.py

# Run the Python extractor service (alias for backwards compatibility)
[group('services')]
extractor:
    uv run python extractor/pyextractor/extractor.py

# Run the graphinator service (Neo4j graph builder)
[group('services')]
graphinator:
    uv run python graphinator/graphinator.py

# Run the tableinator service (PostgreSQL table builder)
[group('services')]
tableinator:
    uv run python tableinator/tableinator.py

# ──────────────────────────────────────────────────────────────────────────────
# Rust Development
# ──────────────────────────────────────────────────────────────────────────────

# Build Rust extractor in release mode
[group('rust')]
rustextractor-build:
    cd extractor/rustextractor && \
    cargo build --release

# Run Rust extractor tests
[group('rust')]
rustextractor-test:
    cd extractor/rustextractor && \
    cargo test

# Run Rust extractor benchmarks
[group('rust')]
rustextractor-bench:
    cd extractor/rustextractor && \
    cargo bench

# Run Rust extractor in release mode
[group('rust')]
rustextractor-run:
    cd extractor/rustextractor && \
    cargo run --release

# Lint Rust code with clippy
[group('rust')]
rustextractor-lint:
    cd extractor/rustextractor && \
    cargo clippy -- -D warnings

# Format Rust code
[group('rust')]
rustextractor-fmt:
    cd extractor/rustextractor && \
    cargo fmt

# Clean Rust build artifacts
[group('rust')]
rustextractor-clean:
    cd extractor/rustextractor && \
    cargo clean

# ──────────────────────────────────────────────────────────────────────────────
# Docker Operations
# ──────────────────────────────────────────────────────────────────────────────

# Start all Docker services in background
[group('docker')]
up:
    docker-compose up -d

# Stop all Docker services
[group('docker')]
down:
    docker-compose down

# Show logs from all services (follow mode)
[group('docker')]
logs:
    docker-compose logs -f

# Rebuild all Docker images and restart services
[group('docker')]
rebuild:
    docker-compose down
    docker-compose build
    docker-compose up -d

# Build specific service Docker images
[group('docker')]
build:
    docker-compose build \
        dashboard \
        discovery \
        pyextractor \
        rustextractor \
        graphinator \
        tableinator

# Build production Docker images
[group('docker')]
build-prod:
    docker-compose \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        build

# Deploy services in production mode
[group('docker')]
deploy-prod:
    docker-compose \
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
    @if [ -d 'extractor/rustextractor/target' ]; then \
        rm -rf extractor/rustextractor/target; \
    fi
    @if [ -d '.hypothesis' ]; then \
        rm -rf .hypothesis; \
    fi
    @if [ -d '.benchmarks' ]; then \
        rm -rf .benchmarks; \
    fi
    @echo '✅ Project cleaned!'
    @echo '📁 Preserved: .claude, .git, uv.lock'

# Deep clean including Docker volumes (use with caution!)
[group('clean')]
deep-clean: clean
    @echo '🐳 Cleaning Docker...'
    @docker compose down -v --remove-orphans 2>/dev/null || true
    @docker system prune -f 2>/dev/null || true
    @echo '✅ Deep clean done!'
