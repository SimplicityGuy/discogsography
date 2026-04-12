"""Brand asset generation script for Discogsography.

Generates the full "Constellation Vinyl" brand asset set:
- Icon mark (vinyl record + network graph star map)
- Banner (horizontal: icon + wordmark + tagline)
- Square (stacked: icon + wordmark)
- OG image (social sharing 1200x630)
- Design showcase (1600x900 reference)
- Favicons in all sizes
- site.webmanifest

Usage:
    uv run python scripts/generate_brand_assets.py          # Generate to explore/ and dashboard/
    uv run python scripts/generate_brand_assets.py --test   # Generate to /tmp/brand_test/
"""

import argparse
import json
import math
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ---------------------------------------------------------------------------
# Color constants — Deep Space + Purple palette
# ---------------------------------------------------------------------------
VOID = (6, 10, 18)  # #060a12
DEEP = (10, 16, 24)  # #0a1018
CARD = (15, 26, 46)  # #0f1a2e
ELEVATED = (22, 37, 64)  # #162540
BORDER = (30, 48, 80)  # #1e3050
CYAN_500 = (0, 188, 212)  # #00bcd4
CYAN_GLOW = (0, 229, 255)  # #00e5ff
PURPLE_500 = (124, 77, 255)  # #7c4dff
PURPLE_300 = (179, 136, 255)  # #b388ff
TEXT_HIGH = (240, 244, 248)  # #f0f4f8
TEXT_MUTED = (74, 94, 120)  # #4a5e78
LIGHT_BG = (240, 244, 248)  # #f0f4f8
LIGHT_TEXT = (13, 27, 42)  # #0d1b2a

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

