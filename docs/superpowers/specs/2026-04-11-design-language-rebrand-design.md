# Discogsography Design Language & Rebrand

**Date:** 2026-04-11
**Status:** Approved
**Scope:** Full visual rebrand of explore and dashboard services, logo generation, favicon set, design token system

## Overview

Replace the existing blue/purple accent system and four-quadrant programmatic logo with a cohesive "Deep Space + Purple" design language across both the explore and dashboard services. Generate all logo and favicon assets programmatically using Python/Pillow. The design is dark-mode-forward with cyan as the primary accent and purple as the secondary.

## Design Direction: Deep Space + Purple

Dark-mode-forward aesthetic. Navy backgrounds throughout — the UI evokes a data observatory. High-contrast cyan and purple accents provide energy and visual hierarchy. The vinyl record floats in space; the graph network glows.

---

## 1. Color System

### 1.1 Background Scale

| Token            | Hex       | Name     | Usage                        |
|------------------|-----------|----------|------------------------------|
| `--bg-void`      | `#060a12` | Void     | Page/body background         |
| `--bg-deep`      | `#0a1018` | Deep     | Section backgrounds          |
| `--card-bg`      | `#0f1a2e` | Card     | Card/panel backgrounds       |
| `--inner-bg`     | `#162540` | Elevated | Nested/inner containers      |
| `--border-color` | `#1e3050` | Border   | All borders and dividers     |
| `--bg-hover`     | `#2a3d58` | Hover    | Hover states on backgrounds  |

### 1.2 Cyan — Primary Accent

| Token          | Hex       | Name      | Usage                                  |
|----------------|-----------|-----------|----------------------------------------|
| `--cyan-900`   | `#004d5a` | 900       | Darkest cyan (subtle backgrounds)      |
| `--cyan-700`   | `#00838f` | 700       | Dark cyan (pressed states)             |
| `--cyan-500`   | `#00bcd4` | 500 base  | Primary buttons, active tabs, links    |
| `--cyan-glow`  | `#00e5ff` | Glow      | Highlighted text, focus rings, glows   |
| `--cyan-bright`| `#80f0ff` | Bright    | Sparkle accents (sparingly)            |

### 1.3 Purple — Secondary Accent

| Token            | Hex       | Name      | Usage                                  |
|------------------|-----------|-----------|----------------------------------------|
| `--purple-900`   | `#311b92` | 900       | Darkest purple (subtle backgrounds)    |
| `--purple-700`   | `#5e35b1` | 700       | Dark purple (pressed states)           |
| `--purple-500`   | `#7c4dff` | 500 base  | Secondary buttons, badges, chart #2    |
| `--purple-300`   | `#b388ff` | 300       | Purple text, hover states              |
| `--purple-bright`| `#d4b8ff` | Bright    | Light purple accents (sparingly)       |

### 1.4 Text Scale

| Token         | Hex       | Name  | Usage                        |
|---------------|-----------|-------|------------------------------|
| `--text-high` | `#f0f4f8` | High  | Headings, primary text       |
| `--text-mid`  | `#b0bec5` | Mid   | Body text                    |
| `--text-dim`  | `#7a8ba3` | Dim   | Secondary/caption text       |
| `--text-muted`| `#4a5e78` | Muted | Labels, placeholders, hints  |

### 1.5 Semantic / Status Colors

| Token            | Hex       | Name    | Usage                     |
|------------------|-----------|---------|---------------------------|
| `--accent-green` | `#00e676` | Success | Healthy, connected, ok    |
| `--accent-red`   | `#ff5252` | Error   | Failed, error, danger     |
| `--accent-yellow`| `#ffab00` | Warning | Warning, slow, attention  |

### 1.6 Accent Usage Guide

**Cyan (primary):**
- Active nav tab / selected state
- Primary action buttons
- Links and interactive elements
- Status: healthy / connected
- Focus rings
- Logo glow effects

**Purple (secondary):**
- Secondary buttons / alternate actions
- Badges and tags
- Chart/data accent #2
- Hover states on secondary elements
- Progress indicators
- Graph edge highlights
- Status: pending

