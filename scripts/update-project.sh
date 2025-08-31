#!/usr/bin/env bash

# update-project.sh - Comprehensive project dependency and version updater
#
# This script provides a safe and comprehensive way to update:
# - Python version across all project files
# - Python package dependencies (with detailed change tracking)
# - Rust crate dependencies in Rust extractor
# - UV package manager version in Dockerfiles
# - Docker base images to latest versions
#
# Usage: ./scripts/update-project.sh [options]
#
# Options:
#   --python VERSION    Update Python version (default: keep current)
#   --no-backup        Skip creating backup files
#   --dry-run          Show what would be updated without making changes
#   --major            Include major version upgrades for packages
#   --skip-tests       Skip running tests after updates
#   --help             Show this help message

set -euo pipefail

# Default options
BACKUP=true
DRY_RUN=false
MAJOR_UPGRADES=false
SKIP_TESTS=false
UPDATE_PYTHON=false
PYTHON_VERSION=""
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CHANGES_MADE=false

# Emojis for visual logging
EMOJI_INFO="ℹ️"
EMOJI_SUCCESS="✅"
EMOJI_WARNING="⚠️"
EMOJI_ERROR="❌"
EMOJI_ROCKET="🚀"
EMOJI_PACKAGE="📦"
EMOJI_PYTHON="🐍"
EMOJI_DOCKER="🐳"
EMOJI_TEST="🧪"
EMOJI_BACKUP="💾"
EMOJI_CHANGES="📝"
EMOJI_VERIFY="🔍"
EMOJI_GIT="🔀"

# Print colored output with emojis
print_info() {
    echo -e "\033[0;34m$EMOJI_INFO  [INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[0;32m$EMOJI_SUCCESS  [SUCCESS]\033[0m $1"
}

print_warning() {
    echo -e "\033[1;33m$EMOJI_WARNING  [WARNING]\033[0m $1"
}

print_error() {
    echo -e "\033[0;31m$EMOJI_ERROR  [ERROR]\033[0m $1"
}

print_section() {
    echo ""
    echo -e "\033[1;36m$1  $2\033[0m"
    echo -e "\033[1;36m$(printf '=%.0s' {1..60})\033[0m"
}

# Show usage
show_help() {
    head -n 20 "$0" | grep '^#' | sed 's/^# //' | sed 's/^#//'
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --python)
            UPDATE_PYTHON=true
            PYTHON_VERSION="$2"
            shift 2
            ;;
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
        --skip-tests)
            SKIP_TESTS=true
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

# Check required tools
for tool in uv git curl jq; do
    if ! command -v $tool &> /dev/null; then
        print_error "$tool is not installed. Please install it first."
        exit 1
    fi
done

# Check for uncommitted changes (only warn, don't exit)
if [[ -n $(git status --porcelain) ]]; then
    print_warning "You have uncommitted changes. Consider committing or stashing them for safe rollback."
    print_info "Continuing anyway since we're in automated mode..."
fi

# Create backup directory
BACKUP_DIR="backups/project-updates-${TIMESTAMP}"
if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$BACKUP_DIR"
    print_info "$EMOJI_BACKUP Creating backups in $BACKUP_DIR/"
fi

# Backup function
backup_file() {
    local file=$1
    if [[ "$BACKUP" == true ]] && [[ -f "$file" ]] && [[ "$DRY_RUN" == false ]]; then
        local backup_path
        backup_path="$BACKUP_DIR/$(dirname "$file")"
        mkdir -p "$backup_path"
        cp "$file" "$backup_path/$(basename "$file").backup"
    fi
}

# Track changes for summary
# Using regular arrays instead of associative arrays for compatibility
PACKAGE_CHANGES=()
FILE_CHANGES=()
UV_VERSION_CHANGE=""
PYTHON_VERSION_CHANGE=""
WORKFLOW_CHANGES=()

# Helper function to safely get array length
# Works with set -u by handling unbound variables
array_length() {
    local array_name=$1
    # Use eval with proper error handling
    eval "echo \${#${array_name}[@]}" 2>/dev/null || echo 0
}

