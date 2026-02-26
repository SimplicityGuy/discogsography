#!/usr/bin/env python3

import os
import sys
import time
from typing import Any

import requests


def get_queue_stats(
    base_url: str = os.environ.get("RABBITMQ_URL", "http://localhost:15672"),
    username: str = os.environ.get("RABBITMQ_USER", "discogsography"),
    password: str = os.environ.get("RABBITMQ_PASSWORD", ""),
) -> list[dict[str, Any]] | None:
    """Fetch queue statistics from RabbitMQ Management API."""
    try:
        response = requests.get(f"{base_url}/api/queues", auth=(username, password), timeout=10)
        response.raise_for_status()
        data: list[dict[str, Any]] = response.json()
        return data
    except requests.RequestException as e:
        print(f"Error connecting to RabbitMQ: {e}")
        return None


def monitor_queues(interval: int = 5) -> None:
    """Monitor queue statistics in real-time."""
    print("Monitoring RabbitMQ queues (Press Ctrl+C to stop)...")
    print("-" * 80)

    try:
        while True:
            queues = get_queue_stats()
            if not queues:
                print("Failed to fetch queue data")
                time.sleep(interval)
                continue

            # Clear screen
            print("\033[2J\033[H")
            print(f"RabbitMQ Queue Monitor - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 80)
            print(f"{'Queue Name':<50} {'Ready':<10} {'Unacked':<10} {'Total':<10}")
            print("-" * 80)

            total_messages = 0
            for queue in sorted(queues, key=lambda x: x["name"]):
                if "discogsography" in queue["name"]:
                    name = queue["name"]
                    ready = queue.get("messages_ready", 0)
                    unacked = queue.get("messages_unacknowledged", 0)
                    total = queue.get("messages", 0)
                    total_messages += total

                    # Highlight queues with unacked messages
                    if unacked > 0:
                        print(f"\033[93m{name:<50} {ready:<10} {unacked:<10} {total:<10}\033[0m")
                    else:
                        print(f"{name:<50} {ready:<10} {unacked:<10} {total:<10}")

            print("-" * 80)
            print(f"Total messages across all queues: {total_messages}")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    monitor_queues(interval)
