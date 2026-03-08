"""Synthetic data generation calibrated from 2026-03-07 production Discogs data.

Generates graph data at two scale points preserving realistic characteristics:
  - 3.97 relationships per node (matching ~134.4M rels / ~33.8M nodes)
  - ~58% orphan artists, ~39% orphan labels
  - Power-law distributions for artist popularity
  - Zipf-like genre/style distributions
  - All 8 relationship types
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import string
from typing import Any


# Scale points derived from real Discogs dataset proportions
SCALES: dict[str, dict[str, int]] = {
    "small": {"artists": 10_000, "labels": 5_000, "masters": 20_000, "releases": 100_000},
    "large": {"artists": 100_000, "labels": 50_000, "masters": 200_000, "releases": 1_000_000},
}

# 16 genres ranked by real release count (2026-03-07 production data)
GENRES = [
    "Rock",
    "Electronic",
    "Pop",
    "Folk, World, & Country",
    "Jazz",
    "Funk / Soul",
    "Classical",
    "Hip Hop",
    "Latin",
    "Stage & Screen",
    "Reggae",
    "Blues",
    "Non-Music",
    "Children's",
    "Brass & Military",
    "No Genre",
]

# Zipf weights from real data (millions of releases)
GENRE_WEIGHTS = [6.18, 4.87, 3.85, 2.48, 1.51, 1.29, 1.20, 0.96, 0.85, 0.58, 0.47, 0.38, 0.27, 0.10, 0.04, 0.01]

# Top 50 styles (representative subset of 757) with Zipf-like weights
STYLES = [
    "Pop Rock",
    "House",
    "Vocal",
    "Experimental",
    "Punk",
    "Techno",
    "Indie Rock",
    "Ambient",
    "Soul",
    "Disco",
    "Synth-pop",
    "Country",
    "Hard Rock",
    "Alternative Rock",
    "Soundtrack",
    "Trance",
    "Hardcore",
    "Ballad",
    "Contemporary Jazz",
    "Downtempo",
    "Folk",
    "Chanson",
    "Schlager",
    "Religious",
    "Progressive Rock",
    "Blues Rock",
    "Drum n Bass",
    "Garage Rock",
    "New Wave",
    "Reggae",
    "Deep House",
    "Death Metal",
    "Black Metal",
    "Breaks",
    "Trip Hop",
    "Noise",
    "Electro",
    "Industrial",
    "Minimal",
    "Dub",
    "Latin Jazz",
    "Swing",
    "Bossa Nova",
    "Musical",
    "Opera",
    "Choral",
    "Baroque",
    "Spoken Word",
    "Poetry",
    "Field Recording",
]

# Year distribution weights by decade (from production data)
YEAR_DECADE_WEIGHTS = {
    range(1860, 1950): 1,
    range(1950, 1960): 3,
    range(1960, 1970): 7,
    range(1970, 1980): 10,
    range(1980, 1990): 12,
    range(1990, 2000): 18,
    range(2000, 2010): 18,
    range(2010, 2020): 21,
    range(2020, 2027): 8,
}


def _zipf_choice(items: list[str], weights: list[float] | None = None, k: int = 1) -> list[str]:
    """Pick k items with Zipf-like distribution."""
    if weights is None:
        weights = [1.0 / (i + 1) for i in range(len(items))]
    return random.choices(items, weights=weights[: len(items)], k=k)  # noqa: S311  # nosec B311


def _random_name(avg_len: float = 14, min_len: int = 2, max_len: int = 255) -> str:
    """Generate a random name with realistic length distribution."""
    # Log-normal distribution centered around avg_len
    length = int(random.lognormvariate(math.log(avg_len), 0.5))
    length = max(min_len, min(length, max_len))
    # Mix of words
    words = []
    remaining = length
    while remaining > 0:
        word_len = min(remaining, random.randint(2, 10))  # noqa: S311  # nosec B311
        word = "".join(random.choices(string.ascii_lowercase, k=word_len))  # noqa: S311  # nosec B311
        words.append(word.capitalize())
        remaining -= word_len + 1  # +1 for space
    return " ".join(words)[:max_len]


def _random_artist_name() -> str:
    return _random_name(avg_len=13.77)


def _random_label_name() -> str:
    return _random_name(avg_len=20.28)


def _random_title() -> str:
    return _random_name(avg_len=20.96)


def _maybe_year(missing_pct: float = 6.73) -> int | None:
    """Generate a year with realistic distribution, or None."""
    if random.random() * 100 < missing_pct:  # noqa: S311  # nosec B311
        return None
    # Pick decade based on weights
    decade_ranges = list(YEAR_DECADE_WEIGHTS.keys())
    decade_weights = list(YEAR_DECADE_WEIGHTS.values())
    decade = random.choices(decade_ranges, weights=decade_weights, k=1)[0]  # noqa: S311  # nosec B311
    return random.choice(list(decade))  # noqa: S311  # nosec B311


def _pick_genres() -> list[str]:
    """Pick genres: avg 1.33, p50=1, p90=2, max=15."""
    n = 1
    if random.random() < 0.30:  # noqa: S311  # nosec B311
        n = 2
    if random.random() < 0.03:  # noqa: S311  # nosec B311
        n = random.randint(3, 5)  # noqa: S311  # nosec B311
    return _zipf_choice(GENRES, GENRE_WEIGHTS, k=n)


def _maybe_pick_styles() -> list[str]:
    """Pick styles: avg 1.79, p50=1, p90=3; ~8% have none."""
    if random.random() < 0.08:  # noqa: S311  # nosec B311
        return []
    n = 1
    if random.random() < 0.45:  # noqa: S311  # nosec B311
        n = 2
    if random.random() < 0.15:  # noqa: S311  # nosec B311
        n = random.randint(3, 5)  # noqa: S311  # nosec B311
    return _zipf_choice(STYLES, k=n)


def _power_law_pick(max_id: int, alpha: float = 1.5) -> int:
    """Pick an ID with power-law distribution (favoring lower IDs)."""
    u = random.random()  # noqa: S311  # nosec B311
    return int(max_id * (1 - u**alpha)) % max_id


def _pick_artist_ids(num_artists: int) -> list[str]:
    """Pick artist IDs for a release: avg 1.21, p50=1, p99=4."""
    n = 1
    if random.random() < 0.18:  # noqa: S311  # nosec B311
        n = 2
    if random.random() < 0.02:  # noqa: S311  # nosec B311
        n = random.randint(3, 4)  # noqa: S311  # nosec B311
    # Use power-law distribution so ~28% of artists get BY edges
    return [str(_power_law_pick(num_artists, alpha=2.5)) for _ in range(n)]


def _pick_label_ids(num_labels: int) -> list[str]:
    """Pick label IDs: avg 1.09, p50=1, p95=2."""
    n = 1
    if random.random() < 0.09:  # noqa: S311  # nosec B311
        n = 2
    # Power-law but less extreme than artists
    return [str(_power_law_pick(num_labels, alpha=1.8)) for _ in range(n)]


def _pick_master(num_masters: int) -> str:
    """Pick a master ID: ~100% of releases have a master."""
    return str(random.randint(0, num_masters - 1))  # noqa: S311  # nosec B311


def _generate_band_memberships(
    num_artists: int,
    member_fraction: float = 0.1338,
    band_fraction: float = 0.0655,
    avg_members: float = 3.54,
) -> list[dict[str, str]]:
    """Generate MEMBER_OF relationships."""
    num_members = int(num_artists * member_fraction)
    num_bands = int(num_artists * band_fraction)

    # Bands are a subset of artists (higher IDs to avoid overlap)
    band_start = num_artists - num_bands
    member_ids = random.sample(range(0, band_start), min(num_members, band_start))  # nosec B311

    relationships = []
    member_idx = 0
    for band_id in range(band_start, num_artists):
        # Each band gets ~avg_members members
        n_members = max(2, int(random.gauss(avg_members, 1.5)))
        for _ in range(n_members):
            if member_idx >= len(member_ids):
                break
            relationships.append(
                {
                    "from_id": str(member_ids[member_idx]),
                    "to_id": str(band_id),
                }
            )
            member_idx += 1

    return relationships


def _generate_aliases(num_artists: int, fraction: float = 0.1282) -> list[dict[str, str]]:
    """Generate ALIAS_OF relationships."""
    num_with_alias = int(num_artists * fraction)
    ids = random.sample(range(num_artists), min(num_with_alias * 2, num_artists))  # nosec B311
    relationships = []
    for i in range(0, len(ids) - 1, 2):
        relationships.append({"from_id": str(ids[i]), "to_id": str(ids[i + 1])})
    return relationships


def _generate_sublabels(num_labels: int, fraction: float = 0.1174) -> list[dict[str, str]]:
    """Generate SUBLABEL_OF relationships."""
    num_sublabels = int(num_labels * fraction)
    parent_ids = list(range(0, num_labels // 10))  # ~10% are parents
    child_ids = random.sample(range(num_labels), min(num_sublabels, num_labels))  # nosec B311
    relationships = []
    for child_id in child_ids:
        parent_id = random.choice(parent_ids)  # noqa: S311  # nosec B311
        if child_id != parent_id:
            relationships.append({"from_id": str(child_id), "to_id": str(parent_id)})
    return relationships


def generate_test_data(scale: str = "small", seed: int = 42) -> dict[str, Any]:
    """Generate synthetic nodes and relationships at the specified scale.

    Args:
        scale: "small" (~135k nodes) or "large" (~1.35M nodes)
        seed: Random seed for reproducibility

    Returns:
        Dict with keys: artists, labels, masters, releases, genres, styles,
        and relationship lists: by_rels, on_rels, derived_from_rels, is_rels,
        member_of_rels, alias_of_rels, sublabel_of_rels, part_of_rels
    """
    random.seed(seed)
    counts = SCALES[scale]
    num_artists = counts["artists"]
    num_labels = counts["labels"]
    num_masters = counts["masters"]
    num_releases = counts["releases"]

    print(f"Generating synthetic data at scale={scale}...")
    print(f"  Artists: {num_artists:,}, Labels: {num_labels:,}, Masters: {num_masters:,}, Releases: {num_releases:,}")

    # --- Nodes ---
    print("  Generating artists...")
    artists = [
        {
            "id": str(i),
            "name": _random_artist_name(),
            "releases_url": f"https://api.discogs.com/artists/{i}/releases",
            "resource_url": f"https://api.discogs.com/artists/{i}",
            "sha256": hashlib.sha256(f"artist-{i}".encode()).hexdigest(),
        }
        for i in range(num_artists)
    ]

    print("  Generating labels...")
    labels = [
        {
            "id": str(i),
            "name": _random_label_name(),
            "sha256": hashlib.sha256(f"label-{i}".encode()).hexdigest(),
        }
        for i in range(num_labels)
    ]

    print("  Generating masters...")
    masters = [
        {
            "id": str(i),
            "title": _random_title(),
            "year": _maybe_year(),
            "genres": _pick_genres(),
            "styles": _maybe_pick_styles(),
            "sha256": hashlib.sha256(f"master-{i}".encode()).hexdigest(),
        }
        for i in range(num_masters)
    ]

    print("  Generating releases...")
    releases = []
    for i in range(num_releases):
        releases.append(
            {
                "id": str(i),
                "title": _random_title(),
                "artist_ids": _pick_artist_ids(num_artists),
                "label_ids": _pick_label_ids(num_labels),
                "master_id": _pick_master(num_masters),
                "genres": _pick_genres(),
                "styles": _maybe_pick_styles(),
                "year": _maybe_year(),
                "sha256": hashlib.sha256(f"release-{i}".encode()).hexdigest(),
            }
        )

    # --- Genre/Style nodes ---
    genres = [{"name": g} for g in GENRES]
    styles = [{"name": s} for s in STYLES]

    # --- Relationships ---
    print("  Generating BY relationships...")
    by_rels = []
    for r in releases:
        for aid in r["artist_ids"]:  # type: ignore[union-attr]
            by_rels.append({"from_id": r["id"], "to_id": aid})

    print("  Generating ON relationships...")
    on_rels = []
    for r in releases:
        for lid in r["label_ids"]:  # type: ignore[union-attr]
            on_rels.append({"from_id": r["id"], "to_id": lid})

    print("  Generating DERIVED_FROM relationships...")
    derived_from_rels = [{"from_id": r["id"], "to_id": r["master_id"]} for r in releases]

    print("  Generating IS relationships...")
    is_rels = []
    for r in releases:
        for g in r["genres"]:  # type: ignore[union-attr]
            is_rels.append({"from_id": r["id"], "to_id": g, "type": "genre"})
        for s in r["styles"]:  # type: ignore[union-attr]
            is_rels.append({"from_id": r["id"], "to_id": s, "type": "style"})

    print("  Generating MEMBER_OF relationships...")
    member_of_rels = _generate_band_memberships(num_artists)

    print("  Generating ALIAS_OF relationships...")
    alias_of_rels = _generate_aliases(num_artists)

    print("  Generating SUBLABEL_OF relationships...")
    sublabel_of_rels = _generate_sublabels(num_labels)

    print("  Generating PART_OF relationships...")
    part_of_rels = []
    for style in STYLES:
        # Each style maps to 1-3 genres
        n_genres = random.randint(1, 3)  # noqa: S311  # nosec B311
        for g in _zipf_choice(GENRES, GENRE_WEIGHTS, k=n_genres):
            part_of_rels.append({"from_id": style, "to_id": g})

    total_nodes = num_artists + num_labels + num_masters + num_releases + len(GENRES) + len(STYLES)
    total_rels = (
        len(by_rels)
        + len(on_rels)
        + len(derived_from_rels)
        + len(is_rels)
        + len(member_of_rels)
        + len(alias_of_rels)
        + len(sublabel_of_rels)
        + len(part_of_rels)
    )
    print(f"  Total nodes: {total_nodes:,}, Total relationships: {total_rels:,}")
    print(f"  Rels per node: {total_rels / total_nodes:.2f}")

    return {
        "scale": scale,
        "artists": artists,
        "labels": labels,
        "masters": masters,
        "releases": releases,
        "genres": genres,
        "styles": styles,
        "by_rels": by_rels,
        "on_rels": on_rels,
        "derived_from_rels": derived_from_rels,
        "is_rels": is_rels,
        "member_of_rels": member_of_rels,
        "alias_of_rels": alias_of_rels,
        "sublabel_of_rels": sublabel_of_rels,
        "part_of_rels": part_of_rels,
    }


def save_test_data(data: dict[str, Any], path: str | Path) -> None:
    """Save test data to a gzipped JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Saving synthetic data to {path}...")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"  Saved ({size_mb:.1f} MB compressed)")


