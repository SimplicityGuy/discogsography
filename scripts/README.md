# 🛠️ Discogsography Scripts

This directory contains utility scripts for maintaining and updating the Discogsography project.

## 📦 update-project.sh

The main script for updating project dependencies and versions. This is a comprehensive tool that combines multiple update operations into a single, safe workflow.

### Features

- 🐍 **Python Version Updates**: Update Python version across all project files
- 📦 **Package Dependency Updates**: Update all Python packages with detailed change tracking
- 🦀 **Rust Dependency Updates**: Update all Rust crates in rustextractor (main, dev, and build deps)
- 🐳 **UV Package Manager Updates**: Update UV version in all Dockerfiles (including nested ones)
- 🔍 **Component Verification**: Verifies all expected components exist before updating
- 💾 **Automatic Backups**: Creates timestamped backups before making changes
- 📝 **Detailed Summaries**: Shows exactly what changed with before/after versions
- 🧪 **Automatic Testing**: Runs lints and tests after updates
- 🛡️ **Manual Verification Guide**: Provides step-by-step verification instructions

### Usage

```bash
# Basic usage - update all packages to latest compatible versions
./scripts/update-project.sh

# Update Python version
./scripts/update-project.sh --python 3.13

# Include major version upgrades
./scripts/update-project.sh --major

# Dry run - see what would change without making changes
./scripts/update-project.sh --dry-run

# Skip backups (not recommended)
./scripts/update-project.sh --no-backup

# Skip tests
./scripts/update-project.sh --skip-tests

# Combined example
./scripts/update-project.sh --python 3.13 --major --dry-run
```

### Options

- `--python VERSION`: Update Python to specified version
- `--no-backup`: Skip creating backup files
- `--dry-run`: Preview changes without applying them
- `--major`: Include major version upgrades for packages
- `--skip-tests`: Skip running tests after updates
- `--help`: Show help message

### Output

The script provides:

1. **Real-time progress** with emoji indicators
1. **Detailed change summary** showing:
   - Python version changes
   - UV package manager version changes
   - Individual package updates with version transitions
1. **Git commands** for staging and committing changes
1. **Manual verification steps** for ensuring everything works

### Component Coverage

The script now includes comprehensive component verification and updates **all** project files:

**Python Configuration (8 files)**:
- ✅ Root `pyproject.toml`
- ✅ All service `pyproject.toml` files including nested extractor subdirectories

**Docker Configuration (7 files)**:
- ✅ All service Dockerfiles including nested `extractor/pyextractor` and `extractor/rustextractor`
- ✅ Documentation standards file

**Rust Configuration (2 files)**:
- ✅ `Cargo.toml` and `Cargo.lock` for rustextractor

**Total: 15+ components verified and updated automatically**

### Example Output

```
🚀  Starting Project Update
============================================================

🔍  Verifying Project Components
============================================================
ℹ️  [INFO] Checking Python configuration files...
ℹ️  [INFO] Checking Dockerfiles...
ℹ️  [INFO] Found Rust extractor (Cargo.toml)
✅  [SUCCESS] Found 15/15 expected components
✅  [SUCCESS] All expected components found!

🐳  Updating UV Version in Dockerfiles
============================================================
ℹ️  [INFO] Latest UV version: 0.8.3
✅  [SUCCESS] UV version is already up to date (0.8.3)

📦  Updating Python Packages
============================================================
ℹ️  [INFO] Compiling upgraded dependencies...
✅  [SUCCESS] Dependencies compiled successfully
✅  [SUCCESS] Dependencies synced successfully

📝  Update Summary
============================================================

📦 Package Updates:
  • fastapi: 0.115.0 → 0.115.2
  • pydantic: 2.9.1 → 2.9.2
  • uvicorn: 0.32.0 → 0.32.1

🔀  Next Steps
============================================================
1. Review the changes:
   git diff --stat
   git diff uv.lock

2. Stage the changes:
   git add uv.lock

3. Commit the changes:
   git commit -m "chore: update dependencies
   - Update 3 Python packages
   "
```

## 🐍 update-python-version.sh

Standalone script for updating Python version across the codebase. This is called by `update-project.sh` when using the `--python` flag.

### Usage

```bash
# Update to Python 3.13 (default)
./scripts/update-python-version.sh

# Update to specific version
./scripts/update-python-version.sh 3.12
```

### What it updates

- All `pyproject.toml` files in:
  - Root directory
  - `common/`, `dashboard/`, `discovery/`, `graphinator/`, `tableinator/`
  - `extractor/pyextractor/` and `extractor/rustextractor/`
- All Dockerfiles including nested ones in:
  - `dashboard/`, `discovery/`, `graphinator/`, `tableinator/`
  - `extractor/pyextractor/` and `extractor/rustextractor/`
  - `docs/dockerfile-standards.md`
- GitHub workflow files
- `pyrightconfig.json`
- `.env.example` (if exists)

## 📦 upgrade-packages.sh (Deprecated)

**Note**: This script is now deprecated. Use `update-project.sh` instead.

The original package upgrade script. Its functionality has been integrated into `update-project.sh` with improvements:

- Better change tracking
- Emoji logging
- UV version updates
- More comprehensive summaries

## 🤖 GitHub Actions Integration

The project includes automated weekly dependency updates via GitHub Actions.

### Workflow: `.github/workflows/update-dependencies.yml`

- **Schedule**: Runs every Monday at 9:00 AM UTC
- **Manual trigger**: Can be run manually with options
- **Creates PR**: Opens a PR on the `automation/updates` branch
- **Auto-assigns**: Assigns to repository owner for review

### Manual Workflow Trigger

You can manually trigger the workflow from the Actions tab with options:

- **Update Python version**: Toggle to update Python
- **Python version**: Specify version (if updating)
- **Major upgrades**: Include major version updates

### PR Review Process

1. The bot creates a PR with detailed summary
1. Review the changes in the Files tab
1. Check that CI passes
1. Test locally if needed
1. Merge when satisfied

## 🛡️ Safety Features

All scripts include safety measures:

1. **Git state check**: Won't run with uncommitted changes
1. **Automatic backups**: Creates timestamped backups
1. **Dry run mode**: Preview changes before applying
1. **Error handling**: Graceful error recovery
1. **Restoration instructions**: Clear steps to undo changes

## 📋 Best Practices

1. **Always commit current changes** before running update scripts
1. **Use dry run** first to preview changes
1. **Review the summary** carefully before committing
1. **Run manual verification** for production deployments
1. **Keep backups** until changes are verified

## 🔧 Troubleshooting

### Script won't run

- Ensure you're in the project root directory
- Check that `uv`, `git`, `curl`, and `jq` are installed
- Commit or stash any uncommitted changes

### Updates fail

- Check the error message for specific issues
- Restore from backup if needed
- Try updating packages individually
- Check for conflicting dependency requirements

### GitHub Action fails

- Check the workflow logs in the Actions tab
- Ensure branch protection rules allow the bot to create PRs
- Verify the GITHUB_TOKEN has appropriate permissions
