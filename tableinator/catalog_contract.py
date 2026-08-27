"""Generated from extractor/contracts/catalog-events/v1/contract.json; do not edit."""

from __future__ import annotations

from os import getenv

CONTRACT_NAME = "groovemap.catalog-events"
CONTRACT_VERSION = 1
AMQP_EXCHANGE_TYPE = "fanout"
DISCOGS_DATA_TYPES = ["artists", "labels", "masters", "releases"]
MUSICBRAINZ_DATA_TYPES = ["artists", "labels", "release-groups", "releases"]
DISCOGS_EXCHANGE_PREFIX = getenv(
    "DISCOGS_EXCHANGE_PREFIX",
    "discogsography-discogs",
)
MUSICBRAINZ_EXCHANGE_PREFIX = getenv(
    "MUSICBRAINZ_EXCHANGE_PREFIX",
    "discogsography-musicbrainz",
)
CONSUMER_SOURCES = {
    "brainzgraphinator": {"source": "musicbrainz"},
    "brainztableinator": {"source": "musicbrainz"},
    "graphinator": {"source": "discogs"},
    "tableinator": {"source": "discogs"},
}

# Compatibility names used by the current services. They are generated from the
# producer-owned contract rather than independently declared by consumers.
DATA_TYPES = DISCOGS_DATA_TYPES
AMQP_QUEUE_PREFIX_GRAPHINATOR = f"{DISCOGS_EXCHANGE_PREFIX}-graphinator"
AMQP_QUEUE_PREFIX_TABLEINATOR = f"{DISCOGS_EXCHANGE_PREFIX}-tableinator"
AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-brainzgraphinator"
AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR = f"{MUSICBRAINZ_EXCHANGE_PREFIX}-brainztableinator"


def entity_types(source: str) -> list[str]:
    """Return the entity vocabulary for a catalog source."""
    if source == "discogs":
        return DISCOGS_DATA_TYPES
    if source == "musicbrainz":
        return MUSICBRAINZ_DATA_TYPES
    raise ValueError(f"Unknown catalog source: {source}")


def exchange_prefix(source: str) -> str:
    """Return the environment-aware exchange prefix for a source."""
    if source == "discogs":
        return DISCOGS_EXCHANGE_PREFIX
    if source == "musicbrainz":
        return MUSICBRAINZ_EXCHANGE_PREFIX
    raise ValueError(f"Unknown catalog source: {source}")


def exchange_name(source: str, entity: str) -> str:
    """Build a producer-owned exchange name."""
    _require_entity(source, entity)
    return f"{exchange_prefix(source)}-{entity}"


def queue_name(consumer: str, entity: str) -> str:
    """Build a registered consumer queue name."""
    try:
        source = CONSUMER_SOURCES[consumer]["source"]
    except KeyError as exc:
        raise ValueError(f"Unknown catalog consumer: {consumer}") from exc
    _require_entity(source, entity)
    return f"{exchange_prefix(source)}-{consumer}-{entity}"


def dead_letter_exchange_name(consumer: str, entity: str) -> str:
    """Build the dead-letter exchange name for a consumer queue."""
    return f"{queue_name(consumer, entity)}.dlx"


def dead_letter_queue_name(consumer: str, entity: str) -> str:
    """Build the dead-letter queue name for a consumer queue."""
    return f"{queue_name(consumer, entity)}.dlq"


def _require_entity(source: str, entity: str) -> None:
    if entity not in entity_types(source):
        raise ValueError(f"Unknown {source} entity: {entity}")
