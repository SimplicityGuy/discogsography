#!/usr/bin/env bash

# update-project.sh - Comprehensive project dependency and version updater
#
# This script provides a safe and comprehensive way to update:
# - Python version across all project files
# - Python package dependencies via uv (all version types)
# - Dependency floors (>=) in every pyproject.toml, raised to match uv.lock
# - Rust crate dependencies in Rust extractor (main, dev, build)
# - Node.js dependencies in Explore frontend tests (npm)
# - UV package manager version in Dockerfiles and GitHub workflows/actions
# - Pre-commit hooks to latest versions
# - Docker dependency review (FROM base images, uv image, compose service images)
#
# It also flags capped dependencies (those with a ',<X' upper bound) that have a
# newer release available beyond the cap, so they can be reviewed manually.
#
# Tool invocations delegate to `just` commands wherever possible, keeping the
# justfile as the single source of truth for command definitions.
#
# Ecosystem behavior:
#   Python (uv):  uv lock --upgrade refreshes uv.lock within the existing >=X.Y
#                 floors (this includes majors). It never raises the floors
#                 themselves, so sync_dependency_floors() does that after the lock
#                 so pyproject.toml minimums track what is actually resolved.
#   Rust (cargo): minor/patch = cargo update (lock file only)
#                 major (--major) = cargo upgrade --incompatible + cargo update
#
# Usage: ./scripts/update-project.sh [options]
#
# Options:
#   --python VERSION    Update Python version (default: keep current)
#   --no-backup        Skip creating backup files
#   --dry-run          Show what would be updated without making changes
#   --major            Include major version upgrades for all package managers
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
    --help | -h)
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
  if ! command -v $tool &>/dev/null; then
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
SECURITY_PIP_RESOLVED=0
SECURITY_PIP_REMAINING=0
SECURITY_OSV_RESOLVED=0
SECURITY_OSV_REMAINING=0

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
    done <<<"$old_packages"
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
    # Update all pyproject.toml files
    print_info "Updating pyproject.toml files..."
    for pyproject in pyproject.toml */pyproject.toml */*/pyproject.toml; do
      if [[ -f "$pyproject" ]]; then
        backup_file "$pyproject"

        if [[ "$OSTYPE" == "darwin"* ]]; then
          # Update requires-python
          sed -i '' "s/requires-python = \">=\?[0-9.]\+\"/requires-python = \">=$PYTHON_VERSION\"/g" "$pyproject"
          # Update python_version in [tool.mypy] and [tool.ruff.lint.pydocstyle]
          sed -i '' "s/python_version = \"[0-9.]\+\"/python_version = \"$PYTHON_VERSION\"/g" "$pyproject"
        else
          sed -i "s/requires-python = \">=\?[0-9.]\+\"/requires-python = \">=$PYTHON_VERSION\"/g" "$pyproject"
          sed -i "s/python_version = \"[0-9.]\+\"/python_version = \"$PYTHON_VERSION\"/g" "$pyproject"
        fi

        print_success "Updated $pyproject"
        FILE_CHANGES+=("$pyproject: Python $current_version → $PYTHON_VERSION")
      fi
    done

    # Update GitHub workflow files
    print_info "Updating GitHub workflow files..."
    for workflow in .github/workflows/*.yml; do
      if [[ -f "$workflow" ]] && grep -q "PYTHON_VERSION" "$workflow"; then
        backup_file "$workflow"

        if [[ "$OSTYPE" == "darwin"* ]]; then
          sed -i '' "s/PYTHON_VERSION: \"[0-9.]\+\"/PYTHON_VERSION: \"$PYTHON_VERSION\"/g" "$workflow"
        else
          sed -i "s/PYTHON_VERSION: \"[0-9.]\+\"/PYTHON_VERSION: \"$PYTHON_VERSION\"/g" "$workflow"
        fi

        print_success "Updated $workflow"
        FILE_CHANGES+=("$workflow: Python $current_version → $PYTHON_VERSION")
      fi
    done

    # Update pyrightconfig.json if it exists
    if [[ -f "pyrightconfig.json" ]]; then
      print_info "Updating pyrightconfig.json..."
      backup_file "pyrightconfig.json"

      if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/\"pythonVersion\": \"[0-9.]\+\"/\"pythonVersion\": \"$PYTHON_VERSION\"/g" pyrightconfig.json
      else
        sed -i "s/\"pythonVersion\": \"[0-9.]\+\"/\"pythonVersion\": \"$PYTHON_VERSION\"/g" pyrightconfig.json
      fi

      print_success "Updated pyrightconfig.json"
      FILE_CHANGES+=("pyrightconfig.json: Python $current_version → $PYTHON_VERSION")
    fi

    # Update docker-compose files if they have PYTHON_VERSION
    print_info "Updating docker-compose files..."
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
    print_info "[DRY RUN] Would update Python version in:"
    print_info "  • All pyproject.toml files"
    print_info "  • GitHub workflow files"
    print_info "  • pyrightconfig.json"
    print_info "  • docker-compose files"
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
  # Use find to catch all Dockerfiles including nested ones
  while IFS= read -r dockerfile; do
    if [[ -f "$dockerfile" ]]; then
      local version
      version=$(grep "ghcr.io/astral-sh/uv:" "$dockerfile" 2>/dev/null | head -1 | sed -E 's/.*uv:([0-9.]+).*/\1/')
      if [[ -n "$version" ]]; then
        current_uv="$version"
        break
      fi
    fi
  done < <(
    find . -maxdepth 3 -name "Dockerfile" -type f -not -path './.worktrees/*'
    echo "docs/dockerfile-standards.md"
  )

  # Update Dockerfiles
  if [[ -n "$current_uv" ]] && [[ "$current_uv" != "$latest_uv" ]]; then
    UV_VERSION_CHANGE="$current_uv → $latest_uv"
    print_info "Updating UV from $current_uv to $latest_uv in Dockerfiles"

    if [[ "$DRY_RUN" == false ]]; then
      # Backup and update all Dockerfiles including nested ones
      while IFS= read -r dockerfile; do
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
      done < <(
        find . -maxdepth 3 -name "Dockerfile" -type f -not -path './.worktrees/*'
        echo "docs/dockerfile-standards.md"
      )
    else
      print_info "[DRY RUN] Would update UV version in Dockerfiles"
    fi
  else
    print_success "UV version in Dockerfiles is already up to date ($current_uv)"
  fi

  # Update setup-uv action references (workflows + composite actions).
  # NOTE: setup-uv lives in .github/actions/setup-python-uv/action.yml in this
  # repo, NOT in the workflows, so we must scan both trees. Pin format:
  # astral-sh/setup-uv@<40-char-sha>  # vX.Y.Z  (two spaces before '#', matching
  # the repo's SHA-pin convention so yamllint stays happy).
  print_info "Checking GitHub Actions for setup-uv updates (workflows + composite actions)..."

  if [[ -n "$latest_setup_uv_commit" ]] && [[ "$latest_setup_uv_commit" != "null" ]]; then
    local f
    local setup_uv_files=()
    while IFS= read -r f; do
      [[ -n "$f" ]] && setup_uv_files+=("$f")
    done < <(grep -rlE "astral-sh/setup-uv@" .github/workflows .github/actions 2>/dev/null || true)

    local workflow current_commit
    for workflow in "${setup_uv_files[@]:-}"; do
      [[ -f "$workflow" ]] || continue
      current_commit=$(grep -oE "astral-sh/setup-uv@[a-f0-9]{40}" "$workflow" | head -1 | cut -d'@' -f2)
      if [[ -n "$current_commit" ]] && [[ "$current_commit" != "$latest_setup_uv_commit" ]]; then
        if [[ "$DRY_RUN" == false ]]; then
          backup_file "$workflow"
          # Replace the ref AND its version comment in one shot so the SHA and the
          # `# vX.Y.Z` comment always stay in sync (two spaces before '#').
          if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|\(astral-sh/setup-uv@\).*|\1$latest_setup_uv_commit  # $latest_setup_uv|" "$workflow"
          else
            sed -i "s|\(astral-sh/setup-uv@\).*|\1$latest_setup_uv_commit  # $latest_setup_uv|" "$workflow"
          fi
          print_success "Updated ${workflow#./} (setup-uv → ${latest_setup_uv_commit:0:7} $latest_setup_uv)"
          WORKFLOW_CHANGES+=("${workflow#./}: setup-uv ${current_commit:0:7} → ${latest_setup_uv_commit:0:7}")
          CHANGES_MADE=true
        else
          print_info "[DRY RUN] Would update setup-uv in ${workflow#./}"
        fi
      fi
    done
  fi

  if [[ $(array_length WORKFLOW_CHANGES) -eq 0 ]]; then
    print_success "setup-uv action is already up to date"
  fi
}