---

## 2. Typography

Three-font system: Space Grotesk for brand, Inter for UI, JetBrains Mono for data.

### 2.1 Brand / Wordmark

| Element  | Font           | Weight | Size   | Tracking | Color       |
|----------|----------------|--------|--------|----------|-------------|
| Wordmark | Space Grotesk  | 700    | 2rem   | -0.03em  | --text-high |
| Tagline  | Space Grotesk  | 400    | 0.9rem | 0.02em   | --text-muted|

- Wordmark text: `discogsography` (all lowercase)
- Tagline text: `the choon network` (all lowercase)
- The tagline appears in the UI — in navbar headers alongside the logo

### 2.2 UI — Inter

| Level         | Weight | Size      | Tracking | Usage              |
|---------------|--------|-----------|-----------|--------------------|
| Page Title    | 700    | 1.5rem    | default   | Top-level headings |
| Section Head  | 600    | 1.125rem  | default   | Section headings   |
| Card Title    | 500    | 0.875rem  | default   | Card/panel titles  |
| Body          | 400    | 0.8125rem | default   | Primary body text  |
| Caption       | 400    | 0.75rem   | default   | Secondary text     |
| Label         | 600    | 0.65rem   | 0.08em    | Uppercase labels   |

### 2.3 Data / Monospace — JetBrains Mono

| Usage       | Weight | Size      | Color      |
|-------------|--------|-----------|------------|
| Metrics     | 500    | 0.8125rem | --cyan-glow|
| Queue names | 400    | 0.75rem   | --text-dim |
| Timestamps  | 400    | 0.7rem    | --text-muted|

### 2.4 Font Loading

All fonts loaded from Google Fonts:
- `Inter` weights: 300, 400, 500, 600, 700
- `Space Grotesk` weights: 400, 500, 600, 700
- `JetBrains Mono` weights: 400, 500
- `Material Symbols Outlined` (variable weight 100-700) — icon system unchanged

---

## 3. Logo & Brand Assets

### 3.1 Logo Concept: Constellation Vinyl

A vinyl record with concentric groove rings. Network graph nodes are scattered organically across the surface like a star map, connected by thin luminous lines in cyan and purple. The center spindle features a cyan-to-purple radial gradient with a dark center hole. Glow halos around nodes enhance the "deep space" aesthetic.

