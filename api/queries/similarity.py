"""Shared similarity utilities for cosine scoring on sparse vectors."""

import math
from typing import Any


def to_genre_vector(genres: list[dict[str, Any]]) -> dict[str, float]:
    """Convert genre list with counts to a normalized percentage vector."""
    total = sum(g["count"] for g in genres)
    if total == 0:
        return {}
    return {g["name"]: g["count"] / total for g in genres}


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors (dict-based)."""
    if not vec_a or not vec_b:
        return 0.0
    all_keys = set(vec_a) | set(vec_b)
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in all_keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)