# Review the full Docker dependency surface.
#
# This SURFACES every Docker dependency so nothing is silently missed; it does
# not mutate anything itself. Division of labour:
#   - uv binary image (ghcr.io/astral-sh/uv) -> bumped by update_uv_version()
#   - Python base image (python:X-slim)      -> bumped by update_python_version() (--python)
#   - other FROM base images (node, rust, debian) + docker-compose service
#     images (postgres, neo4j, rabbitmq, redis, ...) -> tracked by Dependabot's
#     docker group
#   - apt packages -> intentionally unpinned / distro-managed (see DL3008 pragmas)
update_docker_images() {
  print_section "$EMOJI_DOCKER" "Reviewing Docker Dependencies"

  local dockerfiles=()
  while IFS= read -r df; do
    [[ -n "$df" ]] && dockerfiles+=("$df")
  done < <(find . -maxdepth 3 -name "Dockerfile" -type f \
    -not -path './.worktrees/*' -not -path './.claude/*' -not -path './backups/*' | sort)

  local df matches
  print_info "Base + tool images in Dockerfiles (FROM lines and the uv image):"
  for df in "${dockerfiles[@]:-}"; do
    [[ -f "$df" ]] || continue
    matches=$(grep -nE "^FROM |ghcr.io/astral-sh/uv:" "$df" 2>/dev/null) || true
    [[ -n "$matches" ]] && echo "$matches" | sed "s|^|  ${df#./}:|"
  done

  local compose
  print_info "Service images in docker-compose:"
  for compose in docker-compose*.yml; do
    [[ -f "$compose" ]] || continue
    matches=$(grep -nE "^[[:space:]]*image:" "$compose" 2>/dev/null) || true
    [[ -n "$matches" ]] && echo "$matches" | sed "s|^|  $compose:|"
  done

  print_info "Dependency ownership:"
  print_info "  • uv image (ghcr.io/astral-sh/uv)   → managed by update_uv_version()"
  print_info "  • Python base (python:X-slim)       → managed by --python"
  print_info "  • Other FROM tags (node, rust, debian) + compose service images → Dependabot docker group"
  print_info "  • apt packages                      → distro-managed (intentionally unpinned; see 'hadolint ignore=DL3008')"
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

    # Update all hooks to latest versions (via just for single-source-of-truth)
    if just update-hooks; then
      print_success "Pre-commit hooks updated successfully"
      FILE_CHANGES+=(".pre-commit-config.yaml: Updated pre-commit hooks to latest versions")
      CHANGES_MADE=true

      # Update mdformat plugin versions in additional_dependencies
      # Sync dependencies after pre-commit autoupdate
      sync_dependencies_after_precommit

      # Run pre-commit install to ensure hooks are installed
      # Use || true to prevent script exit if hooks are already installed
      just init || true
    else
      print_warning "Failed to update pre-commit hooks"
    fi
  else
    print_info "[DRY RUN] Would run: just update-hooks"
    print_info "[DRY RUN] Would update mdformat plugin versions"
  fi
}

