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

# Build reverse lookup: lowercase role fragment → category
# Use ROLE_CATEGORIES (ordered dict) as iteration source to ensure deterministic
# ordering — longer fragments first within each category for specificity.
_ROLE_TO_CATEGORY: dict[str, str] = {}
for _cat, _roles in ROLE_CATEGORIES.items():
    for _role in sorted(_roles, key=len, reverse=True):
        _ROLE_TO_CATEGORY[_role] = _cat


def categorize_role(raw_role: str) -> str:
    """Map a raw Discogs credit role string to a high-level category.

    The raw role may contain multiple comma-separated roles
    (e.g. "Recorded By, Mixed By").  We check each fragment against
    the taxonomy and return the first match.

    Returns:
        One of: "production", "engineering", "mastering", "session",
        "design", "management", or "other" if no match.
    """
    lower = raw_role.lower().strip()

    # Direct match first
    if lower in _ROLE_TO_CATEGORY:
        return _ROLE_TO_CATEGORY[lower]

    # Check if any known role fragment is contained in the raw string
    for role_fragment, category in _ROLE_TO_CATEGORY.items():
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
