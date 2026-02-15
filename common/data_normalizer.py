"""Data normalization utilities for Discogs data.

This module provides functions to normalize data from different extractors
(pyextractor using xmltodict, extractor using quick-xml) into a consistent
format for processing by graphinator and tableinator.

The normalized format ensures:
1. ID fields use 'id' key (not '@id')
2. List-type fields always contain arrays (not single objects)
3. Text content is extracted from '#text' when present
4. Consistent structure regardless of extractor used
"""

from typing import Any

import structlog


logger = structlog.get_logger(__name__)


def normalize_id(obj: Any) -> str | None:
    """Extract ID from an object that may have 'id', '@id', or be a string.

    Args:
        obj: Object to extract ID from (dict, str, or other)

    Returns:
        The ID as a string, or None if not found
    """
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        # Try 'id' first (extractor format), then '@id' (xmltodict format)
        return obj.get("id") or obj.get("@id")
    return None


def normalize_text(obj: Any) -> str | None:
    """Extract text content from an object.

    Args:
        obj: Object to extract text from

    Returns:
        The text content as a string, or None if not found
    """
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        # xmltodict uses '#text' for text content when attributes are present
        return obj.get("#text")
    return None


def ensure_list(obj: Any) -> list[Any]:
    """Ensure an object is a list.

    Args:
        obj: Object to convert to list

    Returns:
        A list (empty if obj is None, single-item if obj is not a list)
    """
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return [obj]


def normalize_nested_list(container: Any, key: str) -> list[Any]:
    """Extract and normalize a nested list from a container.

    Handles formats like:
    - {"artist": [{"id": "1", "name": "..."}]}  (xmltodict/extractor)
    - {"artist": {"id": "1", "name": "..."}}    (single item)
    - ["name1", "name2"]                         (flat list - old extractor)

    Args:
        container: The container dict (e.g., release["artists"])
        key: The key to extract (e.g., "artist")

    Returns:
        A normalized list of items
    """
    if container is None:
        return []

    # If container is already a list (old extractor format), return as-is
    if isinstance(container, list):
        return container

    # If container is a dict, extract the nested key
    if isinstance(container, dict):
        nested = container.get(key)
        if nested is None:
            return []
        return ensure_list(nested)

    return []


def normalize_item_with_id(item: Any) -> dict[str, Any] | None:
    """Normalize an item that should have an ID.

    Converts various formats to a consistent dict with 'id' key:
    - String ID -> {"id": "123"}
    - {"@id": "123", "#text": "name"} -> {"id": "123", "name": "name"}
    - {"id": "123", "name": "..."} -> as-is with 'id' key preserved

    Args:
        item: The item to normalize

    Returns:
        Normalized dict with 'id' key, or None if no ID found
    """
    if item is None:
        return None

    if isinstance(item, str):
        # String is treated as the ID itself
        return {"id": item}

    if isinstance(item, dict):
        result: dict[str, Any] = {}

        # Extract ID (prefer 'id' over '@id')
        item_id = item.get("id") or item.get("@id")
        if item_id:
            result["id"] = item_id

        # Extract text content as 'name' if present
        text = item.get("#text")
        if text:
            result["name"] = text

        # Copy other relevant fields
        for key, value in item.items():
            if key in ("id", "@id", "#text"):
                continue
            # Remove @ prefix from attribute keys
            if key.startswith("@"):
                result[key[1:]] = value
            else:
                result[key] = value

        return result if result.get("id") else None

    return None


