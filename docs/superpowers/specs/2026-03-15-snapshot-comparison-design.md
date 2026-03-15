# Vinyl Archaeology — Snapshot Comparison Design

**Issue:** #126
**Date:** 2026-03-15
**Status:** Approved

## Overview

Add snapshot comparison to the existing Vinyl Archaeology feature, allowing users to pin two years and see a color-coded overlay diff of the graph state between them.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Year selection UI | Dual range slider | Intuitive, minimal UI change, both years always visible |
| Display mode | Overlay with color coding | Full screen width, spatial diff is immediate, reuses existing graph |
| Diff computation | Client-side | No new API endpoints, existing `before_year` on `/api/expand` provides the foundation |

## Interaction: Dual Range Slider

The existing `TimelineScrubber` gains a Compare mode:

1. A "Compare" toggle button is added to the timeline controls (next to the speed toggle)
2. When activated, the single slider is replaced with two range inputs — Year A (left thumb, indigo) and Year B (right thumb, purple)
3. Both year labels are shown: `1975 ↔ 1995`
4. Play/pause, speed controls, and genre emergence highlighting are all disabled during comparison mode
5. Clicking Compare again exits back to single-slider explore mode, restoring the previous `beforeYear` state

No new API endpoints needed. The client makes two parallel `expand()` calls with different `before_year` values.

### State interaction with `setBeforeYear()`

- When compare mode activates, the current `this.beforeYear` value is saved to `this._savedBeforeYear`
- `this.beforeYear` is set to `null` (comparison mode uses its own state: `this.compareYearA` and `this.compareYearB`)
- `setBeforeYear()` is not called during comparison mode — `setCompareYears()` is the active method
- When exiting compare mode, `this.beforeYear` is restored from `this._savedBeforeYear` and `setBeforeYear()` is called to re-render the single-year view

## Overlay Visualization: Color-Coded Diff

When comparison mode is active and both years are set, the graph renders a merged overlay:

### Node identity for diffing

Nodes are matched using the composite key `child.type + ":" + child.id` (the Discogs numeric ID), not the display `name`. This ensures stable, unique matching — display names can have duplicates across types.

### Node coloring

- **Both years** (intersection): Normal node color, standard opacity — no special treatment
- **Year A only** (removed by Year B): Dashed border, reduced opacity (0.4), Year A color (indigo). Tooltip shows "(Year A only)"
- **Year B only** (added since Year A): Solid glowing border (green/emerald), full opacity. Tooltip shows "(Year B only)"

### Link styling

Links inherit the `compareStatus` of their child node:
- Links to "both" nodes: normal styling
- Links to "only_a" nodes: dashed stroke, reduced opacity (matching node)
- Links to "only_b" nodes: green stroke (matching node)

### Category count labels

Updated to show the diff using API `total` values: `"Releases (Year A total → Year B total)"`, e.g., `"Releases (45 → 128)"`.

### Implementation

1. `graph.js` gets a new `setCompareYears(yearA, yearB)` method
2. For each expanded category, two parallel `expand()` calls are made via a dedicated `_fetchComparisonData()` method that collects both responses before mutating the graph (unlike `_expandCategoryFiltered()` which inserts nodes immediately)
3. Results are diffed client-side using the composite node key: `bothSets = A ∩ B`, `onlyA = A \ B`, `onlyB = B \ A`
4. The merged node set (union) is inserted into the graph, each node annotated with a `compareStatus` property (`"both"`, `"only_a"`, `"only_b"`) that drives styling
5. A `clearComparison()` method removes comparison annotations and restores normal rendering

### Legend

A small floating legend appears in the bottom-left corner showing the three states with their visual indicators. It is positioned to avoid collision with the existing `.graph-legend` element and is dismissible via a close button.

### Transition behavior

During comparison re-fetch (when slider thumbs are dragged), the existing diff remains visible until both new fetch responses arrive. A subtle loading indicator (spinner on the category node) shows that data is being refreshed.

## Error Handling

- If either `expand()` call fails during comparison, show a toast notification and fall back to single-year mode
- If Year A === Year B, disable diff styling (everything is "both") and show a hint: "Select different years to compare"
- Debounce slider changes (existing 300ms) to avoid double API storms when dragging

## Edge Cases

- **Year ordering**: Year A is always `min(thumb1, thumb2)` and Year B is always `max(thumb1, thumb2)`, regardless of which thumb the user drags. This ensures "Year A only" consistently means "removed by Year B" and "Year B only" means "added since Year A"
- When no entity is expanded yet, comparison mode activates but shows nothing different until categories are expanded
- Load-more pagination is disabled in comparison mode — first page (30 items) per year only, to keep the diff manageable
- Aliases remain unfiltered by `before_year` (timeless relationships, consistent with existing behavior)

## Files to Modify

| File | Changes |
|------|---------|
| `explore/static/js/app.js` | `TimelineScrubber` — add compare toggle, dual slider state, disable play/emergence, save/restore `beforeYear` |
| `explore/static/js/graph.js` | `setCompareYears()`, `clearComparison()`, `_fetchComparisonData()`, diff logic, node/link styling |
| `explore/static/index.html` | Compare toggle button, dual slider markup, comparison legend, CSS for diff states and link styles |

## Out of Scope

- Server-side diff endpoint (client-side approach chosen)
- Split-view / side-by-side panels
- Summary panel with textual diff
- JS test framework (tracked in #145)
- Keyboard accessibility for dual range slider (tracked as future work)
