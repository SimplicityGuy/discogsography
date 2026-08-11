#!/usr/bin/env python3

import os
import sys

import psutil


def _excluded_pids() -> set[int]:
    """PIDs that must never count as a match: this process and every ancestor.

    psutil.process_iter() enumerates the calling process itself, and this
    script's own cmdline is ``[..., "healthcheck.py", "<process_name>"]`` —
    argv[1] IS the search string, so without this exclusion check_process()
    always matches itself. Under `uv run` the parent chain is deeper than one
    hop (uv -> python), so every ancestor (not just the immediate parent) is
    excluded (discogsography-pyt3).
    """
    excluded = {os.getpid()}
    try:
        proc = psutil.Process(os.getpid())
        excluded.update(p.pid for p in proc.parents())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return excluded


def check_process(process_name: str) -> bool:
    """Check if a process (other than this healthcheck and its ancestors) is running."""
    excluded_pids = _excluded_pids()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info.get("pid") in excluded_pids:
                continue
            cmdline = proc.info.get("cmdline") or []
            if cmdline and any(process_name in arg for arg in cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: healthcheck.py <process_name>")
        sys.exit(1)

    process_name = sys.argv[1]

    if check_process(process_name):
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Failure


if __name__ == "__main__":
    main()
