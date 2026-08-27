#!/usr/bin/env python3

import json
import os
import sys
from typing import Any

import pika

from common.config import get_secret
from utilities.catalog_contract import (
    AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR,
    AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR,
    AMQP_QUEUE_PREFIX_GRAPHINATOR,
    AMQP_QUEUE_PREFIX_TABLEINATOR,
)


def get_message_from_queue(
    queue_name: str,
    host: str = "localhost",
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any] | None:
    """Peek at a message from the queue without consuming it."""
    username = username or os.environ.get("RABBITMQ_USERNAME", "discogsography")
    password = password or get_secret("RABBITMQ_PASSWORD", "")
    connection = None
    try:
        # Connect to RabbitMQ
        credentials = pika.PlainCredentials(username, password)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=host, credentials=credentials, socket_timeout=10, blocked_connection_timeout=30)
        )
        channel = connection.channel()

        # Get a single message
        method, _properties, body = channel.basic_get(queue=queue_name, auto_ack=False)

        if method:
            # Reject the message to put it back in the queue before parsing
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            # Parse the message (safe to fail now — message is already requeued)
            message: dict[str, Any] = json.loads(body)
            return message
        else:
            return None

    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        if connection and not connection.is_closed:
            connection.close()


# Field specs are keyed on (source, message_type) because the type names
# "artists"/"labels"/"releases" are shared between Discogs and MusicBrainz, but
# the wire schemas differ (see extractor/src/jsonl_parser.rs, the schema source of
# truth per CLAUDE.md). Discogs messages carry "title" for masters/releases;
# MusicBrainz messages carry "name" for every type (parse_mb_release_line emits
# "name": v["title"]) and always set "sha256" to the empty string rather than
# omitting it (discogsography-y69g).
_DISCOGS_FIELD_SPECS: dict[str, tuple[list[str], list[str]]] = {
    "masters": (["id", "title", "sha256"], ["artists", "genres", "styles", "year"]),
    "artists": (["id", "name", "sha256"], ["members", "groups", "aliases"]),
    "labels": (["id", "name", "sha256"], ["parentLabel", "sublabels"]),
    "releases": (["id", "title", "sha256"], ["artists", "labels", "master_id", "genres", "styles"]),
}

_MUSICBRAINZ_FIELD_SPECS: dict[str, tuple[list[str], list[str]]] = {
    "artists": (["id", "name", "sha256"], ["disambiguation", "external_links"]),
    "labels": (["id", "name", "sha256"], ["disambiguation", "external_links"]),
    "releases": (["id", "name", "sha256"], ["disambiguation", "barcode", "status", "release_group_mbid", "external_links"]),
    "release-groups": (["id", "name", "sha256"], ["mb_type", "secondary_types", "first_release_date", "disambiguation", "external_links"]),
}


def analyze_message(message: dict[str, Any] | None, message_type: str, source: str) -> None:
    """Analyze a message for potential issues.

    ``source`` is "discogs" or "musicbrainz" and selects the correct field
    schema for ``message_type`` — the two sources share type names but not
    wire shapes (discogsography-y69g).
    """
    print(f"\n📋 Message Analysis for {message_type} ({source})")
    print("=" * 60)

    if not message:
        print("No message available in queue")
        return

    # Basic info
    print(f"Message ID: {message.get('id', 'MISSING')}")
    print(f"SHA256: {str(message.get('sha256', 'MISSING'))[:16]}...")

    # Check for required fields based on (source, type)
    field_specs = _MUSICBRAINZ_FIELD_SPECS if source == "musicbrainz" else _DISCOGS_FIELD_SPECS
    required_fields, optional_fields = field_specs.get(message_type, (["id", "sha256"], []))

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
    formatted = json.dumps(message, indent=2)
    print(formatted[:1000] + "..." if len(formatted) > 1000 else formatted)


_CONSUMER_PREFIXES = {
    "graphinator": AMQP_QUEUE_PREFIX_GRAPHINATOR,
    "tableinator": AMQP_QUEUE_PREFIX_TABLEINATOR,
    "brainzgraphinator": AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR,
    "brainztableinator": AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR,
}

_DISCOGS_TYPES = ["artists", "labels", "masters", "releases"]
_MUSICBRAINZ_TYPES = ["artists", "labels", "release-groups", "releases"]

# Consumers that read from the MusicBrainz fanout exchanges — every other
# consumer (graphinator/tableinator) reads from the Discogs exchanges. Used to
# pick the correct queue-type set AND field schema for a given consumer
# (discogsography-y69g).
_BRAINZ_CONSUMERS = {"brainzgraphinator", "brainztableinator"}


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: debug_message.py <queue_type> [consumer]")
        print(f"Queue types (Discogs): {', '.join(_DISCOGS_TYPES)}")
        print(f"Queue types (MusicBrainz): {', '.join(_MUSICBRAINZ_TYPES)}")
        print(f"Consumers: {', '.join(_CONSUMER_PREFIXES)} (default: graphinator)")
        sys.exit(1)

    queue_type = sys.argv[1]
    consumer = sys.argv[2] if len(sys.argv) > 2 else "graphinator"

    if consumer not in _CONSUMER_PREFIXES:
        print(f"Invalid consumer: {consumer}. Must be one of: {', '.join(_CONSUMER_PREFIXES)}")
        sys.exit(1)

    source = "musicbrainz" if consumer in _BRAINZ_CONSUMERS else "discogs"
    valid_types = _MUSICBRAINZ_TYPES if source == "musicbrainz" else _DISCOGS_TYPES

    # Validate queue_type against the types the CONSUMER actually supports, not
    # the union of both sources — e.g. "masters brainzgraphinator" or
    # "release-groups graphinator" are impossible (source, type) combinations
    # that previously passed validation and built a queue name no consumer ever
    # declares, producing a confusing broker error instead of a clear message.
    if queue_type not in valid_types:
        print(f"Invalid queue type {queue_type!r} for consumer {consumer!r} (source: {source}). Must be one of: {', '.join(valid_types)}")
        sys.exit(1)

    queue_name = f"{_CONSUMER_PREFIXES[consumer]}-{queue_type}"

    print(f"🔍 Debugging Queue: {queue_name}")

    # Get a message from the queue
    message = get_message_from_queue(queue_name)

    # Analyze the message
    analyze_message(message, queue_type, source)


if __name__ == "__main__":
    main()