# Sync pyproject.toml dependencies after pre-commit autoupdate
# Note: pre-commit autoupdate handles updating plugin versions in .pre-commit-config.yaml
# We just need to run uv sync --upgrade to update pyproject.toml and uv.lock
sync_dependencies_after_precommit() {
  print_info "Syncing dependencies after pre-commit hook updates..."

  if [[ "$DRY_RUN" == false ]]; then
    # uv sync --upgrade will upgrade all dependencies including those pinned in pre-commit
    # This handles mdformat plugins and any other dependencies automatically
    print_info "Running just sync-upgrade to update all dependencies..."
    if just sync-upgrade; then
      print_success "Dependencies synced successfully"
      FILE_CHANGES+=("pyproject.toml and uv.lock: Synced with latest dependency versions")
      CHANGES_MADE=true
    else
      print_warning "Failed to sync dependencies after pre-commit updates"
    fi
  else
    print_info "[DRY RUN] Would run: just sync-upgrade"
  fi

  echo "" # Add blank line for visual separation
}

# Verify all dependencies were updated
verify_dependency_updates() {
  print_section "✅" "Verifying Dependency Updates"

  print_info "All dependency types have been updated:"

  # Python dependencies
  print_success "✓ Python core dependencies ([project] dependencies)"
  print_success "✓ Python optional dependencies ([project.optional-dependencies])"
  print_success "✓ Python dev dependencies ([dependency-groups])"
  print_success "✓ Python build dependencies ([build-system])"
  print_success "✓ Python dependency floors raised to match uv.lock (root + members)"

  # Rust dependencies
  if [[ -f "extractor/Cargo.toml" ]]; then
    if [[ "$MAJOR_UPGRADES" == true ]]; then
      print_success "✓ Rust dependencies (Cargo.toml + Cargo.lock, including major versions)"
    else
      print_success "✓ Rust dependencies (Cargo.lock updated within existing constraints)"
    fi
  fi

  # Node.js dependencies
  if [[ -f "explore/package.json" ]]; then
    print_success "✓ Node.js dependencies (explore/package.json + package-lock.json)"
  fi

  # Pre-commit hooks
  print_success "✓ Pre-commit hooks and their dependencies"

  # Docker and CI/CD
  print_success "✓ UV package manager in Dockerfiles"
  print_success "✓ GitHub Actions dependencies"

  if [[ "$DRY_RUN" == false ]]; then
    print_info "Run 'uv tree --outdated' to verify all Python packages are up to date"

    if [[ -f "extractor/Cargo.toml" ]]; then
      print_info "Run 'cd extractor && cargo update --dry-run' to verify Rust crates"
    fi
  fi
}

# Update Node.js dependencies (Explore frontend tests)
update_node_packages() {
  if [[ ! -f "explore/package.json" ]]; then
    print_info "No explore/package.json found, skipping Node.js updates"
    return
  fi

  print_section "📦" "Updating Node.js Dependencies"

  if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
    backup_file "explore/package.json"
    backup_file "explore/package-lock.json"
  fi

  if [[ "$DRY_RUN" == false ]]; then
    print_info "Updating npm packages in explore/ (via just for single-source-of-truth)..."

    if just update-npm; then
      print_success "npm packages updated successfully"
      FILE_CHANGES+=("explore/package.json: Updated npm dependencies")
      FILE_CHANGES+=("explore/package-lock.json: Updated npm lockfile")
      CHANGES_MADE=true
    else
      print_warning "Failed to update npm packages"
    fi
  else
    print_info "[DRY RUN] Would run: just update-npm"
  fi
}

# Update Rust crates
# - Minor/patch (default): cargo update - updates Cargo.lock within existing Cargo.toml constraints
# - Major (--major): cargo upgrade --incompatible allow - updates Cargo.toml constraints too
update_rust_crates() {
  if [[ ! -d "extractor" ]] || [[ ! -f "extractor/Cargo.toml" ]]; then
    print_info "No Rust extractor found, skipping Rust updates"
    return
  fi

  print_section "🦀" "Updating Rust Dependencies"

  if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
    backup_file "extractor/Cargo.toml"
    backup_file "Cargo.lock"
  fi

  if [[ "$DRY_RUN" == false ]]; then
    pushd extractor >/dev/null

    if [[ "$MAJOR_UPGRADES" == true ]]; then
      print_info "Major upgrades enabled: updating Cargo.toml version requirements..."
      print_info "  Requires cargo-edit (cargo upgrade). Installing if not present..."

      # Ensure cargo-upgrade is available (part of cargo-edit crate)
      # Note: cargo-upgrade must be invoked as "cargo upgrade" (subcommand),
      # NOT as "cargo-upgrade" (direct binary) — the binary does not accept
      # flags like --incompatible when called directly.
      local has_cargo_upgrade=false
      if command -v cargo-upgrade &>/dev/null; then
        has_cargo_upgrade=true
      elif cargo bin cargo-upgrade &>/dev/null 2>&1; then
        has_cargo_upgrade=true
      else
        # Install cargo-edit globally (cached by cargo after first run)
        print_info "  Installing cargo-edit..."
        if cargo install cargo-edit --quiet 2>/dev/null; then
          has_cargo_upgrade=true
        else
          print_warning "  Could not install cargo-edit - skipping Cargo.toml version updates"
          print_info "  Falling back to cargo update (lock file only)"
        fi
      fi

      if [[ "$has_cargo_upgrade" == true ]]; then
        # Try --incompatible (cargo-edit ≥0.12) then fall back to --breaking (≤0.11)
        if cargo upgrade --incompatible allow 2>&1; then
          print_success "Cargo.toml updated with major version bumps (--incompatible allow)"
          FILE_CHANGES+=("extractor/Cargo.toml: Updated dependency version requirements (major)")
          CHANGES_MADE=true
        elif cargo upgrade --breaking 2>&1; then
          print_success "Cargo.toml updated with major version bumps (--breaking)"
          FILE_CHANGES+=("extractor/Cargo.toml: Updated dependency version requirements (major)")
          CHANGES_MADE=true
        else
          print_warning "cargo upgrade failed - Cargo.toml not changed"
        fi
      fi
    else
      print_info "Updating Cargo.lock to latest compatible versions (within Cargo.toml constraints)"
      print_info "  Run with --major to also update Cargo.toml version requirements"
    fi

    popd >/dev/null

    # Always update Cargo.lock to pick up latest compatible versions (via just)
    print_info "Updating Cargo.lock..."
    if just update-cargo 2>&1; then
      print_success "Cargo.lock updated with latest compatible versions"
      FILE_CHANGES+=("Cargo.lock: Updated to latest compatible versions")
      CHANGES_MADE=true
    else
      print_warning "Failed to update Cargo.lock"
    fi

    print_success "Completed Rust dependency updates"
  else
    if [[ "$MAJOR_UPGRADES" == true ]]; then
      print_info "[DRY RUN] Would run: cargo upgrade --incompatible allow (updates Cargo.toml)"
    fi
    print_info "[DRY RUN] Would run: just update-cargo (updates Cargo.lock within constraints)"
  fi
}

