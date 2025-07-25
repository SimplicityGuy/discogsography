#!/usr/bin/env python3

import json
import sys
from typing import Any

import pika


def get_message_from_queue(
    queue_name: str,
    host: str = "localhost",
    username: str = "discogsography",
    password: str = "discogsography",  # noqa: S107  # nosec B107
) -> dict[str, Any] | None:
    """Peek at a message from the queue without consuming it."""
    try:
        # Connect to RabbitMQ
        credentials = pika.PlainCredentials(username, password)
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=host, credentials=credentials))
        channel = connection.channel()

        # Get a single message
        method, properties, body = channel.basic_get(queue=queue_name, auto_ack=False)

        if method:
            # Parse the message
            message: dict[str, Any] = json.loads(body)

            # Reject the message to put it back in the queue
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            connection.close()
            return message
        else:
            connection.close()
            return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def analyze_message(message: dict[str, Any] | None, message_type: str) -> None:
    """Analyze a message for potential issues."""
    print(f"\n📋 Message Analysis for {message_type}")
    print("=" * 60)

    if not message:
        print("No message available in queue")
        return

    # Basic info
    print(f"Message ID: {message.get('id', 'MISSING')}")
    print(f"SHA256: {message.get('sha256', 'MISSING')[:16]}...")

    # Check for required fields based on type
    if message_type == "masters":
        required_fields = ["id", "title", "sha256"]
        optional_fields = ["artists", "genres", "styles", "year"]
    elif message_type == "artists":
        required_fields = ["id", "name", "sha256"]
        optional_fields = ["members", "groups", "aliases"]
    elif message_type == "labels":
        required_fields = ["id", "name", "sha256"]
        optional_fields = ["parentLabel", "sublabels"]
    elif message_type == "releases":
        required_fields = ["id", "title", "sha256"]
        optional_fields = ["artists", "labels", "master_id", "genres", "styles"]
    else:
        required_fields = ["id", "sha256"]
        optional_fields = []

    print("\n✅ Required Fields:")
    missing_required = []
    for field in required_fields:
        if field in message:
            print(f"  ✓ {field}: {str(message[field])[:50]}...")
        else:
            missing_required.append(field)
            print(f"  ✗ {field}: MISSING")

    print("\n📌 Optional Fields:")
    for field in optional_fields:
        if field in message:
            value = message[field]
            if isinstance(value, dict):
                print(f"  ✓ {field}: {type(value).__name__} with {len(value)} keys")
            elif isinstance(value, list):
                print(f"  ✓ {field}: {type(value).__name__} with {len(value)} items")
            else:
                print(f"  ✓ {field}: {str(value)[:50]}...")
        else:
            print(f"  - {field}: not present")

    # Check for potential issues
    print("\n⚠️  Potential Issues:")
    issues = []

    if missing_required:
        issues.append(f"Missing required fields: {', '.join(missing_required)}")

    # Check for nested structure issues
    if message_type == "masters" and "artists" in message:
        artists = message["artists"]
        if isinstance(artists, dict) and "artist" in artists:
            artist_list = artists["artist"]
            if isinstance(artist_list, list):
                for i, artist in enumerate(artist_list[:3]):  # Check first 3
                    if not isinstance(artist, dict) or "id" not in artist:
                        issues.append(f"Artist {i} missing 'id' field")
            elif isinstance(artist_list, dict) and "id" not in artist_list:
                issues.append("Single artist missing 'id' field")

    if issues:
        for issue in issues:
            print(f"  • {issue}")
    else:
        print("  No obvious issues detected")

    # Show full message structure
    print("\n📄 Full Message Structure:")
    print(json.dumps(message, indent=2)[:1000] + "..." if len(json.dumps(message)) > 1000 else json.dumps(message, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: debug_message.py <queue_type>")
        print("Queue types: artists, labels, masters, releases")
        sys.exit(1)

    queue_type = sys.argv[1]
    if queue_type not in ["artists", "labels", "masters", "releases"]:
        print(f"Invalid queue type: {queue_type}")
        sys.exit(1)

    queue_name = f"discogsography-graphinator-{queue_type}"

    print(f"🔍 Debugging Queue: {queue_name}")

    # Get a message from the queue
    message = get_message_from_queue(queue_name)

    # Analyze the message
    analyze_message(message, queue_type)


if __name__ == "__main__":
    main()
