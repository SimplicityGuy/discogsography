"""SVG taste card generator.

Produces a 600x400 SVG summarising a user's taste fingerprint.
All user-supplied strings are escaped via ``html.escape`` to prevent XSS.
"""

import html

from api.models import TasteDriftYear


def render_taste_card(
    *,
    peak_decade: int | None,
    obscurity_score: float,
    top_genres: list[str],
    top_labels: list[str],
    drift: list[TasteDriftYear],
) -> str:
    """Return a 600x400 SVG string summarising the user's taste fingerprint."""
    decade_text = html.escape(str(peak_decade)) if peak_decade is not None else "N/A"
    bar_width = max(4, min(200, int(obscurity_score * 200)))

    genre_lines = ""
    for i, genre in enumerate(top_genres[:5]):
        y = 155 + i * 20
        genre_lines += f'    <text x="30" y="{y}" font-size="13" fill="#ccc">{html.escape(genre)}</text>\n'

    label_lines = ""
    for i, label in enumerate(top_labels[:5]):
        y = 155 + i * 20
        label_lines += f'    <text x="320" y="{y}" font-size="13" fill="#ccc">{html.escape(label)}</text>\n'

    drift_lines = ""
    for i, d in enumerate(drift[-5:]):
        y = 320 + i * 18
        drift_lines += f'    <text x="30" y="{y}" font-size="12" fill="#aaa">{html.escape(d.year)}: {html.escape(d.top_genre)}</text>\n'

    svg = f"""\
<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <rect width="600" height="400" rx="12" fill="#1a1a2e"/>
  <text x="300" y="35" font-size="18" font-weight="bold" fill="#e0e0e0" text-anchor="middle">Taste Fingerprint</text>

  <!-- Peak Decade -->
  <text x="30" y="70" font-size="14" fill="#888">Peak Decade</text>
  <text x="30" y="92" font-size="22" font-weight="bold" fill="#fff">{decade_text}s</text>

  <!-- Obscurity -->
  <text x="320" y="70" font-size="14" fill="#888">Obscurity</text>
  <rect x="320" y="78" width="200" height="16" rx="4" fill="#333"/>
  <rect x="320" y="78" width="{bar_width}" height="16" rx="4" fill="#6c5ce7"/>
  <text x="530" y="91" font-size="12" fill="#ccc">{obscurity_score:.0%}</text>

  <!-- Top Genres -->
  <text x="30" y="130" font-size="14" fill="#888">Top Genres</text>
{genre_lines}
  <!-- Top Labels -->
  <text x="320" y="130" font-size="14" fill="#888">Top Labels</text>
{label_lines}
  <!-- Drift -->
  <text x="30" y="300" font-size="14" fill="#888">Taste Drift</text>
{drift_lines}</svg>"""

    return svg
