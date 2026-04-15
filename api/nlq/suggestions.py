"""Template-based suggestion engine for the NLQ Ask pill."""

from __future__ import annotations


_MAX_FOCUS_LEN = 120
_MAX_SUGGESTION_LEN = 256

_DEFAULT_EXPLORE = [
    "How are Kraftwerk and Afrika Bambaataa connected?",
    "What genres emerged in the 1990s?",
    "Most prolific electronic label",
    "Show the shortest path from David Bowie to Daft Punk",
]

_DEFAULT_TRENDS = [
    "Which labels grew the most in 2024?",
    "Show the trend of techno releases over the last decade",
    "Peak year for Detroit techno",
    "Which genres are declining since 2020?",
]

_DEFAULT_INSIGHTS = [
    "Biggest labels of 2024",
    "Most connected artists overall",
    "Top collaborators in electronic music",
    "Rarest releases on Warp Records",
]

_DEFAULT_GENRES = [
    "What genres split off from house in the 1990s?",
    "Parent genre of jungle",
    "Sub-genres of ambient",
    "Genres that combine jazz and electronic",
]

_DEFAULT_CREDITS = [
    "Who produced 'Computer World'?",
    "Engineers credited on Kraftwerk releases",
    "Writers who collaborated with Brian Eno",
    "Vocalists credited on Massive Attack releases",
]

_PANE_DEFAULTS: dict[str, list[str]] = {
    "explore": _DEFAULT_EXPLORE,
    "trends": _DEFAULT_TRENDS,
    "insights": _DEFAULT_INSIGHTS,
    "genres": _DEFAULT_GENRES,
    "credits": _DEFAULT_CREDITS,
}

_ARTIST_TEMPLATES = [
    "Who influenced {focus}?",
    "What labels has {focus} released on?",
    "{focus}'s collaborators in the 70s",
    "Most prolific decade for {focus}",
    "How are {focus} and Kraftwerk connected?",
]

_LABEL_TEMPLATES = [
    "Biggest artists on {focus}",
    "Genres most associated with {focus}",
    "Peak year for {focus}",
    "Artists who moved from {focus} to a rival label",
]

_GENRE_TEMPLATES = [
    "Who are the pioneers of {focus}?",
    "Sub-genres of {focus}",
    "Labels most associated with {focus}",
    "How did {focus} evolve between 1990 and 2010?",
]


def build_suggestions(
    *,
    pane: str,
    focus: str | None,
    focus_type: str | None,
) -> list[str]:
    """Return 4-6 suggested queries for the given context."""
    if focus is None or focus_type is None:
        return _PANE_DEFAULTS.get(pane, _DEFAULT_EXPLORE)[:6]

    focus_trimmed = focus.strip()[:_MAX_FOCUS_LEN]
    if not focus_trimmed:
        return _PANE_DEFAULTS.get(pane, _DEFAULT_EXPLORE)[:6]

    templates = {
        "artist": _ARTIST_TEMPLATES,
        "label": _LABEL_TEMPLATES,
        "genre": _GENRE_TEMPLATES,
        "style": _GENRE_TEMPLATES,
    }.get(focus_type, _ARTIST_TEMPLATES)

    rendered = [t.format(focus=focus_trimmed) for t in templates]
    capped = [q[:_MAX_SUGGESTION_LEN] for q in rendered]
    return capped[:6]
