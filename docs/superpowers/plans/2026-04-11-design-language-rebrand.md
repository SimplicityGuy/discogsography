# Design Language Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing blue/purple accent system and four-quadrant logo with the "Deep Space + Purple" design language across explore and dashboard services, including programmatically generated brand assets.

**Architecture:** A Python script generates all logo/favicon/brand assets using Pillow, outputting to both `explore/static/brand/` and `dashboard/static/brand/`. CSS variables are replaced in-place. The light/dark theme toggle is removed — single dark theme only. Google Fonts adds Space Grotesk for the wordmark.

**Tech Stack:** Python/Pillow (asset generation), CSS custom properties, Tailwind CSS, HTML

**Spec:** `docs/superpowers/specs/2026-04-11-design-language-rebrand-design.md`

---

### Task 1: Add Pillow dependency and download Space Grotesk font

**Files:**
- Modify: `pyproject.toml` (dev dependencies)
- Create: `static/fonts/SpaceGrotesk-Bold.ttf`
- Create: `static/fonts/SpaceGrotesk-Regular.ttf`

- [ ] **Step 1: Add Pillow as a dev dependency**

```bash
cd /Users/Robert/Code/public/discogsography/.claude/worktrees/design-language
uv add --dev Pillow
```

- [ ] **Step 2: Download Space Grotesk font files from Google Fonts**

```bash
mkdir -p static/fonts
curl -L "https://github.com/nicholasc/google-fonts-releases/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf" -o static/fonts/SpaceGrotesk-Variable.ttf 2>/dev/null || \
curl -L "https://fonts.google.com/download?family=Space+Grotesk" -o /tmp/space-grotesk.zip && \
unzip -o /tmp/space-grotesk.zip -d /tmp/space-grotesk/ && \
cp /tmp/space-grotesk/static/SpaceGrotesk-Bold.ttf static/fonts/ && \
cp /tmp/space-grotesk/static/SpaceGrotesk-Regular.ttf static/fonts/
```

If the variable font downloads, use it for both weights. If individual statics download, use those. Verify files exist:

```bash
ls -la static/fonts/SpaceGrotesk*
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock static/fonts/
git commit -m "chore: add Pillow dev dependency and Space Grotesk font files"
```

---

### Task 2: Create brand asset generation script — vinyl icon rendering

**Files:**
- Create: `scripts/generate_brand_assets.py`

This task builds the core rendering functions. The script will be extended in Tasks 3-4.

- [ ] **Step 1: Create the script with color constants and vinyl icon renderer**

Create `scripts/generate_brand_assets.py`:

```python
#!/usr/bin/env env uv run python
"""Generate Discogsography brand assets — Constellation Vinyl logo."""

from __future__ import annotations

import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# === Brand colors ===
VOID = (6, 10, 18)
DEEP = (10, 16, 24)
CARD = (15, 26, 46)
ELEVATED = (22, 37, 64)
BORDER = (30, 48, 80)
HOVER = (42, 61, 88)

CYAN_500 = (0, 188, 212)
CYAN_GLOW = (0, 229, 255)
PURPLE_500 = (124, 77, 255)
PURPLE_300 = (179, 136, 255)

TEXT_HIGH = (240, 244, 248)
TEXT_MUTED = (74, 94, 120)
TEXT_DIM = (122, 139, 163)

LIGHT_BG = (240, 244, 248)
LIGHT_TEXT = (13, 27, 42)
LIGHT_TEXT_MUTED = (90, 112, 136)

# Outer nodes: 5 nodes scattered organically
OUTER_NODES = [
    # (angle_degrees, radius_fraction, color, size_fraction)
    (70, 0.82, CYAN_GLOW, 0.055),
    (145, 0.78, CYAN_GLOW, 0.05),
    (200, 0.85, PURPLE_300, 0.045),
    (280, 0.80, PURPLE_300, 0.045),
    (340, 0.75, CYAN_GLOW, 0.05),
]

# Inner nodes: 3 smaller nodes
INNER_NODES = [
    (95, 0.50, CYAN_500, 0.03),
    (210, 0.55, PURPLE_500, 0.03),
    (315, 0.48, CYAN_500, 0.03),
]

# Network edges: pairs of node indices (outer=0-4, inner=5-7)
EDGES = [
    (0, 1, CYAN_500, 0.4),
    (1, 2, CYAN_500, 0.4),
    (2, 3, PURPLE_500, 0.4),
    (3, 4, PURPLE_500, 0.4),
    (4, 0, CYAN_500, 0.4),
    # Cross connections
    (0, 3, (0, 131, 143), 0.2),
    (1, 4, (94, 53, 177), 0.2),
    # Inner connections
    (5, 6, CYAN_500, 0.3),
    (6, 7, PURPLE_500, 0.3),
    (7, 5, CYAN_500, 0.3),
]


def _node_positions(
    cx: float, cy: float, radius: float
) -> list[tuple[float, float, tuple[int, int, int], float]]:
    """Compute absolute positions for all nodes."""
    positions = []
    all_nodes = OUTER_NODES + INNER_NODES
    for angle_deg, r_frac, color, size_frac in all_nodes:
        angle = math.radians(angle_deg)
        x = cx + radius * r_frac * math.cos(angle)
        y = cy + radius * r_frac * math.sin(angle)
        positions.append((x, y, color, size_frac * radius * 2))
    return positions


def _draw_glow_circle(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    cx: float,
    cy: float,
    radius: float,
    color: tuple[int, int, int],
    opacity: float = 0.15,
) -> None:
    """Draw a glowing circle with halo effect."""
    # Glow halo on separate layer
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    halo_r = radius * 1.8
    glow_draw.ellipse(
        [cx - halo_r, cy - halo_r, cx + halo_r, cy + halo_r],
        fill=(*color, int(255 * opacity)),
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius * 0.6))
    img.paste(Image.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 0)), glow_layer), (0, 0), glow_layer)
    # Solid core
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(*color, int(255 * 0.9)),
    )


def render_icon(size: int, bg_color: tuple[int, int, int] = VOID) -> Image.Image:
    """Render the Constellation Vinyl icon mark at the given size."""
    img = Image.new("RGBA", (size, size), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    cx, cy = size / 2, size / 2
    radius = size * 0.44

    # Vinyl body
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(*DEEP, 255),
        outline=(*BORDER, 255),
        width=max(1, int(size * 0.015)),
    )

    # Groove rings
    for frac in [0.88, 0.76, 0.64, 0.52, 0.40]:
        r = radius * frac
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(*ELEVATED, 255),
            width=max(1, int(size * 0.004)),
        )

    # Compute node positions
    nodes = _node_positions(cx, cy, radius)

    # Network edges
    for src, dst, color, opacity in EDGES:
        x1, y1 = nodes[src][0], nodes[src][1]
        x2, y2 = nodes[dst][0], nodes[dst][1]
        edge_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        edge_draw = ImageDraw.Draw(edge_layer)
        edge_draw.line(
            [(x1, y1), (x2, y2)],
            fill=(*color, int(255 * opacity)),
            width=max(1, int(size * 0.008)),
        )
        img = Image.alpha_composite(img, edge_layer)
        draw = ImageDraw.Draw(img)

    # Network nodes
    for x, y, color, node_size in nodes:
        _draw_glow_circle(draw, img, x, y, node_size / 2, color)
        draw = ImageDraw.Draw(img)

    # Center spindle — outer ring
    spindle_r = radius * 0.18
    draw.ellipse(
        [cx - spindle_r, cy - spindle_r, cx + spindle_r, cy + spindle_r],
        fill=(*CARD, 255),
        outline=(*BORDER, 255),
        width=max(1, int(size * 0.012)),
    )

    # Center spindle — gradient fill (approximate with concentric circles)
    inner_r = spindle_r * 0.6
    steps = max(10, int(inner_r))
    for i in range(steps):
        t = i / steps
        r = inner_r * (1 - t)
        cr = int(CYAN_GLOW[0] * (1 - t) + PURPLE_500[0] * t)
        cg = int(CYAN_GLOW[1] * (1 - t) + PURPLE_500[1] * t)
        cb = int(CYAN_GLOW[2] * (1 - t) + PURPLE_500[2] * t)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(cr, cg, cb, 255),
        )

    # Center hole
    hole_r = spindle_r * 0.25
    draw.ellipse(
        [cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r],
        fill=(*VOID, 255),
    )

    return img


if __name__ == "__main__":
    # Quick test render
    icon = render_icon(512)
    icon.save("/tmp/discogsography_icon_test.png")
    print("Test icon saved to /tmp/discogsography_icon_test.png")
```

- [ ] **Step 2: Run the test render to verify it works**

```bash
uv run python scripts/generate_brand_assets.py
```