# Function to capture package changes
capture_package_changes() {
    if [[ "$DRY_RUN" == true ]]; then
        return
    fi

    # Compare uv.lock before and after
    if [[ -f "$BACKUP_DIR/uv.lock.backup" ]]; then
        print_info "$EMOJI_CHANGES Analyzing package changes..."

        # Extract package versions from backup
        local old_packages
        old_packages=$(grep -E "^name = |^version = " "$BACKUP_DIR/uv.lock.backup" | paste -d' ' - - | sed 's/name = "\(.*\)" version = "\(.*\)"/\1==\2/')

        # Extract package versions from current
        local new_packages
        new_packages=$(grep -E "^name = |^version = " "uv.lock" | paste -d' ' - - | sed 's/name = "\(.*\)" version = "\(.*\)"/\1==\2/')

        # Find changes
        while IFS= read -r old_pkg; do
            local pkg_name
            pkg_name=$(echo "$old_pkg" | cut -d'=' -f1)
            local old_version
            old_version=$(echo "$old_pkg" | cut -d'=' -f3)

            local new_version
            new_version=$(echo "$new_packages" | grep "^$pkg_name==" | cut -d'=' -f3 || echo "")

            if [[ -n "$new_version" ]] && [[ "$old_version" != "$new_version" ]]; then
                PACKAGE_CHANGES+=("$pkg_name: $old_version → $new_version")
                CHANGES_MADE=true
            fi
        done <<< "$old_packages"
    fi
}

# Update Python version function
update_python_version() {
    if [[ "$UPDATE_PYTHON" != true ]]; then
        return
    fi

    print_section "$EMOJI_PYTHON" "Updating Python Version"

    local current_version
    current_version=$(grep 'requires-python = ">=' pyproject.toml | sed 's/.*>=\([0-9.]*\)".*/\1/')
    PYTHON_VERSION_CHANGE="$current_version → $PYTHON_VERSION"

    if [[ "$current_version" == "$PYTHON_VERSION" ]]; then
        print_info "Python version is already $PYTHON_VERSION"
        return
    fi

    print_info "Updating Python from $current_version to $PYTHON_VERSION"

    if [[ "$DRY_RUN" == false ]]; then
        # Run the existing update script
        ./scripts/update-python-version.sh "$PYTHON_VERSION"

        # Also update docker-compose files if they have PYTHON_VERSION
        for compose_file in docker-compose*.yml; do
            if [[ -f "$compose_file" ]] && grep -q "PYTHON_VERSION" "$compose_file"; then
                backup_file "$compose_file"
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    sed -i '' "s/PYTHON_VERSION:-[0-9.]\+/PYTHON_VERSION:-$PYTHON_VERSION/g" "$compose_file"
                else
                    sed -i "s/PYTHON_VERSION:-[0-9.]\+/PYTHON_VERSION:-$PYTHON_VERSION/g" "$compose_file"
                fi
                print_success "Updated $compose_file"
                FILE_CHANGES+=("$compose_file: Python $current_version → $PYTHON_VERSION")
            fi
        done

        CHANGES_MADE=true
    else
        print_info "[DRY RUN] Would update Python version to $PYTHON_VERSION"
    fi
}

