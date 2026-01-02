# Platform Targeting Configuration

This document explains how Discogsography handles platform-specific Python package wheels to ensure compatibility with
our Docker build environments.

## Problem

Some Python packages (like Pillow) include platform-specific wheels for iOS that are incompatible with Docker builds on
Linux. These wheels cause `uv sync` to fail with errors like:

```
failed to parse `pillow-11.3.0-cp313-cp313-ios_13_0_arm64_iphoneos.whl` as wheel filename:
The wheel filename has an invalid platform tag: Unknown platform tag format: ios_13_0_arm64_iphoneos
```

## Solution

We use uv's built-in environment restrictions feature to limit which platform wheels are included in `uv.lock`.

### Configuration

In `pyproject.toml`, we've added:

```toml
[tool.uv]
environments = [
    # Only support Linux platforms that we build for in CI/CD
    "sys_platform == 'linux' and platform_machine == 'x86_64'",  # linux/amd64
    "sys_platform == 'linux' and platform_machine == 'aarch64'",  # linux/arm64
    # Also support local development on macOS
    "sys_platform == 'darwin' and platform_machine == 'x86_64'",  # macOS Intel
    "sys_platform == 'darwin' and platform_machine == 'arm64'",   # macOS Apple Silicon
]
```

### Supported Platforms

This configuration ensures `uv.lock` only includes wheels for:

1. **Linux amd64** (x86_64) - Used in production Docker containers
1. **Linux arm64** (aarch64) - Used in production Docker containers on ARM
1. **macOS Intel** (x86_64) - For local development on Intel Macs
1. **macOS Apple Silicon** (arm64) - For local development on M1/M2/M3 Macs

### Benefits

1. **No manual cleanup needed**: iOS and other incompatible wheels are automatically excluded
1. **Consistent builds**: Docker builds work reliably across all platforms
1. **Smaller lock file**: Only includes relevant wheels for our target platforms
1. **Future-proof**: Any new incompatible platforms are automatically excluded

## Usage

When upgrading packages:

```bash
# The platform restrictions are automatically applied
./scripts/upgrade-packages.sh
```

Or when manually updating the lock file:

```bash
# uv automatically respects the environment restrictions
uv lock
```

## References

- [uv Environment Configuration](https://docs.astral.sh/uv/reference/settings/#environments)
- [PEP 427 - Wheel Binary Package Format](https://www.python.org/dev/peps/pep-0427/)
