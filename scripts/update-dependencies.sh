#!/bin/bash
# Update dependencies safely without iOS wheels
# This script ensures uv.lock is generated without iOS-specific wheels

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "📦 Updating dependencies..."
echo ""

# Method 1: Use Docker to ensure Linux-only wheels
if command -v docker &> /dev/null; then
    echo "🐳 Using Docker to generate Linux-compatible uv.lock..."

    # Create a temporary Dockerfile for dependency updates
    cat > Dockerfile.update-deps << 'EOF'
FROM ghcr.io/astral-sh/uv:0.5.19 AS uv
FROM python:3.13-slim

# Copy uv from the uv image
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY common/pyproject.toml ./common/
COPY dashboard/pyproject.toml ./dashboard/
COPY discovery/pyproject.toml ./discovery/
COPY extractor/pyproject.toml ./extractor/
COPY graphinator/pyproject.toml ./graphinator/
COPY tableinator/pyproject.toml ./tableinator/

# Update dependencies
RUN uv lock --upgrade
EOF

    # Build and run the container
    docker build -f Dockerfile.update-deps -t uv-update-deps .
    docker run --rm -v "$PROJECT_ROOT:/output" uv-update-deps sh -c "cp uv.lock /output/"

    # Clean up
    rm Dockerfile.update-deps
    docker rmi uv-update-deps

    echo "✅ Dependencies updated using Docker (Linux-only wheels)"

else
    echo "⚠️  Docker not available, using local uv..."
    echo ""

    # Method 2: Use local uv but clean iOS wheels after
    uv lock --upgrade

    # Check for iOS wheels
    if grep -q "ios_[0-9]\+_[0-9]\+_.*\.whl" uv.lock; then
        echo "🔧 Removing iOS wheels..."
        "$SCRIPT_DIR/remove-ios-wheels.sh"
    fi
fi

echo ""
echo "📋 Summary:"
echo "  - Dependencies updated"
echo "  - iOS wheels removed (if any)"
echo ""
echo "🚀 Next steps:"
echo "  1. Review changes: git diff uv.lock"
echo "  2. Test locally: uv sync --all-extras"
echo "  3. Test Docker builds: docker build -f <service>/Dockerfile ."
echo "  4. Commit changes: git add uv.lock && git commit -m 'chore: update dependencies'"