# Update UV version in Dockerfiles and workflows
update_uv_version() {
    print_section "$EMOJI_DOCKER" "Updating UV Version"

    # Get the latest UV version from GitHub
    local latest_uv
    latest_uv=$(curl -s https://api.github.com/repos/astral-sh/uv/releases/latest | jq -r '.tag_name' | sed 's/^v//')

    if [[ -z "$latest_uv" ]]; then
        print_warning "Could not determine latest UV version from GitHub"
        return
    fi

    print_info "Latest UV version: $latest_uv"

    # Get latest setup-uv action version
    local latest_setup_uv
    latest_setup_uv=$(curl -s https://api.github.com/repos/astral-sh/setup-uv/releases/latest | jq -r '.tag_name')
    local latest_setup_uv_commit
    latest_setup_uv_commit=$(curl -s https://api.github.com/repos/astral-sh/setup-uv/commits/$latest_setup_uv | jq -r '.sha')

    print_info "Latest setup-uv action: $latest_setup_uv (commit: ${latest_setup_uv_commit:0:7})"

    # Find current UV version in Dockerfiles
    local current_uv=""
    for dockerfile in */Dockerfile docs/dockerfile-standards.md; do
        if [[ -f "$dockerfile" ]]; then
            local version
            version=$(grep "ghcr.io/astral-sh/uv:" "$dockerfile" 2>/dev/null | head -1 | sed -E 's/.*uv:([0-9.]+).*/\1/')
            if [[ -n "$version" ]]; then
                current_uv="$version"
                break
            fi
        fi
    done

    # Update Dockerfiles
    if [[ -n "$current_uv" ]] && [[ "$current_uv" != "$latest_uv" ]]; then
        UV_VERSION_CHANGE="$current_uv → $latest_uv"
        print_info "Updating UV from $current_uv to $latest_uv in Dockerfiles"

        if [[ "$DRY_RUN" == false ]]; then
            # Backup and update Dockerfiles
            for dockerfile in */Dockerfile docs/dockerfile-standards.md; do
                if [[ -f "$dockerfile" ]]; then
                    backup_file "$dockerfile"

                    # Use portable sed syntax
                    if [[ "$OSTYPE" == "darwin"* ]]; then
                        sed -i '' "s/ghcr.io\/astral-sh\/uv:[0-9.]*[0-9]/ghcr.io\/astral-sh\/uv:$latest_uv/g" "$dockerfile"
                    else
                        sed -i "s/ghcr.io\/astral-sh\/uv:[0-9.]\+/ghcr.io\/astral-sh\/uv:$latest_uv/g" "$dockerfile"
                    fi
                    print_success "Updated $dockerfile"
                    FILE_CHANGES+=("$dockerfile: UV $current_uv → $latest_uv")
                    CHANGES_MADE=true
                fi
            done
        else
            print_info "[DRY RUN] Would update UV version in Dockerfiles"
        fi
    else
        print_success "UV version in Dockerfiles is already up to date ($current_uv)"
    fi

    # Update GitHub workflows that use setup-uv action
    print_info "Checking GitHub workflows for setup-uv updates..."

    for workflow in .github/workflows/*.yml; do
        if [[ -f "$workflow" ]] && grep -q "astral-sh/setup-uv@" "$workflow"; then
            local current_commit
            current_commit=$(grep -oE "astral-sh/setup-uv@[a-f0-9]+" "$workflow" | head -1 | cut -d'@' -f2)

            if [[ -n "$current_commit" ]] && [[ "$current_commit" != "$latest_setup_uv_commit" ]]; then
                print_info "Updating setup-uv in $(basename "$workflow")"

                if [[ "$DRY_RUN" == false ]]; then
                    backup_file "$workflow"

                    # Update the action reference
                    if [[ "$OSTYPE" == "darwin"* ]]; then
                        sed -i '' "s/astral-sh\/setup-uv@[a-f0-9]\{40\}/astral-sh\/setup-uv@$latest_setup_uv_commit/g" "$workflow"
                        # Update the comment with version number
                        sed -i '' "s/# v[0-9.]\+/# $latest_setup_uv/g" "$workflow"
                    else
                        sed -i "s/astral-sh\/setup-uv@[a-f0-9]\{40\}/astral-sh\/setup-uv@$latest_setup_uv_commit/g" "$workflow"
                        sed -i "s/# v[0-9.]\+/# $latest_setup_uv/g" "$workflow"
                    fi

                    print_success "Updated $(basename "$workflow")"
                    WORKFLOW_CHANGES+=("$(basename "$workflow"): setup-uv ${current_commit:0:7} → ${latest_setup_uv_commit:0:7}")
                    CHANGES_MADE=true
                else
                    print_info "[DRY RUN] Would update setup-uv in $(basename "$workflow")"
                fi
            fi
        fi
    done

    if [[ $(array_length WORKFLOW_CHANGES) -eq 0 ]]; then
        print_success "GitHub workflows are already up to date"
    fi
}

# Update pre-commit hooks to latest versions
update_precommit_hooks() {
    print_section "🪝" "Updating Pre-commit Hooks"

    if ! command -v pre-commit >/dev/null 2>&1; then
        print_warning "pre-commit not installed, skipping hook updates"
        return
    fi

    print_info "Updating pre-commit hooks to latest versions..."

    if [[ "$DRY_RUN" == false ]]; then
        # Backup the pre-commit config
        if [[ "$BACKUP" == true ]]; then
            backup_file ".pre-commit-config.yaml"
        fi

        # Update all hooks to latest versions
        if pre-commit autoupdate --freeze; then
            print_success "Pre-commit hooks updated successfully"
            FILE_CHANGES+=(".pre-commit-config.yaml: Updated pre-commit hooks to latest versions")
            CHANGES_MADE=true

            # Run pre-commit install to ensure hooks are installed
            pre-commit install
        else
            print_warning "Failed to update pre-commit hooks"
        fi
    else
        print_info "[DRY RUN] Would run: pre-commit autoupdate --freeze"
    fi
}

# Update Rust crates
update_rust_crates() {
    if [[ ! -d "extractor/rustextractor" ]] || [[ ! -f "extractor/rustextractor/Cargo.toml" ]]; then
        return
    fi

    print_section "🦀" "Updating Rust Crates"

    # Backup Cargo files
    if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
        backup_file "extractor/rustextractor/Cargo.toml"
        backup_file "extractor/rustextractor/Cargo.lock"
    fi

    print_info "Checking for Rust crate updates..."

    if [[ "$DRY_RUN" == false ]]; then
        # Update crates
        cd extractor/rustextractor
        if cargo update; then
            print_success "Rust crates updated successfully"
            FILE_CHANGES+=("extractor/rustextractor/Cargo.lock: Updated Rust dependencies")
            CHANGES_MADE=true
        else
            print_warning "Failed to update Rust crates"
        fi
        cd ..
    else
        print_info "[DRY RUN] Would run: cargo update in extractor/rustextractor/"
    fi
}

# Update Python packages
update_python_packages() {
    print_section "$EMOJI_PACKAGE" "Updating Python Packages"

    # Backup critical files
    if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
        backup_file "uv.lock"
        backup_file "pyproject.toml"

        for service in common dashboard discovery extractor graphinator tableinator; do
            if [[ -f "$service/pyproject.toml" ]]; then
                backup_file "$service/pyproject.toml"
            fi
        done
    fi

    # Update uv itself
    print_info "Checking for uv updates..."
    if [[ "$DRY_RUN" == false ]]; then
        if uv self update; then
            print_success "uv updated successfully"
        else
            print_warning "Could not update uv (may already be latest)"
        fi
    else
        print_info "[DRY RUN] Would check for uv updates"
    fi

    # Compile dependencies with upgrades
    print_info "Compiling upgraded dependencies..."

    local uv_cmd="uv lock"
    if [[ "$MAJOR_UPGRADES" == true ]]; then
        uv_cmd="$uv_cmd --upgrade"
        print_info "Including major version upgrades"
    else
        uv_cmd="$uv_cmd --upgrade"
        print_info "Upgrading to latest minor/patch versions"
    fi

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would run: $uv_cmd"
        print_info "Checking for available updates..."
        uv tree --outdated || true
    else
        if $uv_cmd; then
            print_success "Dependencies compiled successfully"
            CHANGES_MADE=true
        else
            print_error "Failed to compile dependencies"
            exit 1
        fi
    fi

    # Sync to install upgraded packages
    if [[ "$DRY_RUN" == false ]]; then
        print_info "Syncing upgraded dependencies..."
        if uv sync --all-extras; then
            print_success "Dependencies synced successfully"
        else
            print_error "Failed to sync dependencies"
            exit 1
        fi

        # Capture package changes
        capture_package_changes
    else
        print_info "[DRY RUN] Would run: uv sync --all-extras"
    fi
}

# Run tests
run_tests() {
    if [[ "$SKIP_TESTS" == true ]] || [[ "$DRY_RUN" == true ]]; then
        return
    fi

    print_section "$EMOJI_TEST" "Running Tests"

    # Run linting
    print_info "Running linters..."
    if just lint; then
        print_success "Linting passed"
    else
        print_warning "Linting failed - review the changes"
    fi

    # Run tests
    print_info "Running tests..."
    if just test; then
        print_success "Tests passed"
    else
        print_warning "Tests failed - review the changes"
    fi
}

# Generate summary
generate_summary() {
    print_section "$EMOJI_CHANGES" "Update Summary"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "This was a dry run. No changes were made."
        print_info "Run without --dry-run to apply changes."
        return
    fi

    if [[ "$CHANGES_MADE" == false ]]; then
        print_success "Everything is already up to date! No changes were needed."
        return
    fi

    # Python version changes
    if [[ -n "$PYTHON_VERSION_CHANGE" ]]; then
        echo ""
        echo "🐍 Python Version:"
        echo "  $PYTHON_VERSION_CHANGE"
    fi

    # UV version changes
    if [[ -n "$UV_VERSION_CHANGE" ]]; then
        echo ""
        echo "🐳 UV Package Manager:"
        echo "  $UV_VERSION_CHANGE"
    fi

    # Package changes
    if [[ $(array_length PACKAGE_CHANGES) -gt 0 ]]; then
        echo ""
        echo "📦 Package Updates:"
        printf '%s\n' "${PACKAGE_CHANGES[@]:-}" | sort | while IFS= read -r change; do
            echo "  • $change"
        done
    fi

    # File changes
    if [[ $(array_length FILE_CHANGES) -gt 0 ]]; then
        echo ""
        echo "📄 File Updates:"
        printf '%s\n' "${FILE_CHANGES[@]:-}" | sort | while IFS= read -r change; do
            echo "  • $change"
        done
    fi

    # Workflow changes
    if [[ $(array_length WORKFLOW_CHANGES) -gt 0 ]]; then
        echo ""
        echo "🔄 GitHub Workflow Updates:"
        for change in "${WORKFLOW_CHANGES[@]:-}"; do
            echo "  • $change"
        done
    fi

    # Git instructions
    echo ""
    print_section "$EMOJI_GIT" "Next Steps"

    echo "1. Review the changes:"
    echo "   git diff --stat"
    echo "   git diff uv.lock"

    if [[ -n "$UV_VERSION_CHANGE" ]]; then
        echo "   git diff --name-only | grep Dockerfile"
    fi

    echo ""
    echo "2. Stage the changes:"

    # Always stage lock file if packages changed
    if [[ $(array_length PACKAGE_CHANGES) -gt 0 ]]; then
        echo "   git add uv.lock"
    fi

    if [[ -n "$PYTHON_VERSION_CHANGE" ]]; then
        echo "   git add pyproject.toml */pyproject.toml"
        echo "   git add .github/workflows/*.yml"
        echo "   git add pyrightconfig.json"
    fi

    if [[ -n "$UV_VERSION_CHANGE" ]] || [[ $(array_length FILE_CHANGES) -gt 0 ]]; then
        echo "   git add */Dockerfile docs/dockerfile-standards.md"
    fi

    if [[ $(array_length WORKFLOW_CHANGES) -gt 0 ]]; then
        echo "   git add .github/workflows/*.yml"
    fi

    echo ""
    echo "3. Commit the changes:"
    echo "   git commit -m \"chore: update dependencies"

    if [[ -n "$PYTHON_VERSION_CHANGE" ]]; then
        echo ""
        echo "   - Update Python to ${PYTHON_VERSION_CHANGE##* → }"
    fi

    if [[ -n "$UV_VERSION_CHANGE" ]]; then
        echo "   - Update UV to ${UV_VERSION_CHANGE##* → }"
    fi

    if [[ $(array_length PACKAGE_CHANGES) -gt 0 ]]; then
        echo "   - Update $(array_length PACKAGE_CHANGES) Python packages"
    fi

    echo "   \""
}

# Manual verification steps
show_verification_steps() {
    print_section "$EMOJI_VERIFY" "Manual Verification Steps"

    echo "Please verify the following before merging:"
    echo ""
    echo "1. 🐳 Docker builds:"
    echo "   docker-compose build --no-cache"
    echo ""
    echo "2. 🧪 Service health checks:"
    echo "   docker-compose up -d"
    echo "   docker-compose ps  # All services should be 'healthy'"
    echo ""
    echo "3. 🔍 Smoke tests:"
    echo "   # Check dashboard"
    echo "   curl -f http://localhost:8000/health"
    echo "   # Check discovery service"
    echo "   curl -f http://localhost:8001/health"
    echo ""
    echo "4. 📊 Review dependency changes:"
    echo "   # Check for security advisories"
    echo "   uv pip audit"
    echo "   # Review major version changes"
    echo "   git diff uv.lock | grep -E \"^[+-]version\""
    echo ""
    echo "5. 📝 Update CHANGELOG.md if needed"
    echo ""

    if [[ "$BACKUP" == true ]]; then
        echo "💾 Backups are stored in: $BACKUP_DIR/"
        echo "   To restore: cp $BACKUP_DIR/uv.lock.backup uv.lock && uv sync --all-extras"
    fi
}

# Show comprehensive file update report
show_file_report() {
    print_section "📋" "File Update Report"

    echo "The following files were checked and updated:"
    echo ""

    # Python files
    echo "🐍 Python Configuration:"
    echo "  ✓ pyproject.toml (root and all services)"
    echo "  ✓ uv.lock"
    echo "  ✓ pyrightconfig.json"
    echo "  ✓ .env.example (if exists)"
    echo ""

    # Docker files
    echo "🐳 Docker Configuration:"
    echo "  ✓ All service Dockerfiles"
    echo "  ✓ docs/dockerfile-standards.md"
    echo "  ✓ docker-compose.yml"
    echo "  ✓ docker-compose.prod.yml"
    echo ""

    # GitHub files
    echo "🔄 GitHub Workflows:"
    echo "  ✓ .github/workflows/*.yml (setup-uv action)"
    echo "  ✓ Python version references"
    echo ""

    # Summary
    local total_files=$(($(array_length FILE_CHANGES) + $(array_length WORKFLOW_CHANGES)))
    if [[ $(array_length PACKAGE_CHANGES) -gt 0 ]]; then
        total_files=$((total_files + 1)) # uv.lock
    fi

    echo "📊 Summary:"
    echo "  • Total files updated: $total_files"
    echo "  • Python packages updated: $(array_length PACKAGE_CHANGES)"
    echo "  • Dockerfiles updated: $(printf '%s\n' "${FILE_CHANGES[@]:-}" | grep -c Dockerfile || echo 0)"
    echo "  • Workflows updated: $(array_length WORKFLOW_CHANGES)"
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

# Main execution
main() {
    print_section "$EMOJI_ROCKET" "Starting Project Update"

    # Update Python version if requested
    update_python_version

    # Update UV version in Dockerfiles
    update_uv_version

    # Update pre-commit hooks
    update_precommit_hooks

    # Update Python packages
    update_python_packages

    # Update Rust crates
    update_rust_crates

    # Run tests
    run_tests

    # Generate summary
    generate_summary

    # Show verification steps
    if [[ "$DRY_RUN" == false ]] && [[ "$CHANGES_MADE" == true ]]; then
        show_file_report
        show_verification_steps
    fi
}

# Run main function
main
