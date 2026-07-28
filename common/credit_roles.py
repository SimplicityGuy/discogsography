"""Credit role taxonomy for Discogs extraartists data.

Groups Discogs credit roles into high-level categories for filtering and
aggregation. Used by the graphinator during ingestion and the credits API
for role-based queries.
"""

from __future__ import annotations


# ── Role category definitions ─────────────────────────────────────────────────
# Each category maps to a set of lowercase Discogs role strings.  When matching,
# we normalise the raw role to lowercase and check for substring containment
# (e.g. "recorded by, mixed by" matches both "recorded by" and "mixed by").

ROLE_CATEGORIES: dict[str, set[str]] = {
    "production": {
        "producer",
        "executive producer",
        "co-producer",
        "executive-producer",
        "produced by",
        "co-produced by",
    },
    "engineering": {
        "engineer",
        "recorded by",
        "mixed by",
        "mixed at",
        "remix",
        "remixed by",
        "recording engineer",
        "mixing engineer",
        "sound engineer",
        "audio engineer",
        "assistant engineer",
    },
    "mastering": {
        "mastered by",
        "mastered at",
        "lacquer cut by",
        "cut by",
        "mastering engineer",
        "remastered by",
    },
    "session": {
        "bass",
        "guitar",
        "drums",
        "keyboards",
        "piano",
        "percussion",
        "saxophone",
        "trumpet",
        "violin",
        "viola",
        "cello",
        "flute",
        "organ",
        "synthesizer",
        "vocals",
        "backing vocals",
        "lead vocals",
        "strings",
        "horns",
        "harmonica",
        "banjo",
        "mandolin",
        "harp",
        "clarinet",
        "oboe",
        "trombone",
        "tuba",
        "accordion",
        "tabla",
        "sitar",
        "congas",
        "bongos",
        "session musician",
        "featuring",
    },
    "design": {
        "artwork",
        "artwork by",
        "design",
        "designed by",
        "photography",
        "photography by",
        "liner notes",
        "cover",
        "layout",
        "illustration",
        "art direction",
    },
    "management": {
        "a&r",
        "management",
        "managed by",
        "booking",
        "booked by",
        "a & r",
    },
}

# Build reverse lookup: lowercase role fragment → category, for the O(1) direct
# (exact-key) match. Iteration order doesn't matter for a dict lookup.
_ROLE_TO_CATEGORY: dict[str, str] = {}
for _cat, _roles in ROLE_CATEGORIES.items():
    for _role in _roles:
        _ROLE_TO_CATEGORY[_role] = _cat

# Substring-scan order: every (fragment, category) pair, sorted by fragment length
# descending GLOBALLY across all categories (not just within one). categorize_role's
# fallback substring scan returns the first match, so specificity must be
# global — a short generic fragment declared in an earlier category (e.g.
# engineering's "engineer") must never pre-empt a longer, more specific fragment
# in a later-declared category (e.g. mastering's "mastering engineer"). A
# per-category-only length sort (the previous approach) let category declaration
# order silently defeat specificity for compound cross-category credits.
_ROLE_FRAGMENTS_BY_SPECIFICITY: list[tuple[str, str]] = sorted(_ROLE_TO_CATEGORY.items(), key=lambda pair: (-len(pair[0]), pair[0]))


def categorize_role(raw_role: str) -> str:
    """Map a raw Discogs credit role string to a high-level category.

    The raw role may contain multiple comma-separated roles
    (e.g. "Recorded By, Mixed By").  We check each fragment against
    the taxonomy and return the first (most specific) match.

    Returns:
        One of: "production", "engineering", "mastering", "session",
        "design", "management", or "other" if no match.
    """
    lower = raw_role.lower().strip()

    # Direct match first
    if lower in _ROLE_TO_CATEGORY:
        return _ROLE_TO_CATEGORY[lower]

    # Check if any known role fragment is contained in the raw string, longest
    # (most specific) fragment first, regardless of which category declared it.
    for role_fragment, category in _ROLE_FRAGMENTS_BY_SPECIFICITY:
        if role_fragment in lower:
            return category

    return "other"


# All valid category names (including "other")
ALL_CATEGORIES: tuple[str, ...] = (
    "production",
    "engineering",
    "mastering",
    "session",
    "design",
    "management",
    "other",
)
