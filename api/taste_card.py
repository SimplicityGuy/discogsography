"""SVG taste card generator.

Produces a 1200x630 (social-share aspect) SVG summarising a user's taste
fingerprint: an obscurity scale, ranked genre/label bars, and a drift sparkline.
All user-supplied strings are escaped via ``html.escape`` to prevent XSS.
"""

import html

from api.models import TasteDriftYear


# Card geometry
_W = 1200
_H = 630

# Palette (purple/violet on deep navy)
_BG_TOP = "#1c1c2e"
_BG_BOTTOM = "#101019"
_HDR_FROM = "#7c3aed"
_HDR_TO = "#a855f7"
_ACCENT_FROM = "#6c5ce7"
_ACCENT_TO = "#a855f7"
_TEXT = "#f5f5fa"
_MUTED = "#8b8ba7"
_FAINT = "#6b6b85"

# Obscurity tiers (mainstream -> obscure). Boundary is inclusive on the upper
# tier (``score >= threshold``), matching the project's tier convention.
# Keep in sync with the Explore strip (explore/static/js/user-panes.js).
_OBSCURITY_TIERS = [
    (0.75, "Deep Cuts", "#f43f5e"),
    (0.50, "Obscure", "#a855f7"),
    (0.25, "Eclectic", "#818cf8"),
    (0.0, "Mainstream", "#38bdf8"),
]


def _esc(value: str) -> str:
    return html.escape(value)


def _obscurity_tier(score: float) -> tuple[str, str]:
    """Return the (name, color) tier for an obscurity score in [0, 1]."""
    for threshold, name, color in _OBSCURITY_TIERS:
        if score >= threshold:
            return name, color
    return _OBSCURITY_TIERS[-1][1], _OBSCURITY_TIERS[-1][2]


def _obscurity_scale(score: float, x: int, y: int, w: int) -> str:
    """A mainstream->obscure gradient track with a glowing marker at ``score``."""
    s = max(0.0, min(1.0, score))
    name, color = _obscurity_tier(s)
    pct = f"{score:.0%}"
    mx = x + s * w
    track_y = y + 15
    h = 12
    dot_cy = track_y + h / 2
    return "\n  ".join(
        [
            f'<text x="{x}" y="{y}" font-size="16" font-weight="bold" fill="{_MUTED}" letter-spacing="2">OBSCURITY</text>',
            f'<text x="{x + w}" y="{y}" font-size="18" font-weight="bold" fill="{color}" text-anchor="end">{_esc(name)} · {pct}</text>',
            f'<rect x="{x}" y="{track_y}" width="{w}" height="{h}" rx="6" fill="url(#obscGrad)"/>',
            f'<circle cx="{mx:.1f}" cy="{dot_cy:.1f}" r="16" fill="{color}" opacity="0.35"/>',
            f'<circle cx="{mx:.1f}" cy="{dot_cy:.1f}" r="9" fill="#fff" stroke="{color}" stroke-width="3"/>',
            f'<text x="{x}" y="{track_y + h + 22}" font-size="13" fill="{_FAINT}">Mainstream</text>',
            f'<text x="{x + w}" y="{track_y + h + 22}" font-size="13" fill="{_FAINT}" text-anchor="end">Obscure</text>',
        ]
    )


def _ranked_bars(items: list[tuple[str, int]], x0: int, y_start: int, col_w: int, row_h: int) -> str:
    """A vertical list of ranked horizontal bars (length proportional to count)."""
    if not items:
        return f'<text x="{x0}" y="{y_start + 4}" font-size="17" fill="{_FAINT}">No data yet</text>'
    max_count = max((c for _, c in items), default=0) or 1
    parts: list[str] = []
    for i, (name, count) in enumerate(items[:5]):
        y = y_start + i * row_h
        bar_w = max(6, round(col_w * (count / max_count)))
        parts.append(f'<text x="{x0}" y="{y}" font-size="21" fill="{_TEXT}">{_esc(name)}</text>')
        parts.append(f'<text x="{x0 + col_w}" y="{y}" font-size="15" fill="{_MUTED}" text-anchor="end">{count:,}</text>')
        parts.append(f'<rect x="{x0}" y="{y + 11}" width="{col_w}" height="9" rx="4.5" fill="#ffffff14"/>')
        parts.append(f'<rect x="{x0}" y="{y + 11}" width="{bar_w}" height="9" rx="4.5" fill="url(#barGrad)"/>')
    return "\n  ".join(parts)


