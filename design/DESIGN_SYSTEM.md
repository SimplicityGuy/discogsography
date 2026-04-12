# Design System

**discogsography** — the choon network

> Deep Space + Purple — dark-mode-forward data observatory aesthetic

---

## Contents

1. [Brand Identity](#brand-identity)
2. [Color System](#color-system)
3. [Typography](#typography)
4. [Spacing](#spacing)
5. [Border Radius](#border-radius)
6. [Shadows & Glows](#shadows--glows)
7. [Component Patterns](#component-patterns)
8. [Accent Usage Guide](#accent-usage-guide)
9. [File Manifest](#file-manifest)
10. [CSS Custom Properties](#css-custom-properties)

---

## Brand Identity

| Property | Value |
|----------|-------|
| Name | discogsography (lowercase in wordmark) |
| Tagline | the choon network |
| Direction | Deep Space + Purple |
| Aesthetic | Dark-mode-forward data observatory |
| Logo concept | Constellation Vinyl — vinyl record with scattered network graph nodes |

---

## Color System

Single dark theme. No light mode.

### Background Scale

| Token | Hex | Name | Usage |
|-------|-----|------|-------|
| `--bg-void` | `#060a12` | Void | Page/body background |
| `--bg-deep` | `#0a1018` | Deep | Section backgrounds |
| `--card-bg` | `#0f1a2e` | Card | Card/panel backgrounds |
| `--inner-bg` | `#162540` | Elevated | Nested/inner containers |
| `--border-color` | `#1e3050` | Border | All borders and dividers |
| `--bg-hover` | `#2a3d58` | Hover | Hover states |

### Cyan — Primary Accent

| Token | Hex | Usage |
|-------|-----|-------|
| `--cyan-900` | `#004d5a` | Subtle backgrounds |
| `--cyan-700` | `#00838f` | Pressed states |
| `--cyan-500` | `#00bcd4` | Primary buttons, active tabs, links |
| `--cyan-glow` | `#00e5ff` | Highlighted text, focus rings, glows |
| `--cyan-bright` | `#80f0ff` | Sparkle accents (sparingly) |

### Purple — Secondary Accent

| Token | Hex | Usage |
|-------|-----|-------|
| `--purple-900` | `#311b92` | Subtle backgrounds |
| `--purple-700` | `#5e35b1` | Pressed states |
| `--purple-500` | `#7c4dff` | Secondary buttons, badges, chart #2 |
| `--purple-300` | `#b388ff` | Purple text, hover states |
| `--purple-bright` | `#d4b8ff` | Light accents (sparingly) |

### Text Scale

| Token | Hex | Usage |
|-------|-----|-------|
| `--text-high` | `#f0f4f8` | Headings, primary text |
| `--text-mid` | `#b0bec5` | Body text |
| `--text-dim` | `#7a8ba3` | Secondary/caption text |
| `--text-muted` | `#4a5e78` | Labels, placeholders |

### Semantic Status

| Token | Hex | Usage |
|-------|-----|-------|
| `--accent-green` | `#00e676` | Healthy, connected, ok |
| `--accent-red` | `#ff5252` | Failed, error, danger |
| `--accent-yellow` | `#ffab00` | Warning, attention |

### Status Badge Backgrounds

12% opacity background tints with 20% opacity borders.

| State | Background | Border |
|-------|-----------|--------|
| Healthy | `rgba(0, 230, 118, 0.12)` | `rgba(0, 230, 118, 0.2)` |
| Error | `rgba(255, 82, 82, 0.12)` | `rgba(255, 82, 82, 0.2)` |
| Warning | `rgba(255, 171, 0, 0.12)` | `rgba(255, 171, 0, 0.2)` |
| Running | `rgba(0, 188, 212, 0.12)` | `rgba(0, 188, 212, 0.2)` |
| Pending | `rgba(124, 77, 255, 0.12)` | `rgba(124, 77, 255, 0.2)` |
| Idle | `rgba(74, 94, 120, 0.12)` | `rgba(74, 94, 120, 0.15)` |

### Graph Node Colors

| Node | Hex | Variable |
|------|-----|----------|
| Artist | `#00e676` | `--node-artist` |
| Release | `#ff5c8a` | `--node-release` |
| Label | `#78909c` | `--node-label` |
| Genre | `#ffd54f` | `--node-genre` |
| Category | `#40c4ff` | `--node-category` |

### UI Tokens

| Token | Value |
|-------|-------|
| `--card-shadow` | `0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)` |
| `--scrollbar-thumb` | `#2a3d58` |
| `--glass-bg` | `rgba(15, 26, 46, 0.9)` |
| `--overlay-bg` | `rgba(0, 0, 0, 0.85)` |
| `--gauge-track` | `#1e3050` |
| `--row-border` | `rgba(255, 255, 255, 0.05)` |

---

## Typography

Three-font system. All fonts loaded from Google Fonts.

### Space Grotesk — Brand / Wordmark

Weights loaded: 400, 500, 600, 700

| Usage | Weight | Size | Tracking |
|-------|--------|------|----------|
| Wordmark | 700 | 2rem | -0.03em |
| Tagline | 400 | 0.9rem | 0.02em |

### Inter — UI

Weights loaded: 300, 400, 500, 600, 700

| Level | Weight | Size | Tracking |
|-------|--------|------|----------|
| Page Title | 700 | 1.5rem | default |
| Section Head | 600 | 1.125rem | default |
| Card Title | 500 | 0.875rem | default |
| Body | 400 | 0.8125rem | default |
| Caption | 400 | 0.75rem | default |
| Label | 600 | 0.65rem | 0.08em (uppercase) |

### JetBrains Mono — Data / Monospace

Weights loaded: 400, 500

| Usage | Weight | Size | Color |
|-------|--------|------|-------|
| Metrics | 500 | 0.8125rem | `--cyan-glow` |
| Queue names | 400 | 0.75rem | `--text-dim` |
| Timestamps | 400 | 0.7rem | `--text-muted` |

### Material Symbols Outlined — Icons

Variable weight 100–700, loaded from Google Fonts.

---

## Spacing

4px base grid.

| Token | Value |
|-------|-------|
| `xs` | 4px |
| `sm` | 8px |
| `md` | 12px |
| `base` | 16px |
| `lg` | 24px |
| `xl` | 32px |
| `2xl` | 48px |

---

## Border Radius

| Element | Radius |
|---------|--------|
| Small buttons | 6px |
| Buttons/inputs | 8px |
| Cards | 12px |
| Sections | 14px |
| Badges | 20px |
| Circles | 50% |

---

## Shadows & Glows

### Elevation

| Level | Shadow | Usage |
|-------|--------|-------|
| `sm` | `0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)` | Card default |
| `md` | `0 4px 6px -1px rgba(0,0,0,0.3), 0 2px 4px -1px rgba(0,0,0,0.2)` | Elevated |
| `lg` | `0 10px 25px -3px rgba(0,0,0,0.4), 0 4px 10px -2px rgba(0,0,0,0.3)` | Dropdowns |

### Glow Effects

| Name | Value |
|------|-------|
| Cyan glow | `0 0 20px rgba(0,188,212,0.2), 0 0 40px rgba(0,188,212,0.1)` |
| Purple glow | `0 0 20px rgba(124,77,255,0.2), 0 0 40px rgba(124,77,255,0.1)` |

---

## Component Patterns

### Buttons

| Variant | Background | Text | Border |
|---------|-----------|------|--------|
| Primary | `--cyan-500` | `--bg-void` | none |
| Secondary | `rgba(124,77,255,0.2)` | `--purple-300` | `1px solid rgba(124,77,255,0.3)` |
| Ghost | transparent | `--text-dim` | `1px solid --border-color` |
| Danger | `rgba(255,82,82,0.15)` | `--accent-red` | `1px solid rgba(255,82,82,0.2)` |

Padding: `8px 18px` (standard), `5px 12px` (small). Radius: `8px` (standard), `6px` (small).

### Status Badges

Pill shape (radius 20px). 12% opacity background tint, 20% opacity border, 7px dot indicator. See [Status Badge Backgrounds](#status-badge-backgrounds).

### Cards

Background `--card-bg`, border `1px solid --border-color`, radius `12px`, shadow `sm`.

### Focus States

```
outline: 2px solid var(--cyan-500);
box-shadow: 0 0 0 3px rgba(0, 188, 212, 0.2);
```

### Active Tab

```
color: var(--cyan-glow);
border-bottom: 2px solid var(--cyan-glow);
background: rgba(0, 188, 212, 0.08);
```

---

## Accent Usage Guide

**Cyan (primary):** Active nav tabs, primary buttons, links, focus rings, logo glows, "running" status

**Purple (secondary):** Secondary buttons, badges, chart accent #2, progress indicators, graph edge highlights, "pending" status

---

## File Manifest

### Brand Assets

Generated by `scripts/generate_brand_assets.py`. Output to `explore/static/brand/` and `dashboard/static/brand/`.

| File | Description |
|------|-------------|
| `banner_dark.png` | Horizontal logo, dark bg (1600x400) |
| `banner_light.png` | Horizontal logo, light bg (1600x400) |
| `square_dark.png` | Stacked logo, dark bg (1024x1024) |
| `square_light.png` | Stacked logo, light bg (1024x1024) |
| `icon_dark.png` | Icon mark, dark bg (1024x1024) |
| `icon_light.png` | Icon mark, light bg (1024x1024) |
| `og_image.png` | Social sharing image (1200x630) |
| `design_showcase.png` | Design reference image (1600x900) |
| `favicon.ico` | Multi-size ICO (16+32+48) |
| `favicon-{16..512}.png` | Individual favicon PNGs |
| `apple-touch-icon.png` | iOS icon (180x180) |
| `site.webmanifest` | PWA manifest |

### Source Files

| File | Description |
|------|-------------|
| `scripts/generate_brand_assets.py` | Python/Pillow asset generator |
| `static/fonts/SpaceGrotesk-Bold.ttf` | Wordmark font (bold) |
| `static/fonts/SpaceGrotesk-Regular.ttf` | Tagline font (regular) |
| `static/fonts/SpaceGrotesk[wght].ttf` | Variable weight font |

### Design Documentation

| File | Description |
|------|-------------|
| `design/DESIGN_SYSTEM.md` | This file |
| `design/showcase.html` | Interactive design showcase |
| `docs/superpowers/specs/2026-04-11-design-language-rebrand-design.md` | Design specification |

---

## CSS Custom Properties

Copy-pasteable `:root` block for all design tokens.

```css
:root {
  /* ── Background Scale ───────────────────────────────── */
  --bg-void:        #060a12;
  --bg-deep:        #0a1018;
  --card-bg:        #0f1a2e;
  --inner-bg:       #162540;
  --border-color:   #1e3050;
  --bg-hover:       #2a3d58;

  /* ── Cyan — Primary Accent ──────────────────────────── */
  --cyan-900:       #004d5a;
  --cyan-700:       #00838f;
  --cyan-500:       #00bcd4;
  --cyan-glow:      #00e5ff;
  --cyan-bright:    #80f0ff;

  /* ── Purple — Secondary Accent ──────────────────────── */
  --purple-900:     #311b92;
  --purple-700:     #5e35b1;
  --purple-500:     #7c4dff;
  --purple-300:     #b388ff;
  --purple-bright:  #d4b8ff;

  /* ── Text Scale ─────────────────────────────────────── */
  --text-high:      #f0f4f8;
  --text-mid:       #b0bec5;
  --text-dim:       #7a8ba3;
  --text-muted:     #4a5e78;

  /* ── Semantic Status ────────────────────────────────── */
  --accent-green:   #00e676;
  --accent-red:     #ff5252;
  --accent-yellow:  #ffab00;

  /* ── Graph Node Colors ──────────────────────────────── */
  --node-artist:    #00e676;
  --node-release:   #ff5c8a;
  --node-label:     #78909c;
  --node-genre:     #ffd54f;
  --node-category:  #40c4ff;

  /* ── UI Tokens ──────────────────────────────────────── */
  --card-shadow:    0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
  --scrollbar-thumb: #2a3d58;
  --glass-bg:       rgba(15, 26, 46, 0.9);
  --overlay-bg:     rgba(0, 0, 0, 0.85);
  --gauge-track:    #1e3050;
  --row-border:     rgba(255, 255, 255, 0.05);

  /* ── Elevation Shadows ──────────────────────────────── */
  --shadow-sm:      0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
  --shadow-md:      0 4px 6px -1px rgba(0,0,0,0.3), 0 2px 4px -1px rgba(0,0,0,0.2);
  --shadow-lg:      0 10px 25px -3px rgba(0,0,0,0.4), 0 4px 10px -2px rgba(0,0,0,0.3);

  /* ── Glow Effects ───────────────────────────────────── */
  --glow-cyan:      0 0 20px rgba(0,188,212,0.2), 0 0 40px rgba(0,188,212,0.1);
  --glow-purple:    0 0 20px rgba(124,77,255,0.2), 0 0 40px rgba(124,77,255,0.1);

  /* ── Border Radius ──────────────────────────────────── */
  --radius-sm:      6px;
  --radius-md:      8px;
  --radius-card:    12px;
  --radius-section: 14px;
  --radius-badge:   20px;
  --radius-circle:  50%;

  /* ── Spacing (4px base) ─────────────────────────────── */
  --space-xs:    4px;
  --space-sm:    8px;
  --space-md:    12px;
  --space-base:  16px;
  --space-lg:    24px;
  --space-xl:    32px;
  --space-2xl:   48px;
}
```
