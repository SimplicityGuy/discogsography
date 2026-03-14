# Taste Fingerprint UI — Design Spec

## Overview

Add a taste fingerprint dashboard strip to the Collection pane in the Explore UI, exposing the 4 taste analytics endpoints from PR #120 (`/api/user/taste/*`) as a compact, always-visible visualization.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Placement | Inside Collection pane, above release table | Keeps analytics close to the data they're derived from; no new nav tab |
| Components | All 4: heatmap, fingerprint summary, blind spots, taste card | Full analytics surface |
| Layout | Always-visible 3-column dashboard strip | Compact, no toggle needed, everything at a glance |
| Data fetching | Single `/fingerprint` call on pane load; SVG card fetched on download click | Minimizes requests; fingerprint endpoint aggregates all sub-queries server-side |

## Layout

```
+---Collection Pane---------------------------------------------+
| [existing stats row: Total Items | Artists | Labels | Rating] |
|                                                                |
| +--Taste Strip----------------------------------------------+ |
| | FINGERPRINT    | HEATMAP              | BLIND SPOTS       | |
| | Obscurity 0.72 | genre x decade grid  | Fusion (8)        | |
| | Peak: 1990s    | (purple intensity)   | Ambient (5)       | |
| | Rock->Elec     |                      | Dub (3)           | |
| |                |                      | [Download Card]   | |
| +-----------------------------------------------------------+ |
|                                                                |
| [existing release table with pagination]                       |
+----------------------------------------------------------------+
```

Three equal-width columns inside a `.taste-strip` container:

1. **Fingerprint column** — Obscurity score (large number), peak decade, taste drift (earliest genre -> latest genre from drift array)
2. **Heatmap column** — CSS grid of genre rows x decade columns, cell background intensity mapped to count. Shows top 5 genres by total count.
3. **Blind Spots column** — List of up to 5 blind spot genres with artist overlap count. "Download Taste Card" button at bottom.

## Data Flow

### On Collection pane load (when user is authenticated + Discogs connected)

1. `UserPanes.loadCollection()` calls `loadTasteFingerprint()` in parallel
2. `loadTasteFingerprint()` calls `apiClient.getTasteFingerprint(token)`
3. On success: render the `.taste-strip` via `_renderTasteStrip(data)`
4. On 422 (< 10 items) or error: hide the strip entirely — no error message

### On "Download Taste Card" click

1. Call `apiClient.getTasteCard(token)` — returns SVG blob
2. Create a blob URL and trigger download as `taste-card.svg`

## API Endpoints Consumed

| Endpoint | Method | When Called | Response Used |
|----------|--------|-------------|---------------|
| `/api/user/taste/fingerprint` | GET | Collection pane load | `heatmap[]`, `obscurity{}`, `drift[]`, `blind_spots[]`, `peak_decade` |
| `/api/user/taste/card` | GET | Download button click | Raw SVG (`image/svg+xml`) |

Both require `Authorization: Bearer <jwt>` header.

## Files Modified

### `explore/static/js/api-client.js`

Add two methods to the `ApiClient` class:

- `getTasteFingerprint(token)` — GET `/api/user/taste/fingerprint` with auth header, returns JSON or null
- `getTasteCard(token)` — GET `/api/user/taste/card` with auth header, returns blob or null

### `explore/static/js/user-panes.js`

Add to the `UserPanes` class:

- `loadTasteFingerprint()` — fetch + render orchestration with loading/error handling
- `_renderTasteStrip(container, data)` — builds the 3-column dashboard strip DOM
- `_renderHeatmapGrid(cells)` — builds the genre x decade CSS grid from heatmap cells
- `_downloadTasteCard()` — fetches SVG and triggers browser download

Modify `loadCollection()` to call `loadTasteFingerprint()` in parallel.

### `explore/static/index.html`

Add `<div id="tasteStrip"></div>` inside `#collectionPane > .user-pane-body`, after `#collectionStats` and before `#collectionLoading`.

### `explore/static/css/styles.css`

Add styles for:
- `.taste-strip` — 3-column CSS grid, gap, background, border-radius
- `.taste-col` — individual column padding and layout
- `.taste-col-header` — small uppercase label (FINGERPRINT, HEATMAP, BLIND SPOTS)
- `.taste-stat` — key-value row for obscurity/peak/drift
- `.taste-stat-value` — large colored number
- `.taste-heatmap-grid` — CSS grid for the heatmap cells
- `.taste-heatmap-cell` — individual cell with dynamic background opacity
- `.taste-blindspot-item` — blind spot list item
- `.taste-download-btn` — styled download button

## Heatmap Rendering

The heatmap cells from the API are `{genre, decade, count}`. To render:

1. Group cells by genre, sort genres by total count descending, take top 5
2. Collect unique decades, sort ascending
3. Render a CSS grid: first column = genre labels, remaining columns = decade headers + cells
4. Cell background: purple scale based on count relative to max count in the dataset
   - `opacity = count / maxCount` applied to a base purple (`#6b46c1`)
   - Zero counts get the darkest background (`#1a1625`)

## Taste Drift Display

The drift array contains `{year, top_genre, count}` entries. To summarize in one line:
- Take first and last entries from the drift array
- Display as `"{first_genre} -> {last_genre}"` if they differ
- Display as `"{genre} (consistent)"` if they're the same

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Not authenticated | Strip not rendered (loadTasteFingerprint skips) |
| 422 (< 10 collection items) | Strip hidden |
| 503 (service not ready) | Strip hidden |
| Network error | Strip hidden |
| Empty heatmap/drift/blindspots | Respective column shows "—" placeholder |

## Security

- All API calls include JWT auth header from `authManager.getToken()`
- SVG taste card is server-rendered with `html.escape()` for XSS prevention — no client-side SVG construction
- Download uses blob URL (no direct DOM insertion of SVG content)