def _drift_sparkline(drift: list[TasteDriftYear], x: int, y: int, w: int, h: int) -> str:
    """A small line chart of additions-per-year, with year labels and genre tooltips."""
    pts = drift[-8:]
    if not pts:
        return f'<text x="{x}" y="{y + h // 2}" font-size="17" fill="{_FAINT}">No drift data yet</text>'
    max_count = max((d.count for d in pts), default=0) or 1
    n = len(pts)
    step = w / (n - 1) if n > 1 else 0.0
    coords: list[tuple[float, float, TasteDriftYear]] = []
    for i, d in enumerate(pts):
        px = x + i * step if n > 1 else x + w / 2
        py = y + h - (d.count / max_count) * h
        coords.append((px, py, d))

    parts: list[str] = []
    if n > 1:
        line = " ".join(f"{px:.1f},{py:.1f}" for px, py, _ in coords)
        parts.append(f'<polyline points="{line}" fill="none" stroke="url(#barGrad)" stroke-width="3" stroke-linejoin="round"/>')
    for idx, (px, py, d) in enumerate(coords):
        last = idx == n - 1
        parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{5 if last else 4}" fill="{_ACCENT_TO if last else _ACCENT_FROM}">'
            f"<title>{_esc(d.year)}: {_esc(d.top_genre)} ({d.count:,})</title></circle>"
        )
        parts.append(f'<text x="{px:.1f}" y="{y + h + 20}" font-size="13" fill="{_MUTED}" text-anchor="middle">{_esc(d.year)}</text>')
    # Caption: the most recent year's top genre.
    parts.append(f'<text x="{x}" y="{y - 14}" font-size="15" fill="{_FAINT}">Now: {_esc(coords[-1][2].top_genre)}</text>')
    return "\n  ".join(parts)


def render_taste_card(
    *,
    peak_decade: int | None,
    obscurity_score: float,
    top_genres: list[tuple[str, int]],
    top_labels: list[tuple[str, int]],
    drift: list[TasteDriftYear],
) -> str:
    """Return a 1200x630 SVG string summarising the user's taste fingerprint."""
    decade_text = f"{_esc(str(peak_decade))}s" if peak_decade is not None else "N/A"

    obscurity = _obscurity_scale(obscurity_score, x=50, y=190, w=1100)
    genre_bars = _ranked_bars(top_genres, x0=50, y_start=330, col_w=480, row_h=48)
    label_bars = _ranked_bars(top_labels, x0=640, y_start=330, col_w=480, row_h=48)
    sparkline = _drift_sparkline(drift, x=360, y=584, w=560, h=26)

    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" viewBox="0 0 {_W} {_H}">
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{_BG_TOP}"/>
      <stop offset="1" stop-color="{_BG_BOTTOM}"/>
    </linearGradient>
    <linearGradient id="hdrGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{_HDR_FROM}"/>
      <stop offset="1" stop-color="{_HDR_TO}"/>
    </linearGradient>
    <linearGradient id="barGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{_ACCENT_FROM}"/>
      <stop offset="1" stop-color="{_ACCENT_TO}"/>
    </linearGradient>
    <linearGradient id="obscGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#38bdf8"/>
      <stop offset="0.33" stop-color="#818cf8"/>
      <stop offset="0.66" stop-color="#a855f7"/>
      <stop offset="1" stop-color="#f43f5e"/>
    </linearGradient>
    <clipPath id="card"><rect x="0" y="0" width="{_W}" height="{_H}" rx="28"/></clipPath>
  </defs>

  <g clip-path="url(#card)">
    <rect x="0" y="0" width="{_W}" height="{_H}" fill="url(#bgGrad)"/>
    <rect x="0" y="0" width="{_W}" height="150" fill="url(#hdrGrad)"/>
  </g>

  <!-- Header -->
  <text x="50" y="70" font-size="40" font-weight="bold" fill="#ffffff" letter-spacing="1">TASTE FINGERPRINT</text>
  <text x="50" y="108" font-size="20" fill="#ffffffcc">Peak decade <tspan font-weight="bold" fill="#ffffff">{decade_text}</tspan></text>

  <!-- Obscurity scale -->
  {obscurity}

  <!-- Section headers -->
  <text x="50" y="300" font-size="18" font-weight="bold" fill="{_MUTED}" letter-spacing="2">TOP GENRES</text>
  <text x="640" y="300" font-size="18" font-weight="bold" fill="{_MUTED}" letter-spacing="2">TOP LABELS</text>

  <!-- Ranked bars -->
  {genre_bars}
  {label_bars}

  <!-- Footer band: drift sparkline + branding -->
  <line x1="50" y1="556" x2="1150" y2="556" stroke="#ffffff14" stroke-width="1"/>
  <text x="50" y="586" font-size="14" font-weight="bold" fill="{_MUTED}" letter-spacing="2">TASTE DRIFT</text>
  {sparkline}
  <text x="1150" y="604" font-size="20" font-weight="bold" fill="url(#barGrad)" text-anchor="end">discogsography</text>
</svg>"""
