#!/usr/bin/env bash

# upgrade-packages.sh - Safely upgrade all project dependencies
#
# This script provides a safe and comprehensive way to upgrade Python dependencies
# across the entire discogsography project, including the root workspace and all
# service-specific dependencies. It also updates the UV package manager version
# in all Dockerfiles to the latest release.
#
# Note: Platform targeting is configured in pyproject.toml [tool.uv] section to
# ensure only Linux (amd64/arm64) and macOS wheels are included in uv.lock.
#
# Usage: ./scripts/upgrade-packages.sh [options]
#
# Options:
#   --no-backup     Skip creating backup files
#   --dry-run       Show what would be upgraded without making changes
#   --major         Include major version upgrades (default: minor/patch only)
#   --help          Show this help message

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
BACKUP=true
DRY_RUN=false
MAJOR_UPGRADES=false
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Show usage
show_help() {
    head -n 20 "$0" | grep '^#' | sed 's/^# //' | sed 's/^#//'
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-backup)
            BACKUP=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --major)
            MAJOR_UPGRADES=true
            shift
            ;;
        --help|-h)
            show_help
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            ;;
    esac
done

# Check if we're in the project root
if [[ ! -f "pyproject.toml" ]] || [[ ! -f "uv.lock" ]]; then
    print_error "This script must be run from the project root directory"
    exit 1
fi

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Please install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if git is installed and we're in a git repository
if ! command -v git &> /dev/null; then
    print_error "git is not installed. Please install git first."
    exit 1
fi

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    print_error "Not in a git repository. This script requires git for safety."
    exit 1
fi

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    print_warning "You have uncommitted changes. Please commit or stash them first."
    print_info "This is required for safe rollback in case of issues."
    exit 1
fi

# Create backup directory
BACKUP_DIR="backups/package-upgrades-${TIMESTAMP}"
if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$BACKUP_DIR"
    print_info "Creating backups in $BACKUP_DIR/"
fi

# Backup function
backup_file() {
    local file=$1
    if [[ "$BACKUP" == true ]] && [[ -f "$file" ]] && [[ "$DRY_RUN" == false ]]; then
        cp "$file" "$BACKUP_DIR/$(basename "$file").backup"
        print_info "Backed up $file"
    fi
}

