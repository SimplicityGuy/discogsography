"""Canonical release label/catalog provenance shared by ingestion writers."""

from typing import Any


CANONICAL_PAIR_VERSION = 1


def canonical_pair_metadata(labels: object) -> dict[str, Any]:
    """Pair first-label fields, clear missing counterparts, preserve absent sources."""
    metadata: dict[str, Any] = {"canonical_pair_version": CANONICAL_PAIR_VERSION}
    first = labels[0] if isinstance(labels, list) and labels else None
    if not isinstance(first, dict):
        return metadata
    name, catno = first.get("name"), first.get("catno")
    name = name if isinstance(name, str) and name else None
    catno = catno if isinstance(catno, str) and catno else None
    if name is not None or catno is not None:
        metadata.update(canonical_pair_source="first-label", canonical_label=name, catalog_number=catno)
    return metadata