def load_test_data(path: str | Path) -> dict[str, Any]:
    """Load test data from a gzipped JSON file."""
    path = Path(path)
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"Loading synthetic data from {path} ({size_mb:.1f} MB)...")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    total_nodes = len(data.get("artists", [])) + len(data.get("labels", [])) + len(data.get("masters", [])) + len(data.get("releases", []))
    total_rels = sum(
        len(data.get(k, []))
        for k in (
            "by_rels",
            "on_rels",
            "derived_from_rels",
            "is_rels",
            "member_of_rels",
            "alias_of_rels",
            "sublabel_of_rels",
            "part_of_rels",
        )
    )
    print(f"  Scale: {data.get('scale', 'unknown')}, Nodes: {total_nodes:,}, Rels: {total_rels:,}")
    return data


def main() -> None:
    """CLI for generating synthetic data files."""
    import argparse

    parser = argparse.ArgumentParser(description="Synthetic data generator for graph database benchmarks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen_parser = subparsers.add_parser("generate", help="Generate synthetic data and save to file")
    gen_parser.add_argument("--scale", default="small", choices=["small", "large"])
    gen_parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    gen_parser.add_argument("--output", "-o", required=True, help="Output path (.json.gz)")

    args = parser.parse_args()

    if args.command == "generate":
        data = generate_test_data(scale=args.scale, seed=args.seed)
        save_test_data(data, args.output)


if __name__ == "__main__":
    main()
