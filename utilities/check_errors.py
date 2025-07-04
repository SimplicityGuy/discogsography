#!/usr/bin/env python3

import re
import subprocess  # nosec B404
import sys


def check_service_errors(service: str, time_window: int = 60) -> list[str]:
    """Check for errors in service logs within the specified time window (minutes)."""
    try:
        # Get logs for the specified time window
        result = subprocess.run(  # noqa: S603  # nosec B603 B607
            ["docker-compose", "logs", service, f"--since={time_window}m"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )

        logs = result.stdout
        errors = []

        # Pattern to match error lines
        error_patterns = [
            r"ERROR.*Failed to process.*message.*'id'",
            r"ERROR.*",
            r"Failed to process.*",
            r"Exception.*",
            r"Traceback.*",
        ]

        for line in logs.split("\n"):
            for pattern in error_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    errors.append(line.strip())
                    break

        return errors

    except subprocess.CalledProcessError as e:
        return [f"Error getting logs: {e.stderr}"]


def main() -> None:
    services = ["extractor", "graphinator", "tableinator"]
    time_window = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    print(f"Checking for errors in the last {time_window} minutes...")
    print("=" * 80)

    total_errors = 0

    for service in services:
        print(f"\n📋 {service.upper()}")
        print("-" * 40)

        errors = check_service_errors(service, time_window)

        if errors:
            # Group similar errors
            error_counts: dict[str, int] = {}
            for error in errors:
                # Extract the core error message
                if "Failed to process" in error and "'id'" in error:
                    key = "Failed to process message: 'id'"
                elif "ERROR" in error:
                    # Extract the error type
                    match = re.search(r"ERROR.*?-\s*(.*?)$", error)
                    if match:
                        key = (
                            match.group(1)[:50] + "..."
                            if len(match.group(1)) > 50
                            else match.group(1)
                        )
                    else:
                        key = error[:80] + "..." if len(error) > 80 else error
                else:
                    key = error[:80] + "..." if len(error) > 80 else error

                error_counts[key] = error_counts.get(key, 0) + 1

            # Display error summary
            for error_msg, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  • {error_msg} (x{count})")
                total_errors += count
        else:
            print("  ✅ No errors found")

    print("\n" + "=" * 80)
    print(f"Total errors found: {total_errors}")

    if total_errors > 0:
        print(
            "\n💡 Tip: Use 'docker-compose logs <service> --tail=100 | grep -A5 -B5 ERROR' for context"
        )


if __name__ == "__main__":
    main()
