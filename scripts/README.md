# Scripts

This directory contains utility scripts for maintaining the discogsography project.

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