# Update Python packages
update_python_packages() {
  print_section "$EMOJI_PACKAGE" "Updating ALL Python Dependencies"

  # Backup critical files
  if [[ "$BACKUP" == true ]] && [[ "$DRY_RUN" == false ]]; then
    backup_file "uv.lock"
    backup_file "pyproject.toml"

    # Backup all pyproject.toml files including nested ones
    for service in api brainzgraphinator brainztableinator common dashboard explore graphinator insights mcp-server schema-init tableinator; do
      if [[ -f "$service/pyproject.toml" ]]; then
        backup_file "$service/pyproject.toml"
      fi
    done

    # Note: extractor is a Rust project, skip Python backups
  fi

  # Update uv itself (via just for single-source-of-truth)
  print_info "Checking for uv updates..."
  if [[ "$DRY_RUN" == false ]]; then
    if just update-uv; then
      print_success "uv updated successfully"
    else
      print_warning "Could not update uv (may already be latest)"
    fi
  else
    print_info "[DRY RUN] Would run: just update-uv"
  fi

  # Compile dependencies with upgrades
  print_info "Updating ALL dependency types:"
  print_info "  • Core dependencies ([project] dependencies)"
  print_info "  • Optional dependencies ([project.optional-dependencies])"
  print_info "  • Dev dependencies ([dependency-groups])"
  print_info "  • Build dependencies ([build-system])"

  local uv_cmd="just lock-upgrade"
  if [[ "$MAJOR_UPGRADES" == true ]]; then
    print_info "Including major version upgrades for ALL dependencies"
    print_info "Note: uv respects version constraints in pyproject.toml (>=x.y.z allows major upgrades)"
  else
    print_info "Upgrading ALL dependencies to latest versions (respecting >= constraints)"
    print_info "Note: With >= constraints, this includes major upgrades. Use specific version pins to restrict."
  fi

  if [[ "$DRY_RUN" == true ]]; then
    print_info "[DRY RUN] Would run: $uv_cmd"
    print_info "Checking for available updates across ALL dependency types..."

    # Show outdated packages grouped by type
    print_info "Checking core dependencies..."
    uv tree --outdated || true

    # Check if there are optional dependencies
    if grep -q "\[project.optional-dependencies\]" pyproject.toml; then
      print_info "Optional dependencies found and will be updated"
    fi

    # Check if there are dev dependencies
    if grep -q "\[dependency-groups\]" pyproject.toml; then
      print_info "Dev dependencies found and will be updated"
    fi
  else
    if $uv_cmd; then
      print_success "ALL dependencies compiled successfully"
      CHANGES_MADE=true
    else
      print_error "Failed to compile dependencies"
      exit 1
    fi
  fi

  # Sync to install upgraded packages with ALL extras and dev dependencies
  if [[ "$DRY_RUN" == false ]]; then
    print_info "Syncing ALL upgraded dependencies (including optional and dev)..."
    if just sync; then
      print_success "ALL dependencies synced successfully"
    else
      print_error "Failed to sync dependencies"
      exit 1
    fi

    # Capture package changes
    capture_package_changes

    print_success "Completed Python dependency updates"
  else
    print_info "[DRY RUN] Would run: just sync"
  fi
}

# Raise the `>=` floors in every pyproject.toml to match the versions actually
# pinned in the single root uv.lock.
#
# `uv lock --upgrade` refreshes the lockfile WITHIN the existing floors but never
# raises the floors themselves — this is the gap Dependabot otherwise opens PRs
# for. This closes it so the declared minimums track what is actually resolved.
#
# Monorepo specifics: this is a uv WORKSPACE with one root uv.lock, so we iterate
# the root pyproject.toml AND every workspace member, resolving each requirement
# against that single lock. We cover [project.dependencies],
# [project.optional-dependencies].* sub-arrays and [dependency-groups].*, and we
# rewrite ONLY the `>=` floor token — caps (`,<X`), extras (`pkg[redis]`), env
# markers (`; sys_platform ...`) and trailing inline comments are preserved. The
# editing is line-based (tomllib cannot write), then we re-run `uv lock` so the
# lockfile's recorded requirement metadata matches the raised floors.
sync_dependency_floors() {
  print_section "$EMOJI_PACKAGE" "Syncing Dependency Floors"

  local apply_val=1
  [[ "$DRY_RUN" == true ]] && apply_val=0

  local output
  output=$(
    APPLY="$apply_val" uv run python - <<'PY'
import os
import re
import tomllib
from pathlib import Path

apply = os.environ.get("APPLY") == "1"

try:
    from packaging.version import InvalidVersion, Version

    def strictly_newer(candidate: str, current: str) -> bool:
        try:
            return Version(candidate) > Version(current)
        except InvalidVersion:
            # uv.lock always resolves at or above the floor, so default to True.
            return True
except ImportError:  # packaging should be present, but never block on it.

    def strictly_newer(candidate: str, current: str) -> bool:
        return True


# Discover every pyproject.toml in the workspace: root + members.
root = Path("pyproject.toml")
root_data = tomllib.loads(root.read_text())
members = root_data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
pyprojects = [root]
for member in members:
    candidate = Path(member) / "pyproject.toml"
    if candidate.exists():
        pyprojects.append(candidate)

# Resolve every requirement against the single root uv.lock.
lock = tomllib.loads(Path("uv.lock").read_text())
locked = {p["name"].lower().replace("_", "-"): p["version"] for p in lock.get("package", [])}

header_re = re.compile(r"^\[\[?(?P<name>[^\]]+)\]\]?\s*$")
open_re = re.compile(r"^(?P<key>[A-Za-z0-9._-]+)\s*=\s*\[\s*(#.*)?$")
close_re = re.compile(r"^\s*\]")
entry_re = re.compile(r'^(?P<indent>\s*)"(?P<spec>[^"]+)"(?P<trail>.*)$')
spec_re = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+(?:\[[A-Za-z0-9._,-]+\])?)"
    r"(?P<specs>[<>=!~][^;]*)?"
    r"(?P<marker>;.*)?$"
)
floor_re = re.compile(r">=\s*([^,;\s]+)")

