#!/usr/bin/env python3
"""Switch between normal and incremental extractor modes."""

import argparse
import sys
from pathlib import Path


def switch_mode(mode: str) -> None:
    """Switch the extractor mode by updating docker-compose configuration."""
    if mode not in ["normal", "incremental"]:
        print(f"❌ Invalid mode: {mode}. Use 'normal' or 'incremental'")
        sys.exit(1)

    docker_compose_file = Path(__file__).parent.parent / "docker-compose.yml"

    if not docker_compose_file.exists():
        print(f"❌ docker-compose.yml not found at {docker_compose_file}")
        sys.exit(1)

    # Read the current docker-compose file
    content = docker_compose_file.read_text()

    if mode == "incremental":
        # Switch to incremental extractor
        if "incremental_extractor.py" in content:
            print("⚠️ Already in incremental mode")
            return

        # Replace extractor.py with incremental_extractor.py
        new_content = content.replace(
            'command: ["python", "extractor/extractor.py"]',
            'command: ["python", "extractor/incremental_extractor.py"]',
        )

        # Ensure PostgreSQL environment variables are set
        if "POSTGRES_ADDRESS" not in new_content:
            print("⚠️ Note: Make sure to set PostgreSQL environment variables for incremental mode")

    else:  # normal mode
        # Switch to normal extractor
        if "incremental_extractor.py" not in content:
            print("⚠️ Already in normal mode")
            return

        # Replace incremental_extractor.py with extractor.py
        new_content = content.replace(
            'command: ["python", "extractor/incremental_extractor.py"]',
            'command: ["python", "extractor/extractor.py"]',
        )

    # Write the updated content
    docker_compose_file.write_text(new_content)
    print(f"✅ Switched to {mode} mode")

    if mode == "incremental":
        print("\n📋 Next steps for incremental mode:")
        print("1. Run database migrations: python scripts/run_migrations.py")
        print("2. Ensure PostgreSQL environment variables are set")
        print("3. Restart the extractor service: docker-compose restart extractor")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Switch between extractor modes")
    parser.add_argument(
        "mode", choices=["normal", "incremental"], help="Extractor mode to switch to"
    )

    args = parser.parse_args()
    switch_mode(args.mode)


if __name__ == "__main__":
    main()
