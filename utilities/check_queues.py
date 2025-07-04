#!/usr/bin/env python3
"""Check RabbitMQ queue status for graphinator."""

import base64
import json
import os
import urllib.request
from urllib.error import URLError


def check_rabbitmq_queues() -> None:
    """Check the status of graphinator queues in RabbitMQ."""
    url = "http://localhost:15672/api/queues"
    username = os.getenv("RABBITMQ_USER", "discogsography")
    password = os.getenv("RABBITMQ_PASS", "discogsography")  # nosec B105

    # Create basic auth header
    credentials = f"{username}:{password}"
    auth_header = base64.b64encode(credentials.encode()).decode()

    # Create request with auth
    request = urllib.request.Request(url)  # noqa: S310  # nosec B310
    request.add_header("Authorization", f"Basic {auth_header}")

    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310  # nosec B310
            data = json.loads(response.read().decode())

        # Filter for graphinator queues
        graphinator_queues = [q for q in data if "graphinator" in q.get("name", "")]

        if not graphinator_queues:
            print("No graphinator queues found!")
            return

        print("Graphinator Queue Status:")
        print("=" * 80)

        for queue in graphinator_queues:
            name = queue.get("name", "Unknown")
            messages = queue.get("messages", 0)
            messages_ready = queue.get("messages_ready", 0)
            messages_unacked = queue.get("messages_unacknowledged", 0)
            consumers = queue.get("consumers", 0)
            state = queue.get("state", "unknown")

            print(f"\nQueue: {name}")
            print(f"  State: {state}")
            print(f"  Total Messages: {messages}")
            print(f"  Ready Messages: {messages_ready}")
            print(f"  Unacked Messages: {messages_unacked}")
            print(f"  Active Consumers: {consumers}")

            # Message stats
            message_stats = queue.get("message_stats", {})
            if message_stats:
                ack_rate = message_stats.get("ack_details", {}).get("rate", 0)
                publish_rate = message_stats.get("publish_details", {}).get("rate", 0)
                print(f"  Ack Rate: {ack_rate:.2f} msg/s")
                print(f"  Publish Rate: {publish_rate:.2f} msg/s")

            # Consumer details
            if consumers > 0 and "consumer_details" in queue:
                print("  Consumer Details:")
                for consumer in queue.get("consumer_details", []):
                    consumer_tag = consumer.get("consumer_tag", "Unknown")
                    channel_details = consumer.get("channel_details", {})
                    connection_name = channel_details.get("connection_name", "Unknown")
                    print(f"    - Tag: {consumer_tag}")
                    print(f"      Connection: {connection_name}")

    except URLError as e:
        print(f"Error: Could not connect to RabbitMQ management API at {url}")
        print(f"Details: {e}")
        print("\nMake sure:")
        print("1. RabbitMQ is running (docker-compose up -d)")
        print("2. Management plugin is enabled")
        print("3. Port 15672 is accessible")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    check_rabbitmq_queues()