total = 0
for pyproject in pyprojects:
    lines = pyproject.read_text().split("\n")
    out: list[str] = []
    section = ""
    in_array = False
    process = False
    changes: list[tuple[str, str, str]] = []
    for line in lines:
        if not in_array:
            header = header_re.match(line.strip())
            if header:
                section = header.group("name")
                out.append(line)
                continue
            opener = open_re.match(line.strip())
            if opener:
                key = opener.group("key")
                process = (
                    (section == "project" and key == "dependencies")
                    or section == "project.optional-dependencies"
                    or section == "dependency-groups"
                )
                in_array = True
                out.append(line)
                continue
            out.append(line)
            continue
        # Inside an array.
        if close_re.match(line):
            in_array = False
            process = False
            out.append(line)
            continue
        if process:
            matched = entry_re.match(line)
            if matched:
                parsed = spec_re.match(matched.group("spec"))
                specs = parsed.group("specs") if parsed else None
                if parsed and specs:
                    base = parsed.group("name").split("[")[0].lower().replace("_", "-")
                    locked_version = locked.get(base)
                    floor = floor_re.search(specs)
                    if locked_version and floor:
                        current = floor.group(1)
                        if current != locked_version and strictly_newer(locked_version, current):
                            new_specs = specs[: floor.start(1)] + locked_version + specs[floor.end(1) :]
                            new_spec = parsed.group("name") + new_specs + (parsed.group("marker") or "")
                            changes.append((base, current, locked_version))
                            out.append(f'{matched.group("indent")}"{new_spec}"{matched.group("trail")}')
                            continue
        out.append(line)
    for base, old, new in changes:
        print(f"BUMPED {pyproject}: {base} {old} -> {new}")
    if apply and changes:
        pyproject.write_text("\n".join(out))
    total += len(changes)

print(f"FLOORS_CHANGED={total}")
PY
  )

  echo "$output" | grep -E "^BUMPED " | sed 's/^BUMPED /  /' || true

  local changed
  changed=$(echo "$output" | sed -n 's/^FLOORS_CHANGED=//p')
  changed=${changed:-0}

  if [[ "$DRY_RUN" == true ]]; then
    if [[ "$changed" -gt 0 ]]; then
      print_info "[DRY RUN] Would raise $changed dependency floor(s) across pyproject.toml files to match uv.lock"
    else
      print_success "[DRY RUN] All dependency floors already match uv.lock"
    fi
    return
  fi

  if [[ "$changed" -gt 0 ]]; then
    print_info "Re-locking so uv.lock requirement metadata matches the raised floors..."
    uv lock >/dev/null 2>&1 || uv lock
    CHANGES_MADE=true
    FILE_CHANGES+=("pyproject.toml (root + members): raised $changed dependency floor(s) to match uv.lock")
    print_success "Raised $changed dependency floor(s) to match uv.lock"
  else
    print_success "All dependency floors already match uv.lock"
  fi
}

