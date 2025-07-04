#!/usr/bin/env python3

import sys

import psutil


def check_process(process_name: str) -> bool:
    """Check if a process is running."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline", [])
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