Key visual elements:
- **Vinyl body**: Dark circle (#0a1018) with #1e3050 stroke
- **Grooves**: 4-5 concentric rings in #162540
- **Outer nodes**: 5 nodes (mix of cyan #00e5ff and purple #b388ff), radius ~5-6px with glow halos at 15% opacity
- **Inner nodes**: 3 smaller nodes (cyan #00bcd4 and purple #7c4dff), radius ~3px
- **Network edges**: Lines connecting nodes, cyan and purple at 30-50% opacity
- **Cross connections**: Fainter diagonal lines at 20-25% opacity
- **Center spindle**: Outer ring (#0f1a2e with #1e3050 stroke), inner gradient (radial, #00e5ff → #7c4dff), center hole (#060a12)

### 3.2 Logo Variants

Each variant is generated in two background modes:
- **Dark** (`_dark.png`): Dark background (#060a12) — used in-app and as primary brand
- **Light** (`_light.png`): Light background (#f0f4f8) — used in README, external sharing, print

**Banner (horizontal):**
- Logo mark (left) + wordmark text + tagline (right)
- Files: `banner_dark.png`, `banner_light.png`
- Export sizes: 800x200px, 1600x400px (@2x)
- Wordmark: Space Grotesk 700, -0.03em tracking
- Tagline: Space Grotesk 400, 0.02em tracking, --text-muted color
- Light variant: wordmark text in #0d1b2a, tagline in #5a7088

**Square (stacked):**
- Logo mark (top) + wordmark text (below)
- Files: `square_dark.png`, `square_light.png`
- Export sizes: 512x512px, 1024x1024px (@2x)

**Icon mark (favicon source):**
- Logo mark only — no text
- Files: `icon_dark.png`, `icon_light.png`
- Source size: 1024x1024px
- Nodes and edges scaled up proportionally for small-size clarity
- Used as the master source for all favicon derivatives

**Open Graph image:**
- Social sharing preview (Slack, Discord, Twitter, etc.)
- File: `og_image.png`
- Size: 1200x630px (standard OG ratio)
- Content: Logo mark + wordmark + tagline on dark background
- Integrated via `<meta property="og:image">` in HTML

**Design showcase:**
- Visual reference showing the full design language in one image
- File: `design_showcase.png`
- Content: Color palette, typography samples, logo variants, component examples
- Used in README and documentation only (not served by the app)

### 3.3 Generation Approach

All logo assets generated programmatically using Python with Pillow (PIL). The generation script:
- Renders the vinyl body, grooves, network edges, nodes, glow effects, and spindle
- Composites the wordmark text using Space Grotesk font
- Exports all variants at required sizes
- Outputs to a shared `static/brand/` directory

---

## 4. Favicon Set

Essential set with web manifest for "add to home screen" support.

### 4.1 Generated Files

| File                  | Size(s)       | Format | Usage                          |
|-----------------------|---------------|--------|--------------------------------|
| `favicon.ico`         | 16+32+48      | ICO    | Browser tab (legacy multi-size)|
| `favicon-16.png`      | 16x16         | PNG    | Small favicon                  |
| `favicon-32.png`      | 32x32         | PNG    | Standard favicon               |
| `favicon-48.png`      | 48x48         | PNG    | Large favicon                  |
| `favicon-64.png`      | 64x64         | PNG    | Extra-large favicon            |
| `favicon-128.png`     | 128x128       | PNG    | High-DPI favicon               |
| `favicon-256.png`     | 256x256       | PNG    | Very high-DPI favicon          |
| `favicon-512.png`     | 512x512       | PNG    | Maximum favicon / manifest     |
| `apple-touch-icon.png`| 180x180       | PNG    | iOS home screen                |
| `site.webmanifest`    | —             | JSON   | PWA manifest                   |

### 4.2 HTML Integration

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

### 4.3 Web Manifest

```json
{
  "name": "Discogsography",
  "short_name": "Discogsography",
  "description": "The Choon Network — music knowledge graph",
  "icons": [
    { "src": "/static/brand/favicon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/static/brand/favicon-512.png", "sizes": "512x512", "type": "image/png" }
  ],
  "theme_color": "#060a12",
  "background_color": "#060a12",
  "display": "standalone"
}
```

---

## 5. Components

### 5.1 Buttons

| Variant   | Background                              | Text         | Border                              |
|-----------|-----------------------------------------|--------------|--------------------------------------|
| Primary   | `--cyan-500` (#00bcd4)                  | `--bg-void`  | none                                 |
| Secondary | `rgba(124,77,255,0.2)`                  | `--purple-300` | `1px solid rgba(124,77,255,0.3)` |
| Ghost     | `transparent`                           | `--text-dim` | `1px solid --border-color`           |
| Danger    | `rgba(255,82,82,0.15)`                  | `--accent-red` | `1px solid rgba(255,82,82,0.2)` |

- Border radius: 8px (standard), 6px (small)
- Padding: 8px 18px (standard), 5px 12px (small)
- Hover: Primary → `--cyan-glow`, Secondary → opacity +0.1, Ghost → border lightens

### 5.2 Status Badges

| Status   | Background opacity | Text color       | Dot color        |
|----------|-------------------|------------------|------------------|
| Healthy  | green 12%         | `--accent-green` | `--accent-green` |
| Error    | red 12%           | `--accent-red`   | `--accent-red`   |
| Warning  | yellow 12%        | `--accent-yellow`| `--accent-yellow`|
| Running  | cyan 12%          | `--cyan-500`     | `--cyan-500`     |
| Pending  | purple 12%        | `--purple-300`   | `--purple-300`   |
| Idle     | gray 12%          | `--text-dim`     | `--text-muted`   |

- Border radius: 20px (pill shape)
- Border: 1px solid at 20% opacity of the status color
- Include 7px dot indicator

### 5.3 Cards

- Background: `--card-bg` (#0f1a2e)
- Border: `1px solid --border-color` (#1e3050)
- Border radius: 12px
- Shadow: `0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)`

### 5.4 Focus & Interactive States

- Focus ring: `2px solid --cyan-500` + `box-shadow: 0 0 0 3px rgba(0,188,212,0.2)`
- Active tab: `--cyan-glow` text + `2px solid --cyan-glow` bottom border + `rgba(0,188,212,0.08)` background
- Inactive tab: `--text-muted` text, no border

---

## 6. Graph Node Colors (Harmonized)

Shifted from original values to complement the deep navy backgrounds. Glow effects (`box-shadow`) added for dark-mode readability.

| Node Type | Old Color  | New Color  | CSS Variable       | Glow shadow                        |
|-----------|------------|------------|--------------------|------------------------------------|
| Artist    | `#1DB954`  | `#00e676`  | `--node-artist`    | `0 0 10px rgba(0,230,118,0.4)`     |
| Release   | `#FF6B6B`  | `#ff5c8a`  | `--node-release`   | `0 0 10px rgba(255,92,138,0.4)`    |
| Label     | `#6c757d`  | `#78909c`  | `--node-label`     | `0 0 10px rgba(120,144,156,0.3)`   |
| Genre     | `#ffc107`  | `#ffd54f`  | `--node-genre`     | `0 0 10px rgba(255,213,79,0.4)`    |
| Category  | `#4A90D9`  | `#40c4ff`  | `--node-category`  | `0 0 10px rgba(64,196,255,0.4)`    |

---

## 7. Spacing & Border Radius

### 7.1 Spacing Scale (4px base unit)

| Token | Value | Usage                    |
|-------|-------|--------------------------|
| xs    | 4px   | Tight gaps, icon margins |
| sm    | 8px   | Between related elements |
| md    | 12px  | Card internal gaps       |
| base  | 16px  | Standard padding         |
| lg    | 24px  | Section padding          |
| xl    | 32px  | Between sections         |
| 2xl   | 48px  | Page-level spacing       |

### 7.2 Border Radius

| Element       | Radius | Usage                      |
|---------------|--------|----------------------------|
| Small buttons | 6px    | `.btn-sm`                  |
| Buttons/inputs| 8px    | Standard interactive       |
| Cards         | 12px   | Card/panel containers      |
| Sections      | 14px   | Top-level section wrappers |
| Badges        | 20px   | Pill-shaped badges         |
| Circles       | 50%    | Avatars, dots, logo        |

---

## 8. Shadows & Effects

### 8.1 Elevation Shadows

| Level | Shadow                                                              | Usage        |
|-------|---------------------------------------------------------------------|--------------|
| sm    | `0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)`           | Card default |
| md    | `0 4px 6px -1px rgba(0,0,0,0.3), 0 2px 4px -1px rgba(0,0,0,0.2)` | Elevated     |
| lg    | `0 10px 25px -3px rgba(0,0,0,0.4), 0 4px 10px -2px rgba(0,0,0,0.3)` | Dropdowns |

### 8.2 Glow Effects

| Type        | Shadow                                                    | Usage              |
|-------------|-----------------------------------------------------------|--------------------|
| Cyan glow   | `0 0 20px rgba(0,188,212,0.2), 0 0 40px rgba(0,188,212,0.1)` | Logo, focus     |
| Purple glow | `0 0 20px rgba(124,77,255,0.2), 0 0 40px rgba(124,77,255,0.1)` | Secondary glow |

### 8.3 Transitions

- Standard: `0.15s ease` (color, background, border-color)
- Animations: existing keyframes (spin, toast-fade, emergence-glow, taste-pulse) remain unchanged

---

## 9. Theme Mode

The existing light/dark toggle is replaced with a single dark theme. The `auto`/`light`/`dark` toggle is removed.

- Remove the theme toggle button from both services
- Remove the `.dark` class toggle logic from `dashboard.js` and explore's inline script
- Remove the light theme CSS variables (`:root` block)
- The dark palette defined in this spec becomes the only theme
- `prefers-color-scheme` media query no longer needed

---

## 10. Implementation Scope

### 10.1 Files to Create

| File | Description |
|------|-------------|
| `scripts/generate_brand_assets.py` | Python script to generate all brand assets |
| `explore/static/brand/*` | Generated brand assets (see full list below) |
| `dashboard/static/brand/*` | Copy of same brand assets for dashboard service |

The generation script outputs directly to `explore/static/brand/` and `dashboard/static/brand/` — each service gets its own copy (no symlinks, since services are deployed independently via Docker).

**Complete generated asset list per service:**

| File | Description |
|------|-------------|
| `banner_dark.png` | Horizontal logo on dark background (1600x400) |
| `banner_light.png` | Horizontal logo on light background (1600x400) |
| `square_dark.png` | Stacked logo on dark background (1024x1024) |
| `square_light.png` | Stacked logo on light background (1024x1024) |
| `icon_dark.png` | Icon mark on dark background (1024x1024) |
| `icon_light.png` | Icon mark on light background (1024x1024) |
| `og_image.png` | Open Graph social sharing image (1200x630) |
| `design_showcase.png` | Full design language reference image |
| `favicon.ico` | Multi-size ICO (16+32+48) |
| `favicon-16.png` | 16x16 favicon |
| `favicon-32.png` | 32x32 favicon |
| `favicon-48.png` | 48x48 favicon |
| `favicon-64.png` | 64x64 favicon |
| `favicon-128.png` | 128x128 favicon |
| `favicon-256.png` | 256x256 favicon |
| `favicon-512.png` | 512x512 favicon |
| `apple-touch-icon.png` | 180x180 iOS icon |
| `site.webmanifest` | PWA manifest |

### 10.2 Files to Modify

| File | Changes |
|------|---------|
| `explore/static/css/styles.css` | Replace all CSS variables with new palette, remove light theme, update node colors |
| `explore/static/index.html` | Replace inline logo with `<img>` tag, add favicon/manifest links, remove theme toggle, update tagline |
| `explore/tailwind.config.js` | Update theme extension colors |
| `explore/tailwind.input.css` | Update button/badge component colors |
| `dashboard/static/index.html` | Replace inline logo, add favicon/manifest links, remove theme toggle, update title area |
| `dashboard/static/admin.html` | Replace inline logo, add favicon/manifest links, remove theme toggle |
| `dashboard/static/dashboard.js` | Remove theme toggle logic, remove light/dark/auto cycle |
| `dashboard/static/admin.js` | Remove theme toggle logic |
| `dashboard/tailwind.config.js` | Update theme extension colors |
| `dashboard/tailwind.input.css` | Update if theme-related utilities exist |

### 10.3 What Does NOT Change

- Service architecture, routing, or backend logic
- Material Symbols Outlined icon system
- Tailwind CSS framework (still used, just different tokens)
- Custom scrollbar styles (updated colors only)
- Animation keyframes (spin, toast-fade, etc.)
- Responsive breakpoints and grid layouts
- Alpine.js, D3.js, Plotly.js integrations
- Font smoothing settings

---

## 11. Brand Asset Generation Script

The `scripts/generate_brand_assets.py` script uses Pillow to programmatically render:

1. **Vinyl body**: Dark circle with subtle border
2. **Groove rings**: 4-5 concentric circles in elevated color
3. **Network edges**: Lines between node positions at varied opacities, cyan and purple
4. **Network nodes**: Circles with glow halos (outer circle at low opacity)
5. **Center spindle**: Three concentric circles (outer ring, gradient fill, center hole)
6. **Wordmark text**: Space Grotesk font rendered for banner/square variants
7. **Favicon scaling**: Master icon scaled down with appropriate detail reduction for small sizes

Dependencies: `Pillow` (already available via `uv add --dev Pillow`).

Font file: Space Grotesk `.ttf` downloaded from Google Fonts at build time or bundled in `static/fonts/`.