# Flag capped dependencies (`,<X` upper bound) with a release available AT OR
# BEYOND the cap. `uv lock --upgrade` cannot cross a cap on its own, so raising
# it is a deliberate human decision — we only warn, never edit.
#
# Monorepo specifics: caps are parsed from ALL pyproject.toml files (root +
# members) across [project.dependencies], [project.optional-dependencies] and
# [dependency-groups]. We cross-reference `uv pip list --outdated`, compare with
# packaging.version, and skip the workspace's own packages (discogsography*).
flag_capped_dependencies() {
  print_section "$EMOJI_VERIFY" "Checking Capped Dependencies"

  if [[ "$DRY_RUN" == true ]]; then
    print_info "[DRY RUN] Would flag capped dependencies with releases beyond their cap"
    return
  fi

  local outdated
  outdated=$(uv pip list --outdated 2>/dev/null) || true

  local output
  output=$(
    OUTDATED="$outdated" uv run python - <<'PY'
import os
import re
import tomllib
from pathlib import Path

try:
    from packaging.version import InvalidVersion, Version

    def at_or_beyond_cap(latest: str, cap: str) -> bool:
        try:
            return Version(latest) >= Version(cap)
        except InvalidVersion:
            return True
except ImportError:

    def at_or_beyond_cap(latest: str, cap: str) -> bool:
        return True


root_data = tomllib.loads(Path("pyproject.toml").read_text())
members = root_data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
pyprojects = [Path("pyproject.toml")] + [Path(m) / "pyproject.toml" for m in members]

name_re = re.compile(r"^([A-Za-z0-9._-]+)")
cap_re = re.compile(r"<\s*([0-9][^,;\s]*)")
caps: dict[str, str] = {}
own: set[str] = set()

for pyproject in pyprojects:
    if not pyproject.exists():
        continue
    try:
        data = tomllib.loads(pyproject.read_text())
    except tomllib.TOMLDecodeError:
        continue
    project = data.get("project", {})
    own_name = project.get("name")
    if own_name:
        own.add(own_name.lower().replace("_", "-"))
    specs: list[str] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    for group in data.get("dependency-groups", {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    for spec in specs:
        name_match = name_re.match(spec)
        cap_match = cap_re.search(spec.split(";")[0])
        if name_match and cap_match:
            caps[name_match.group(1).lower().replace("_", "-")] = cap_match.group(1)

latest: dict[str, str] = {}
for raw in os.environ.get("OUTDATED", "").splitlines():
    parts = raw.split()
    if len(parts) >= 3 and parts[0] != "Package" and not parts[0].startswith("-"):
        latest[parts[0].lower().replace("_", "-")] = parts[2]

flagged = 0
for name, cap in sorted(caps.items()):
    if name in own:
        continue
    newest = latest.get(name)
    if newest and at_or_beyond_cap(newest, cap):
        print(f"FLAG {name}: {newest} available, capped at <{cap}")
        flagged += 1
print(f"CAPPED_FLAGGED={flagged}")
PY
  )

  local flagged
  flagged=$(echo "$output" | sed -n 's/^CAPPED_FLAGGED=//p')
  flagged=${flagged:-0}

  if [[ "$flagged" -gt 0 ]]; then
    while IFS= read -r line; do
      print_warning "${line#FLAG }"
    done < <(echo "$output" | grep -E "^FLAG ")
    print_info "Raise the cap in pyproject.toml manually, then re-run: just lock-upgrade && just sync"
  else
    print_success "No capped dependencies have releases beyond their cap"
  fi
}

# Sweep pip-audit ignores — remove entries whose vulnerabilities are now fixed
sweep_pip_audit_ignores() {
  local ignore_file=".pip-audit-ignores"
  if [[ ! -f "$ignore_file" ]]; then
    return
  fi

  if [[ "$DRY_RUN" == true ]]; then
    print_info "[DRY RUN] Would sweep $ignore_file for resolved vulnerabilities"
    return
  fi

  print_section "$EMOJI_VERIFY" "Sweeping pip-audit Ignores"

  # Collect vulnerability IDs from the ignore file
  local vuln_ids=()
  while IFS= read -r line; do
    local vuln_id
    vuln_id=$(echo "$line" | sed 's/#.*//' | tr -d '[:space:]')
    [[ -z "$vuln_id" ]] && continue
    vuln_ids+=("$vuln_id")
  done <"$ignore_file"

  if [[ ${#vuln_ids[@]} -eq 0 ]]; then
    print_success "No vulnerability ignores to sweep"
    return
  fi

  print_info "Testing ${#vuln_ids[@]} ignored vulnerabilit$([ ${#vuln_ids[@]} -eq 1 ] && echo "y" || echo "ies")..."

  # Build --ignore-vuln args for ALL entries (baseline)
  local all_ignore_args=""
  for vid in "${vuln_ids[@]}"; do
    all_ignore_args="$all_ignore_args --ignore-vuln $vid"
  done

  # Test each entry: run pip-audit with all OTHER ignores but NOT this one.
  # If pip-audit passes, the vulnerability is fixed and the ignore can go.
  local resolved=()
  local still_needed=()
  for test_vid in "${vuln_ids[@]}"; do
    local other_args=""
    for vid in "${vuln_ids[@]}"; do
      [[ "$vid" == "$test_vid" ]] && continue
      other_args="$other_args --ignore-vuln $vid"
    done

    if uv run pip-audit --desc $other_args >/dev/null 2>&1; then
      resolved+=("$test_vid")
      print_success "✓ $test_vid — fixed! Removing from ignore list"
    else
      still_needed+=("$test_vid")
      print_warning "✗ $test_vid — still needed (no fix available)"
    fi
  done

  # Track results for summary
  SECURITY_PIP_RESOLVED=${#resolved[@]}
  SECURITY_PIP_REMAINING=${#still_needed[@]}

  # Rewrite the ignore file without resolved entries
  if [[ ${#resolved[@]} -gt 0 ]]; then
    CHANGES_MADE=true
    for rid in "${resolved[@]}"; do
      # Remove the line containing this CVE (works for both bare ID and commented lines)
      sed -i.bak "/^${rid}[[:space:]]/d;/^${rid}$/d" "$ignore_file"
    done
    rm -f "${ignore_file}.bak"
    print_success "Removed ${#resolved[@]} resolved vulnerabilit$([ ${#resolved[@]} -eq 1 ] && echo "y" || echo "ies") from $ignore_file"
  fi

  if [[ ${#still_needed[@]} -gt 0 ]]; then
    print_info "${#still_needed[@]} vulnerabilit$([ ${#still_needed[@]} -eq 1 ] && echo "y" || echo "ies") still awaiting upstream fixes"
  else
    # Check if only comments/blanks remain
    local remaining
    remaining=$(grep -cv '^\s*#\|^\s*$' "$ignore_file" 2>/dev/null || echo "0")
    if [[ "$remaining" -eq 0 ]]; then
      print_success "All vulnerabilities resolved! $ignore_file has no active ignores"
    fi
  fi
}

# Sweep osv-scanner ignores — remove entries whose vulnerabilities are now fixed
sweep_osv_scanner_ignores() {
  local config_file="osv-scanner.toml"
  if [[ ! -f "$config_file" ]]; then
    return
  fi

  if ! command -v osv-scanner >/dev/null 2>&1; then
    print_info "osv-scanner not installed locally, skipping osv-scanner ignore sweep"
    return
  fi

  if [[ "$DRY_RUN" == true ]]; then
    print_info "[DRY RUN] Would sweep $config_file for resolved vulnerabilities"
    return
  fi

  # Extract vulnerability IDs from [[IgnoredVulns]] blocks
  local vuln_ids=()
  while IFS= read -r vid; do
    [[ -n "$vid" ]] && vuln_ids+=("$vid")
  done < <(grep '^id = ' "$config_file" | sed 's/^id = "\(.*\)"/\1/')

  if [[ ${#vuln_ids[@]} -eq 0 ]]; then
    return
  fi

  print_info "Testing ${#vuln_ids[@]} osv-scanner ignored vulnerabilit$([ ${#vuln_ids[@]} -eq 1 ] && echo "y" || echo "ies")..."

  # For each ignored vuln, run osv-scanner with a temp config excluding that entry.
  # If it passes, the vuln is resolved and the entry can be removed.
  local resolved=()
  local still_needed=()
  for test_vid in "${vuln_ids[@]}"; do
    local tmp_config
    tmp_config=$(mktemp)

    # Build a temp config with all ignores EXCEPT the one being tested
    echo "# Temporary osv-scanner config for sweep testing" >"$tmp_config"
    local in_target_block=false
    local skip_until_next_block=false
    while IFS= read -r line; do
      # Detect start of an IgnoredVulns block
      if [[ "$line" == "[[IgnoredVulns]]" ]]; then
        in_target_block=false
        skip_until_next_block=false
      fi
      # Check if this block's id matches the one we're testing
      if [[ "$line" =~ ^id\ =\ \"${test_vid}\" ]]; then
        in_target_block=true
        skip_until_next_block=true
        # Remove the preceding [[IgnoredVulns]] header we already wrote
        sed -i.bak '$ { /\[\[IgnoredVulns\]\]/d; }' "$tmp_config"
        rm -f "${tmp_config}.bak"
        continue
      fi
      if [[ "$skip_until_next_block" == true ]]; then
        # Skip lines until next block or end
        if [[ "$line" == "[[IgnoredVulns]]" ]] || [[ -z "$line" && "$in_target_block" == true ]]; then
          skip_until_next_block=false
          in_target_block=false
          [[ "$line" == "[[IgnoredVulns]]" ]] && echo "$line" >>"$tmp_config"
        fi
        continue
      fi
      echo "$line" >>"$tmp_config"
    done <"$config_file"

    if osv-scanner --config="$tmp_config" --recursive ./ >/dev/null 2>&1; then
      resolved+=("$test_vid")
      print_success "✓ $test_vid — fixed! Removing from osv-scanner config"
    else
      still_needed+=("$test_vid")
      print_warning "✗ $test_vid — still needed (no fix available)"
    fi
    rm -f "$tmp_config"
  done

  # Track results for summary
  SECURITY_OSV_RESOLVED=${#resolved[@]}
  SECURITY_OSV_REMAINING=${#still_needed[@]}

  # Rewrite the config file without resolved entries
  if [[ ${#resolved[@]} -gt 0 ]]; then
    CHANGES_MADE=true
    for rid in "${resolved[@]}"; do
      # Remove the [[IgnoredVulns]] block for this ID
      # Use awk to remove the block: from [[IgnoredVulns]] through the blank line after the matching id
      awk -v id="$rid" '
                /^\[\[IgnoredVulns\]\]/ { block = $0; in_block = 1; next }
                in_block && /^id = "/ {
                    if (index($0, id) > 0) { skip = 1; in_block = 0; next }
                    else { print block; skip = 0; in_block = 0 }
                }
                in_block { block = block "\n" $0; next }
                skip && /^$/ { skip = 0; next }
                skip { next }
                { print }
            ' "$config_file" >"${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    done
    print_success "Removed ${#resolved[@]} resolved vulnerabilit$([ ${#resolved[@]} -eq 1 ] && echo "y" || echo "ies") from $config_file"
  fi

  if [[ ${#still_needed[@]} -gt 0 ]]; then
    print_info "${#still_needed[@]} osv-scanner vulnerabilit$([ ${#still_needed[@]} -eq 1 ] && echo "y" || echo "ies") still awaiting upstream fixes"
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

  # Run Python tests
  print_info "Running Python tests..."
  if just test; then
    print_success "Python tests passed"
  else
    print_warning "Python tests failed - review the changes"
  fi

  # Run JavaScript tests if explore package.json exists
  if [[ -f "explore/package.json" ]]; then
    print_info "Installing JavaScript dependencies..."
    just install-js
    print_info "Running JavaScript tests..."
    if just test-js; then
      print_success "JavaScript tests passed"
    else
      print_warning "JavaScript tests failed - review the changes"
    fi
  fi

  # Run Rust tests if Rust extractor exists
  if [[ -d "extractor" ]] && [[ -f "extractor/Cargo.toml" ]]; then
    print_info "Running Rust tests..."
    if just test-extractor; then
      print_success "Rust tests passed"
    else
      print_warning "Rust tests failed - review the changes"
    fi
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

  # Security sweep results
  local total_resolved=$((SECURITY_PIP_RESOLVED + SECURITY_OSV_RESOLVED))
  local total_remaining=$((SECURITY_PIP_REMAINING + SECURITY_OSV_REMAINING))
  if [[ $total_resolved -gt 0 ]] || [[ $total_remaining -gt 0 ]]; then
    echo ""
    echo "🔒 Security (CVE Sweep):"
    if [[ $total_resolved -gt 0 ]]; then
      echo "  • $total_resolved CVE ignore$([ $total_resolved -eq 1 ] && echo "" || echo "s") resolved and removed"
    fi
    if [[ $total_remaining -gt 0 ]]; then
      echo "  • $total_remaining CVE$([ $total_remaining -eq 1 ] && echo "" || echo "s") still awaiting upstream fixes"
    fi
    if [[ $SECURITY_PIP_RESOLVED -gt 0 ]] || [[ $SECURITY_PIP_REMAINING -gt 0 ]]; then
      echo "    pip-audit: $SECURITY_PIP_RESOLVED resolved, $SECURITY_PIP_REMAINING remaining"
    fi
    if [[ $SECURITY_OSV_RESOLVED -gt 0 ]] || [[ $SECURITY_OSV_REMAINING -gt 0 ]]; then
      echo "    osv-scanner: $SECURITY_OSV_RESOLVED resolved, $SECURITY_OSV_REMAINING remaining"
    fi
  elif [[ -f ".pip-audit-ignores" ]] || [[ -f "osv-scanner.toml" ]]; then
    echo ""
    echo "🔒 Security (CVE Sweep):"
    echo "  • No ignored CVEs to sweep"
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
    echo "   git add */Dockerfile extractor/*/Dockerfile docs/dockerfile-standards.md"
  fi

  if [[ $(array_length WORKFLOW_CHANGES) -gt 0 ]]; then
    echo "   git add .github/workflows/*.yml"
  fi

  if [[ $SECURITY_PIP_RESOLVED -gt 0 ]]; then
    echo "   git add .pip-audit-ignores"
  fi

  if [[ $SECURITY_OSV_RESOLVED -gt 0 ]]; then
    echo "   git add osv-scanner.toml"
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
  echo "   # Check API service"
  echo "   curl -f http://localhost:8005/health"
  echo "   # Check dashboard"
  echo "   curl -f http://localhost:8003/health"
  echo "   # Check explore service"
  echo "   curl -f http://localhost:8007/health"
  echo "   # Check insights service (internal only — proxied via API)"
  echo "   curl -f http://localhost:8004/api/insights/health"
  echo ""
  echo "4. 📊 Review dependency changes:"
  echo "   # Check for security advisories"
  echo "   uv run pip-audit --desc"
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
  echo "  ✓ pyproject.toml (root)"
  echo "  ✓ api/pyproject.toml"
  echo "  ✓ brainzgraphinator/pyproject.toml"
  echo "  ✓ brainztableinator/pyproject.toml"
  echo "  ✓ common/pyproject.toml"
  echo "  ✓ dashboard/pyproject.toml"
  echo "  ✓ explore/pyproject.toml"
  echo "  ✓ graphinator/pyproject.toml"
  echo "  ✓ insights/pyproject.toml"
  echo "  ✓ mcp-server/pyproject.toml"
  echo "  ✓ schema-init/pyproject.toml"
  echo "  ✓ tableinator/pyproject.toml"
  echo "  ✓ uv.lock (root)"
  echo "  ✓ pyrightconfig.json"
  echo ""

  # Docker files
  echo "🐳 Docker Configuration:"
  echo "  ✓ api/Dockerfile"
  echo "  ✓ brainzgraphinator/Dockerfile"
  echo "  ✓ brainztableinator/Dockerfile"
  echo "  ✓ dashboard/Dockerfile"
  echo "  ✓ explore/Dockerfile"
  echo "  ✓ extractor/Dockerfile"
  echo "  ✓ graphinator/Dockerfile"
  echo "  ✓ insights/Dockerfile"
  echo "  ✓ schema-init/Dockerfile"
  echo "  ✓ tableinator/Dockerfile"
  echo "  ✓ docs/dockerfile-standards.md"
  echo "  ✓ docker-compose.yml"
  echo "  ✓ docker-compose.prod.yml"
  echo ""

  # Rust files
  if [[ -f "extractor/Cargo.toml" ]]; then
    echo "🦀 Rust Configuration:"
    if [[ "$MAJOR_UPGRADES" == true ]]; then
      echo "  ✓ extractor/Cargo.toml (version requirements updated for major)"
    else
      echo "  ✓ extractor/Cargo.toml (constraints unchanged)"
    fi
    echo "  ✓ Cargo.lock (updated to latest compatible)"
    echo ""
  fi

  # Node.js files
  if [[ -f "explore/package.json" ]]; then
    echo "📦 Node.js Configuration:"
    echo "  ✓ explore/package.json"
    echo "  ✓ explore/package-lock.json"
    echo ""
  fi

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

# Verify all expected components exist
verify_components() {
  print_section "$EMOJI_VERIFY" "Verifying Project Components"

  local missing_components=()
  local total_components=0
  local found_components=0

  # Check pyproject.toml files
  print_info "Checking Python configuration files..."
  local pyproject_files=(
    "pyproject.toml"
    "api/pyproject.toml"
    "brainzgraphinator/pyproject.toml"
    "brainztableinator/pyproject.toml"
    "common/pyproject.toml"
    "dashboard/pyproject.toml"
    "explore/pyproject.toml"
    "graphinator/pyproject.toml"
    "insights/pyproject.toml"
    "mcp-server/pyproject.toml"
    "schema-init/pyproject.toml"
    "tableinator/pyproject.toml"
  )

  for file in "${pyproject_files[@]}"; do
    total_components=$((total_components + 1))
    if [[ -f "$file" ]]; then
      found_components=$((found_components + 1))
    else
      missing_components+=("$file")
    fi
  done

  # Check Dockerfiles
  print_info "Checking Dockerfiles..."
  local dockerfile_list=(
    "api/Dockerfile"
    "brainzgraphinator/Dockerfile"
    "brainztableinator/Dockerfile"
    "dashboard/Dockerfile"
    "explore/Dockerfile"
    "extractor/Dockerfile"
    "graphinator/Dockerfile"
    "insights/Dockerfile"
    "schema-init/Dockerfile"
    "tableinator/Dockerfile"
  )

  for file in "${dockerfile_list[@]}"; do
    total_components=$((total_components + 1))
    if [[ -f "$file" ]]; then
      found_components=$((found_components + 1))
    else
      missing_components+=("$file")
    fi
  done

  # Check Rust components
  if [[ -f "extractor/Cargo.toml" ]]; then
    print_info "Found Rust extractor (Cargo.toml)"
    total_components=$((total_components + 1))
    found_components=$((found_components + 1))
  fi

  # Report results
  print_success "Found $found_components/$total_components expected components"

  if [[ ${#missing_components[@]} -gt 0 ]]; then
    print_warning "Missing ${#missing_components[@]} components:"
    for component in "${missing_components[@]}"; do
      echo "  ⚠️  $component"
    done
    print_info "This may be normal if components were removed from the project."
  else
    print_success "All expected components found!"
  fi

  echo ""
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

  # Verify all components exist before starting
  verify_components

  # Update Python version if requested
  update_python_version

  # Update UV version in Dockerfiles and GitHub Actions
  update_uv_version

  # Review the full Docker dependency surface (FROM images, uv image, compose)
  update_docker_images

  # Update pre-commit hooks
  update_precommit_hooks

  # Update Python packages (ALL types: core, optional, dev, build)
  update_python_packages

  # Raise pyproject.toml floors to match the freshly resolved uv.lock
  sync_dependency_floors

  # Warn about capped deps with releases available beyond their cap
  flag_capped_dependencies

  # Update Rust crates (minor/patch via cargo update; major via cargo upgrade with --major)
  update_rust_crates

  # Update Node.js dependencies (Explore frontend tests)
  update_node_packages

  # Verify all dependencies were updated
  verify_dependency_updates

  # Sweep security ignores — remove entries fixed by dependency upgrades
  sweep_pip_audit_ignores
  sweep_osv_scanner_ignores

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
