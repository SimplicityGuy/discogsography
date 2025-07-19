# Scripts

This directory contains utility scripts for maintaining the discogsography project.

## upgrade-packages.sh

Safely upgrades all Python dependencies across the entire project, including the root workspace and all service-specific dependencies.

### Usage

```bash
# Basic upgrade (minor/patch versions only)
./scripts/upgrade-packages.sh

# Include major version upgrades
./scripts/upgrade-packages.sh --major

# Dry run to see what would be upgraded
./scripts/upgrade-packages.sh --dry-run

# Skip backup creation (not recommended)
./scripts/upgrade-packages.sh --no-backup

# Show help
./scripts/upgrade-packages.sh --help
```

### Features

- **Safe upgrades**: Creates timestamped backups before making changes
- **Git safety**: Requires clean working directory to ensure safe rollback
- **Comprehensive**: Upgrades all dependencies across the monorepo
- **Validation**: Runs linters and tests after upgrade to verify compatibility
- **Dry run mode**: Preview changes without applying them
- **Version control**: Choose between minor/patch or major version upgrades

### What it does

1. Checks prerequisites (uv installed, git repo, clean working directory)
1. Creates timestamped backups of `uv.lock` and all `pyproject.toml` files
1. Updates uv to the latest version
1. Compiles upgraded dependencies based on upgrade strategy
1. Syncs all dependencies with `uv sync --all-extras`
1. Runs linters and tests to verify compatibility
1. Shows a summary of changes

### Recovery

If something goes wrong, backups are stored in `backups/package-upgrades-TIMESTAMP/`. To restore:

```bash
cp backups/package-upgrades-TIMESTAMP/uv.lock.backup uv.lock
uv sync --all-extras
```

## update-python-version.sh

Updates the Python version across all configuration files in the project.

### Usage

```bash
# Update to Python 3.14
./scripts/update-python-version.sh 3.14

# Use default version (3.13)
./scripts/update-python-version.sh
```

### What it updates

- All `pyproject.toml` files (requires-python, tool configurations)
- All Dockerfiles (FROM statements and labels)
- GitHub Actions workflows (python-version)
- `pyrightconfig.json`
- `.env.example` (if present)

### Notes

- The script preserves the use of environment variables in Dockerfiles
- After updating, run `uv sync` to update dependencies
- Documentation files may need manual updates