_FONT_DIR = Path(__file__).parent.parent / "static" / "fonts"


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font by name from static/fonts/. Try variable font first, then static weights."""
    candidates = [
        _FONT_DIR / "SpaceGrotesk[wght].ttf",
        _FONT_DIR / "SpaceGrotesk-Bold.ttf",
        _FONT_DIR / "SpaceGrotesk-Regular.ttf",
    ]
    if "bold" in name.lower():
        candidates = [
            _FONT_DIR / "SpaceGrotesk-Bold.ttf",
            _FONT_DIR / "SpaceGrotesk[wght].ttf",
            _FONT_DIR / "SpaceGrotesk-Regular.ttf",
        ]
    elif "regular" in name.lower():
        candidates = [
            _FONT_DIR / "SpaceGrotesk-Regular.ttf",
            _FONT_DIR / "SpaceGrotesk[wght].ttf",
            _FONT_DIR / "SpaceGrotesk-Bold.ttf",
        ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Node layout — (angle_degrees, radius_fraction, color, size_fraction)
# Outer 5 nodes scattered like a star map, 3 inner nodes nearer center
# ---------------------------------------------------------------------------
OUTER_NODES = [
    (18, 0.72, CYAN_GLOW, 0.048),
    (90, 0.68, PURPLE_300, 0.042),
    (162, 0.74, CYAN_GLOW, 0.040),
    (234, 0.70, PURPLE_300, 0.044),
    (306, 0.66, CYAN_GLOW, 0.046),
]

INNER_NODES = [
    (45, 0.36, CYAN_500, 0.036),
    (165, 0.40, PURPLE_500, 0.032),
    (285, 0.38, CYAN_500, 0.034),
]

ALL_NODES = OUTER_NODES + INNER_NODES

# Edge pairs: (node_index_a, node_index_b, opacity_fraction)
EDGES = [
    # Pentagon outer ring
    (0, 1, 0.55),
    (1, 2, 0.55),
    (2, 3, 0.55),
    (3, 4, 0.55),
    (4, 0, 0.55),
    # Cross connections (lower opacity)
    (0, 2, 0.28),
    (1, 3, 0.28),
    (2, 4, 0.28),
    (3, 0, 0.28),
    (4, 1, 0.28),
    # Inner connections
    (5, 6, 0.45),
    (6, 7, 0.45),
    (7, 5, 0.45),
    # Outer-to-inner spokes
    (0, 5, 0.30),
    (1, 5, 0.25),
    (2, 6, 0.30),
    (3, 7, 0.30),
    (4, 7, 0.25),
]


def _node_xy(cx: float, cy: float, radius: float, angle_deg: float, radius_frac: float) -> tuple[float, float]:
    """Convert polar coords (angle, radius_fraction) to cartesian (x, y)."""
    angle_rad = math.radians(angle_deg - 90)  # 0° at top
    r = radius * radius_frac
    return cx + r * math.cos(angle_rad), cy + r * math.sin(angle_rad)


def _draw_glow_circle(
    canvas: Image.Image,
    cx: float,
    cy: float,
    radius: float,
    color: tuple[int, int, int],
    glow_radius: float,
    opacity: int = 255,
) -> None:
    """Draw a glowing circle by compositing a blurred halo + sharp core."""
    # Glow layer
    glow_size = int(glow_radius * 6) * 2 + 2
    glow_layer = Image.new("RGBA", (glow_size, glow_size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gc = glow_size // 2
    halo_r = int(glow_radius * 2.5)
    gd.ellipse(
        (gc - halo_r, gc - halo_r, gc + halo_r, gc + halo_r),
        fill=(*color, min(180, opacity)),
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=glow_radius * 1.8))
    px = int(cx - glow_size / 2)
    py = int(cy - glow_size / 2)
    canvas.alpha_composite(glow_layer, (px, py))

    # Sharp core
    core = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    r = int(radius)
    cd.ellipse(
        (int(cx) - r, int(cy) - r, int(cx) + r, int(cy) + r),
        fill=(*color, opacity),
    )
    canvas.alpha_composite(core)


def _draw_glow_line(
    canvas: Image.Image,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: tuple[int, int, int],
    width: int,
    opacity: int,
    blur_radius: float = 2.5,
) -> None:
    """Draw a luminous edge line with a blurred glow underneath."""
    # Glow pass
    glow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.line([(x0, y0), (x1, y1)], fill=(*color, min(120, opacity)), width=max(1, width * 3))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    canvas.alpha_composite(glow_layer)

    # Sharp line
    line_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(line_layer)
    ld.line([(x0, y0), (x1, y1)], fill=(*color, opacity), width=width)
    canvas.alpha_composite(line_layer)


# ---------------------------------------------------------------------------
# Core icon renderer
# ---------------------------------------------------------------------------


def render_icon(size: int = 1024, bg_color: tuple = VOID) -> Image.Image:
    """Render the Constellation Vinyl icon mark at `size` x `size` pixels."""
    img = Image.new("RGBA", (size, size), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    cx = size / 2
    cy = size / 2
    vinyl_r = size * 0.44

    # ---- Vinyl body ----
    body_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body_layer)
    bd.ellipse(
        (cx - vinyl_r, cy - vinyl_r, cx + vinyl_r, cy + vinyl_r),
        fill=(*DEEP, 255),
    )
    img.alpha_composite(body_layer)

    # ---- Vinyl border glow ----
    border_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bord = ImageDraw.Draw(border_layer)
    bord.ellipse(
        (cx - vinyl_r, cy - vinyl_r, cx + vinyl_r, cy + vinyl_r),
        outline=(*BORDER, 200),
        width=max(1, size // 128),
    )
    border_layer = border_layer.filter(ImageFilter.GaussianBlur(radius=size * 0.006))
    img.alpha_composite(border_layer)
    # Sharp border
    draw.ellipse(
        (cx - vinyl_r, cy - vinyl_r, cx + vinyl_r, cy + vinyl_r),
        outline=(*BORDER, 160),
        width=max(1, size // 256),
    )

    # ---- Groove rings ----
    groove_fracs = [0.82, 0.70, 0.58, 0.46, 0.34]
    for frac in groove_fracs:
        r = vinyl_r * frac
        groove_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gd = ImageDraw.Draw(groove_layer)
        gd.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            outline=(*BORDER, 60),
            width=max(1, size // 512),
        )
        img.alpha_composite(groove_layer)

    # ---- Network edges ----
    node_positions = [_node_xy(cx, cy, vinyl_r, ang, rfrac) for ang, rfrac, _col, _sz in ALL_NODES]

    for ia, ib, alpha_frac in EDGES:
        xa, ya = node_positions[ia]
        xb, yb = node_positions[ib]
        # Pick edge color as mix between node colors
        col_a = ALL_NODES[ia][2]
        col_b = ALL_NODES[ib][2]
        edge_color = (
            (col_a[0] + col_b[0]) // 2,
            (col_a[1] + col_b[1]) // 2,
            (col_a[2] + col_b[2]) // 2,
        )
        opacity = int(255 * alpha_frac)
        line_w = max(1, size // 512)
        _draw_glow_line(img, xa, ya, xb, yb, edge_color, line_w, opacity, blur_radius=size * 0.004)

    # ---- Nodes ----
    for ang, rfrac, color, size_frac in ALL_NODES:
        nx, ny = _node_xy(cx, cy, vinyl_r, ang, rfrac)
        node_r = vinyl_r * size_frac
        glow_r = node_r * 2.2
        _draw_glow_circle(img, nx, ny, node_r, color, glow_r, opacity=230)

    # ---- Center spindle (cyan-to-purple gradient) ----
    spindle_r = vinyl_r * 0.12
    spindle_steps = max(1, int(spindle_r * 2))
    for i in range(spindle_steps, 0, -1):
        t = i / spindle_steps
        # gradient: cyan at top, purple at bottom → radial: cyan edge → purple center
        r_col = int(CYAN_500[0] * t + PURPLE_500[0] * (1 - t))
        g_col = int(CYAN_500[1] * t + PURPLE_500[1] * (1 - t))
        b_col = int(CYAN_500[2] * t + PURPLE_500[2] * (1 - t))
        alpha = int(200 * t + 80 * (1 - t))
        ri = spindle_r * t
        draw.ellipse(
            (cx - ri, cy - ri, cx + ri, cy + ri),
            fill=(r_col, g_col, b_col, alpha),
        )

    # ---- Center hole ----
    hole_r = spindle_r * 0.30
    draw.ellipse(
        (cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r),
        fill=(*VOID, 255),
    )

    return img


# ---------------------------------------------------------------------------
# Banner renderer
# ---------------------------------------------------------------------------


def render_banner(
    width: int = 1600,
    height: int = 400,
    bg_color: tuple = VOID,
    text_color: tuple = TEXT_HIGH,
    tagline_color: tuple = TEXT_MUTED,
) -> Image.Image:
    """Render horizontal banner: icon left + wordmark + tagline."""
    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    padding = height // 8
    icon_size = height - padding * 2
    icon_img = render_icon(icon_size, bg_color)

    # Paste icon
    icon_x = padding
    icon_y = padding
    img.alpha_composite(icon_img, (icon_x, icon_y))

    # Text area
    text_x = icon_x + icon_size + padding
    wordmark_size = int(height * 0.28)
    tagline_size = int(height * 0.13)

    font_word = _load_font("bold", wordmark_size)
    font_tag = _load_font("regular", tagline_size)

    word = "discogsography"
    tag = "the choon network"

    # Measure
    wb = draw.textbbox((0, 0), word, font=font_word)
    tb = draw.textbbox((0, 0), tag, font=font_tag)
    w_h = wb[3] - wb[1]
    t_h = tb[3] - tb[1]
    total_text_h = w_h + padding // 2 + t_h
    text_y = (height - total_text_h) // 2

    # Wordmark with subtle cyan glow
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.text((text_x, text_y), word, font=font_word, fill=(*CYAN_GLOW, 40))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=8))
    img.alpha_composite(glow_layer)
    draw.text((text_x, text_y), word, font=font_word, fill=(*text_color, 255))

    # Tagline
    tag_y = text_y + w_h + padding // 2
    draw.text((text_x, tag_y), tag, font=font_tag, fill=(*tagline_color, 255))

    # Subtle bottom accent line (cyan)
    line_y = height - 3
    accent_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent_layer)
    ad.line([(0, line_y), (width, line_y)], fill=(*CYAN_500, 80), width=2)
    accent_layer = accent_layer.filter(ImageFilter.GaussianBlur(radius=3))
    img.alpha_composite(accent_layer)

    return img


# ---------------------------------------------------------------------------
# Square renderer
# ---------------------------------------------------------------------------


def render_square(
    size: int = 1024,
    bg_color: tuple = VOID,
    text_color: tuple = TEXT_HIGH,
) -> Image.Image:
    """Render stacked square: icon top + wordmark below."""
    img = Image.new("RGBA", (size, size), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    padding = size // 12
    icon_size = int(size * 0.58)
    icon_x = (size - icon_size) // 2
    icon_y = padding

    icon_img = render_icon(icon_size, bg_color)
    img.alpha_composite(icon_img, (icon_x, icon_y))

    # Wordmark
    text_y_start = icon_y + icon_size + padding // 2
    available_h = size - text_y_start - padding
    font_size = int(available_h * 0.40)
    font_word = _load_font("bold", font_size)
    font_tag = _load_font("regular", int(font_size * 0.52))

    word = "discogsography"
    tag = "the choon network"

    wb = draw.textbbox((0, 0), word, font=font_word)
    tb = draw.textbbox((0, 0), tag, font=font_tag)
    w_w = wb[2] - wb[0]
    w_h = wb[3] - wb[1]
    t_w = tb[2] - tb[0]

    word_x = (size - w_w) // 2
    word_y = text_y_start
    tag_x = (size - t_w) // 2
    tag_y = word_y + w_h + padding // 4

    # Wordmark glow
    glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.text((word_x, word_y), word, font=font_word, fill=(*CYAN_GLOW, 35))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=6))
    img.alpha_composite(glow_layer)

    draw.text((word_x, word_y), word, font=font_word, fill=(*text_color, 255))
    draw.text((tag_x, tag_y), tag, font=font_tag, fill=(*TEXT_MUTED, 255))

    return img


# ---------------------------------------------------------------------------
# OG image (1200x630)
# ---------------------------------------------------------------------------


def render_og_image() -> Image.Image:
    """Render 1200x630 Open Graph social sharing image."""
    w, h = 1200, 630
    img = Image.new("RGBA", (w, h), (*VOID, 255))
    draw = ImageDraw.Draw(img)

    # Subtle radial background gradient (simulated with circles)
    for step in range(20, 0, -1):
        t = step / 20
        r_bg = int(CARD[0] * t)
        g_bg = int(CARD[1] * t)
        b_bg = int(CARD[2] * t)
        alpha = int(80 * t)
        radius = int(h * 0.9 * t)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.ellipse(
            (w // 2 - radius, h // 2 - radius, w // 2 + radius, h // 2 + radius),
            fill=(r_bg, g_bg, b_bg, alpha),
        )
        img.alpha_composite(layer)

    # Icon on the left
    icon_h = int(h * 0.70)
    icon_img = render_icon(icon_h, VOID)
    icon_x = int(w * 0.05)
    icon_y = (h - icon_h) // 2
    img.alpha_composite(icon_img, (icon_x, icon_y))

    # Text block on right
    text_x = icon_x + icon_h + int(w * 0.04)
    font_title = _load_font("bold", int(h * 0.115))
    font_sub = _load_font("regular", int(h * 0.058))
    font_tag = _load_font("regular", int(h * 0.042))

    title = "discogsography"
    sub = "music knowledge graph"
    tag = "the choon network"

    tb = draw.textbbox((0, 0), title, font=font_title)
    sb = draw.textbbox((0, 0), sub, font=font_sub)
    gb = draw.textbbox((0, 0), tag, font=font_tag)

    t_h = tb[3] - tb[1]
    s_h = sb[3] - sb[1]
    g_h = gb[3] - gb[1]
    gap = int(h * 0.025)
    total = t_h + gap + s_h + gap * 2 + g_h
    ty = (h - total) // 2

    # Title glow
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text((text_x, ty), title, font=font_title, fill=(*CYAN_GLOW, 50))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=10))
    img.alpha_composite(glow)

    draw.text((text_x, ty), title, font=font_title, fill=(*TEXT_HIGH, 255))
    draw.text((text_x, ty + t_h + gap), sub, font=font_sub, fill=(*CYAN_500, 220))
    draw.text((text_x, ty + t_h + gap + s_h + gap * 2), tag, font=font_tag, fill=(*TEXT_MUTED, 255))

    # Bottom border accent
    accent = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent)
    ad.line([(0, h - 4), (w, h - 4)], fill=(*CYAN_GLOW, 100), width=4)
    accent = accent.filter(ImageFilter.GaussianBlur(radius=4))
    img.alpha_composite(accent)

    return img


# ---------------------------------------------------------------------------
# Design showcase (1600x900)
# ---------------------------------------------------------------------------


def render_design_showcase() -> Image.Image:
    """Render 1600x900 design reference sheet showing palette, typography, logo variants."""
    w, h = 1600, 900
    img = Image.new("RGBA", (w, h), (*VOID, 255))
    draw = ImageDraw.Draw(img)

    pad = 48

    # ---- Title ----
    font_h1 = _load_font("bold", 38)
    font_h2 = _load_font("bold", 24)
    font_small = _load_font("regular", 14)

    draw.text((pad, pad), "Discogsography — Deep Space + Purple Design Language", font=font_h1, fill=(*TEXT_HIGH, 255))

    # ---- Section: Color palette ----
    section_y = pad + 60
    draw.text((pad, section_y), "Color Palette", font=font_h2, fill=(*CYAN_GLOW, 220))

    palette = [
        ("Void", VOID, "#060a12"),
        ("Deep", DEEP, "#0a1018"),
        ("Card", CARD, "#0f1a2e"),
        ("Elevated", ELEVATED, "#162540"),
        ("Border", BORDER, "#1e3050"),
        ("Cyan 500", CYAN_500, "#00bcd4"),
        ("Cyan Glow", CYAN_GLOW, "#00e5ff"),
        ("Purple 500", PURPLE_500, "#7c4dff"),
        ("Purple 300", PURPLE_300, "#b388ff"),
        ("Text High", TEXT_HIGH, "#f0f4f8"),
        ("Text Muted", TEXT_MUTED, "#4a5e78"),
    ]

    swatch_w = 100
    swatch_h = 60
    swatch_gap = 12
    swatch_y = section_y + 36
    for i, (name, color, hex_code) in enumerate(palette):
        sx = pad + i * (swatch_w + swatch_gap)
        # Swatch box
        draw.rounded_rectangle(
            (sx, swatch_y, sx + swatch_w, swatch_y + swatch_h),
            radius=6,
            fill=(*color, 255),
            outline=(*BORDER, 180),
            width=1,
        )
        # Color name
        draw.text((sx + 4, swatch_y + swatch_h + 4), name, font=font_small, fill=(*TEXT_HIGH, 200))
        draw.text((sx + 4, swatch_y + swatch_h + 20), hex_code, font=font_small, fill=(*TEXT_MUTED, 200))

    # ---- Section: Typography ----
    typo_y = swatch_y + swatch_h + 58
    draw.text((pad, typo_y), "Typography — Space Grotesk", font=font_h2, fill=(*CYAN_GLOW, 220))

    font_display = _load_font("bold", 52)
    font_heading = _load_font("bold", 32)
    font_body2 = _load_font("regular", 20)

    ty = typo_y + 36
    draw.text((pad, ty), "discogsography", font=font_display, fill=(*TEXT_HIGH, 255))
    ty += 64
    draw.text((pad, ty), "The Choon Network", font=font_heading, fill=(*CYAN_500, 220))
    ty += 40
    draw.text((pad, ty), "Music knowledge graph powered by Discogs data → Neo4j & PostgreSQL", font=font_body2, fill=(*TEXT_MUTED, 200))

    # ---- Section: Logo variants ----
    logo_y = typo_y + 36 + 64 + 40 + 32 + 32
    draw.text((pad, logo_y), "Logo Variants", font=font_h2, fill=(*CYAN_GLOW, 220))

    variant_size = 180
    variants = [
        ("Icon Dark", render_icon(variant_size, VOID)),
        ("Icon Light", render_icon(variant_size, LIGHT_BG)),
    ]
    vx = pad
    vy = logo_y + 36
    for label, vimg in variants:
        # Background box
        draw.rounded_rectangle(
            (vx - 8, vy - 8, vx + variant_size + 8, vy + variant_size + 8),
            radius=10,
            fill=(*CARD, 255),
            outline=(*BORDER, 180),
            width=1,
        )
        img.alpha_composite(vimg, (vx, vy))
        draw.text((vx, vy + variant_size + 12), label, font=font_small, fill=(*TEXT_MUTED, 200))
        vx += variant_size + 48

    # Banner preview (right side)
    banner_x = pad + variant_size * 2 + 96 + pad
    banner_w = w - banner_x - pad
    banner_h = 100
    banner_preview = render_banner(banner_w, banner_h, VOID, TEXT_HIGH, TEXT_MUTED)
    img.alpha_composite(banner_preview, (banner_x, vy))
    draw.text((banner_x, vy + banner_h + 12), "Banner Dark", font=font_small, fill=(*TEXT_MUTED, 200))

    banner_light = render_banner(banner_w, banner_h, LIGHT_BG, LIGHT_TEXT, TEXT_MUTED)
    img.alpha_composite(banner_light, (banner_x, vy + banner_h + 40))
    draw.text((banner_x, vy + banner_h * 2 + 52), "Banner Light", font=font_small, fill=(*TEXT_MUTED, 200))

    # ---- Bottom accent ----
    accent = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent)
    ad.line([(0, h - 3), (w, h - 3)], fill=(*CYAN_GLOW, 100), width=3)
    accent = accent.filter(ImageFilter.GaussianBlur(radius=3))
    img.alpha_composite(accent)

    return img


# ---------------------------------------------------------------------------
# Favicon generation
# ---------------------------------------------------------------------------


def generate_favicons(icon_img: Image.Image, output_dir: Path) -> None:
    """Generate favicon-{16,32,48,64,128,192,256,512}.png, apple-touch-icon.png, favicon.ico."""
    sizes = [16, 32, 48, 64, 128, 192, 256, 512]
    ico_sizes = []

    for size in sizes:
        resized = icon_img.resize((size, size), Image.Resampling.LANCZOS)
        out_path = output_dir / f"favicon-{size}.png"
        resized.convert("RGBA").save(str(out_path), "PNG")
        if size in (16, 32, 48):
            ico_sizes.append(resized.convert("RGBA"))

    # Apple touch icon — 180x180, no transparency, VOID background
    apple_bg = Image.new("RGBA", (180, 180), (*VOID, 255))
    apple_icon = icon_img.resize((180, 180), Image.Resampling.LANCZOS).convert("RGBA")
    apple_bg.alpha_composite(apple_icon)
    apple_bg.convert("RGB").save(str(output_dir / "apple-touch-icon.png"), "PNG")

    # favicon.ico — multi-size (16 + 32 + 48)
    ico_path = output_dir / "favicon.ico"
    base_ico = ico_sizes[1]  # 32px as base
    base_ico.save(
        str(ico_path),
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=ico_sizes,
    )


# ---------------------------------------------------------------------------
# Web manifest
# ---------------------------------------------------------------------------


def write_webmanifest(output_dir: Path) -> None:
    """Write site.webmanifest to output_dir."""
    manifest = {
        "name": "Discogsography",
        "short_name": "Discogsography",
        "description": "The Choon Network — music knowledge graph",
        "icons": [
            {"src": "/static/brand/favicon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/brand/favicon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
        "theme_color": "#060a12",
        "background_color": "#060a12",
        "display": "standalone",
    }
    manifest_path = output_dir / "site.webmanifest"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main export pipeline
# ---------------------------------------------------------------------------


def generate_all(output_dirs: list[Path]) -> None:
    """Render all brand assets and write to each output directory."""
    print("Rendering brand assets...")

    print("  Rendering icon variants...")
    icon_dark = render_icon(1024, VOID)
    icon_light = render_icon(1024, LIGHT_BG)

    print("  Rendering banner variants...")
    banner_dark = render_banner(1600, 400, VOID, TEXT_HIGH, TEXT_MUTED)
    banner_light = render_banner(1600, 400, LIGHT_BG, LIGHT_TEXT, TEXT_MUTED)

    print("  Rendering square variants...")
    square_dark = render_square(1024, VOID, TEXT_HIGH)
    square_light = render_square(1024, LIGHT_BG, LIGHT_TEXT)

    print("  Rendering OG image...")
    og_image = render_og_image()

    print("  Rendering design showcase...")
    showcase = render_design_showcase()

    for output_dir in output_dirs:
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Writing to {output_dir}...")

        icon_dark.save(str(output_dir / "icon_dark.png"), "PNG")
        icon_light.save(str(output_dir / "icon_light.png"), "PNG")
        banner_dark.save(str(output_dir / "banner_dark.png"), "PNG")
        banner_light.save(str(output_dir / "banner_light.png"), "PNG")
        square_dark.save(str(output_dir / "square_dark.png"), "PNG")
        square_light.save(str(output_dir / "square_light.png"), "PNG")
        og_image.save(str(output_dir / "og_image.png"), "PNG")
        showcase.save(str(output_dir / "design_showcase.png"), "PNG")

        generate_favicons(icon_dark, output_dir)
        write_webmanifest(output_dir)

    print("Done.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Discogsography brand assets")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Generate test renders to a temp directory instead of project directories",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent

    if args.test:
        test_dir = Path(tempfile.mkdtemp(prefix="brand_test_"))
        dirs = [test_dir]
        print(f"Test mode: generating to {test_dir}")
    else:
        dirs = [
            repo_root / "explore" / "static" / "brand",
            repo_root / "dashboard" / "static" / "brand",
        ]

    generate_all(dirs)

    for d in dirs:
        files = sorted(d.glob("*"))
        print(f"\n{d}:")
        for f in files:
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name:<40} {size_kb:>8.1f} KB")