Expected: "Test icon saved to /tmp/discogsography_icon_test.png". Open the file to verify the vinyl/network logo renders correctly.

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_brand_assets.py
git commit -m "feat: add brand asset generation script with vinyl icon renderer"
```

---

### Task 3: Add banner, square, OG image, and showcase renderers

**Files:**
- Modify: `scripts/generate_brand_assets.py`

- [ ] **Step 1: Add the banner, square, OG image, and showcase render functions**

Add these functions to `scripts/generate_brand_assets.py` after `render_icon()`:

```python
def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font from static/fonts/ directory."""
    font_dir = Path(__file__).parent.parent / "static" / "fonts"
    # Try variable font first, then static
    for pattern in [f"{name}-Variable.ttf", f"{name}.ttf"]:
        path = font_dir / pattern
        if path.exists():
            return ImageFont.truetype(str(path), size)
    # Fallback for static weight-specific files
    return ImageFont.truetype(str(font_dir / f"{name}.ttf"), size)


def render_banner(
    width: int = 1600,
    height: int = 400,
    bg_color: tuple[int, int, int] = VOID,
    text_color: tuple[int, int, int] = TEXT_HIGH,
    tagline_color: tuple[int, int, int] = TEXT_MUTED,
) -> Image.Image:
    """Render horizontal banner: icon (left) + wordmark + tagline (right)."""
    img = Image.new("RGBA", (width, height), (*bg_color, 255))

    # Render icon at 70% of height
    icon_size = int(height * 0.7)
    icon = render_icon(icon_size, bg_color)
    icon_x = int(width * 0.08)
    icon_y = (height - icon_size) // 2
    img.paste(icon, (icon_x, icon_y), icon)

    # Wordmark text
    text_x = icon_x + icon_size + int(width * 0.03)
    try:
        font_bold = _load_font("SpaceGrotesk-Bold", int(height * 0.18))
        font_regular = _load_font("SpaceGrotesk-Regular", int(height * 0.09))
    except OSError:
        font_bold = ImageFont.load_default()
        font_regular = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    # Wordmark
    wordmark_y = int(height * 0.32)
    draw.text(
        (text_x, wordmark_y),
        "discogsography",
        fill=(*text_color, 255),
        font=font_bold,
    )
    # Tagline
    tagline_y = wordmark_y + int(height * 0.22)
    draw.text(
        (text_x, tagline_y),
        "the choon network",
        fill=(*tagline_color, 255),
        font=font_regular,
    )

    return img


def render_square(
    size: int = 1024,
    bg_color: tuple[int, int, int] = VOID,
    text_color: tuple[int, int, int] = TEXT_HIGH,
) -> Image.Image:
    """Render stacked square: icon (top) + wordmark (below)."""
    img = Image.new("RGBA", (size, size), (*bg_color, 255))

    # Icon at 55% of size
    icon_size = int(size * 0.55)
    icon = render_icon(icon_size, bg_color)
    icon_x = (size - icon_size) // 2
    icon_y = int(size * 0.12)
    img.paste(icon, (icon_x, icon_y), icon)

    # Wordmark text centered below
    try:
        font_bold = _load_font("SpaceGrotesk-Bold", int(size * 0.08))
    except OSError:
        font_bold = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    text_y = icon_y + icon_size + int(size * 0.06)
    bbox = draw.textbbox((0, 0), "discogsography", font=font_bold)
    text_w = bbox[2] - bbox[0]
    text_x = (size - text_w) // 2
    draw.text(
        (text_x, text_y),
        "discogsography",
        fill=(*text_color, 255),
        font=font_bold,
    )

    return img


def render_og_image(
    width: int = 1200,
    height: int = 630,
) -> Image.Image:
    """Render Open Graph social sharing image."""
    img = Image.new("RGBA", (width, height), (*VOID, 255))

    # Icon centered, 40% of height
    icon_size = int(height * 0.40)
    icon = render_icon(icon_size, VOID)
    icon_x = (width - icon_size) // 2
    icon_y = int(height * 0.12)
    img.paste(icon, (icon_x, icon_y), icon)

    # Wordmark centered below icon
    try:
        font_bold = _load_font("SpaceGrotesk-Bold", int(height * 0.09))
        font_regular = _load_font("SpaceGrotesk-Regular", int(height * 0.05))
    except OSError:
        font_bold = ImageFont.load_default()
        font_regular = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # Wordmark
    wordmark_y = icon_y + icon_size + int(height * 0.06)
    bbox = draw.textbbox((0, 0), "discogsography", font=font_bold)
    text_w = bbox[2] - bbox[0]
    draw.text(
        ((width - text_w) // 2, wordmark_y),
        "discogsography",
        fill=(*TEXT_HIGH, 255),
        font=font_bold,
    )

    # Tagline
    tagline_y = wordmark_y + int(height * 0.11)
    bbox = draw.textbbox((0, 0), "the choon network", font=font_regular)
    text_w = bbox[2] - bbox[0]
    draw.text(
        ((width - text_w) // 2, tagline_y),
        "the choon network",
        fill=(*TEXT_MUTED, 255),
        font=font_regular,
    )

    return img


def render_design_showcase(width: int = 1600, height: int = 900) -> Image.Image:
    """Render a design showcase image showing palette, typography, and logo."""
    img = Image.new("RGBA", (width, height), (*VOID, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_bold = _load_font("SpaceGrotesk-Bold", 36)
        font_regular = _load_font("SpaceGrotesk-Regular", 18)
        font_label = _load_font("SpaceGrotesk-Regular", 14)
    except OSError:
        font_bold = font_regular = font_label = ImageFont.load_default()

    # Title
    draw.text((60, 40), "discogsography", fill=(*TEXT_HIGH, 255), font=font_bold)
    draw.text((60, 85), "Design Language — Deep Space + Purple", fill=(*TEXT_MUTED, 255), font=font_regular)

    # Color palette section
    y = 140
    draw.text((60, y), "BACKGROUND SCALE", fill=(*TEXT_DIM, 255), font=font_label)
    y += 30
    bg_colors = [
        (VOID, "Void"), (DEEP, "Deep"), (CARD, "Card"),
        (ELEVATED, "Elevated"), (BORDER, "Border"), (HOVER, "Hover"),
    ]
    for i, (color, name) in enumerate(bg_colors):
        x = 60 + i * 105
        draw.rounded_rectangle([x, y, x + 90, y + 60], radius=8, fill=(*color, 255), outline=(*BORDER, 255))
        draw.text((x + 5, y + 65), name, fill=(*TEXT_MUTED, 255), font=font_label)

    y += 110
    draw.text((60, y), "CYAN — PRIMARY", fill=(*TEXT_DIM, 255), font=font_label)
    y += 30
    cyan_colors = [
        ((0, 77, 90), "900"), ((0, 131, 143), "700"), (CYAN_500, "500"),
        (CYAN_GLOW, "Glow"), ((128, 240, 255), "Bright"),
    ]
    for i, (color, name) in enumerate(cyan_colors):
        x = 60 + i * 105
        draw.rounded_rectangle([x, y, x + 90, y + 60], radius=8, fill=(*color, 255))
        draw.text((x + 5, y + 65), name, fill=(*TEXT_MUTED, 255), font=font_label)

    y += 110
    draw.text((60, y), "PURPLE — SECONDARY", fill=(*TEXT_DIM, 255), font=font_label)
    y += 30
    purple_colors = [
        ((49, 27, 146), "900"), ((94, 53, 177), "700"), (PURPLE_500, "500"),
        (PURPLE_300, "300"), ((212, 184, 255), "Bright"),
    ]
    for i, (color, name) in enumerate(purple_colors):
        x = 60 + i * 105
        draw.rounded_rectangle([x, y, x + 90, y + 60], radius=8, fill=(*color, 255))
        draw.text((x + 5, y + 65), name, fill=(*TEXT_MUTED, 255), font=font_label)

    # Status colors
    y += 110
    draw.text((60, y), "STATUS", fill=(*TEXT_DIM, 255), font=font_label)
    y += 30
    status_colors = [
        ((0, 230, 118), "Success"), ((255, 82, 82), "Error"), ((255, 171, 0), "Warning"),
    ]
    for i, (color, name) in enumerate(status_colors):
        x = 60 + i * 105
        draw.rounded_rectangle([x, y, x + 90, y + 60], radius=8, fill=(*color, 255))
        draw.text((x + 5, y + 65), name, fill=(*TEXT_MUTED, 255), font=font_label)

    # Node colors
    draw.text((400, y - 30), "GRAPH NODES", fill=(*TEXT_DIM, 255), font=font_label)
    node_colors = [
        ((0, 230, 118), "Artist"), ((255, 92, 138), "Release"),
        ((120, 144, 156), "Label"), ((255, 213, 79), "Genre"),
        ((64, 196, 255), "Category"),
    ]
    for i, (color, name) in enumerate(node_colors):
        x = 400 + i * 105
        draw.rounded_rectangle([x, y, x + 90, y + 60], radius=8, fill=(*color, 255))
        draw.text((x + 5, y + 65), name, fill=(*TEXT_MUTED, 255), font=font_label)

    # Logo variants on the right side
    icon_sm = render_icon(200, VOID)
    img.paste(icon_sm, (width - 280, 140), icon_sm)
    draw.text((width - 280, 350), "Icon Mark", fill=(*TEXT_MUTED, 255), font=font_label)

    # Banner preview
    banner = render_banner(600, 150, VOID)
    img.paste(banner, (width - 660, 400), banner)
    draw.text((width - 660, 560), "Banner", fill=(*TEXT_MUTED, 255), font=font_label)

    return img
```

- [ ] **Step 2: Test the new renderers**

Add a quick test to the `__main__` block — replace the existing one:

```python
if __name__ == "__main__":
    render_icon(512).save("/tmp/discogsography_icon_test.png")
    render_banner().save("/tmp/discogsography_banner_test.png")
    render_square().save("/tmp/discogsography_square_test.png")
    render_og_image().save("/tmp/discogsography_og_test.png")
    render_design_showcase().save("/tmp/discogsography_showcase_test.png")
    print("All test renders saved to /tmp/discogsography_*_test.png")
```

```bash
uv run python scripts/generate_brand_assets.py
```

Expected: "All test renders saved" — open each file to verify visual quality.

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_brand_assets.py
git commit -m "feat: add banner, square, OG image, and showcase renderers"
```

---

### Task 4: Add favicon generation and full export pipeline

**Files:**
- Modify: `scripts/generate_brand_assets.py`

- [ ] **Step 1: Add favicon generation and the main export function**

Add these functions to `scripts/generate_brand_assets.py`, replacing the `__main__` block:

```python
def generate_favicons(icon_img: Image.Image, output_dir: Path) -> None:
    """Generate all favicon sizes from a master icon image."""
    sizes = [16, 32, 48, 64, 128, 256, 512]

    for size in sizes:
        resized = icon_img.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(output_dir / f"favicon-{size}.png", "PNG")

    # Apple touch icon (180x180, no transparency)
    apple = icon_img.resize((180, 180), Image.Resampling.LANCZOS)
    apple_rgb = Image.new("RGB", (180, 180), VOID)
    apple_rgb.paste(apple, (0, 0), apple)
    apple_rgb.save(output_dir / "apple-touch-icon.png", "PNG")

    # favicon.ico (multi-size: 16, 32, 48)
    ico_images = []
    for size in [16, 32, 48]:
        ico_images.append(icon_img.resize((size, size), Image.Resampling.LANCZOS))
    ico_images[0].save(
        output_dir / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=ico_images[1:],
    )


def write_webmanifest(output_dir: Path) -> None:
    """Write the site.webmanifest file."""
    import json

    manifest = {
        "name": "Discogsography",
        "short_name": "Discogsography",
        "description": "The Choon Network \u2014 music knowledge graph",
        "icons": [
            {"src": "/static/brand/favicon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/brand/favicon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
        "theme_color": "#060a12",
        "background_color": "#060a12",
        "display": "standalone",
    }
    (output_dir / "site.webmanifest").write_text(json.dumps(manifest, indent=2) + "\n")


def generate_all(output_dirs: list[Path]) -> None:
    """Generate all brand assets and write to each output directory."""
    for output_dir in output_dirs:
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Generating assets in {output_dir}...")

        # Icon mark (dark + light)
        icon_dark = render_icon(1024, VOID)
        icon_dark.save(output_dir / "icon_dark.png", "PNG")

        icon_light = render_icon(1024, LIGHT_BG)
        icon_light.save(output_dir / "icon_light.png", "PNG")

        # Banner (dark + light)
        render_banner(1600, 400, VOID, TEXT_HIGH, TEXT_MUTED).save(
            output_dir / "banner_dark.png", "PNG"
        )
        render_banner(1600, 400, LIGHT_BG, LIGHT_TEXT, LIGHT_TEXT_MUTED).save(
            output_dir / "banner_light.png", "PNG"
        )

        # Square (dark + light)
        render_square(1024, VOID, TEXT_HIGH).save(output_dir / "square_dark.png", "PNG")
        render_square(1024, LIGHT_BG, LIGHT_TEXT).save(output_dir / "square_light.png", "PNG")

        # OG image
        render_og_image().save(output_dir / "og_image.png", "PNG")

        # Design showcase
        render_design_showcase().save(output_dir / "design_showcase.png", "PNG")

        # Favicons (generated from dark icon — dark bg looks best at small sizes)
        # Render a favicon-specific icon at 512px for best quality scaling
        favicon_source = render_icon(512, VOID)
        generate_favicons(favicon_source, output_dir)

        # Also generate a 192px favicon for the manifest
        favicon_192 = favicon_source.resize((192, 192), Image.Resampling.LANCZOS)
        favicon_192.save(output_dir / "favicon-192.png", "PNG")

        # Web manifest
        write_webmanifest(output_dir)

        print(f"  Done: {len(list(output_dir.glob('*')))} files")


if __name__ == "__main__":
    import sys

    root = Path(__file__).parent.parent
    output_dirs = [
        root / "explore" / "static" / "brand",
        root / "dashboard" / "static" / "brand",
    ]

    if "--test" in sys.argv:
        render_icon(512).save("/tmp/discogsography_icon_test.png")
        render_banner().save("/tmp/discogsography_banner_test.png")
        render_square().save("/tmp/discogsography_square_test.png")
        render_og_image().save("/tmp/discogsography_og_test.png")
        render_design_showcase().save("/tmp/discogsography_showcase_test.png")
        print("Test renders saved to /tmp/discogsography_*_test.png")
    else:
        generate_all(output_dirs)
        print("\nAll brand assets generated successfully.")
```

- [ ] **Step 2: Run the full generation pipeline**

```bash
uv run python scripts/generate_brand_assets.py
```

Expected: Assets generated in both `explore/static/brand/` and `dashboard/static/brand/`. Verify:

```bash
ls -la explore/static/brand/
ls -la dashboard/static/brand/
```

Should see 20 files each: `banner_dark.png`, `banner_light.png`, `square_dark.png`, `square_light.png`, `icon_dark.png`, `icon_light.png`, `og_image.png`, `design_showcase.png`, `favicon.ico`, `favicon-{16,32,48,64,128,192,256,512}.png`, `apple-touch-icon.png`, `site.webmanifest`.

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_brand_assets.py explore/static/brand/ dashboard/static/brand/
git commit -m "feat: generate complete brand asset set for explore and dashboard"
```

---

### Task 5: Rebrand explore CSS — replace color system

**Files:**
- Modify: `explore/static/css/styles.css:6-79` (CSS variables)

- [ ] **Step 1: Replace the `:root` light theme variables (lines 6-47) with the Deep Space palette**

Replace the entire `:root { ... }` block (lines 6-47 of `explore/static/css/styles.css`) with:

```css
:root {
    /* Background scale */
    --bg-void: #060a12;
    --bg-deep: #0a1018;
    --card-bg: #0f1a2e;
    --inner-bg: #162540;
    --border-color: #1e3050;
    --inner-border: #1e3050;
    --bg-hover: #2a3d58;

    /* Text scale */
    --text-high: #f0f4f8;
    --text-mid: #b0bec5;
    --text-dim: #7a8ba3;
    --text-muted: #4a5e78;

    /* Cyan — primary accent */
    --cyan-900: #004d5a;
    --cyan-700: #00838f;
    --cyan-500: #00bcd4;
    --cyan-glow: #00e5ff;
    --cyan-bright: #80f0ff;

    /* Purple — secondary accent */
    --purple-900: #311b92;
    --purple-700: #5e35b1;
    --purple-500: #7c4dff;
    --purple-300: #b388ff;
    --purple-bright: #d4b8ff;

    /* Legacy aliases (used by Tailwind classes and existing markup) */
    --blue-accent: #00bcd4;
    --purple-accent: #7c4dff;

    /* Semantic status */
    --accent-green: #00e676;
    --accent-yellow: #ffab00;
    --accent-red: #ff5252;

    /* UI tokens */
    --card-shadow: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
    --scrollbar-thumb: #2a3d58;
    --glass-bg: rgba(15,26,46,0.9);
    --label-bg: rgba(10,16,24,0.7);
    --overlay-bg: rgba(0,0,0,0.85);
    --gauge-track: #1e3050;
    --log-msg: #b0bec5;
    --row-border: rgba(255,255,255,0.05);

    /* Graph node colors (harmonized) */
    --node-artist: #00e676;
    --node-release: #ff5c8a;
    --node-label: #78909c;
    --node-genre: #ffd54f;
    --node-category: #40c4ff;
    --node-load-more: #162540;
    --node-load-more-border: #1e3050;
    --node-load-more-text: #7a8ba3;
}
```

- [ ] **Step 2: Remove the `.dark` class override block (lines 49-79)**

Delete the entire `.dark { ... }` block. Since we only have one theme now, all values are in `:root`.

- [ ] **Step 3: Verify no other light-theme-specific CSS exists in the file**

Search for any remaining references to the old colors:

```bash
grep -n "#F5F6F8\|#FFFFFF\|#1A202C\|#4A5568\|#718096\|#A0AEC0\|#3B82F6\|#7C3AED\|#1DB954\|#FF6B6B\|#ffc107\|#4A90D9" explore/static/css/styles.css
```

If any matches, update them to use the new `var(--token)` references or the new hex values.

- [ ] **Step 4: Commit**

```bash
git add explore/static/css/styles.css
git commit -m "feat: replace explore CSS color system with Deep Space palette"
```

---

### Task 6: Update explore Tailwind config and input CSS

**Files:**
- Modify: `explore/tailwind.config.js`
- Modify: `explore/tailwind.input.css`

- [ ] **Step 1: Update `explore/tailwind.config.js` — remove darkMode, add new color tokens**

Replace the full content of `explore/tailwind.config.js`:

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ["./static/index.html", "./static/js/**/*.js"],
    theme: {
        extend: {
            colors: {
                "bg-void": "var(--bg-void)",
                "bg-deep": "var(--bg-deep)",
                "card-bg": "var(--card-bg)",
                "inner-bg": "var(--inner-bg)",
                "bg-hover": "var(--bg-hover)",
                "text-high": "var(--text-high)",
                "text-mid": "var(--text-mid)",
                "text-dim": "var(--text-dim)",
                "text-muted": "var(--text-muted)",
                "cyan-500": "var(--cyan-500)",
                "cyan-glow": "var(--cyan-glow)",
                "purple-500": "var(--purple-500)",
                "purple-300": "var(--purple-300)",
                "blue-accent": "var(--blue-accent)",
                "purple-accent": "var(--purple-accent)",
                "accent-green": "var(--accent-green)",
                "accent-yellow": "var(--accent-yellow)",
                "accent-red": "var(--accent-red)",
                "border-color": "var(--border-color)",
            },
        },
    },
    plugins: [require("@tailwindcss/forms")],
};
```

- [ ] **Step 2: Update `explore/tailwind.input.css` — replace blue-accent references with cyan**

Replace the full content of `explore/tailwind.input.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer components {
    /* Button base */
    .btn-base {
        @apply inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bg-deep;
    }

    /* Button variants */
    .btn-primary {
        @apply btn-base bg-cyan-500 text-white hover:bg-cyan-glow focus:ring-cyan-500;
    }

    .btn-success {
        @apply btn-base bg-accent-green text-white hover:bg-green-700 focus:ring-accent-green;
    }

    .btn-warning {
        @apply btn-base bg-accent-yellow text-black hover:bg-yellow-500 focus:ring-accent-yellow;
    }

    .btn-secondary {
        @apply btn-base bg-purple-500 text-white hover:bg-purple-300 focus:ring-purple-500;
    }

    .btn-outline-secondary {
        @apply btn-base border border-border-color text-text-mid hover:bg-card-bg hover:text-text-high focus:ring-border-color;
    }

    .btn-outline-primary {
        @apply btn-base border border-cyan-500 text-cyan-500 hover:bg-cyan-500 hover:text-white focus:ring-cyan-500;
    }

    .btn-outline-danger {
        @apply btn-base border border-accent-red text-accent-red hover:bg-accent-red hover:text-white focus:ring-accent-red;
    }

    .btn-outline-warning {
        @apply btn-base border border-accent-yellow text-accent-yellow hover:bg-accent-yellow hover:text-black focus:ring-accent-yellow;
    }

    .btn-sm {
        @apply px-2 py-1 text-xs;
    }

    /* Form input */
    .form-input-dark {
        @apply w-full rounded border border-border-color bg-bg-deep text-text-high placeholder-text-mid px-3 py-2 text-sm focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 focus:outline-none;
    }

    /* Badge */
    .badge {
        @apply inline-flex items-center rounded px-2 py-0.5 text-xs font-medium;
    }

    /* Spinner */
    .spinner {
        @apply inline-block h-8 w-8 animate-spin rounded-full border-4 border-cyan-500 border-r-transparent;
    }
}
```

- [ ] **Step 3: Rebuild Tailwind CSS for explore**

```bash
cd /Users/Robert/Code/public/discogsography/.claude/worktrees/design-language/explore
npx tailwindcss -i tailwind.input.css -o static/css/tailwind.css --minify
cd ..
```

- [ ] **Step 4: Commit**

```bash
git add explore/tailwind.config.js explore/tailwind.input.css explore/static/css/tailwind.css
git commit -m "feat: update explore Tailwind config and components for Deep Space palette"
```

---

### Task 7: Update explore HTML — logo, favicons, fonts, remove theme toggle

**Files:**
- Modify: `explore/static/index.html:3-14` (head), `explore/static/index.html:436-465` (logo), `explore/static/index.html:523-527` (theme toggle)

- [ ] **Step 1: Update the `<head>` section (lines 3-14) — add Space Grotesk font, favicon links, OG meta**

Find the existing Google Fonts `<link>` tag (line 8) and replace it to include Space Grotesk. Add favicon and OG links after the existing `<link>` tags:

Replace the Google Fonts link (line 8 approximately):
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
```

Add after the Material Symbols link (line 9):
```html
<link rel="icon" type="image/x-icon" href="/static/brand/favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/static/brand/favicon-16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/static/brand/apple-touch-icon.png">
<link rel="manifest" href="/static/brand/site.webmanifest">
<meta property="og:image" content="/static/brand/og_image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
```

- [ ] **Step 2: Replace the inline logo (lines 436-465) with an `<img>` tag and tagline**

Replace the entire `#app-logo` contents (the four-quadrant circle div structure) with:

```html
<div id="app-logo">
    <img src="/static/brand/icon_dark.png" alt="Discogsography" style="width:32px;height:32px;border-radius:50%;">
</div>
```

Also find the existing title text next to the logo (look for "Discogsography" or "discogsography" text near the logo) and ensure it uses Space Grotesk:

```html
<span style="font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:0.95rem;letter-spacing:-0.03em;" class="t-high">discogsography</span>
<span style="font-family:'Space Grotesk',sans-serif;font-size:0.6rem;letter-spacing:0.02em;" class="t-muted ml-1">the choon network</span>
```

- [ ] **Step 3: Remove the theme toggle button (lines 523-527)**

Delete the theme toggle button element and its three icon children. Search for `id="theme-toggle"` or the `brightness_auto` / `light_mode` / `dark_mode` material icon spans.

Also remove the inline `<script>` block at the top of the `<body>` that applies the theme before first paint (search for `localStorage.getItem('theme')` in the early part of the HTML). The `<html>` element should have the `dark` class hardcoded:

```html
<html lang="en" class="dark">
```

- [ ] **Step 4: Update body background color**

Find the `<body>` tag and ensure it uses the void background:

```html
<body style="background:#060a12;" ...>
```

- [ ] **Step 5: Commit**

```bash
git add explore/static/index.html
git commit -m "feat: update explore HTML with new logo, favicons, and remove theme toggle"
```

---

### Task 8: Rebrand dashboard — inline CSS variables

**Files:**
- Modify: `dashboard/static/index.html:11-46` (inline CSS variables)

- [ ] **Step 1: Replace the inline `:root` and `.dark` CSS variable blocks (lines 11-46)**

The dashboard has its CSS variables in an inline `<style>` tag. Replace the `:root { ... }` block with the new palette (same values as explore Task 5, Step 1). Remove the `.dark { ... }` block entirely.

The inline `<style>` should contain only:

```css
:root {
    --bg-void: #060a12;
    --bg-deep: #0a1018;
    --card-bg: #0f1a2e;
    --inner-bg: #162540;
    --border-color: #1e3050;
    --inner-border: #1e3050;
    --bg-hover: #2a3d58;
    --text-high: #f0f4f8;
    --text-mid: #b0bec5;
    --text-dim: #7a8ba3;
    --text-muted: #4a5e78;
    --cyan-500: #00bcd4;
    --cyan-glow: #00e5ff;
    --purple-500: #7c4dff;
    --purple-300: #b388ff;
    --blue-accent: #00bcd4;
    --purple-accent: #7c4dff;
    --accent-green: #00e676;
    --accent-yellow: #ffab00;
    --accent-red: #ff5252;
    --card-shadow: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
    --scrollbar-thumb: #2a3d58;
    --gauge-track: #1e3050;
    --log-msg: #b0bec5;
    --row-border: rgba(255,255,255,0.05);
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: replace dashboard CSS variables with Deep Space palette"
```

---

### Task 9: Update dashboard HTML — logo, favicons, fonts, remove theme toggle (index.html)

**Files:**
- Modify: `dashboard/static/index.html:8` (fonts), `dashboard/static/index.html:101-134` (logo), `dashboard/static/index.html:155-159` (theme toggle)

- [ ] **Step 1: Update Google Fonts link (line 8) to include Space Grotesk**

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Add favicon and OG links in `<head>` (after line 9)**

```html
<link rel="icon" type="image/x-icon" href="/static/brand/favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/static/brand/favicon-16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/static/brand/apple-touch-icon.png">
<link rel="manifest" href="/static/brand/site.webmanifest">
<meta property="og:image" content="/static/brand/og_image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
```

- [ ] **Step 3: Replace inline logo (lines 101-134) with `<img>` tag**

Replace the `#app-logo` contents with:

```html
<div id="app-logo">
    <img src="/static/brand/icon_dark.png" alt="Discogsography" style="width:40px;height:40px;border-radius:50%;">
</div>
```

Update the adjacent title text to use Space Grotesk and add the tagline:

```html
<span style="font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:1.1rem;letter-spacing:-0.03em;" class="t-high">discogsography</span>
<span style="font-family:'Space Grotesk',sans-serif;font-size:0.65rem;letter-spacing:0.02em;" class="t-muted ml-1">the choon network</span>
```

- [ ] **Step 4: Remove theme toggle button (lines 155-159)**

Delete the theme toggle button. Hardcode `class="dark"` on the `<html>` element. Remove the early `<script>` that applies theme before first paint.

- [ ] **Step 5: Update body background**

```html
<body style="background:#060a12;">
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: update dashboard index with new logo, favicons, remove theme toggle"
```

---

### Task 10: Update dashboard admin.html — logo, favicons, remove theme toggle

**Files:**
- Modify: `dashboard/static/admin.html:233-261` (logo), `dashboard/static/admin.html:275-279` (theme toggle)

- [ ] **Step 1: Add Space Grotesk to Google Fonts link in `<head>`**

Same font link update as Task 9 Step 1.

- [ ] **Step 2: Add favicon and OG links in `<head>`**

Same links as Task 9 Step 2.

- [ ] **Step 3: Replace inline logo (lines 233-261) with `<img>` tag**

```html
<div aria-label="Logo">
    <img src="/static/brand/icon_dark.png" alt="Discogsography" style="width:40px;height:40px;border-radius:50%;">
</div>
```

- [ ] **Step 4: Remove theme toggle button (lines 275-279)**

Delete the theme toggle button. Hardcode `class="dark"` on the `<html>` element.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/admin.html
git commit -m "feat: update dashboard admin with new logo, favicons, remove theme toggle"
```

---

### Task 11: Remove theme toggle logic from dashboard JavaScript

**Files:**
- Modify: `dashboard/static/dashboard.js:26-74`
- Modify: `dashboard/static/admin.js:69-116`

- [ ] **Step 1: Remove `initializeThemeToggle()` from `dashboard/static/dashboard.js` (lines 26-74)**

Delete the entire `initializeThemeToggle()` method body. Replace with an empty method or remove entirely (depends on whether it's called from an init method). If it's called from an initialization function, replace the call with nothing or remove the call.

Also search for any references to `theme-toggle`, `theme`, `localStorage` related to theming in the file and remove them.

- [ ] **Step 2: Remove `initTheme()` from `dashboard/static/admin.js` (lines 69-116)**

Same approach: delete the theme toggle logic. Remove the method body and any calls to it.

- [ ] **Step 3: Verify no remaining theme references**

```bash
grep -n "theme-toggle\|initTheme\|initializeThemeToggle\|prefers-color-scheme\|light_mode\|dark_mode\|brightness_auto" dashboard/static/dashboard.js dashboard/static/admin.js
```

Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/dashboard.js dashboard/static/admin.js
git commit -m "feat: remove theme toggle logic from dashboard JavaScript"
```

---

### Task 12: Rebuild dashboard Tailwind CSS

**Files:**
- Modify: `dashboard/tailwind.config.js`
- Modify: `dashboard/static/dashboard.css` (or wherever Tailwind output goes)

- [ ] **Step 1: Update `dashboard/tailwind.config.js` — remove darkMode**

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ["./static/index.html", "./static/dashboard.js", "./static/admin.html", "./static/admin.js"],
    plugins: [require("@tailwindcss/forms")],
};
```

- [ ] **Step 2: Rebuild Tailwind CSS for dashboard**

```bash
cd /Users/Robert/Code/public/discogsography/.claude/worktrees/design-language/dashboard
npx tailwindcss -i tailwind.input.css -o static/dashboard.css --minify
cd ..
```

Check for the correct output filename — it may be `static/tailwind.css` or `static/dashboard.css`. Use `grep -r "tailwind\|dashboard.css" dashboard/static/index.html` to find the referenced stylesheet name.

- [ ] **Step 3: Commit**

```bash
git add dashboard/tailwind.config.js dashboard/static/dashboard.css
git commit -m "feat: rebuild dashboard Tailwind CSS without dark mode toggle"
```

---

### Task 13: Visual verification

**Files:** None (verification only)

- [ ] **Step 1: Start the explore dev server and verify in browser**

```bash
cd /Users/Robert/Code/public/discogsography/.claude/worktrees/design-language
# Start explore (check how it's typically started — might be `just` or direct python)
```

Open `http://localhost:8006` and verify:
- Logo shows as the Constellation Vinyl icon (not the old four-quadrant)
- "discogsography" wordmark in Space Grotesk with "the choon network" tagline
- Background is deep navy (#060a12), not white or gray
- Cyan accents on active tabs, links
- Purple accents on secondary elements
- No theme toggle button visible
- Favicon shows in browser tab
- Graph node colors updated (check the force-directed graph if data is available)

- [ ] **Step 2: Start the dashboard and verify**

Open `http://localhost:8003` and verify the same checklist.
Open the admin panel and verify the same checklist.

- [ ] **Step 3: Check generated brand assets visually**

```bash
open explore/static/brand/banner_dark.png
open explore/static/brand/banner_light.png
open explore/static/brand/square_dark.png
open explore/static/brand/icon_dark.png
open explore/static/brand/og_image.png
open explore/static/brand/design_showcase.png
open explore/static/brand/favicon-32.png
```

Verify each asset renders correctly with the Constellation Vinyl logo.

- [ ] **Step 4: Run existing tests to check for regressions**

```bash
just test-explore
just test-dashboard
just test-js
```

- [ ] **Step 5: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: visual verification adjustments"
```