def normalize_artist(artist_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize an artist record.

    Args:
        artist_data: Raw artist data from extractor

    Returns:
        Normalized artist data
    """
    result = {
        "id": artist_data.get("id"),
        "name": artist_data.get("name"),
        "sha256": artist_data.get("sha256"),
    }

    # Normalize members
    members = artist_data.get("members")
    if members:
        normalized_members = []
        for member in normalize_nested_list(members, "name"):
            normalized = normalize_item_with_id(member)
            if normalized:
                normalized_members.append(normalized)
        if normalized_members:
            result["members"] = normalized_members

    # Normalize groups
    groups = artist_data.get("groups")
    if groups:
        normalized_groups = []
        for group in normalize_nested_list(groups, "name"):
            normalized = normalize_item_with_id(group)
            if normalized:
                normalized_groups.append(normalized)
        if normalized_groups:
            result["groups"] = normalized_groups

    # Normalize aliases
    aliases = artist_data.get("aliases")
    if aliases:
        normalized_aliases = []
        for alias in normalize_nested_list(aliases, "name"):
            normalized = normalize_item_with_id(alias)
            if normalized:
                normalized_aliases.append(normalized)
        if normalized_aliases:
            result["aliases"] = normalized_aliases

    # Copy other fields
    for key in ("realname", "profile", "data_quality", "urls", "namevariations"):
        if key in artist_data:
            result[key] = artist_data[key]

    return result


def normalize_label(label_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a label record.

    Args:
        label_data: Raw label data from extractor

    Returns:
        Normalized label data
    """
    result = {
        "id": label_data.get("id"),
        "name": label_data.get("name"),
        "sha256": label_data.get("sha256"),
    }

    # Normalize parent label
    parent = label_data.get("parentLabel")
    if parent:
        normalized_parent = normalize_item_with_id(parent)
        if normalized_parent:
            result["parentLabel"] = normalized_parent

    # Normalize sublabels
    sublabels = label_data.get("sublabels")
    if sublabels:
        normalized_sublabels = []
        for sublabel in normalize_nested_list(sublabels, "label"):
            normalized = normalize_item_with_id(sublabel)
            if normalized:
                normalized_sublabels.append(normalized)
        if normalized_sublabels:
            result["sublabels"] = normalized_sublabels

    # Copy other fields
    for key in ("profile", "contactinfo", "data_quality", "urls"):
        if key in label_data:
            result[key] = label_data[key]

    return result


def normalize_master(master_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a master record.

    Args:
        master_data: Raw master data from extractor

    Returns:
        Normalized master data
    """
    result = {
        "id": master_data.get("id"),
        "title": master_data.get("title"),
        "year": master_data.get("year"),
        "sha256": master_data.get("sha256"),
    }

    # Normalize artists
    artists = master_data.get("artists")
    if artists:
        normalized_artists = []
        for artist in normalize_nested_list(artists, "artist"):
            normalized = normalize_item_with_id(artist)
            if normalized:
                normalized_artists.append(normalized)
        if normalized_artists:
            result["artists"] = normalized_artists

    # Normalize genres (simple string list)
    genres = master_data.get("genres")
    if genres:
        genre_list = normalize_nested_list(genres, "genre")
        # Genres are simple strings
        result["genres"] = [g if isinstance(g, str) else normalize_text(g) or str(g) for g in genre_list]

    # Normalize styles (simple string list)
    styles = master_data.get("styles")
    if styles:
        style_list = normalize_nested_list(styles, "style")
        result["styles"] = [s if isinstance(s, str) else normalize_text(s) or str(s) for s in style_list]

    # Copy other fields
    for key in ("main_release", "notes", "data_quality", "videos"):
        if key in master_data:
            result[key] = master_data[key]

    return result


def normalize_release(release_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a release record.

    Args:
        release_data: Raw release data from extractor

    Returns:
        Normalized release data
    """
    result = {
        "id": release_data.get("id"),
        "title": release_data.get("title"),
        "sha256": release_data.get("sha256"),
    }

    # Normalize artists
    artists = release_data.get("artists")
    if artists:
        normalized_artists = []
        for artist in normalize_nested_list(artists, "artist"):
            normalized = normalize_item_with_id(artist)
            if normalized:
                normalized_artists.append(normalized)
        if normalized_artists:
            result["artists"] = normalized_artists

    # Normalize labels
    labels = release_data.get("labels")
    if labels:
        normalized_labels = []
        for label in normalize_nested_list(labels, "label"):
            normalized = normalize_item_with_id(label)
            if normalized:
                normalized_labels.append(normalized)
        if normalized_labels:
            result["labels"] = normalized_labels

    # Normalize master_id
    master_id = release_data.get("master_id")
    if master_id:
        if isinstance(master_id, dict):
            result["master_id"] = master_id.get("#text") or master_id.get("id")
        else:
            result["master_id"] = master_id

    # Normalize genres (simple string list)
    genres = release_data.get("genres")
    if genres:
        genre_list = normalize_nested_list(genres, "genre")
        result["genres"] = [g if isinstance(g, str) else normalize_text(g) or str(g) for g in genre_list]

    # Normalize styles (simple string list)
    styles = release_data.get("styles")
    if styles:
        style_list = normalize_nested_list(styles, "style")
        result["styles"] = [s if isinstance(s, str) else normalize_text(s) or str(s) for s in style_list]

    # Copy other fields
    for key in ("released", "country", "notes", "data_quality", "formats", "tracklist", "identifiers", "videos", "companies"):
        if key in release_data:
            result[key] = release_data[key]

    return result


def normalize_record(data_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a record based on its data type.

    Args:
        data_type: The type of record ("artists", "labels", "masters", "releases")
        data: The raw record data

    Returns:
        Normalized record data
    """
    normalizers = {
        "artists": normalize_artist,
        "labels": normalize_label,
        "masters": normalize_master,
        "releases": normalize_release,
    }

    normalizer = normalizers.get(data_type)
    if normalizer:
        return normalizer(data)

    logger.warning("⚠️ Unknown data type, returning data as-is", data_type=data_type)
    return data
