#!/usr/bin/env bash
# Script to update Python version across the entire codebase

set -euo pipefail

# Default Python version
DEFAULT_PYTHON_VERSION="3.13"

# Get Python version from argument or use default
PYTHON_VERSION="${1:-$DEFAULT_PYTHON_VERSION}"
PYTHON_VERSION_SHORT="py${PYTHON_VERSION//./}"

echo "Updating Python version to: $PYTHON_VERSION"
echo "Short version (for tools): $PYTHON_VERSION_SHORT"

# Function to update pyproject.toml files
update_pyproject() {
    local file="$1"
    echo "Updating $file..."

    # Update requires-python
    sed -i.bak "s/requires-python = \">=.*\"/requires-python = \">=$PYTHON_VERSION\"/" "$file"

    # Update classifier
    sed -i.bak "s/\"Programming Language :: Python :: [0-9.]*\"/\"Programming Language :: Python :: $PYTHON_VERSION\"/" "$file"

    # Update ruff target-version
    sed -i.bak "s/target-version = \"py[0-9]*\"/target-version = \"$PYTHON_VERSION_SHORT\"/" "$file"

    # Update mypy python_version
    sed -i.bak "s/python_version = \"[0-9.]*\"/python_version = \"$PYTHON_VERSION\"/" "$file"

    # Update black target-version
    sed -i.bak "s/target-version = \[\"py[0-9]*\"\]/target-version = [\"$PYTHON_VERSION_SHORT\"]/" "$file"

    # Clean up backup files
    rm -f "${file}.bak"
}

# Function to update Dockerfiles
update_dockerfile() {
    local file="$1"
    echo "Updating $file..."

    # Update FROM statements
    sed -i.bak "s/FROM python:[0-9.]*-slim/FROM python:\${PYTHON_VERSION}-slim/g" "$file"

    # Update base image label
    sed -i.bak "s/python:[0-9.]*-slim/python:\${PYTHON_VERSION}-slim/" "$file"

    # Update Python version label
    sed -i.bak "s/com.discogsography.python.version=\"[0-9.]*\"/com.discogsography.python.version=\"\${PYTHON_VERSION}\"/" "$file"

    # Clean up backup files
    rm -f "${file}.bak"
}

# Function to update GitHub workflows
update_workflow() {
    local file="$1"
    echo "Updating $file..."

    # Update python-version in workflows
    sed -i.bak "s/python-version: \"[0-9.]*\"/python-version: \"$PYTHON_VERSION\"/" "$file"

    # Clean up backup files
    rm -f "${file}.bak"
}

# Function to update pyrightconfig.json
update_pyright() {
    local file="$1"
    echo "Updating $file..."

    # Update pythonVersion
    sed -i.bak "s/\"pythonVersion\": \"[0-9.]*\"/\"pythonVersion\": \"$PYTHON_VERSION\"/" "$file"

    # Clean up backup files
    rm -f "${file}.bak"
}

# Update all pyproject.toml files
for pyproject in pyproject.toml */pyproject.toml; do
    if [ -f "$pyproject" ]; then
        update_pyproject "$pyproject"
    fi
done

# Update all Dockerfiles
for dockerfile in */Dockerfile; do
    if [ -f "$dockerfile" ]; then
        update_dockerfile "$dockerfile"
    fi
done

# Update GitHub workflows
if [ -f ".github/workflows/build.yml" ]; then
    update_workflow ".github/workflows/build.yml"
fi

# Update pyrightconfig.json
if [ -f "pyrightconfig.json" ]; then
    update_pyright "pyrightconfig.json"
fi

# Update .env.example if it exists
if [ -f ".env.example" ]; then
    echo "Updating .env.example..."
    sed -i.bak "s/PYTHON_VERSION=.*/PYTHON_VERSION=$PYTHON_VERSION/" .env.example
    sed -i.bak "s/PYTHON_VERSION_FULL=.*/PYTHON_VERSION_FULL=$PYTHON_VERSION/" .env.example
    sed -i.bak "s/PYTHON_VERSION_SHORT=.*/PYTHON_VERSION_SHORT=$PYTHON_VERSION_SHORT/" .env.example
    rm -f .env.example.bak
fi

echo "✅ Python version updated to $PYTHON_VERSION across all files"
echo ""
echo "Note: You may need to update documentation files manually."
echo "Remember to run 'uv sync' to update dependencies for the new Python version."