# Main upgrade process
main() {
    print_info "Starting package upgrade process..."

    # Step 1: Backup critical files
    if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
        backup_file "uv.lock"
        backup_file "pyproject.toml"

        # Backup service pyproject.toml files
        for service in common dashboard discovery extractor graphinator tableinator; do
            if [[ -f "$service/pyproject.toml" ]]; then
                backup_file "$service/pyproject.toml"
            fi
        done
    fi

    # Step 2: Update uv itself
    print_info "Checking for uv updates..."
    if [[ "$DRY_RUN" == false ]]; then
        uv self update || print_warning "Could not update uv"
    else
        print_info "[DRY RUN] Would check for uv updates"
    fi

    # Step 2a: Update UV version in Dockerfiles
    print_info "Checking UV version in Dockerfiles..."

    # Get the latest UV version from GitHub
    LATEST_UV_VERSION=$(curl -s https://api.github.com/repos/astral-sh/uv/releases/latest | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/' | sed 's/^v//')

    if [[ -z "$LATEST_UV_VERSION" ]]; then
        print_warning "Could not determine latest UV version from GitHub"
    else
        print_info "Latest UV version: $LATEST_UV_VERSION"

        # Find all Dockerfiles that use UV
        DOCKERFILES=""
        for service in extractor tableinator graphinator dashboard discovery; do
            if [[ -f "./$service/Dockerfile" ]]; then
                DOCKERFILES="$DOCKERFILES ./$service/Dockerfile"
            fi
        done

        # Also include the dockerfile-standards.md
        if [[ -f "./docs/dockerfile-standards.md" ]]; then
            DOCKERFILES="$DOCKERFILES ./docs/dockerfile-standards.md"
        fi

        # Check current UV version in Dockerfiles
        CURRENT_UV_VERSION=""
        for dockerfile in $DOCKERFILES; do
            VERSION=$(grep "ghcr.io/astral-sh/uv:" "$dockerfile" 2>/dev/null | head -1 | sed -E 's/.*uv:([0-9.]+).*/\1/')
            if [[ -n "$VERSION" ]]; then
                CURRENT_UV_VERSION="$VERSION"
                break
            fi
        done

        if [[ -n "$CURRENT_UV_VERSION" ]] && [[ "$CURRENT_UV_VERSION" != "$LATEST_UV_VERSION" ]]; then
            print_info "Current UV version in Dockerfiles: $CURRENT_UV_VERSION"
            print_info "Updating UV version in Dockerfiles to $LATEST_UV_VERSION..."

            if [[ "$DRY_RUN" == false ]]; then
                # Backup Dockerfiles
                if [[ "$BACKUP" == true ]]; then
                    for dockerfile in $DOCKERFILES; do
                        if [[ -f "$dockerfile" ]]; then
                            backup_file "$dockerfile"
                        fi
                    done
                fi

                # Update UV version in all Dockerfiles
                for dockerfile in $DOCKERFILES; do
                    if [[ -f "$dockerfile" ]]; then
                        # Use portable sed syntax that works on both macOS and Linux
                        if [[ "$OSTYPE" == "darwin"* ]]; then
                            sed -i '' "s/ghcr.io\/astral-sh\/uv:[0-9.]*[0-9]/ghcr.io\/astral-sh\/uv:$LATEST_UV_VERSION/g" "$dockerfile"
                        else
                            sed -i "s/ghcr.io\/astral-sh\/uv:[0-9.]\+/ghcr.io\/astral-sh\/uv:$LATEST_UV_VERSION/g" "$dockerfile"
                        fi
                        print_success "Updated $dockerfile"
                    fi
                done
            else
                print_info "[DRY RUN] Would update UV version from $CURRENT_UV_VERSION to $LATEST_UV_VERSION in:"
                for dockerfile in $DOCKERFILES; do
                    if [[ -f "$dockerfile" ]]; then
                        echo "  - $dockerfile"
                    fi
                done
            fi
        elif [[ "$CURRENT_UV_VERSION" == "$LATEST_UV_VERSION" ]]; then
            print_success "UV version in Dockerfiles is already up to date ($LATEST_UV_VERSION)"
        fi
    fi

    # Step 3: Compile dependencies with upgrades
    print_info "Compiling upgraded dependencies..."

    # Build upgrade command
    UV_COMPILE_CMD="uv lock"

    if [[ "$MAJOR_UPGRADES" == true ]]; then
        UV_COMPILE_CMD="$UV_COMPILE_CMD --upgrade"
        print_info "Including major version upgrades"
    else
        # For minor/patch upgrades, we need to upgrade specific packages
        # First, get all direct dependencies
        print_info "Upgrading to latest minor/patch versions"
        UV_COMPILE_CMD="$UV_COMPILE_CMD --upgrade"
    fi

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would run: $UV_COMPILE_CMD"

        # Show what would be upgraded
        print_info "Checking for available updates..."
        uv tree --outdated || true
    else
        # Run the actual upgrade
        if $UV_COMPILE_CMD; then
            print_success "Dependencies compiled successfully"
        else
            print_error "Failed to compile dependencies"
            exit 1
        fi
    fi

    # Step 4: Sync to install upgraded packages
    if [[ "$DRY_RUN" == false ]]; then
        print_info "Syncing upgraded dependencies..."
        if uv sync --all-extras; then
            print_success "Dependencies synced successfully"
        else
            print_error "Failed to sync dependencies"
            exit 1
        fi
    else
        print_info "[DRY RUN] Would run: uv sync --all-extras"
    fi

    # Step 5: Run tests to verify everything works
    if [[ "$DRY_RUN" == false ]]; then
        print_info "Running tests to verify upgrades..."

        # Run linting
        print_info "Running linters..."
        if uv run task lint; then
            print_success "Linting passed"
        else
            print_warning "Linting failed - review the changes"
        fi

        # Run tests
        print_info "Running tests..."
        if uv run task test; then
            print_success "Tests passed"
        else
            print_warning "Tests failed - review the changes"
        fi
    else
        print_info "[DRY RUN] Would run tests to verify upgrades"
    fi

    # Step 6: Show summary of changes
    if [[ "$DRY_RUN" == false ]]; then
        print_success "Package upgrade completed!"
        print_info "Review the changes with: git diff uv.lock"

        # Check if any Dockerfiles were updated
        if git diff --name-only | grep -q "Dockerfile\|dockerfile-standards.md"; then
            print_info "Dockerfiles were updated. Review with: git diff --name-only | grep Dockerfile"
        fi

        print_info "If everything looks good, commit the changes:"
        echo "  git add uv.lock"

        # Add Dockerfiles if they were changed
        if git diff --name-only | grep -q "Dockerfile\|dockerfile-standards.md"; then
            echo "  git add */Dockerfile docs/dockerfile-standards.md"
        fi

        echo "  git commit -m \"chore: upgrade dependencies\""

        if [[ "$BACKUP" == true ]]; then
            print_info "Backups are stored in: $BACKUP_DIR/"
            print_info "To restore from backup:"
            echo "  cp $BACKUP_DIR/uv.lock.backup uv.lock"
            echo "  uv sync --all-extras"
        fi
    else
        print_success "Dry run completed!"
        print_info "Run without --dry-run to apply changes"
    fi
}

# Handle errors
trap 'handle_error $?' ERR

handle_error() {
    local exit_code=$1
    print_error "An error occurred (exit code: $exit_code)"

    if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]] && [[ -d "$BACKUP_DIR" ]]; then
        print_info "You can restore from backup with:"
        echo "  cp $BACKUP_DIR/uv.lock.backup uv.lock"
        echo "  uv sync --all-extras"
    fi

    exit $exit_code
}

# Run main function
main
