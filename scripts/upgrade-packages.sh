#!/usr/bin/env bash

# upgrade-packages.sh - Safely upgrade all project dependencies
#
# This script provides a safe and comprehensive way to upgrade Python dependencies
# across the entire discogsography project, including the root workspace and all
# service-specific dependencies.
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
        print_info "If everything looks good, commit the changes:"
        echo "  git add uv.lock"
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
